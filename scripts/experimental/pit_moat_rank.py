"""逐筛选年、只用当年可得信息，按护城河判据的**等权综合分**取前 N 只，重建时点股票库。

与 `pit_moat_screen.py` 的阈值版相比，本版有两处刻意的设计：

1. **等权、不拟合。** 八个分项各自对应 §5.4 的一条判据，逐年在全市场内做**分位归一**后等权相加。
   权重不去拟合已知的 141 家护城河名单——那样会把后视塞进阈值里。141 家只用作**事后验收**
   （召回率与入选时点），不参与任何调参。
2. **规模由 N 控制，不由阈值控制。** 阈值型判据在跨年比较时极脆（毛利率的行业分布逐年漂移），
   取分位则天然随年份自适应，且面板规模可预先定死，便于与现行 116 家面板对照。

八个分项（全部只用报告期 ≤ Y−1 且可得日 ≤ Y-04-30 的年报）：

| 分项 | 对应判据 | 含义 |
| --- | --- | --- |
| gm_level   | 锚3／锚12 | 五年毛利率中位——品牌与品类垄断的直接签名 |
| gm_stable  | 锚3 | 毛利率五年标准差取负——真壁垒的毛利率不塌 |
| gm_vs_ind  | 锚1 | 毛利率减同行业当年中位——「显著高于同业」 |
| rev_growth | 判据5② | 五年营收复合增速——规模在扩张 |
| gm_hold    | 判据5② | 期末毛利率减期初——扩张的同时守住了毛利 |
| roe_level  | 通用 | 五年 ROE 中位 |
| trough     | 判例6 | 行业深谷年里本公司仍盈利且 ROE 高出同业的年数（牧原那一条） |
| scale      | 锚6 | log 营收——规模本身构成的结构性壁垒 |

**一旦入选不再退出**，与 §12.32 的 MOATB 口径一致：看错了也一路持有，避免退出择时的后视。

用法：
    python3 pit_moat_rank.py --top-n 200 --out <面板CSV>
    python3 pit_moat_rank.py --top-n 200 --calib     # 只验收，不写面板
"""
import csv, glob, collections, statistics, argparse, math

ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
FIN = f"{ROOT}/data/raw/financials"
SEC = f"{ROOT}/data/raw/a_share_securities.csv"
MOAT = f"{ROOT}/data/archive/pit-judgment-2026-08/verdicts_panel.csv"
COMPONENTS = ["gm_level", "gm_stable", "gm_vs_ind", "rev_growth",
              "gm_hold", "roe_level", "trough", "scale"]


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
            y = r["report_date"][:4]
            nd = r.get("notice_date") or ""
            legal = f"{int(y)+1}-04-30"
            per[r["security_code"]][y] = dict(
                avail=(min(nd, legal) if len(nd) == 10 else legal),
                roe=num(r.get("weightavg_roe")), gm=num(r.get("gross_margin")),
                rev=num(r.get("total_operate_income")), np=num(r.get("parent_netprofit")))
    return per


def load_industry():
    with open(SEC, encoding="utf-8-sig") as fh:
        return {r["security_code"]: ((r.get("industry") or "").strip() or "未分类")
                for r in csv.DictReader(fh)}


def load_names():
    with open(SEC, encoding="utf-8-sig") as fh:
        return {r["security_code"]: (r.get("security_name") or "") for r in csv.DictReader(fh)}


