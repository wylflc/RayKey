#!/usr/bin/env python3
"""OI-148 执行成本压力档位报告（每边滑点 0／10／20／30bp）。

读 `<exp>/sweep_tiers.txt`（全样本＋剔除集 A，A 由 0bp 的 BASE 锚点自动取）与 `<exp>/sweep_tiers_U.txt`
（剔除集 U 按 0bp 锚点固定单遍），出五段：
  1. 0bp 逐位复现：14 起点 × 全部列对 `exp_metric_m2/sweep.txt` 同臂同起点逐值核对；2011 锚点产物逐字节核对；
  2. 各档 BASE 成本表：水平（各起点再取中位）＋对 0bp 的逐起点配对差中位，全样本与 A 各一份；
  3. 各档候选（BUY2）与同档 BASE 配对：§12.1 第 2 款五项决策读数与判定，A／U 均按 0bp 锚点固定；
  4. 第 4 款 U 全面性：标准指标集各项配对差，比率项按两种读法（OI-151：两位小数显示 0.005／字面 0.0015）；
  5. 成交价核对：2011 锚点 0bp 与 30bp 成交流水首批同笔成交的价格比（买 1.003／卖 0.997）。
不预设任何档位为否决线；只报读数与判定变化。"""
import argparse
import csv
import filecmp
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sweep  # noqa: E402

TIERS = (0, 10, 20, 30)
NAN = float("nan")
DISPLAY_TOL = 0.005      # 比率项「两位小数显示」读法：|Δ| < 0.005 视为不劣
STRICT_TOL = 0.0015      # 比率项字面读法：与 pp 项同用 0.0015


def base_label(t: int) -> str:
    return "BASE" if t == 0 else f"S{t}"


def cand_label(t: int) -> str:
    return "BUY2" if t == 0 else f"BUY2_S{t}"


def level(arms, label, key):
    arm = arms.get(label)
    if not arm:
        return NAN
    vals = [v[key] for v in arm.values() if v[key] == v[key]]
    return statistics.median(vals) if vals else NAN


def paired(arms, label, ref, key):
    a, b = arms.get(label), arms.get(ref)
    if not a or not b:
        return NAN
    common = [s for s in a if s in b]
    return statistics.median(a[s][key] - b[s][key] for s in common) if common else NAN


def positives(arms, label, ref, key, good):
    a, b = arms.get(label), arms.get(ref)
    if not a or not b:
        return "—"
    common = [s for s in a if s in b]
    return f"{sum(1 for s in common if (a[s][key] - b[s][key]) * good > 0)}/{len(common)}"


def fmt(x, scale=100.0, prec=2):
    return "—" if x != x else f"{x * scale:.{prec}f}"


def sfmt(x, scale=100.0, prec=2):
    return "—" if x != x else f"{x * scale:+.{prec}f}"


def verdict(arms_all, arms_ex, label, ref):
    """§12.1 第 2 款：主读数／复利读数两表各取；闸门／否决取全样本。与 sweep._print_verdicts 同式，对照臂可指定。"""
    vals = {}
    for name, key in sweep.VERDICT_KEYS:
        vals[name] = (paired(arms_all, label, ref, key), paired(arms_ex, label, ref, key))
    verdict_, reasons = "可采纳", []
    for name, (a, e) in vals.items():
        if a != a or e != e:
            return "不可判", [f"{name}缺表"], vals
        lo, hi = min(a, e), max(a, e)
        if lo < -sweep.RULING_TOLERANCE:
            verdict_ = "不采纳"; reasons.append(f"{name} {lo*100:+.2f}pp < −{sweep.RULING_TOLERANCE*100:.0f}pp"); break
        if lo < -sweep.NOISE_BAND:
            if hi >= sweep.CLEAR_GAIN and verdict_ != "不采纳":
                verdict_ = "报用户裁定"; reasons.append(f"{name}两表反向（{a*100:+.2f}／{e*100:+.2f}）")
            else:
                verdict_ = "不采纳"; reasons.append(f"{name}一表 {lo*100:+.2f}pp 而另一表不到 +{sweep.CLEAR_GAIN*100:.0f}pp"); break
    a, b = arms_all.get(label, {}), arms_all.get(ref, {})
    common = [s for s in a if s in b]
    if common and verdict_ != "不可判":
        dd = statistics.median(a[s]["滚动5年回撤中位"] - b[s]["滚动5年回撤中位"] for s in common)
        neg_up = sum(1 for s in common if a[s]["滚动5年为负的窗口占比"] > b[s]["滚动5年为负的窗口占比"])
        if dd > sweep.DRAWDOWN_GATE:
            verdict_ = "不采纳"; reasons.append(f"闸门：回撤 Δ {dd*100:+.1f}pp")
        if neg_up > len(common) / 2:
            verdict_ = "不采纳"; reasons.append(f"否决：负窗↑ {neg_up}/{len(common)}")
    return verdict_, reasons, vals


