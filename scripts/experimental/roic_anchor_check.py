"""ROIC 口径的锚点定标（§12.67）：用公认时点的公认结论给指标变体打分。

方法（用户 2026-08-15 指令）：不先跑全局回测，而是选一组**市场后来给出过明确裁决**的
「关键公司 × 关键时点」当锚点——塑化剂后的茅台、2016 年的煤炭水泥底、2021 年初的
赛道股顶——要求指标在这些点上读对方向；按锚点修好指标后，再回到 23 起点全局验证。

锚点入选标准（三条都要满足，避免用后视当共识）：
1. **当时就有公开的估值争议或极端读数**（PE 个位数／PE 上百），不是事后才显得极端；
2. 其后三年的市场走向给出了明确裁决；
3. 公司在 V5 面板内且非金融（银行走股利折现覆盖，不在本口径的定标范围）。

打分（无阈值、免标度，变体之间可直接比）：
- **配对正确率**：所有（低估锚, 高估锚）配对里 P/V(低估) < P/V(高估) 的比例（AUC）；
- **Spearman(P/V, 前向3年收益)**：越负越好（P/V 低 → 未来收益高）；
- 分组中位 P/V 与分离度，另列出两侧的读错名单。

前向收益按送转折算（复权），**不含分红**——对神华一类高股息锚点会低估其裁决强度，读数时记住。

用法：
    python3 scripts/experimental/roic_anchor_check.py --variants v1 v2 v3
    python3 scripts/experimental/roic_anchor_check.py --bands <现成带文件> --tag 某变体
"""
import argparse
import csv
import itertools
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_historical_valuation_bands as bhv  # noqa: E402  (只用其数据装载函数)

PY = sys.executable
SCRATCH = Path("/private/tmp/claude-501/-Users-yaleiwang-WorkSpace-AgentLab-RayKey/"
               "81d2c992-2d15-4712-a049-e294cf756ff3/scratchpad")

# (代码, 名称, 报告期, 共识, 当时的公开依据)
ANCHORS = [
    # ---------------- 公认低估 ----------------
    ("600519", "贵州茅台", "2013-12-31", "低估", "塑化剂+限三公后 PE~9，2014 全年争议'白酒还有没有未来'"),
    ("000858", "五粮液", "2013-12-31", "低估", "同轮白酒危机，PE~7"),
    ("600519", "贵州茅台", "2018-12-31", "低估", "2018Q3 单季增速骤降跌停后 PE~20，2019 初分歧极大"),
    ("000858", "五粮液", "2018-12-31", "低估", "2018 大跌后 PE~15"),
    ("000568", "泸州老窖", "2018-12-31", "低估", "同上，PE~17"),
    ("000333", "美的集团", "2018-12-31", "低估", "2018-10 跌至 PE~10，家电悲观顶点"),
    ("002415", "海康威视", "2018-12-31", "低估", "贸易战实体清单恐慌，PE~17"),
    ("000651", "格力电器", "2015-12-31", "低估", "2015 股灾+渠道去库存后 PE~8"),
    ("601088", "中国神华", "2015-12-31", "低估", "煤价大底，破净+股息率>5%"),
    ("600585", "海螺水泥", "2015-12-31", "低估", "水泥利润底，PB~1.1"),
    ("600309", "万华化学", "2015-12-31", "低估", "MDI 价格底部，周期低点 PE 看似高实则底"),
    ("600887", "伊利股份", "2015-12-31", "低估", "股灾后 PE~15，龙头份额仍在提升"),
    ("601001", "晋控煤业", "2021-12-31", "低估", "煤价新中枢已现而估值仍按旧周期，PE~4"),
    ("000933", "神火股份", "2021-12-31", "低估", "电解铝+煤双主业重估前夜，PE~5"),
    # ---------------- 公认高估（含低 PE 陷阱） ----------------
    ("600519", "贵州茅台", "2020-12-31", "高估", "2021-02 见顶 2627，PE~70，'yyds'情绪顶"),
    ("300750", "宁德时代", "2021-12-31", "高估", "2021-12 见顶 690，PE~150，'宁指数'"),
    ("603259", "药明康德", "2021-12-31", "高估", "CXO 景气顶，PE~100"),
    ("300760", "迈瑞医疗", "2020-12-31", "高估", "2021 中见顶 ~500，PE~90"),
    ("002812", "恩捷股份", "2021-12-31", "高估", "隔膜产能扩张顶点 PE~70，其后 −85%"),
    ("000568", "泸州老窖", "2020-12-31", "高估", "白酒抱团顶，PE~60"),
    ("603288", "海天味业", "2020-12-31", "高估", "PE~100 的'酱油茅'，其后 −70%"),
    ("600276", "恒瑞医药", "2020-12-31", "高估", "PE~90 集采前夜，其后 −60%"),
    ("000661", "长春高新", "2020-12-31", "高估", "生长激素单品 PE~50，2021-05 见顶后 −80%"),
    ("002714", "牧原股份", "2020-12-31", "高估", "猪周期利润顶，PE~10 的周期陷阱"),
    ("600507", "方大特钢", "2018-12-31", "高估", "钢铁利润顶，PE~5 的周期陷阱"),
    ("300308", "中际旭创", "2018-12-31", "高估", "壳重组后商誉高企，光模块景气回落"),
]