def pct_rank(values):
    """{键: 值} → {键: 分位∈[0,1]}，并列取平均位次。"""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    out = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        r = (i + j) / 2.0 / max(1, n - 1)
        for k in range(i, j + 1):
            out[items[k][0]] = r
        i = j + 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-n", type=int, default=200, help="到末年为止累计在册的目标只数")
    ap.add_argument("--from-year", type=int, default=2009)
    ap.add_argument("--to-year", type=int, default=2026)
    ap.add_argument("--min-rev", type=float, default=10.0, help="营收下限（亿），只为剔除壳与微盘")
    ap.add_argument("--out")
    ap.add_argument("--calib", action="store_true")
    ap.add_argument("--dump-scores")
    a = ap.parse_args()

    ANN, IND, NAMES = load_annuals(), load_industry(), load_names()
    print(f"年报覆盖 {len(ANN):,} 只", flush=True)
    moat = {r["security_code"]: (int(r["worth_from"]), r["security_name"], r["rule"])
            for r in csv.DictReader(open(MOAT, encoding="utf-8"))
            if r["worth_from"] not in ("", "0")}

    years = list(range(a.from_year, a.to_year + 1))
    # 名额随年份线性放开：早年可选标的少，一上来就要 200 只会把垃圾也收进来
    quota = {Y: max(30, round(a.top_n * (i + 1) / len(years))) for i, Y in enumerate(years)}

    admitted = {}
    dump = []
    for Y in years:
        cut = f"{Y}-04-30"
        feats = {}
        ind_gm_year = collections.defaultdict(list)
        ind_roe_year = collections.defaultdict(lambda: collections.defaultdict(list))
        snap = {}
        for c, rows in ANN.items():
            vis = [(y, rows[str(y)]) for y in range(Y - 5, Y)
                   if str(y) in rows and rows[str(y)]["avail"] <= cut]
            if len(vis) < 3:
                continue
            snap[c] = vis
            g = IND.get(c, "未分类")
            if vis[-1][1]["gm"] is not None:
                ind_gm_year[g].append(vis[-1][1]["gm"])
            for y, r in vis:
                if r["roe"] is not None:
                    ind_roe_year[g][y].append(r["roe"])
        ind_gm_med = {g: statistics.median(v) for g, v in ind_gm_year.items() if len(v) >= 5}
        ind_roe_med = {(g, y): statistics.median(v)
                       for g, d in ind_roe_year.items() for y, v in d.items() if len(v) >= 5}

        for c, vis in snap.items():
            g = IND.get(c, "未分类")
            gms = [r["gm"] for _, r in vis if r["gm"] is not None]
            roes = [r["roe"] for _, r in vis if r["roe"] is not None]
            revs = [r["rev"] / 1e8 for _, r in vis if r["rev"]]
            nps = [r["np"] for _, r in vis if r["np"] is not None]
            if len(gms) < 3 or len(revs) < 3 or not nps or revs[-1] < a.min_rev:
                continue
            n = len(revs) - 1
            cagr = (revs[-1] / revs[0]) ** (1 / n) - 1 if revs[0] > 0 else -1.0
            th = 0
            for y, r in vis:
                m = ind_roe_med.get((g, y))
                if m is not None and m < 5.0 and r["np"] and r["np"] > 0 \
                        and r["roe"] is not None and r["roe"] - m >= 10.0:
                    th += 1
            feats[c] = dict(
                gm_level=statistics.median(gms),
                gm_stable=-(statistics.pstdev(gms) if len(gms) > 1 else 99.0),
                gm_vs_ind=(gms[-1] - ind_gm_med[g]) if g in ind_gm_med else 0.0,
                rev_growth=max(-0.5, min(1.5, cagr)),
                gm_hold=gms[-1] - gms[0],
                roe_level=statistics.median(roes) if roes else 0.0,
                trough=float(th),
                scale=math.log10(max(1.0, revs[-1])),
            )
        if not feats:
            continue
        ranks = {k: pct_rank({c: f[k] for c, f in feats.items()}) for k in COMPONENTS}
        score = {c: sum(ranks[k][c] for k in COMPONENTS) / len(COMPONENTS) for c in feats}
        # 已在册的保留名额，新名额给当年得分最高者
        need = quota[Y] - len(admitted)
        if need > 0:
            for c, s in sorted(score.items(), key=lambda kv: -kv[1]):
                if c in admitted:
                    continue
                admitted[c] = Y
                need -= 1
                if need <= 0:
                    break
        if a.dump_scores:
            for c, s in score.items():
                dump.append(dict(year=Y, code=c, name=NAMES.get(c, ""), score=f"{s:.4f}",
                                 **{k: f"{feats[c][k]:.3f}" for k in COMPONENTS}))
        print(f"  {Y}: 在册 {len(admitted)}（名额 {quota[Y]}，候选 {len(feats)}）", flush=True)

    # ---- 验收：对 141 家已知护城河名单的召回与时点 ----
    rec = [(c, wf, nm, rule, admitted.get(c)) for c, (wf, nm, rule) in sorted(moat.items())]
    got = [x for x in rec if x[4] is not None]
    ontime = [x for x in got if x[4] <= x[1]]
    print(f"\n验收（141 家护城河名单，未参与调参）：命中 {len(got)}（{len(got)/len(rec)*100:.0f}%），"
          f"其中**不晚于其判定年** {len(ontime)}（{len(ontime)/len(rec)*100:.0f}%）")
    for key in ("300750", "002594", "603259", "300308", "002714", "688981", "300015",
                "600519", "000333", "600036"):
        if key in moat:
            wf, nm, _ = moat[key]
            got_y = admitted.get(key)
            mark = "✓" if got_y and got_y <= wf else ("迟" if got_y else "✗")
            print(f"  {mark} {nm:<8} 判定 {wf}  本筛 {got_y or '未入选'}")
    inpanel = collections.Counter()
    for c, y in admitted.items():
        inpanel["护城河名单内" if c in moat else "名单外"] += 1
    print(f"入选构成：{dict(inpanel)}")

    if a.dump_scores:
        with open(a.dump_scores, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(dump[0].keys()))
            w.writeheader(); w.writerows(dump)
        print(f"打分明细已写 {a.dump_scores}（{len(dump):,} 行）")

    if a.out and not a.calib:
        HDR = ["effective_from", "effective_to", "screen_year", "security_code",
               "security_name", "avg_roe_3y", "rank"]
        rows = []
        for i, Y in enumerate(years):
            ef, et = f"{Y}-04-30", (f"{years[i+1]}-04-30" if i + 1 < len(years) else "")
            for j, c in enumerate(sorted(c for c, y0 in admitted.items() if y0 <= Y), 1):
                rows.append(dict(effective_from=ef, effective_to=et, screen_year=str(Y),
                                 security_code=c, security_name=NAMES.get(c, ""),
                                 avg_roe_3y="", rank=str(j)))
        with open(a.out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=HDR)
            w.writeheader(); w.writerows(rows)
        print(f"已写 {a.out}（{len(rows):,} 档，{len(admitted)} 只）")


if __name__ == "__main__":
    main()
