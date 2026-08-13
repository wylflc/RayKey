"""重判档案：按**用户三问**重排信息，并修掉时点重判（§12.34）暴露的两处口径缺陷。

§12.35 审出的缺陷：
  1. **对照组错**。原档案的「同业中位」取自 `a_share_securities.csv` 的 `industry` 字段，
     那是**门类**级——「C 制造业」一个桶 2,021 家，中际旭创/宁德时代/比亚迪/格力同桶。
     本脚本改用 `judgment_log.csv` 的 `business_desc_at_period` 首段（106 个细分桶，覆盖 802/802），
     并在桶内不足 5 家时显式标注「对照组过小，不可用」而非静默回退。
  2. **窗口错**。原档案把历史切成早/中/近三段并要求段段超额，
     等于要求「一直很强」；而 bloom 队列的 T2 触发选的正是「最近变强」。两层互相抵消。
     本脚本改为标注**业务变更年**（营收单年跳升 ≥3 倍视为借壳/重组），
     变更年之前的读数单独标灰，不参与「有没有护城河」的判断。

档案按三问组织，财务只作**佐证**不作判据：
  Q1 有没有护城河    → 扩张期毛利率轨迹、同细分行业内的位次
  Q2 会不会被挑战    → 同细分行业内的家数与本公司份额代理（营收占桶内合计）
  Q3 发展会不会被限制 → 营收是否仍在增长、行业桶整体是否在增长

用法：
    python3 build_rejudge_dossiers.py --codes <代码清单> --out <档案>
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
    ap.add_argument("--codes", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    ann = collections.defaultdict(dict)
    for f in sorted(glob.glob(f"{FIN}/*-12-31.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            ann[r["security_code"]][int(r["report_date"][:4])] = dict(
                roe=num(r.get("weightavg_roe")), gm=num(r.get("gross_margin")),
                rev=num(r.get("total_operate_income")), np=num(r.get("parent_netprofit")))
    with open(SEC, encoding="utf-8-sig") as fh:
        NAME = {r["security_code"]: r.get("security_name", "") for r in csv.DictReader(fh)}

    # ---- 细分行业键：judgment_log 的业务描述首段（「制造业-汽车制造业」这一级）----
    fine, desc = {}, collections.defaultdict(list)
    for r in csv.DictReader(open(f"{PIT}/judgment_log.csv", encoding="utf-8")):
        t = (r.get("business_desc_at_period") or "").strip()
        if not t:
            continue
        fine[r["security_code"]] = t.split("｜")[0]
        desc[r["security_code"]].append((r["as_of_year"], t))
    for c in desc:
        desc[c].sort()

    gm_all, roe_all, rev_all = (collections.defaultdict(list) for _ in range(3))
    for c, yrs in ann.items():
        g = fine.get(c)
        if not g:
            continue
        for y, r in yrs.items():
            if r["gm"] is not None: gm_all[(g, y)].append(r["gm"])
            if r["roe"] is not None: roe_all[(g, y)].append(r["roe"])
            if r["rev"]: rev_all[(g, y)].append(r["rev"])
    med = lambda d: {k: statistics.median(v) for k, v in d.items() if len(v) >= 5}
    gm_med, roe_med = med(gm_all), med(roe_all)
    bucket_n = collections.Counter(g for g in fine.values())

    want = [ln.strip().zfill(6) for ln in open(a.codes, encoding="utf-8") if ln.strip()]
    out = []
    for c in want:
        yrs = ann.get(c) or {}
        ys = sorted(y for y in yrs if yrs[y]["rev"])
        if len(ys) < 4:
            continue
        g = fine.get(c, "?")
        ds = desc.get(c) or []
        # 业务变更年：营收单年跳升 ≥3 倍
        chg = [y for y in ys[1:] if (y - 1) in yrs and yrs[y]["rev"] and yrs[y - 1]["rev"]
               and yrs[y]["rev"] >= 3 * yrs[y - 1]["rev"]]
        base = chg[-1] if chg else ys[0]
        cur = [y for y in ys if y >= base]

        head = f"### {c} {NAME.get(c,'')}｜{g}（桶内 {bucket_n[g]} 家）"
        if chg:
            head += f"｜⚠业务变更年 {chg[-1]}，此前读数属另一家公司，不计入判断"
        lines = [head]
        for y0, t in ds[:1] + (ds[-1:] if len(ds) > 1 else []):
            lines.append(f"  [{y0}] {t}")

        def seg(w, lbl):
            if not w:
                return None
            rv = [yrs[y]["rev"] / 1e8 for y in w if yrs[y]["rev"]]
            dg = [yrs[y]["gm"] - gm_med[(g, y)] for y in w
                  if yrs[y]["gm"] is not None and (g, y) in gm_med]
            dr = [yrs[y]["roe"] - roe_med[(g, y)] for y in w
                  if yrs[y]["roe"] is not None and (g, y) in roe_med]
            gm = [yrs[y]["gm"] for y in w if yrs[y]["gm"] is not None]
            pos = sum(1 for y in w if (yrs[y]["np"] or 0) > 0)
            sh = []
            for y in w:
                tot = sum(rev_all.get((g, y)) or [])
                if tot and yrs[y]["rev"]:
                    sh.append(yrs[y]["rev"] / tot * 100)
            f = lambda v, d=0: (f"{statistics.median(v):+.{d}f}" if v else "n/a")
            return (f"  {lbl} {w[0]}-{w[-1]}｜营收 {rv[0]:.0f}→{rv[-1]:.0f}亿"
                    f"｜毛利 {(gm[0] if gm else 0):.0f}→{(gm[-1] if gm else 0):.0f}%"
                    f"｜毛利差{f(dg)} ROE差{f(dr)}"
                    f"｜桶内营收份额 {(statistics.median(sh) if sh else 0):.1f}%"
                    f"｜盈利 {pos}/{len(w)}")

        s = seg(cur, "现业务")
        if s:
            lines.append(s)
        if chg and len([y for y in ys if y < base]) >= 2:
            s0 = seg([y for y in ys if y < base], "（旧业务·仅备查）")
            if s0:
                lines.append(s0)
        if bucket_n[g] < 5:
            lines.append("  ⚠对照组过小，毛利差/ROE差不可用，只看绝对轨迹")
        out.append("\n".join(lines))

    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("# 重判档案（细分行业对照组｜业务变更年已标注）\n"
                 "# 判据顺序：Q1 有没有护城河 → Q2 会不会被挑战 → Q3 发展会不会被限制。\n"
                 "# 财务只作佐证：毛利差/ROE差用于确认壁垒是否**已经**变现，不作为壁垒存在与否的判据。\n\n")
        fh.write("\n\n".join(out))
    print(f"已写 {a.out}（{len(out)} 只）")


if __name__ == "__main__":
    main()
