"""给 bloom queue 逐只装配「时点档案」，供逐筛选年的**定性**护城河重判使用。

每份档案只含**当年可得**的事实，不含任何事后信息：
  * 逐财年读数（营收／毛利率／ROE／归母净利），每行标注该年报的**可得日**
    （= min(公告日, 法定截止日 Y+1-04-30)，见 OI-042）；
  * **各时点的业务描述**（取自 `judgment_log.csv` 的 `business_desc_at_period`，
    该字段本就是按 `as_of_year` 记的，不是今天的描述）；
  * 同行业当年中位毛利率与中位 ROE，供「显著高于同业」一类判据比对。

**不含**：股价、市值、后续年份的读数、今天的分类与结论、`verdicts_panel.csv` 的任何内容。

判读者据此定的是**首次成立年** `worth_from`——护城河判定天然是「证据最早在哪一年成立」，
不是逐年独立重判，故 802 只需 802 次判断而非 802×18 次。

用法：
    python3 build_pit_dossiers.py --codes <代码清单> --out <档案文本>
    python3 build_pit_dossiers.py --sample 200 --seed 7 --out <档案文本>
"""
import csv, glob, collections, statistics, argparse, random, math

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


def load_annuals():
    per = collections.defaultdict(dict)
    for f in sorted(glob.glob(f"{FIN}/*-12-31.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            y = int(r["report_date"][:4])
            nd = r.get("notice_date") or ""
            legal = f"{y+1}-04-30"
            per[r["security_code"]][y] = dict(
                avail=(min(nd, legal) if len(nd) == 10 else legal),
                roe=num(r.get("weightavg_roe")), gm=num(r.get("gross_margin")),
                rev=num(r.get("total_operate_income")), np=num(r.get("parent_netprofit")))
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", required=True)
    ap.add_argument("--list-out", help="同时写出本批代码清单")
    a = ap.parse_args()

    bloom = list(csv.DictReader(open(f"{PIT}/bloom_queue.csv", encoding="utf-8")))
    if a.codes:
        want = {ln.strip().zfill(6) for ln in open(a.codes, encoding="utf-8") if ln.strip()}
        bloom = [r for r in bloom if r["security_code"] in want]
    elif a.sample:
        # 按触发类型分层抽样：T1（ROE 型）与 T2（营收×毛利型）各按其占比抽
        strata = collections.defaultdict(list)
        for r in bloom:
            strata[(r["why"] or "T?")[:2]].append(r)
        rng = random.Random(a.seed)
        picked = []
        tot = len(bloom)
        for k, v in sorted(strata.items()):
            n = round(a.sample * len(v) / tot)
            rng.shuffle(v)
            picked += v[:n]
        bloom = picked[:a.sample]

    ANN = load_annuals()
    with open(SEC, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    NAME = {r["security_code"]: r.get("security_name", "") for r in rows}
    IND = {r["security_code"]: ((r.get("industry") or "").strip() or "未分类") for r in rows}

    desc = collections.defaultdict(list)
    for r in csv.DictReader(open(f"{PIT}/judgment_log.csv", encoding="utf-8")):
        d = (r.get("business_desc_at_period") or "").strip()
        if d:
            desc[r["security_code"]].append((r["as_of_year"], d))
    for c in desc:
        desc[c].sort()

    # 各行业逐年中位（全市场，供同业比对）
    ind_gm = collections.defaultdict(list)
    ind_roe = collections.defaultdict(list)
    for c, yrs in ANN.items():
        g = IND.get(c, "未分类")
        for y, r in yrs.items():
            if r["gm"] is not None: ind_gm[(g, y)].append(r["gm"])
            if r["roe"] is not None: ind_roe[(g, y)].append(r["roe"])
    gm_med = {k: statistics.median(v) for k, v in ind_gm.items() if len(v) >= 5}
    roe_med = {k: statistics.median(v) for k, v in ind_roe.items() if len(v) >= 5}

    out = []
    codes = []
    for r in sorted(bloom, key=lambda x: x["security_code"]):
        c = r["security_code"]
        yrs = ANN.get(c) or {}
        if not yrs:
            continue
        codes.append(c)
        g = IND.get(c, "未分类")
        ds = desc.get(c) or []
        d0 = ds[0][1] if ds else ""
        d1 = ds[-1][1] if len(ds) > 1 else ""
        head = f"### {c} {NAME.get(c,'')}｜{g}｜[{ds[0][0] if ds else '?'}] {d0}"
        if d1 and d1 != d0:
            head += f"｜[{ds[-1][0]}] {d1}"
        ys = [y for y in sorted(yrs) if y >= 2001]
        if not ys:
            continue
        def row(lbl, fn):
            return lbl + " " + " ".join(fn(y) for y in ys)
        fmt = lambda x, d=1: ("—" if x is None else f"{x:.{d}f}")
        lines = [head, f"财年 {ys[0]}-{ys[-1]}（可得日均为次年4月底或更早，逐年不再列）"]
        lines.append(row("营收亿", lambda y: fmt(yrs[y]["rev"] / 1e8 if yrs[y]["rev"] else None)))
        lines.append(row("毛利%", lambda y: fmt(yrs[y]["gm"])))
        lines.append(row("同业毛利中位", lambda y: fmt(gm_med.get((g, y)))))
        lines.append(row("ROE%", lambda y: fmt(yrs[y]["roe"])))
        lines.append(row("同业ROE中位", lambda y: fmt(roe_med.get((g, y)))))
        lines.append(row("归母亿", lambda y: fmt(yrs[y]["np"] / 1e8 if yrs[y]["np"] is not None else None)))
        late = [y for y in ys if yrs[y]["avail"] > f"{y+1}-04-30"]
        if late:
            lines.append("注：以下财年的年报可得日晚于次年4月底：" + ",".join(map(str, late)))
        out.append("\n".join(lines))

    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(f"# 时点档案：{len(out)} 只（毛利率/ROE 单位 %，营收与归母单位亿元）\n"
                 f"# 每行的「可得日」即该年报最早可用之日；判定年 Y 只可使用可得日 ≤ Y-04-30 的行。\n\n")
        fh.write("\n\n".join(out))
    print(f"已写 {a.out}（{len(out)} 只）")
    if a.list_out:
        open(a.list_out, "w", encoding="utf-8").write("\n".join(codes))
        print(f"代码清单 {a.list_out}")


if __name__ == "__main__":
    main()