# 银行锚点：**只用于给生产基准（DCF + 银行股利折现覆盖）打分**，不进 ROIC 变体的打分——
# 框架 §6 规定金融企业不走 ROIC 口径，变体在银行上退回的是权益 DCF 而非生产的股利折现，
# 给变体按银行打分会把「没实现的东西」错算成它的成绩。
BANK_ANCHORS = [
    ("601166", "兴业银行", "2013-12-31", "低估", "破净+PE~4.5，2014'银行股还有没有人要'大讨论，当年Q4起大涨"),
    ("601939", "建设银行", "2013-12-31", "低估", "四大行集体破净，股息率~7%"),
    ("600036", "招商银行", "2020-12-31", "高估", "'银茅'抱团顶，PB~2 创十年新高，2021-02 见顶后三年腰斩"),
]

VARIANT_FLAGS = {
    "v1": [],
    # v2：只修「稳定性缺陷」——IC 下限 + NOPAT 单边（含周期守卫），g 仍走资本口径
    "v2": ["--roic-ic-floor", "0.25", "--roic-nopat-source", "onesided_max"],
    # v3：v2 + 增长两条腿取大（资本自由的增长不再判 0）
    "v3": ["--roic-ic-floor", "0.25", "--roic-nopat-source", "onesided_max",
           "--roic-growth", "hybrid"],
    # v3h：同 v3 但利润增速那条腿减半，测剂量
    "v3h": ["--roic-ic-floor", "0.25", "--roic-nopat-source", "onesided_max",
            "--roic-growth", "hybrid", "--roic-trail-weight", "0.5"],
    # v4：只开 hybrid，不动分子——隔离两组修改各自的贡献
    "v4": ["--roic-growth", "hybrid"],
    # v5：hybrid + peak 守卫（当前比率>K×十年中位才判周期，替换打错目标的单调度守卫）
    "v5a": ["--roic-growth", "hybrid", "--roic-cycle-guard", "peak", "--roic-peak-k", "1.5"],
    "v5b": ["--roic-growth", "hybrid", "--roic-cycle-guard", "peak", "--roic-peak-k", "2.0"],
    # DCF 侧（§12.68）：dcf = 生产口径复现（非银行应与「生产基准」列一致，作自检）；
    # dcf_guard = 生产口径 + peak 守卫（利润顶不做 λ=2 单边上抬），检验牧原/方大两类错读能否修掉
    "dcf": ["--value-model", "dcf"],
    "dcf_guard": ["--value-model", "dcf", "--dcf-peak-guard", "1.5"],
}