def clause4(arms_u, label, ref):
    """第 4 款 U 全面性：pp 项阈值 0.0015；比率项按显示读法（0.005）与字面读法（0.0015）各判一次。返回两种读法的 (通过?, 越带项)。"""
    out = {}
    for mode, ratio_tol in (("显示读法", DISPLAY_TOL), ("字面读法", STRICT_TOL)):
        bad, worse = [], []
        for name, key, scale, _w, _p, good in sweep.STANDARD_SET:
            if name in ("换手", "仓位"):
                continue
            d = paired(arms_u, label, ref, key)
            if d != d:
                bad.append(f"{name}缺"); continue
            d_good = d * good
            tol = ratio_tol if scale == 1 else sweep.NOISE_BAND
            if d_good < -tol:
                worse.append((name, d_good, scale))
        # 第 4 款：均 ≥ −tol，或至多一项落在 [−1pp, −0.15pp)（比率项按各自阈值的同倍放宽）
        ok = not bad and (len(worse) == 0 or (len(worse) == 1 and all(
            (d >= -sweep.RULING_TOLERANCE) if scale != 1 else (d >= -ratio_tol / sweep.NOISE_BAND * sweep.RULING_TOLERANCE)
            for _n, d, scale in worse)))
        out[mode] = (ok, [f"{n} {d*(100 if sc != 1 else 1):+.{2 if sc != 1 else 4}f}{'pp' if sc != 1 else ''}" for n, d, sc in worse] + bad)
    return out


def identity(exp: Path, say):
    ref_path = ROOT / "data/experiments/exp_metric_m2/sweep.txt"
    say("## 1. 0bp 逐位复现")
    if not ref_path.exists():
        say(f"  参照 {ref_path} 不存在，跳过读数核对"); return
    g_new, *_ = sweep.load_scan(exp / "sweep_tiers.txt")
    g_ref, *_ = sweep.load_scan(ref_path)
    worst, n = 0.0, 0
    for grp in ("", sweep.EX5_PREFIX):
        for label in ("BASE", "BUY2"):
            a, b = g_new[grp].get(label, {}), g_ref[grp].get(label, {})
            for start in sorted(set(a) & set(b)):
                for k in sweep.FIELDS:
                    x, y = a[start].get(k, NAN), b[start].get(k, NAN)
                    if x != x and y != y:
                        continue
                    diff = abs(x - y) if (x == x and y == y) else float("inf")
                    n += 1
                    if diff > worst:
                        worst = diff
                        if diff > 0:
                            say(f"  ✗ {grp or '全样本'} {label} {start} {k}: 本轮 {x} 参照 {y}")
    say(f"  14 起点读数对 exp_metric_m2 同臂同起点核对 {n} 个值，最大绝对差 {worst:.3e}")
    pairs = []
    for kind in ("equity", "trades"):
        new = sorted(exp.glob(f"artifacts/*_slip0_BASE_{kind}.csv"))
        old = sorted((ROOT / "data/experiments/exp_metric_m2").glob(f"artifacts/*_m2_BASE_{kind}.csv"))
        if new and old:
            pairs.append((kind, filecmp.cmp(old[0], new[0], shallow=False), sum(1 for _ in new[0].open(encoding="utf-8")) - 1))
    for kind, same, rows in pairs:
        say(f"  2011-11-01 锚点 {kind} {rows} 行逐字节相同：{same}")


