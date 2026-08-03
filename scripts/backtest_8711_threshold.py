"""§12 回放：§8.7.11 的门槛校准与流程口径复核。

**为什么这个脚本必须入库**：v1.37 采纳 §8.7.11 时记的「77 次触发、20 日中位 +1.4%、
胜率 51%」是一次性脚本跑出来的，脚本未入库、窗口与 universe 未记录，v2.12 重跑时
**任何窗口都复现不出该组合**，也就无从判断是口径不同还是原结论有误——一条正式买入信号
的准入依据变成无人能复核（OI-028）。本脚本存在的意义就是不让下一次修订重蹈此覆辙。

两种统计口径（`--gate`）：

- `price`：只判形态本身（§8.7.11 是否成立）。衡量的是**形态的边际**，与是否可买无关。
- `pipeline`：**严格按选股流程**——worth_attention（universe 即全池）→ 当日价格自动定档
  （§6.2.1.6）过 §6.2.1 质量×估值矩阵 → 未触发 §8.8 过度延伸 → 过 §11.8 流动性门槛，
  即产出 `signal_state = buy_candidate` 的那一天。衡量的是**流程实际会给出的候选**。

⚠ `pipeline` 口径有**不可消除的前视偏差**，读数时必须一并读这一段（§12.3 已明文）：
合理价区间与质量分层用的都是**今天**的值（`valuation_reviewed_at` 多在 2026-08），
拿它去判 2024 年某天「是否处在估值合理区间」，用到了当时不存在的信息；且 universe 是
今天仍在关注名单里的 261 家，被垃圾化剔除的公司不在其中。两项偏差**方向一致且都利好信号**。
故 `pipeline` 的数字是**上界**，不是无偏估计；`price` 口径没有估值前视，但也不代表可买。

用法：
    python3 scripts/backtest_8711_threshold.py --as-of 2026-08-03
    python3 scripts/backtest_8711_threshold.py --as-of 2026-08-03 --gate pipeline --forwards 20,60,120
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import screen_daily_volume_price_signals as S  # noqa: E402
from build_a_share_core_valuation_pool import (  # noqa: E402
    TIER_ELIGIBLE_VALUATIONS,
    effective_valuation_tier,
)

DEFAULT_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"


def load_history(item):
    code, exchange, name, cap_bn, valuation_price, quality_tier, low, high = item
    try:
        _, rows = S.fetch_daily_rows(code, exchange, load_history.as_of, load_history.timeout)
    except Exception:                                     # noqa: BLE001
        return None
    if len(rows) < 120:
        return None
    S.add_indicators(rows)
    return code, name, rows, cap_bn, valuation_price, quality_tier, low, high


def describe(returns: list[float]) -> str:
    if not returns:
        return f"{'—':>9} {'—':>9} {'—':>7}"
    win = sum(1 for r in returns if r > 0) / len(returns)
    return (f"{statistics.median(returns) * 100:>8.2f}% {statistics.mean(returns) * 100:>8.2f}%"
            f" {win * 100:>6.1f}%")


def main() -> int:
    parser = argparse.ArgumentParser(description="§8.7.11 门槛校准与流程口径复核（§12 回放）")
    parser.add_argument("--as-of", required=True, help="回放截止交易日 YYYY-MM-DD")
    parser.add_argument("--since", default="2022-07-01",
                        help="评估窗起始日（含）。**固定它是可复现的前提**——行情源返回的历史长度"
                             "不稳定（东财 lmt=1000，失败时回落腾讯，两者区间不同），不锁窗则每次跑批"
                             "的样本都不一样。窗前的 K 线仍用于指标预热，只是不参与评估。")
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL, help="universe（核心估值合格池 CSV）")
    parser.add_argument("--thresholds", default="0,0.5,1,1.5,2,3", help="逗号分隔的突破日涨幅门槛（百分数）")
    parser.add_argument("--forwards", default="20,60,120", help="逗号分隔的前瞻交易日数")
    parser.add_argument("--gate", choices=("price", "pipeline", "both"), default="both",
                        help="price=只判形态；pipeline=严格按选股流程（矩阵资格+§8.8+§11.8）")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()

    thresholds = [float(x) for x in args.thresholds.split(",") if x.strip()]
    forwards = [int(x) for x in args.forwards.split(",") if x.strip()]
    gates = ["price", "pipeline"] if args.gate == "both" else [args.gate]
    load_history.as_of, load_history.timeout = args.as_of, args.timeout

    targets = [(r["security_code"], r.get("exchange", ""), r["security_name"],
                S.to_float(r.get("total_market_cap_bn")), S.to_float(r.get("valuation_price")),
                (r.get("quality_tier") or "")[:2],
                S.to_float(r.get("fair_price_low")), S.to_float(r.get("fair_price_high")))
               for r in csv.DictReader(args.pool.open(encoding="utf-8"))]
    print(f"universe {len(targets)} 只｜as_of {args.as_of}｜前瞻 {forwards} 日｜门槛 {thresholds}｜口径 {gates}")

    # hits[gate][threshold][horizon] = [(code, date, forward_return), ...]
    hits = {g: {t: {f: [] for f in forwards} for t in thresholds} for g in gates}
    base = {g: {f: [] for f in forwards} for g in gates}
    failed, spans, evaluated, first_day = 0, [], 0, {}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for payload in pool.map(load_history, targets):
            if payload is None:
                failed += 1
                continue
            code, name, rows, cap_bn, valuation_price, quality_tier, low, high = payload
            n = len(rows)
            spans.append((rows[0]["date"], rows[-1]["date"]))
            eligible_tiers = TIER_ELIGIBLE_VALUATIONS.get(quality_tier, set())
            # §8.5.6 巨盘门槛 cap_bn*10*close/valuation_price >= MEGACAP_MIN_YI 等价于一个固定价位
            mega_price = (S.MEGACAP_MIN_YI * valuation_price / (cap_bn * 10.0)
                          if cap_bn and valuation_price else None)

            shape, effective, megacap_ok, pct = ([False] * n, [False] * n, [False] * n, [0.0] * n)
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

            for i in range(80, n - min(forwards)):
                row_i = rows[i]
                if str(row_i["date"]) < args.since:      # 窗前只作指标预热，不参与评估
                    continue
                evaluated += 1
                first_day.setdefault(code, str(row_i["date"]))
                close_i = float(row_i["close"])
                fwd = {f: (float(rows[i + f]["close"]) / close_i - 1.0) for f in forwards if i + f < n}

                # ——— 流程闸门（与 classify_signal / scan_one 同判据）———
                ma20 = S.to_float(row_i.get("ma20"))
                ret_5d = S.pct_return(rows, i, 5) or 0.0
                ret_20d = S.pct_return(rows, i, 20) or 0.0
                overextended = bool(ma20 and (close_i / ma20 - 1 > 0.25 or ret_5d > 0.30 or ret_20d > 0.60))
                liquid = float(row_i.get("amount_ma20", 0.0) or 0.0) >= S.MIN_AMOUNT_MA20
                tier_i = effective_valuation_tier(close_i, low, high) if (low and high) else None
                eligible = bool(tier_i and tier_i in eligible_tiers)
                gate_ok = {"price": True, "pipeline": eligible and not overextended and liquid}

                for g in gates:
                    if gate_ok[g]:
                        for f, r in fwd.items():
                            base[g][f].append((row_i["date"], r))

                is_megacap = bool(mega_price is not None and close_i >= mega_price)
                candidates = [j for j in range(max(60, i - 20), i)
                              if shape[j] and (effective[j] or (is_megacap and megacap_ok[j]))]
                if not candidates:
                    continue
                for t in thresholds:
                    days = [j for j in candidates if pct[j] >= t]
                    if not (days and S.pullback_after_breakout(rows, i, days)):
                        continue
                    for g in gates:
                        if gate_ok[g]:
                            for f, r in fwd.items():
                                hits[g][t][f].append((code, row_i["date"], r))

    if not spans:
        print("没有可评估的交易日——检查行情源与 universe")
        return 1
    # 报**实际评估到的**首日，而不是 --since：K 线不足 80 根的预热期会把窗口往后推，
    # 两者可以差几个月；只报参数等于报了一个没发生的窗口。
    真实首日 = min(first_day.values()) if first_day else "—"
    print(f"行情失败 {failed} 只｜取回区间 {min(s[0] for s in spans)} → {max(s[1] for s in spans)}"
          f"｜--since {args.since}｜**实际评估窗 {真实首日} → {args.as_of}**｜评估股票日 {evaluated:,}")
    late = sorted(c for c, d in first_day.items() if d > 真实首日)
    if late:
        print(f"  其中 {len(late)} 只晚于该首日才进入评估（上市晚/停牌/预热不足），最晚 "
              f"{max(first_day[c] for c in late)}")

    for g in gates:
        label = ("**对照口径**：只判形态（无估值/过度延伸/流动性闸门）。§12.7 规定信号取舍不看这组数字" if g == "price"
                 else "**判定口径（§12.7）**：严格按选股流程（矩阵资格 + §8.8 + §11.8）⚠含前视偏差，读超额不读水平")
        print(f"\n{'=' * 78}\n口径 {g}：{label}")
        for f in forwards:
            b = [x[1] for x in base[g][f]]
            if not b:
                continue
            bm = statistics.median(b)
            print(f"\n  ── 前瞻 {f} 日 ──  基准样本 {len(b):,}｜基准 {describe(b)}")
            print(f"  {'门槛':>7} | {'触发':>5} | {'中位':>9} {'均值':>9} {'胜率':>7} | {'减基准中位':>10}")
            print("  " + "-" * 64)
            for t in thresholds:
                rets = [x[2] for x in hits[g][t][f]]
                excess = (f"{(statistics.median(rets) - bm) * 100:>+9.2f}pp" if rets else f"{'—':>11}")
                print(f"  {t:>6.2f}% | {len(rets):>5} | {describe(rets)} |{excess}")

    ref_t = (S.BREAKOUT_DAY_MIN_PCT if S.BREAKOUT_DAY_MIN_PCT in thresholds
             else thresholds[len(thresholds) // 2])
    ref_f = forwards[0]
    for g in gates:
        by_year, base_by_year = defaultdict(list), defaultdict(list)
        for _, day, r in hits[g][ref_t][ref_f]:
            by_year[day[:4]].append(r)
        for day, r in base[g][ref_f]:
            base_by_year[day[:4]].append(r)
        if not by_year:
            continue
        print(f"\n按年份（口径 {g}｜门槛 {ref_t}%｜前瞻 {ref_f} 日）：")
        for year in sorted(by_year):
            rs, bs = by_year[year], base_by_year[year]
            med, bmed = statistics.median(rs) * 100, statistics.median(bs) * 100
            print(f"  {year}: 触发 {len(rs):>4}｜中位 {med:>6.2f}%"
                  f"｜胜率 {sum(1 for r in rs if r > 0) / len(rs) * 100:>5.1f}%"
                  f"｜基准 {bmed:>6.2f}%｜超额 {med - bmed:>+6.2f}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