def build_variant(tag: str, flags: list[str]) -> Path:
    out = SCRATCH / f"anchor_bands_{tag}.csv"
    # 银行代码也建带——只为拿到 available_at（银行走 equity_fallback，其值不进变体打分）
    codes = ",".join(sorted({a[0] for a in ANCHORS + BANK_ANCHORS}))
    cmd = [PY, str(ROOT / "scripts/build_historical_valuation_bands.py"),
           "--codes", codes,
           "--roe-source", "onesided_max", "--roe-lift", "2.0", "--uniform-tier", "L2",
           "--since", "2012-01-01", "--out-bands", str(out), *flags]
    if "--value-model" not in flags:
        cmd += ["--value-model", "roic"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{tag} 建带失败：\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return out


def price_at(prices, day, forward=False):
    """`forward=False`: 首个 ≥ day 的交易日；True: 最后一个 ≤ day 的交易日。"""
    if forward:
        cand = [p for p in prices if p[0] <= day]
        return cand[-1] if cand else None
    cand = [p for p in prices if p[0] >= day]
    return cand[0] if cand else None


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="*", default=["v1", "v2", "v3", "v3h", "v4"])
    ap.add_argument("--bands", type=Path, help="用现成带文件替代重建（配 --tag）")
    ap.add_argument("--tag", default="custom")
    a = ap.parse_args()

    all_anchors = ANCHORS + BANK_ANCHORS
    codes = sorted({x[0] for x in all_anchors})
    prices = {c: bhv.load_ohlcv(c) for c in codes}
    actions = bhv.load_actions()

    # 每个锚点的价格日、前向 3 年复权收益、DCF 参照 P/V（都与变体无关，先算一次）
    fixed = {}
    for code, name, period, label, note in all_anchors:
        fixed[(code, period)] = None
    dcf_pv = {}

    variant_bands = {}
    if a.bands:
        variant_bands[a.tag] = a.bands
    else:
        for tag in a.variants:
            variant_bands[tag] = build_variant(tag, VARIANT_FLAGS[tag])
            print(f"  {tag} 带已建")

    # 各变体的 (code, period) → (available_at, value)
    readings = {}
    for tag, path in variant_bands.items():
        rd = {}
        with path.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                key = (r["security_code"].zfill(6), r["report_date"])
                if key in fixed and r["status"] == "ok":
                    rd[key] = r
        readings[tag] = rd

    # 价格日按「全变体一致」取：available_at 理论上不因变体而变（同一份财报）
    any_tag = next(iter(readings))
    rows = []
    for code, name, period, label, note in all_anchors:
        band = readings[any_tag].get((code, period))
        if band is None:
            rows.append((code, name, period, label, note, None, None, None))
            continue
        p0 = price_at(prices[code], band["available_at"])
        fwd_day = f"{int(band['available_at'][:4]) + 3}{band['available_at'][4:]}"
        p3 = price_at(prices[code], fwd_day, forward=True)
        fwd = None
        if p0 and p3 and p3[0] > p0[0]:
            factor = bhv.split_factor(actions.get(code, []), p0[0], p3[0])
            fwd = p3[1] * factor / p0[1] - 1
        rows.append((code, name, period, label, note, band["available_at"],
                     p0[1] if p0 else None, fwd))

    # DCF 参照：采纳逐日状态在价格日的 valuation_ratio
    want = {(c, r[5]) for c, r in zip((x[0] for x in ANCHORS), rows) if r[5]}
    want = set()
    for r in rows:
        if r[5] and r[6] is not None:
            p0 = price_at(prices[r[0]], r[5])
            want.add((r[0], p0[0]))
    with (ROOT / "data/processed/a_share_daily_states_adopted.csv").open(encoding="utf-8") as fh:
        for rr in csv.DictReader(fh):
            k = (rr["security_code"].zfill(6), rr["date"])
            if k in want:
                dcf_pv[k] = float(rr["valuation_ratio"])

    # ---------------- 逐变体报表 ----------------
    print(f"\n锚点 {len(ANCHORS)} 个（低估 {sum(1 for x in ANCHORS if x[3]=='低估')}"
          f"／高估 {sum(1 for x in ANCHORS if x[3]=='高估')}）")
    summary = []
    for tag in variant_bands:
        rd = readings[tag]
        print(f"\n{'=' * 108}\n变体 {tag}"
              + (f"（{' '.join(VARIANT_FLAGS[tag])}）" if tag in VARIANT_FLAGS and VARIANT_FLAGS[tag] else "（v1 缺省）")
              + f"\n{'=' * 108}")
        print(f"{'公司':<10}{'报告期':<12}{'共识':<5}{'P/V':>7}{'DCF参照':>8}{'前向3年':>9}"
              f"{'路径':>13}{'分子':>16}{'g来源':>9}{'g0':>7}  判定")
        pvs, fwds, labels = [], [], []
        cheap_miss, exp_miss = [], []
        bank_keys = {(c, p) for c, _n, p, _l, _w in BANK_ANCHORS}
        for (code, name, period, label, note, avail, p0, fwd) in rows:
            if (code, period) in bank_keys:
                continue          # 银行不进变体打分（见 BANK_ANCHORS 注释）
            band = rd.get((code, period))
            if band is None or p0 is None:
                print(f"{name:<10}{period:<12}{label:<5}{'—':>7}   （无带或无价格）")
                continue
            pv = p0 / float(band["intrinsic_value"])
            k0 = price_at(prices[code], avail)
            dref = dcf_pv.get((code, k0[0]))
            ok = (pv <= 1.0) if label == "低估" else (pv >= 1.5)
            mark = "✓" if ok else ("✗ 读成贵" if label == "低估" else "✗ 读成便宜")
            if not ok:
                (cheap_miss if label == "低估" else exp_miss).append(name + period[:4])
            g0 = band.get("g0")
            print(f"{name:<10}{period:<12}{label:<5}{pv:>7.2f}"
                  f"{dref if dref is not None else float('nan'):>8.2f}"
                  f"{fwd * 100 if fwd is not None else float('nan'):>8.0f}%"
                  f"{band['roic_path']:>13}{band.get('roic_nopat_mode') or '—':>16}"
                  f"{band.get('roic_g_source') or '—':>9}"
                  f"{float(g0) * 100 if g0 not in (None, '', 'None') else float('nan'):>6.1f}%  {mark}")
            pvs.append(pv)
            labels.append(label)
            if fwd is not None:
                fwds.append((pv, fwd))
        cheap = [p for p, l in zip(pvs, labels) if l == "低估"]
        exp = [p for p, l in zip(pvs, labels) if l == "高估"]
        pairs = [(c, e) for c, e in itertools.product(cheap, exp)]
        auc = sum(1 for c, e in pairs if c < e) / len(pairs) if pairs else float("nan")
        rho = spearman([x for x, _ in fwds], [y for _, y in fwds]) if len(fwds) > 2 else float("nan")
        print(f"\n  配对正确率（低估P/V < 高估P/V）：**{auc:.1%}**（{len(pairs)} 对）"
              f"｜Spearman(P/V, 前向3年)：**{rho:+.3f}**"
              f"｜低估组中位 {statistics.median(cheap):.2f} vs 高估组中位 {statistics.median(exp):.2f}"
              f"（分离 {statistics.median(exp) / statistics.median(cheap):.2f}×）")
        if cheap_miss:
            print(f"  低估读错（P/V>1.0）：{'、'.join(cheap_miss)}")
        if exp_miss:
            print(f"  高估读错（P/V<1.5）：{'、'.join(exp_miss)}")
        summary.append((tag, auc, rho))

    # ---------------- 生产基准自身的成绩单 ----------------
    # P/V 取自 §9.3.1.2 采纳的逐日状态（--uniform-tier L2、λ=2.0、银行股利折现覆盖），
    # 即回测与每日扫描**实际消费**的那一列——不是重算，是审计。
    bank_keys = {(c, p) for c, _n, p, _l, _w in BANK_ANCHORS}
    print(f"\n{'=' * 108}\n生产基准（§9.3.1.2 采纳口径：DCF L2 λ=2.0 ＋ 银行股利折现）"
          f"\n{'=' * 108}")
    print(f"{'公司':<10}{'报告期':<12}{'共识':<5}{'P/V':>7}{'前向3年':>9}  判定")
    core_pvs, core_labels = [], []
    all_pvs, all_labels, fwd_pairs = [], [], []
    cheap_miss, exp_miss = [], []
    for (code, name, period, label, note, avail, p0, fwd) in rows:
        if avail is None or p0 is None:
            continue
        k0 = price_at(prices[code], avail)
        pv = dcf_pv.get((code, k0[0]))
        if pv is None:
            print(f"{name:<10}{period:<12}{label:<5}{'—':>7}   （采纳逐日状态无该日读数）")
            continue
        is_bank = (code, period) in bank_keys
        ok = (pv <= 1.0) if label == "低估" else (pv >= 1.5)
        mark = ("✓" if ok else ("✗ 读成贵" if label == "低估" else "✗ 读成便宜")) \
            + ("（银行）" if is_bank else "")
        if not ok:
            (cheap_miss if label == "低估" else exp_miss).append(name + period[:4])
        print(f"{name:<10}{period:<12}{label:<5}{pv:>7.2f}"
              f"{fwd * 100 if fwd is not None else float('nan'):>8.0f}%  {mark}")
        all_pvs.append(pv)
        all_labels.append(label)
        if not is_bank:
            core_pvs.append(pv)
            core_labels.append(label)
        if fwd is not None:
            fwd_pairs.append((pv, fwd))

    def auc_of(vals, labs):
        cheap = [p for p, l in zip(vals, labs) if l == "低估"]
        exp = [p for p, l in zip(vals, labs) if l == "高估"]
        pairs = [(c, e) for c in cheap for e in exp]
        return (sum(1 for c, e in pairs if c < e) / len(pairs), len(pairs),
                statistics.median(cheap), statistics.median(exp))

    auc_c, n_c, med_lo, med_hi = auc_of(core_pvs, core_labels)
    auc_a, n_a, _, _ = auc_of(all_pvs, all_labels)
    rho = spearman([x for x, _ in fwd_pairs], [y for _, y in fwd_pairs]) \
        if len(fwd_pairs) > 2 else float("nan")
    print(f"\n  核心 26 锚（与 ROIC 变体同口径可比）：配对正确率 **{auc_c:.1%}**（{n_c} 对）"
          f"｜低估组中位 {med_lo:.2f} vs 高估组中位 {med_hi:.2f}")
    print(f"  含银行 {len(all_pvs)} 锚：配对正确率 **{auc_a:.1%}**（{n_a} 对）"
          f"｜Spearman(P/V, 前向3年) **{rho:+.3f}**（银行前向收益不含分红，被低估）")
    if cheap_miss:
        print(f"  低估读错（P/V>1.0）：{'、'.join(cheap_miss)}")
    if exp_miss:
        print(f"  高估读错（P/V<1.5）：{'、'.join(exp_miss)}")
    summary.append(("生产基准·核心26", auc_c, rho))

    print(f"\n{'=' * 60}\n汇总")
    for tag, auc, rho in summary:
        print(f"  {tag:<12} 配对正确率 {auc:.1%}｜Spearman {rho:+.3f}")


if __name__ == "__main__":
    main()
