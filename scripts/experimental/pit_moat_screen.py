"""逐筛选年、只用当年可得信息，按**护城河判据**重判全市场——不用「ROE 连续几年达标」。

**为什么要另起一套**（回测日志 §12.32）：现行时点面板建自 `verdicts_report_level.csv`，
判据是机械财务门槛（ROE 达标年数、判据 4b 摊薄、判据 4c 需求爆发），
于是宁德时代、比亚迪、药明康德、中际旭创、牧原股份**任何时点都未入选**；
而仓库里另有一份按护城河判的 `verdicts_panel.csv`（141 家），换上去回测 +9.04pp——
但那份是 2026 年判的，**入选侧带后视**，不可实现。本脚本把护城河判据本身机械化。

**时点纪律**：筛选年 Y 的判定只用报告期 ≤ Y−1 且可得日 ≤ Y-04-30 的年报。
可得日 = min(公告日, 法定截止日 Y-04-30)——OI-042 记录了 1998-2015 年公告日系统性后移约一年，
按法规该日数据必然已公开，故封顶不引入前视，只纠正偏移。

**五条签名，各自对应 §5.4 的一条判据**（并联，任一命中即入，一旦入选不再退出——
与 §12.32 的 MOATB 口径一致，看错了也一路持有，避免退出择时的后视）：

  M1 品牌/品类定价权（锚3、锚12）：毛利率长期极高且不塌
  M2 显著高于同业（锚1）：毛利率高出同行业中位一大截且连续
  M3 扩张而毛利不降（判据5②）：营收大幅扩张的同时毛利率守住
  M4 周期抗压（判例6，牧原那一条）：全行业深亏的年份本公司仍然赚钱
  M5 规模龙头（锚6）：营收数倍于同业中位且绝对规模足够

用法：
    python3 pit_moat_screen.py --out <面板CSV> [--calib] [各阈值]
    --calib 只打印对 141 家已知护城河名单的召回与逐年入选规模，不写面板
"""
import csv, glob, collections, statistics, argparse, os, sys, bisect

