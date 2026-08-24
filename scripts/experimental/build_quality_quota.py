"""生成「质量组」成员区间：面板内 `roe0` 排前 N% 的公司，逐档时点判定。

用途是 §12.60 那条规则的输入——**换仓不得卖出质量组的持仓**（`--quota-file` + `--quota-pct`）。

**为什么用相对分位而不是绝对门槛**：V4 面板本身已是护城河筛选的结果，`roe0 ≥ 20%` 能圈进
211 只里的 197 只，等于没筛。改用「该档面板内排前 20%」后每档约 23 只，才真的选出了
「这一批里最赚钱的那一撮」。

**为什么无后视**：`roe0` 取自估值带，按 `available_at ≤ 该档生效日` 取最近一期；
面板档位本身也是时点的（年报 04-30 生效）。判定只用当日可得的信息。

用法：
    python3 build_quality_quota.py --bands <估值带.csv> --panel <面板.csv> --top 0.20 --out <成员区间.csv>

估值带须与回测实际在跑的那套同源（§9.3.1.2）；`roe0` 不受 `--n1`／`--roe-terminal-ratio`
影响，故任一档的带文件都可以用。
"""
import argparse
import bisect
import collections
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bands", type=Path, required=True, help="估值带（须含 roe0 与 available_at）")
    ap.add_argument("--panel", type=Path,
                    default=ROOT / "data/archive/pit-judgment-2026-08/panel_moat_bank_v4.csv")
    ap.add_argument("--top", type=float, default=0.20, help="取该档面板内 roe0 的前多少比例")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    names = {}
    with open(ROOT / "data/raw/a_share_securities.csv", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            names[r["security_code"]] = r.get("security_name", "")

    # 面板是**成员区间**（effective_from/effective_to），不是逐档完整快照——§12.80 的
    # 回测 loader 曾把区间当快照消费，本脚本首版同病。每个档位日的在册集合必须由
    # 「区间覆盖该日」求出，否则每档只剩当天新进的公司。
    intervals = []
    with open(a.panel, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            intervals.append((r["security_code"].zfill(6), r["effective_from"],
                              r.get("effective_to") or "9999-12-31"))
    # 工作流 §12：effective_from/effective_to 均为有效期边界，**结束日包含在内**。
    vintages = {}
    for day in {iv[1] for iv in intervals}:
        vintages[day] = {c for c, lo, hi in intervals if lo <= day <= hi}

    seq = collections.defaultdict(list)
    with open(a.bands, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not (r.get("roe0") and r.get("available_at")):
                continue
            try:
                seq[r["security_code"].zfill(6)].append((r["available_at"], float(r["roe0"])))
            except ValueError:
                pass
    for c in seq:
        seq[c].sort()
    keys = {c: [x[0] for x in v] for c, v in seq.items()}

    def roe_at(code, day):
        """该档生效日**当天可得**的最近一期 roe0；没有就返回 None（不外推、不借未来）。"""
        ks = keys.get(code)
        if not ks:
            return None
        i = bisect.bisect_right(ks, day) - 1
        return seq[code][i][1] if i >= 0 else None

    days = sorted(vintages)
    segments = collections.defaultdict(list)
    per_vintage = []
    for i, day in enumerate(days):
        end = days[i + 1] if i + 1 < len(days) else "9999-12-31"
        scored = sorted(((v, c) for c in vintages[day] if (v := roe_at(c, day)) is not None),
                        reverse=True)
        k = max(1, int(len(scored) * a.top))
        per_vintage.append(k)
        for _, code in scored[:k]:
            if segments[code] and segments[code][-1][1] == day:
                segments[code][-1][1] = end          # 连续在选就并成一段
            else:
                segments[code].append([day, end])

    rows = sum(len(v) for v in segments.values())
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["security_code", "security_name", "effective_from", "effective_to"])
        for code in sorted(segments):
            for lo, hi in segments[code]:
                w.writerow([code, names.get(code, ""), lo, hi])
    print(f"面板 {len(days)} 档｜每档取前 {a.top:.0%}（约 {sum(per_vintage)//len(per_vintage)} 只）"
          f"｜成员 {len(segments)} 只、区间 {rows} 段 → {a.out}")


if __name__ == "__main__":
    main()