def fill_check(exp: Path, say):
    say("\n## 5. 成交价核对（2011 锚点 0bp 对 30bp 成交流水；同日同票同向且股数相同的首批成交）")
    l0, l30 = exp / "artifacts/ledger_slip0.csv", exp / "artifacts/ledger_slip30.csv"
    if not (l0.exists() and l30.exists()):
        say("  流水缺失，跳过"); return
    rows0 = list(csv.DictReader(l0.open(encoding="utf-8")))
    rows30 = list(csv.DictReader(l30.open(encoding="utf-8")))
    checked, worst = {"买入": 0, "卖出": 0}, {"买入": 0.0, "卖出": 0.0}
    for r0, r30 in zip(rows0, rows30):
        key0 = (r0["date"], r0["security_code"], r0["action"])
        if key0 != (r30["date"], r30["security_code"], r30["action"]):
            break
        p0, p30 = float(r0["price"]), float(r30["price"])
        if p0 <= 0 or r0["action"] not in checked:
            continue
        expect = 1.003 if r0["action"] == "买入" else 0.997
        dev = abs(p30 / p0 - expect)
        checked[r0["action"]] += 1
        worst[r0["action"]] = max(worst[r0["action"]], dev)
    for side in ("买入", "卖出"):
        say(f"  {side} {checked[side]} 笔：价比对 {1.003 if side == '买入' else 0.997} 的最大偏差 {worst[side]:.2e}（价保留三位小数）")
    say(f"  两条流水首次分叉前共 {sum(checked.values())} 笔；分叉后路径不同，不再逐笔比")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=Path, default=ROOT / "data/experiments/exp_oi148_slippage")
    args = ap.parse_args()
    exp = args.exp
    lines = []

    def say(s=""):
        print(s); lines.append(s)

    say(f"# OI-148 执行成本压力档位（每边滑点 {'/'.join(map(str, TIERS))}bp）报告")
    say("买价 × (1 + s)、卖价 × (1 − s)，进股数、整手、可用现金、成本、费税；盯市与信号价不变；同日买卖先净额对冲再对净额收；"
        "强平与退市清仓同样收；分红、送转、配股认购不收。A／U 均按 0bp 锚点固定。")
    g_all, order, failed, note_a, ver, _f = sweep.load_scan(exp / "sweep_tiers.txt")
    arms_all, arms_a = g_all[""], g_all[sweep.EX5_PREFIX]
    if (exp / "sweep_tiers_A.txt").exists():           # A 以固定剔除集单遍另跑时（并发扫描曾使自动第二遍被跳过）
        g_a, _o, _f1, note_a, _v, _ff = sweep.load_scan(exp / "sweep_tiers_A.txt")
        arms_a = g_a[sweep.EX5_PREFIX]
    arms_u, note_u = {}, ""
    if (exp / "sweep_tiers_U.txt").exists():
        g_u, _o, _f2, note_u, _v, _ff = sweep.load_scan(exp / "sweep_tiers_U.txt")
        arms_u = g_u[sweep.EX5_PREFIX]
    say(f"计量版本 {ver}；剔除集 A：{note_a}；剔除集 U：{note_u or '缺'}；跑挂：{dict(failed[''])} / {dict(failed[sweep.EX5_PREFIX])}")
    identity(exp, say)

    say("\n## 2. 各档 BASE 成本表（水平 = 各起点再取中位；Δ = 对 0bp 的逐起点配对差中位，pp；最低担保／强平取 14 起点最值）")
    cost_keys = (("年化", "年化"), ("滚5中位", "滚动5年年化中位"), ("滚5P25", "滚动5年年化P25"), ("滚5回撤", "滚动5年回撤中位"),
                 ("最大回撤", "最大回撤"), ("5年块", "互不重叠5年块中位"))
    for gname, arms in (("全样本", arms_all), ("剔除集A", arms_a)):
        say(f"\n### {gname}")
        say("| 档 | " + " | ".join(f"{n} 水平" for n, _k in cost_keys) + " | Sharpe | Calmar | 换手 | 最低担保 | 强平次/起点 | "
            + " | ".join(f"Δ{n}" for n, _k in cost_keys[:4]) + " | 换手×bp |")
        say("| --- | " + " | ".join("---:" for _ in range(len(cost_keys) + 5 + 4 + 1)) + " |")
        turn0 = level(arms, "BASE", "年均换手")
        for t in TIERS:
            lab = base_label(t)
            if lab not in arms:
                say(f"| {t}bp | 缺 |"); continue
            arm = arms[lab]
            mr = min((v["最低担保比例"] for v in arm.values() if v["最低担保比例"] == v["最低担保比例"]), default=NAN)
            liq = f"{sum(int(v['强平次数']) for v in arm.values())}/{sum(1 for v in arm.values() if v['强平次数'] > 0)}"
            row = [f"{t}bp"] + [fmt(level(arms, lab, k)) for _n, k in cost_keys]
            row += [fmt(level(arms, lab, "Sharpe"), 1, 3), fmt(level(arms, lab, "Calmar"), 1, 3), fmt(level(arms, lab, "年均换手"), 1, 2),
                    fmt(mr, 100, 1), liq]
            row += [sfmt(paired(arms, lab, "BASE", k)) for _n, k in cost_keys[:4]]
            row += [f"{-turn0 * t / 1e4 * 100:+.2f}" if turn0 == turn0 else "—"]
            say("| " + " | ".join(row) + " |")

    say("\n## 3. 候选 BUY2 与同档 BASE 配对（§12.1 第 2 款；Δ 单位 pp；A／U 按 0bp 锚点固定）")
    say("| 档 | Δ主(全) | Δ主(A) | Δ主(U) | Δ复利(全) | Δ复利(A) | Δ复利(U) | ΔP25(全) | Δ滚5回撤(全) | 判定 |")
    say("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    verdicts = {}
    for t in TIERS:
        b, c = base_label(t), cand_label(t)
        v, reasons, vals = verdict(arms_all, arms_a, c, b)
        verdicts[t] = v
        say(f"| {t}bp | {sfmt(vals['主读数'][0])} | {sfmt(vals['主读数'][1])} | {sfmt(paired(arms_u, c, b, '滚动5年年化中位'))} | "
            f"{sfmt(vals['复利读数'][0])} | {sfmt(vals['复利读数'][1])} | {sfmt(paired(arms_u, c, b, '年化'))} | "
            f"{sfmt(paired(arms_all, c, b, '滚动5年年化P25'))} | {sfmt(paired(arms_all, c, b, '滚动5年回撤中位'))} | "
            f"{v}{('（' + '；'.join(reasons) + '）') if reasons else ''} |")
    flips = [f"{a}bp→{b}bp" for a, b in zip(TIERS, TIERS[1:]) if verdicts.get(a) != verdicts.get(b)]
    say(f"判定随档位变化：{'、'.join(flips) if flips else '无'}；各档判定 {' / '.join(f'{t}bp {verdicts[t]}' for t in TIERS)}")

    say("\n## 4. 第 4 款 U 全面性（标准指标集各项配对差中位；比率项按两种读法，OI-151）")
    if not arms_u:
        say("  U 单遍缺失")
    else:
        say("| 档 | " + " | ".join(n for n, *_ in sweep.STANDARD_SET) + " | 显示读法 | 字面读法 |")
        say("| --- | " + " | ".join("---:" for _ in sweep.STANDARD_SET) + " | --- | --- |")
        for t in TIERS:
            b, c = base_label(t), cand_label(t)
            cells = []
            for name, key, scale, _w, prec, good in sweep.STANDARD_SET:
                d = paired(arms_u, c, b, key)
                cells.append("—" if d != d else f"{d * scale:+.{max(prec, 1) if scale != 1 else 4}f}")
            c4 = clause4(arms_u, c, b)
            say(f"| {t}bp | " + " | ".join(cells) + " | "
                + " | ".join(f"{'通过' if ok else '不通过'}{('（' + '、'.join(items) + '）') if items else ''}" for ok, items in c4.values()) + " |")
    fill_check(exp, say)
    (exp / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
