#!/usr/bin/env python3
"""§10.3 策略收益跟踪：按时间加权口径重算账户快照的策略列。

读 `data/processed/portfolio_account_snapshot.csv`，从策略基准日（首个填了 `strategy_base_net_assets_cny` 的行）起
逐行链乘策略单位净值：
    F = 0 或未填流前估值：r = (N − F) ÷ N₋₁ − 1            （F = 0 时精确；F ≠ 0 时为「现金流在收盘前最后时点」的近似，标 eod_approx）
    F ≠ 0 且填了 `net_assets_before_flow_cny`：r = N_pre ÷ N₋₁ × N ÷ (N_pre + F) − 1   （精确 TWR，标 exact）
单位净值 = 前一快照日单位净值 × (1 + r)；收益率 = (单位净值 − 1) × 100；峰值与回撤按单位净值算，
`account_peak_net_assets_cny` = 最高单位净值 × 基准净资产。纪元列只标段，从不重置链。

用法：
    python3 scripts/strategy_return_tracker.py --check                 # 只核对，不一致退出码 1
    python3 scripts/strategy_return_tracker.py --write                 # 重算并写回
    python3 scripts/strategy_return_tracker.py --write --epoch E2 --from 2026-10-01
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/processed/portfolio_account_snapshot.csv"
DEFAULT_EPOCH = "E1"
NEW_COLUMNS = ("net_assets_before_flow_cny", "strategy_nav_basis", "strategy_unit_nav", "strategy_epoch")
STRATEGY_COLUMNS = ("strategy_return_pct", "account_peak_net_assets_cny", "drawdown_from_peak_pct",
                    "strategy_nav_basis", "strategy_unit_nav", "strategy_epoch")


def _num(text: str | None) -> float | None:
    text = (text or "").strip().replace(",", "")
    if not text:
        return None
    return float(text)


def compute(rows: list[dict], epoch_from: tuple[str, str] | None = None) -> list[dict]:
    """返回 {as_of: 策略列取值} 的列表（与 rows 同序，基准日前的行为 None）。rows 须按 as_of 升序。"""
    out: list[dict | None] = []
    base_value, prev_n, nav, peak, epoch = None, None, 1.0, 1.0, DEFAULT_EPOCH
    for row in rows:
        base = _num(row.get("strategy_base_net_assets_cny"))
        if base_value is None:
            if base is None:
                out.append(None)
                continue
            base_value = base
            n = _num(row.get("net_assets_cny"))
            if n is None or abs(n - base_value) > 0.005:
                raise ValueError(f"{row['as_of']}：基准日净资产 {n} 与 strategy_base_net_assets_cny {base_value} 不一致")
            prev_n, nav, peak = n, 1.0, 1.0
            basis = "exact"
        else:
            if base is not None and abs(base - base_value) > 0.005:
                raise ValueError(f"{row['as_of']}：strategy_base_net_assets_cny {base} 与基准 {base_value} 不一致")
            n = _num(row.get("net_assets_cny"))
            if n is None:
                raise ValueError(f"{row['as_of']}：缺 net_assets_cny")
            flow = _num(row.get("external_cash_flow_cny")) or 0.0
            pre = _num(row.get("net_assets_before_flow_cny"))
            if flow == 0:
                r, basis = n / prev_n - 1, "exact"
            elif pre is not None:
                if pre <= 0 or pre + flow <= 0:
                    raise ValueError(f"{row['as_of']}：流前估值 {pre} 与现金流 {flow} 使子期净值非正")
                r, basis = pre / prev_n * n / (pre + flow) - 1, "exact"
            else:
                r, basis = (n - flow) / prev_n - 1, "eod_approx"
            nav *= 1 + r
            peak = max(peak, nav)
            prev_n = n
        if epoch_from and row["as_of"] >= epoch_from[1]:
            epoch = epoch_from[0]
        elif (row.get("strategy_epoch") or "").strip():
            epoch = row["strategy_epoch"].strip()
        out.append({"strategy_unit_nav": f"{nav:.6f}",
                    "strategy_return_pct": f"{(nav - 1) * 100:.2f}",
                    "account_peak_net_assets_cny": f"{peak * base_value:.2f}",
                    "drawdown_from_peak_pct": f"{(nav / peak - 1) * 100:.2f}",
                    "strategy_nav_basis": basis,
                    "strategy_epoch": epoch})
    return out


def load(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    pos = fields.index("strategy_return_pct")
    for col in NEW_COLUMNS:                      # 缺的列按 NEW_COLUMNS 顺序依次插在 strategy_return_pct 之后
        if col in fields:
            pos = fields.index(col)
            continue
        pos += 1
        fields.insert(pos, col)
        for row in rows:
            row[col] = ""
    return fields, rows


def main() -> int:
    ap = argparse.ArgumentParser(description="§10.3 策略收益跟踪（时间加权单位净值）")
    ap.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    ap.add_argument("--write", action="store_true", help="重算并写回快照")
    ap.add_argument("--check", action="store_true", help="只核对已登记的策略列，不一致退出码 1")
    ap.add_argument("--epoch", help="新纪元标签（与 --from 同给）")
    ap.add_argument("--from", dest="epoch_from", help="新纪元生效日 YYYY-MM-DD")
    args = ap.parse_args()
    if bool(args.epoch) != bool(args.epoch_from):
        ap.error("--epoch 与 --from 必须同给")
    fields, rows = load(args.snapshot)
    order = sorted(range(len(rows)), key=lambda i: rows[i]["as_of"])
    computed = compute([rows[i] for i in order], (args.epoch, args.epoch_from) if args.epoch else None)
    mismatches = 0
    print(f"{'as_of':<11}{'净资产':>14}{'现金流':>11}{'单位净值':>10}{'收益%':>8}{'回撤%':>8}  口径      纪元")
    for i, values in zip(order, computed):
        row = rows[i]
        if values is None:
            continue
        for col in STRATEGY_COLUMNS:
            old = (row.get(col) or "").strip()
            if old and old != values[col]:
                try:
                    same = abs(float(old) - float(values[col])) < 0.005 + 1e-9
                except ValueError:
                    same = False
                if not same:
                    mismatches += 1
                    print(f"  ✗ {row['as_of']} {col}: 登记 {old} → 重算 {values[col]}", file=sys.stderr)
        print(f"{row['as_of']:<11}{float(row['net_assets_cny']):>14,.2f}{_num(row.get('external_cash_flow_cny')) or 0:>11,.2f}"
              f"{values['strategy_unit_nav']:>10}{values['strategy_return_pct']:>8}{values['drawdown_from_peak_pct']:>8}"
              f"  {values['strategy_nav_basis']:<9} {values['strategy_epoch']}")
        if args.write:
            row.update(values)
    if args.write:
        with args.snapshot.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"已写回 {args.snapshot.relative_to(ROOT) if args.snapshot.is_relative_to(ROOT) else args.snapshot}")
    elif mismatches:
        print(f"{mismatches} 处登记值与重算不一致（--write 可写回）", file=sys.stderr)
        return 1 if args.check else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
