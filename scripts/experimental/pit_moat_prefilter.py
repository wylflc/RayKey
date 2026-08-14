"""护城河的**必要条件**筛：只排除、不选择。

§12.33 失败的那版是「综合分取前 N」——它在**做选择**，于是选中的都是基本面顶点的公司。
本脚本反过来：只回答「这家公司有没有可能满足 §5.4 的任何一条判据」，
凡是**任何一年都没有出现过持续超额**的，一律不必再判——因为锚1/锚3/锚12/§5.4.1-4/判例N
无一例外都要求某种可持续的超额（定价权体现为毛利率、资本效率体现为 ROE）。

判据（并联，任一命中即保留）：
  A 毛利率连续 `--years` 年 ≥ 同行业当年中位 + `--gm-gap`  （定价权路径）
  B ROE 连续 `--years` 年 ≥ 同行业当年中位 + `--roe-gap` 且当年归母为正 （资本效率路径，
    金融业无毛利率数据，只能走这条）

**刻意设得宽**：宁可多留一批要人判的，也不能把真候选筛掉。
脚本会同时打印对两组已知名单的召回，作为「筛得太紧」的报警：
  * `verdicts_panel.csv` 的 141 家护城河名单
  * 本轮已人工判入选的名单（`verdicts_pit_moat.csv` 中 worth_from ≠ 0）

用法：
    python3 pit_moat_prefilter.py --out <保留代码清单>
"""
import csv, glob, collections, statistics, argparse

ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
FIN = f"{ROOT}/data/raw/financials"
SEC = f"{ROOT}/data/raw/a_share_securities.csv"
PIT = f"{ROOT}/data/processed/pit_attention"


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3, help="需连续满足的年数")
    ap.add_argument("--gm-gap", type=float, default=8.0, help="毛利率高出同业中位的百分点")
    ap.add_argument("--roe-gap", type=float, default=8.0, help="ROE 高出同业中位的百分点")
    ap.add_argument("--min-rev", type=float, default=3.0, help="峰值营收下限（亿）")
    ap.add_argument("--out")
    ap.add_argument("--codes", help="代码清单文件；不给则用 bloom 队列")
    a = ap.parse_args()

    ann = collections.defaultdict(dict)
    for f in sorted(glob.glob(f"{FIN}/*-12-31.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            ann[r["security_code"]][int(r["report_date"][:4])] = dict(
                roe=num(r.get("weightavg_roe")), gm=num(r.get("gross_margin")),
                rev=num(r.get("total_operate_income")), np=num(r.get("parent_netprofit")))
    with open(SEC, encoding="utf-8-sig") as fh:
        IND = {r["security_code"]: ((r.get("industry") or "").strip() or "未分类")
               for r in csv.DictReader(fh)}

    gm_all = collections.defaultdict(list)
    roe_all = collections.defaultdict(list)
    for c, yrs in ann.items():
        g = IND.get(c, "未分类")
        for y, r in yrs.items():
            if r["gm"] is not None: gm_all[(g, y)].append(r["gm"])
            if r["roe"] is not None: roe_all[(g, y)].append(r["roe"])
    gm_med = {k: statistics.median(v) for k, v in gm_all.items() if len(v) >= 5}
    roe_med = {k: statistics.median(v) for k, v in roe_all.items() if len(v) >= 5}

    # `--codes` 给了就按该清单筛，否则默认 bloom 队列（2026-08-14 补，OI-053）。
    # **原实现只认 bloom 队列**，而 OI-053 要复判的 51 只全不在队列内——
    # 与 `build_pit_dossiers.py` 是同一处「把增量队列当完整宇宙」。
    if a.codes:
        bloom = [ln.strip().zfill(6) for ln in open(a.codes, encoding="utf-8") if ln.strip()]
    else:
        bloom = [r["security_code"] for r in
                 csv.DictReader(open(f"{PIT}/bloom_queue.csv", encoding="utf-8"))]
    keep, drop = [], []
    why = collections.Counter()
    for c in bloom:
        yrs = ann.get(c) or {}
        if not yrs:
            drop.append(c); continue
        g = IND.get(c, "未分类")
        peak = max((r["rev"] or 0) for r in yrs.values()) / 1e8
        if peak < a.min_rev:
            drop.append(c); why["规模不足"] += 1; continue
        runA = runB = 0
        hit = None
        for y in sorted(yrs):
            r = yrs[y]
            mg, mr = gm_med.get((g, y)), roe_med.get((g, y))
            runA = runA + 1 if (r["gm"] is not None and mg is not None
                                and r["gm"] - mg >= a.gm_gap) else 0
            runB = runB + 1 if (r["roe"] is not None and mr is not None and r["np"]
                                and r["np"] > 0 and r["roe"] - mr >= a.roe_gap) else 0
            if runA >= a.years or runB >= a.years:
                hit = "毛利" if runA >= a.years else "资本效率"
                break
        if hit:
            keep.append(c); why[hit] += 1
        else:
            drop.append(c); why["无持续超额"] += 1
    print(f"bloom 队列 {len(bloom)} 只 → 保留 {len(keep)}、排除 {len(drop)}")
    print("  " + "｜".join(f"{k} {v}" for k, v in why.most_common()))

    ks = set(keep)
    moat = {r["security_code"] for r in csv.DictReader(open(f"{PIT}/verdicts_panel.csv", encoding="utf-8"))
            if r["worth_from"] not in ("", "0")}
    inb = moat & set(bloom)
    print(f"\n报警检查一：141 家护城河名单里落在 bloom 队列的 {len(inb)} 只，"
          f"本筛保留 {len(inb & ks)}（{len(inb & ks)/max(1,len(inb))*100:.0f}%）")
    lost = sorted(inb - ks)
    if lost:
        nm = {}
        with open(SEC, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                nm[r["security_code"]] = r.get("security_name", "")
        print("  被筛掉的：" + "｜".join(f"{nm.get(c,c)}" for c in lost))

    try:
        mine = {r["security_code"] for r in
                csv.DictReader(open(f"{PIT}/verdicts_pit_moat.csv", encoding="utf-8"))
                if r["worth_from"] not in ("", "0")}
        print(f"报警检查二：本轮已人工判入选 {len(mine)} 只，本筛保留 {len(mine & ks)}"
              f"（{len(mine & ks)/max(1,len(mine))*100:.0f}%）")
        if mine - ks:
            print("  被筛掉的：" + "｜".join(sorted(mine - ks)))
    except FileNotFoundError:
        pass

    if a.out:
        open(a.out, "w", encoding="utf-8").write("\n".join(keep))
        print(f"\n已写 {a.out}")


if __name__ == "__main__":
    main()
