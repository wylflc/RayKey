"""**分档估值**：给「成长股」单独一套估值口径，其余股票的估值带**逐位不动**。

动机（§12.37 / OI-050）：现行 DCF 在秩意义上等同于按 PE 排序（`P/V` 与 `PE_ttm` 秩相关 +0.876、
隐含 PE 中位 11.0、极差仅 1.51×），成长股因此被系统性地判贵、永远排在换仓队列末尾。
§12.37 试过**统一**改模型（n1 全池生效），失败——买入线为维持同一合格面被同步收紧，
n1 变成一次重排序，把钱从格力/陕西煤业挪走，全局盈亏 −58%。

本脚本改为用户 2026-08-13 指定的做法：**只给成长股换模型，让它和资源股站在同一条起跑线**。
资源股/周期股的 `P/V` 一个字不改，所以它们原有的合格日与排序位置全部保留；
新增的只是成长股那一侧的合格面。

成长判据（**全部只用判定年 Y 的 4-30 之前已可得的年报**，可得日按法定截止 Y+1-04-30 封顶）：
  1. 扩张   最近 3 年营收中位 ≥ 更早 3 年营收中位 × `--mult`
  2. 持续   最近 5 年里营收同比为正的年数 ≥ `--pos-years`（周期股营收忽上忽下，过不了）
  3. 不塌   最近 3 年毛利率中位 ≥ 更早 3 年毛利率中位 − `--gm-drop`（价格驱动的暴涨会先崩毛利）
  4. 盈利   最近 3 年归母全部为正
  5. 规模   最近一年营收 ≥ `--min-rev` 亿
  6. **硬排除**：采矿／钢铁／有色／石化化工原料／电力燃气／银行金融／房地产／建筑
     ——「让成长股与资源股同台竞技」这句话本身要求资源股不得自称成长股。

一旦判为成长，该档从 `Y-04-30` 生效到下一档；**逐年重判，可进可出**。

用法：
    python3 growth_segment.py --out <成长档CSV> [--report]
"""
import csv, glob, collections, statistics, argparse

ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
FIN = f"{ROOT}/data/raw/financials"
SEC = f"{ROOT}/data/raw/a_share_securities.csv"
PIT = f"{ROOT}/data/processed/pit_attention"

EXCLUDE_FINE = ("采矿业", "黑色金属", "有色金属", "石油", "化学原料", "电力", "燃气",
                "金融业", "房地产", "建筑业", "煤炭", "水的生产")


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def load_annuals():
    per = collections.defaultdict(dict)
    for f in sorted(glob.glob(f"{FIN}/*-12-31.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            y = int(r["report_date"][:4])
            nd = r.get("notice_date") or ""
            legal = f"{y+1}-04-30"
            per[r["security_code"]][y] = dict(
                avail=(min(nd, legal) if len(nd) == 10 else legal),
                gm=num(r.get("gross_margin")), rev=num(r.get("total_operate_income")),
                np=num(r.get("parent_netprofit")))
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mult", type=float, default=1.6, help="近三年营收中位 ÷ 更早三年中位 的下限")
    ap.add_argument("--pos-years", type=int, default=4, help="近五年里营收同比为正的年数下限")
    ap.add_argument("--gm-drop", type=float, default=3.0, help="毛利率允许的中位跌幅（pp）")
    ap.add_argument("--min-rev", type=float, default=10.0, help="最近一年营收下限（亿）")
    ap.add_argument("--from-year", type=int, default=2009)
    ap.add_argument("--to-year", type=int, default=2026)
    ap.add_argument("--codes", help="只判这些代码（每行一个）；缺省判全部有年报的")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    ANN = load_annuals()
    with open(SEC, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    NAME = {r["security_code"]: r.get("security_name", "") for r in rows}
    fine = {}
    for r in csv.DictReader(open(f"{PIT}/judgment_log.csv", encoding="utf-8")):
        t = (r.get("business_desc_at_period") or "").strip()
        if t:
            fine[r["security_code"]] = t.split("｜")[0]

    want = None
    if a.codes:
        want = {ln.strip().zfill(6) for ln in open(a.codes, encoding="utf-8") if ln.strip()}

    out, hits = [], collections.defaultdict(list)
    excluded = set()
    for code, yrs in ANN.items():
        if want is not None and code not in want:
            continue
        g = fine.get(code, "")
        if any(k in g for k in EXCLUDE_FINE):
            excluded.add(code)
            continue
        for Y in range(a.from_year, a.to_year + 1):
            cut = f"{Y}-04-30"
            vis = sorted(y for y in yrs if yrs[y]["avail"] <= cut and yrs[y]["rev"])
            if len(vis) < 6:
                continue
            late, early = vis[-3:], vis[-6:-3]
            rv_l = [yrs[y]["rev"] for y in late]
            rv_e = [yrs[y]["rev"] for y in early]
            if not rv_e or statistics.median(rv_e) <= 0:
                continue
            if statistics.median(rv_l) < a.mult * statistics.median(rv_e):
                continue
            last5 = vis[-5:]
            pos = sum(1 for i in range(1, len(last5))
                      if yrs[last5[i]]["rev"] > yrs[last5[i - 1]]["rev"])
            # 近五年只有四个同比，故门槛按 min(pos_years, len-1)
            if pos < min(a.pos_years, len(last5) - 1):
                continue
            gm_l = [yrs[y]["gm"] for y in late if yrs[y]["gm"] is not None]
            gm_e = [yrs[y]["gm"] for y in early if yrs[y]["gm"] is not None]
            if gm_l and gm_e and statistics.median(gm_l) < statistics.median(gm_e) - a.gm_drop:
                continue
            if any((yrs[y]["np"] or -1) <= 0 for y in late):
                continue
            if (yrs[late[-1]]["rev"] or 0) / 1e8 < a.min_rev:
                continue
            out.append((code, Y))
            hits[Y].append(code)

    # 写成区间档（同一只连续年份合并）
    per = collections.defaultdict(list)
    for c, Y in out:
        per[c].append(Y)
    recs = []
    for c, ys in per.items():
        ys.sort()
        s = p = ys[0]
        for y in ys[1:]:
            if y == p + 1:
                p = y
            else:
                recs.append((c, f"{s}-04-30", f"{p+1}-04-30")); s = p = y
        recs.append((c, f"{s}-04-30", f"{p+1}-04-30" if p < a.to_year else ""))
    recs.sort()
    with open(a.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["security_code", "security_name", "effective_from", "effective_to"])
        for c, ef, et in recs:
            w.writerow([c, NAME.get(c, ""), ef, et])
    print(f"成长档 {len(recs):,} 段｜{len(per)} 只｜行业硬排除 {len(excluded)} 只｜已写 {a.out}")

    if a.report:
        print("\n逐年在册成长股只数：")
        print("  " + "｜".join(f"{Y}:{len(hits[Y])}" for Y in sorted(hits) if hits[Y]))
        print("\n点名公司的成长档：")
        for c in ("300750", "603259", "300308", "300502", "600519", "000651", "000333",
                  "601225", "002128", "002714", "600809", "300760", "002475"):
            if c in per:
                ys = sorted(per[c])
                print(f"  ✓ {NAME.get(c,c):<8} {ys[0]}~{ys[-1]}（{len(ys)} 年）")
            elif c in excluded:
                print(f"  ✗ {NAME.get(c,c):<8} 行业硬排除")
            else:
                print(f"  ✗ {NAME.get(c,c):<8} 未判为成长")


if __name__ == "__main__":
    main()