from pathlib import Path
ROOT = str(Path(__file__).resolve().parents[2])
FIN = f"{ROOT}/data/raw/financials"
SEC = f"{ROOT}/data/raw/a_share_securities.csv"
MOAT = f"{ROOT}/data/archive/pit-judgment-2026-08/verdicts_panel.csv"


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def load_annuals():
    """{代码: {财年: 指标}}，只收年报，可得日按法定截止封顶。"""
    per = collections.defaultdict(dict)
    for f in sorted(glob.glob(f"{FIN}/*-12-31.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            y = r["report_date"][:4]
            nd = r.get("notice_date") or ""
            legal = f"{int(y)+1}-04-30"
            avail = min(nd, legal) if len(nd) == 10 else legal
            per[r["security_code"]][y] = dict(
                avail=avail,
                roe=num(r.get("weightavg_roe")),
                gm=num(r.get("gross_margin")),
                rev=num(r.get("total_operate_income")),
                np=num(r.get("parent_netprofit")),
            )
    return per


def load_industry():
    ind = {}
    with open(SEC, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            ind[r["security_code"]] = (r.get("industry") or "").strip() or "未分类"
    return ind


def visible(rows, Y, back=5):
    """筛选年 Y 可见的财年读数：报告期 ≤ Y−1 且可得日 ≤ Y-04-30。"""
    cut = f"{Y}-04-30"
    out = []
    for y in range(Y - back, Y):
        r = rows.get(str(y))
        if r and r["avail"] <= cut:
            out.append((y, r))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--calib", action="store_true")
    ap.add_argument("--from-year", type=int, default=2009)
    ap.add_argument("--to-year", type=int, default=2026)
    # M1 品牌/品类定价权
    ap.add_argument("--m1-gm-med", type=float, default=50.0)
    ap.add_argument("--m1-gm-min", type=float, default=42.0)
    ap.add_argument("--m1-rev", type=float, default=5.0, help="亿元")
    ap.add_argument("--m1-roe", type=float, default=0.0, help="五年 ROE 中位下限")
    # M2 显著高于同业
    ap.add_argument("--m2-gap", type=float, default=20.0, help="毛利率高出同业中位的百分点")
    ap.add_argument("--m2-years", type=int, default=3)
    ap.add_argument("--m2-rev", type=float, default=10.0)
    # M3 扩张而毛利不降
    ap.add_argument("--m3-cagr", type=float, default=0.20)
    ap.add_argument("--m3-gm-drop", type=float, default=2.0, help="允许的毛利率下滑百分点")
    ap.add_argument("--m3-rev", type=float, default=20.0)
    ap.add_argument("--m3-gm-floor", type=float, default=0.0, help="M3 另要求毛利率最低水平")
    # M4 周期抗压
    ap.add_argument("--m4-gap", type=float, default=10.0, help="ROE 高出同业中位的百分点")
    ap.add_argument("--m4-ind-roe", type=float, default=5.0, help="同业中位 ROE 低于此值才算深谷")
    ap.add_argument("--m4-hits", type=int, default=2, help="需命中的深谷年数")
    ap.add_argument("--m4-rev", type=float, default=20.0)
    # M5 规模龙头
    ap.add_argument("--m5-mult", type=float, default=8.0, help="营收为同业中位的倍数")
    ap.add_argument("--m5-rev", type=float, default=100.0)
    a = ap.parse_args()

    ANN = load_annuals()
    IND = load_industry()
    print(f"年报覆盖 {len(ANN):,} 只｜行业分类 {len(IND):,} 只", flush=True)

    # 已知护城河名单（只用于标定与召回统计，不参与判定）
    moat = {}
    for r in csv.DictReader(open(MOAT, encoding="utf-8")):
        if r["worth_from"] not in ("", "0"):
            moat[r["security_code"]] = (int(r["worth_from"]), r["security_name"], r["rule"])

    admitted = {}          # 代码 -> 首次命中年
    hit_by = collections.Counter()
    per_year = {}

    for Y in range(a.from_year, a.to_year + 1):
        # 行业中位（只用当年可见读数）——同业比较必须与被比较者同一时点
        ind_gm = collections.defaultdict(list)
        ind_roe = collections.defaultdict(list)
        ind_rev = collections.defaultdict(list)
        snap = {}
        for c, rows in ANN.items():
            vis = visible(rows, Y)
            if not vis:
                continue
            snap[c] = vis
            last = vis[-1][1]
            g = IND.get(c, "未分类")
            if last["gm"] is not None: ind_gm[g].append(last["gm"])
            if last["roe"] is not None: ind_roe[g].append(last["roe"])
            if last["rev"]: ind_rev[g].append(last["rev"] / 1e8)
        med = lambda d, g: statistics.median(d[g]) if len(d.get(g, ())) >= 5 else None

        # 逐年各深谷年的行业中位 ROE（M4 要按年比）
        trough = {}
        for c, vis in snap.items():
            for y, r in vis:
                g = IND.get(c, "未分类")
                trough.setdefault((g, y), []).append(r["roe"])
        trough_med = {k: statistics.median([x for x in v if x is not None])
                      for k, v in trough.items() if len([x for x in v if x is not None]) >= 5}

        for c, vis in snap.items():
            if c in admitted:
                continue
            g = IND.get(c, "未分类")
            gms = [r["gm"] for _, r in vis if r["gm"] is not None]
            roes = [r["roe"] for _, r in vis if r["roe"] is not None]
            revs = [r["rev"] / 1e8 for _, r in vis if r["rev"]]
            nps = [r["np"] for _, r in vis if r["np"] is not None]
            if not revs or not nps or nps[-1] <= 0:
                continue
            rev_last = revs[-1]
            hits = []

            # M1 品牌/品类定价权（锚3、锚12）
            if len(gms) >= 3 and statistics.median(gms) >= a.m1_gm_med \
                    and min(gms) >= a.m1_gm_min and rev_last >= a.m1_rev \
                    and (not roes or statistics.median(roes) >= a.m1_roe):
                hits.append("M1")

            # M2 显著高于同业（锚1）
            gmed = med(ind_gm, g)
            if gmed is not None and len(gms) >= a.m2_years and rev_last >= a.m2_rev:
                recent = gms[-a.m2_years:]
                if len(recent) == a.m2_years and all(x - gmed >= a.m2_gap for x in recent):
                    hits.append("M2")

            # M3 扩张而毛利不降（判据5②）。**毛利水平也要够**——否则「规模扩张 + 低毛利」
            # 的代工与工程类会大量涌入，那不是护城河而是需求景气。
            if len(revs) >= 4 and len(gms) >= 4 and rev_last >= a.m3_rev and revs[0] > 0:
                n = len(revs) - 1
                cagr = (revs[-1] / revs[0]) ** (1 / n) - 1
                if cagr >= a.m3_cagr and gms[-1] >= gms[0] - a.m3_gm_drop \
                        and min(gms) >= a.m3_gm_floor:
                    hits.append("M3")

            # M4 周期抗压（判例6）
            if rev_last >= a.m4_rev:
                n_hit = 0
                for y, r in vis:
                    m = trough_med.get((g, y))
                    if m is None or r["roe"] is None or r["np"] is None:
                        continue
                    if m < a.m4_ind_roe and r["np"] > 0 and r["roe"] - m >= a.m4_gap:
                        n_hit += 1
                if n_hit >= a.m4_hits:
                    hits.append("M4")

            # M5 规模龙头（锚6）
            rmed = med(ind_rev, g)
            if rmed and rev_last >= a.m5_rev and rev_last >= a.m5_mult * rmed:
                hits.append("M5")

            if hits:
                admitted[c] = Y
                for h in hits:
                    hit_by[h] += 1

        per_year[Y] = sum(1 for v in admitted.values() if v <= Y)
        print(f"  {Y}: 累计在册 {per_year[Y]}", flush=True)

    print(f"\n签名命中分布（按首次入选那年计）: {dict(hit_by)}")
    print(f"总入选 {len(admitted)} 只")

    # ---- 对 141 家已知护城河名单的召回 ----
    rec = [(c, wf, nm, rule, admitted.get(c)) for c, (wf, nm, rule) in sorted(moat.items())]
    got = [x for x in rec if x[4] is not None]
    ontime = [x for x in got if x[4] <= x[1]]
    print(f"\n对 141 家已知护城河名单：命中 {len(got)}/{len(rec)}（{len(got)/len(rec)*100:.0f}%），"
          f"其中不晚于其判定入选年的 {len(ontime)}（{len(ontime)/len(rec)*100:.0f}%）")
    miss = [x for x in rec if x[4] is None]
    print(f"漏掉 {len(miss)} 家，前 20：" + "｜".join(f"{x[2]}({x[3]})" for x in miss[:20]))
    late = sorted([x for x in got if x[4] > x[1]], key=lambda x: -(x[4] - x[1]))[:10]
    print(f"晚于判定年最多的：" + "｜".join(f"{x[2]} {x[1]}→{x[4]}" for x in late))
    for key in ("300750", "002594", "603259", "300308", "002714", "688981", "300015"):
        if key in moat:
            wf, nm, rule = moat[key]
            print(f"  {nm:<8} 判定 {wf}  本筛 {admitted.get(key, '未入选')}")

    if a.out and not a.calib:
        HDR = ["effective_from", "effective_to", "screen_year", "security_code",
               "security_name", "avg_roe_3y", "rank"]
        nm_all = {}
        with open(SEC, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                nm_all[r["security_code"]] = r.get("security_name", "")
        years = list(range(a.from_year, a.to_year + 1))
        rows = []
        for i, Y in enumerate(years):
            ef = f"{Y}-04-30"
            et = f"{years[i+1]}-04-30" if i + 1 < len(years) else ""
            mem = sorted(c for c, y0 in admitted.items() if y0 <= Y)
            for j, c in enumerate(mem, 1):
                rows.append(dict(effective_from=ef, effective_to=et, screen_year=str(Y),
                                 security_code=c, security_name=nm_all.get(c, ""),
                                 avg_roe_3y="", rank=str(j)))
        with open(a.out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=HDR)
            w.writeheader(); w.writerows(rows)
        print(f"\n已写 {a.out}（{len(rows):,} 档，{len(admitted)} 只）")


if __name__ == "__main__":
    main()
