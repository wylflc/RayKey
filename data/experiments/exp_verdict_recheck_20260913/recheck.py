"""OI-172/173 历史核对：对全部 m3 扫描文件，比较旧实现（任意负窗增大计否决、交集配对）与现行实现的判定。"""
import glob, statistics, sys
from pathlib import Path
sys.path.insert(0, "scripts")
import sweep_backtest_configs as sw

def old_verdict(arms_all, arms_ex, label):
    """旧口径：负窗任意增大计入否决；起点/窗口取交集（对应 c1207ee8 实现）。"""
    keys = sw.VERDICT_KEYS
    pm = lambda arms, key: sw._paired_median(arms, label, key, coverage="common")
    vals = {name: (pm(arms_all, key), pm(arms_ex, key)) for name, key in keys}
    ma, me = pm(arms_all, "最大回撤"), pm(arms_ex, "最大回撤")
    w = pm(arms_all, "滚动5年年化最差")
    eps = sw.drawdown_episodes(arms_all, arms_ex, label)
    verdict, reasons = "可采纳", []
    for name, _k in keys:
        a, e = vals[name]
        if a != a or e != e:
            return "不可判", ["缺表"]
        lo, hi = min(a, e), max(a, e)
        if lo < -sw.RULING_TOLERANCE:
            verdict = "不采纳"; reasons.append(name); break
        if lo < -sw.NOISE_BAND:
            if hi >= sw.CLEAR_GAIN and verdict != "不采纳":
                verdict = "报用户裁定"
            else:
                verdict = "不采纳"; break
    if verdict != "可采纳":
        main, comp = vals["主读数"], vals["复利读数"]
        deep = [ep for ep in eps if ep["delta"] <= -sw.DD_PATH_MDD_GAIN]
        mdd_ok = ma == ma and me == me and max(ma, me) <= -sw.DD_PATH_MDD_GAIN
        if (min(main) >= -sw.RULING_TOLERANCE and min(comp) >= -sw.NOISE_BAND and mdd_ok
                and w == w and w >= -sw.NOISE_BAND and len(deep) >= sw.DD_PATH_EPISODES):
            verdict = "可采纳·回撤通道"
    base, arm = arms_all.get("BASE", {}), arms_all.get(label, {})
    common = [s for s in arm if s in base]
    neg_up = sum(1 for s in common if arm[s]["滚动5年为负的窗口占比"] > base[s]["滚动5年为负的窗口占比"])
    dd = statistics.median(arm[s]["滚动5年回撤中位"] - base[s]["滚动5年回撤中位"] for s in common) if common else float("nan")
    if common and dd > sw.DRAWDOWN_GATE:
        verdict = "不采纳"
    if common and neg_up > len(common) / 2:
        verdict = "不采纳"; reasons.append(f"旧否决 负窗↑ {neg_up}/{len(common)}")
    return verdict, reasons, neg_up, len(common)

files = sorted(glob.glob("data/experiments/*/sweep*.txt"))
total = flips = 0
rows = []
for f in files:
    txt = Path(f).read_text(encoding="utf-8")
    if not txt.startswith("#METRIC|m3"):
        continue
    groups, orders, failed, note, version, fields = sw.load_scan(Path(f))
    arms_all, arms_ex = groups[""], groups[sw.EX5_PREFIX]
    if "BASE" not in arms_all:
        continue
    for label in orders[""]:
        if label == "BASE" or label not in arms_all:
            continue
        total += 1
        old = old_verdict(arms_all, arms_ex, label) if arms_ex else ("无去赢家表",)
        new_v, new_r, vals = sw.adoption_verdict(arms_all, arms_ex, label) if arms_ex else ("无去赢家表", [], {})
        base, arm = arms_all["BASE"], arms_all[label]
        common = [s for s in arm if s in base]
        any_up = sum(1 for s in common if arm[s]["滚动5年为负的窗口占比"] > base[s]["滚动5年为负的窗口占比"])
        flip0 = sum(1 for s in common if sw.neg_window_flip(arm[s], base[s]))
        if old[0] != new_v or any_up != flip0:
            flips += 1
            rows.append((f, label, old[0], new_v, any_up, flip0, len(common), "；".join(new_r)[:120]))
print(f"m3 扫描文件 {sum(1 for f in files if Path(f).read_text(encoding='utf-8').startswith('#METRIC|m3'))} 份，候选臂 {total} 条，判定或负窗计数有差异 {flips} 条")
for r in rows:
    print(" | ".join(map(str, r)))
