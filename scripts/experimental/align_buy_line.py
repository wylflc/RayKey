"""买入线对齐（§12.30 / OI-045）。

换了估值口径就不能沿用原来的 `--width`——`P/V` 的分布整体平移之后，同一条名义线
放行的合格面完全不同，比出来的是「两条不同宽度的闸门」而不是「两套估值」。
故对每条臂重解一条线，使**面板在册观测中 `P/V ≤ 线` 的比例与基准相同**。

用法：python3 align_line.py <基准逐日> <基准线> <待对齐逐日> [<待对齐逐日> ...]
"""
import bisect
import collections
import csv
import sys

ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
PANEL = f"{ROOT}/data/processed/pit_attention/panel_moat_bank_adopted.csv"

spans = collections.defaultdict(list)
with open(PANEL, encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        spans[r["security_code"].zfill(6)].append((r["effective_from"], r["effective_to"]))


def in_panel(code, day):
    return any(a <= day < b for a, b in spans.get(code, ()))


def ratios(path):
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            code = r["security_code"].zfill(6)
            if not in_panel(code, r["date"]):
                continue
            try:
                out.append(float(r["valuation_ratio"]))
            except (TypeError, ValueError):
                pass
    out.sort()
    return out


base_path, base_line = sys.argv[1], float(sys.argv[2])
base = ratios(base_path)
share = bisect.bisect_right(base, base_line) / len(base)
print(f"基准 {base_path.split('/')[-1]}：面板内观测 {len(base):,}｜"
      f"线 {base_line:.4f} → 合格面 {share * 100:.3f}%")

for path in sys.argv[3:]:
    arm = ratios(path)
    idx = min(int(share * len(arm)), len(arm) - 1)
    line = arm[idx]
    got = bisect.bisect_right(arm, line) / len(arm)
    print(f"  {path.split('/')[-1]:<24} 观测 {len(arm):,}｜对齐线 **{line:.4f}**"
          f"（`--width {1 - line:.4f}`）→ 合格面 {got * 100:.3f}%")
