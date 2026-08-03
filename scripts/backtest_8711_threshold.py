"""§12 回放：§8.7.11 突破日「当日涨幅」门槛（`BREAKOUT_DAY_MIN_PCT`）的校准。

**为什么这个脚本必须入库**：v1.37 采纳 §8.7.11 时记的「77 次触发、20 日中位 +1.4%、
胜率 51%」是一次性脚本跑出来的，脚本未入库、窗口与 universe 未记录，v2.12 重跑时
**任何窗口都复现不出该组合**，也就无从判断是口径不同还是原结论有误——一条正式买入信号
的准入依据变成无人能复核（OI-028）。本脚本存在的意义就是不让下一次修订重蹈此覆辙。

口径：判据一律调用 `screen_daily_volume_price_signals` 的真实实现，不另写一份；
§8.5.6 巨盘条件取决于**评估日**市值，故等价折算为一个固定价位后按评估日判定。

用法：
    python3 scripts/backtest_8711_threshold.py --as-of 2026-08-03
    python3 scripts/backtest_8711_threshold.py --as-of 2026-08-03 --thresholds 0,1,3 --forward 20
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import screen_daily_volume_price_signals as S  # noqa: E402

DEFAULT_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"


def load_history(item: tuple[str, str, str, float | None, float | None]):
    code, exchange, name, cap_bn, valuation_price = item
    try:
        _, rows = S.fetch_daily_rows(code, exchange, load_history.as_of, load_history.timeout)
    except Exception:                                     # noqa: BLE001
        return code, name, None
    if len(rows) < 120:
        return code, name, None
    S.add_indicators(rows)
    return code, name, (rows, cap_bn, valuation_price)


def describe(returns: list[float]) -> str:
    if not returns:
        return f"{'—':>9} {'—':>9} {'—':>7}"
    win = sum(1 for r in returns if r > 0) / len(returns)
    return (f"{statistics.median(returns) * 100:>8.2f}% {statistics.mean(returns) * 100:>8.2f}%"
            f" {win * 100:>6.1f}%")


def main() -> int:
    parser = argparse.ArgumentParser(description="§8.7.11 突破日涨幅门槛的 §12 回放校准")
    parser.add_argument("--as-of", required=True, help="回放截止交易日 YYYY-MM-DD")
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL, help="universe（核心估值合格池 CSV）")
    parser.add_argument("--thresholds", default="0,0.5,1,1.5,2,3", help="逗号分隔的门槛（百分数）")
    parser.add_argument("--forward", type=int, default=20, help="前瞻交易日数")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()

    thresholds = [float(x) for x in args.thresholds.split(",") if x.strip()]
    fwd = args.forward
    load_history.as_of, load_history.timeout = args.as_of, args.timeout

    targets = [(r["security_code"], r.get("exchange", ""), r["security_name"],
                S.to_float(r.get("total_market_cap_bn")), S.to_float(r.get("valuation_price")))
               for r in csv.DictReader(args.pool.open(encoding="utf-8"))]
    print(f"universe {len(targets)} 只｜as_of {args.as_of}｜前瞻 {fwd} 日｜门槛 {thresholds}")

    hits: dict[float, list[tuple[str, str, str, float]]] = {t: [] for t in thresholds}
    baseline: list[tuple[str, float]] = []
    failed, spans = 0, []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for code, name, payload in pool.map(load_history, targets):
            if payload is None:
                failed += 1
                continue
            rows, cap_bn, valuation_price = payload
            n = len(rows)
            spans.append((rows[0]["date"], rows[-1]["date"]))
            # §8.5.6 巨盘门槛 cap_bn*10*close/valuation_price >= MEGACAP_MIN_YI 等价于一个固定价位
            mega_price = (S.MEGACAP_MIN_YI * valuation_price / (cap_bn * 10.0)
                          if cap_bn and valuation_price else None)

            shape = [False] * n
            effective = [False] * n
            megacap_ok = [False] * n
            pct = [0.0] * n
            for j in range(60, n):
                cond = S.volume_conditions(rows, j, None)      # None → 先不含 §8.5.6
                if cond is None:
                    continue
                rj = rows[j]
                pct[j] = float(rj["pct_chg"])
                effective[j] = bool(cond["effective"])
                megacap_ok[j] = bool(pct[j] > 0 and (float(cond["day_vol_ratio"]) >= 1.3
                                                     or float(cond["vol_3d_ratio"]) >= 1.25))
                shape[j] = bool(
                    float(rj["close_location"]) >= 0.6
                    and any(rj.get(f"prev_high_{w}") is not None
                            and float(rj["close"]) > float(rj[f"prev_high_{w}"]) * 1.005
                            for w in (60, 120, 250))
                )

            for i in range(80, n - fwd):
                close_i = float(rows[i]["close"])
                baseline.append((rows[i]["date"], float(rows[i + fwd]["close"]) / close_i - 1.0))
                is_megacap = bool(mega_price is not None and close_i >= mega_price)
                candidates = [j for j in range(max(60, i - 20), i)
                              if shape[j] and (effective[j] or (is_megacap and megacap_ok[j]))]
                if not candidates:
                    continue
                forward = float(rows[i + fwd]["close"]) / close_i - 1.0
                for t in thresholds:
                    days = [j for j in candidates if pct[j] >= t]
                    if days and S.pullback_after_breakout(rows, i, days):
                        hits[t].append((code, name, rows[i]["date"], forward))

    if not baseline:
        print("没有可评估的交易日——检查行情源与 universe")
        return 1
    print(f"行情失败 {failed} 只｜窗口 {min(s[0] for s in spans)} → {max(s[1] for s in spans)}"
          f"｜可评估交易日 {len(baseline):,}")
    base_returns = [b[1] for b in baseline]
    base_median = statistics.median(base_returns)
    print(f"同窗口同 universe 基准（全部可评估日）：{describe(base_returns)}\n")

    print(f"{'门槛':>7} | {'触发':>5} | {'中位':>9} {'均值':>9} {'胜率':>7} | {'减基准中位':>10}")
    print("-" * 66)
    for t in thresholds:
        returns = [h[3] for h in hits[t]]
        excess = f"{(statistics.median(returns) - base_median) * 100:>+9.2f}pp" if returns else f"{'—':>11}"
        print(f"{t:>6.2f}% | {len(returns):>5} | {describe(returns)} |{excess}")

    # 分年表按**生产在用的**门槛展开，便于与现行配置直接对照；不在清单里才退回中位数。
    ref = (S.BREAKOUT_DAY_MIN_PCT if S.BREAKOUT_DAY_MIN_PCT in thresholds
           else thresholds[len(thresholds) // 2])
    by_year: dict[str, list[float]] = defaultdict(list)
    base_by_year: dict[str, list[float]] = defaultdict(list)
    for _, _, day, r in hits[ref]:
        by_year[day[:4]].append(r)
    for day, r in baseline:
        base_by_year[day[:4]].append(r)
    print(f"\n按年份（门槛 {ref}%）：")
    for year in sorted(by_year):
        rs, bs = by_year[year], base_by_year[year]
        med, bmed = statistics.median(rs) * 100, statistics.median(bs) * 100
        print(f"  {year}: 触发 {len(rs):>4}｜中位 {med:>6.2f}%"
              f"｜胜率 {sum(1 for r in rs if r > 0) / len(rs) * 100:>5.1f}%"
              f"｜基准 {bmed:>6.2f}%｜超额 {med - bmed:>+6.2f}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
