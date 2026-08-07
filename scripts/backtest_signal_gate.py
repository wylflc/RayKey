#!/usr/bin/env python3
"""§12 回放：任意 §8.7 信号按 §12.7 流程口径的重测（结 OI-029）。

登记的缺陷
----------
v2.13 定 §12.7「信号取舍一律按流程口径」后，**存量的信号取舍结论全部建立在旧口径上**：
§8.7.10 被否决（330 次/−1.3%/45% → 加严后 78 次/−3.7%/40%）、§8.7.12 判样本不足（4 次）、
OI-012 记 §8.7.3 缩量涨停 20 日中位 −5.5%/胜率 35% 为全信号最差——**三者都是只判形态的
数字**。而 §8.7.11 的判例已经证明换口径会翻转结论（形态 −1.03pp/47.3%、与被否的 §8.7.10
同档 → 流程 −0.41pp/56.9%、明显好于它）。叠加的第二个缺陷是**不可重放**：这些结论同样
出自未入库的一次性脚本，窗口与 universe 未记录。

用户 2026-08-07 裁定：**只重测处置为「不产生买入候选」的三个**（§8.7.10／§8.7.12／
§8.7.3），理由是误判的代价不对称——**错杀一个有效信号不会留下任何痕迹**。

与 `backtest_8711_threshold.py` 的关系
--------------------------------------
那个脚本为 §8.7.11 的**门槛校准**而写，把该信号的判据内联重写了一遍。本脚本不复制判据：
直接逐日调用 `screen_daily_volume_price_signals.classify_signal(at_index=i)`，命中与否按它
实际吐出的 `signals`/`observation_tags` 判断。**好处是回放与生产共用同一份判据**——判据一改，
回放自动跟着改，不会再出现「回放里的信号和线上跑的不是同一个」。

性能：`classify_signal` 每次调用都会重算全序列指标（O(n)），逐日回放会退化成 O(n²)。
本脚本对每只票**先算一次指标、随后在回放期间把 `add_indicators` 置为空操作**。这不引入
前视——`add_indicators` 的每个量（均线、量均、prev_high、MACD）在下标 i 处都只用 ≤ i 的
数据，先整段算好与逐日算的结果逐点相同。

⚠ `pipeline` 口径的前视偏差不可消除（§12.4 唯一豁免，v2.13 用户裁定照用）：合理价区间与
质量分层用的都是**今天**的值，universe 也是今天仍在名单里的 261 家。故其绝对水平是**上界**，
**只读组间超额、不读绝对收益**。

用法::

    python3 scripts/backtest_signal_gate.py --as-of 2026-08-07 --signals 8.7.3,8.7.10,8.7.12
    python3 scripts/backtest_signal_gate.py --as-of 2026-08-07 --signals 8.7.11 --gate pipeline
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
from build_a_share_core_valuation_pool import (  # noqa: E402
    TIER_ELIGIBLE_VALUATIONS,
    effective_valuation_tier,
)

DEFAULT_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"

# 用户裁定的重测范围：处置为「不产生买入候选」的三个。
DEFAULT_SIGNALS = "8.7.3,8.7.10,8.7.12"


def load_history(item):
    code, exchange, name, cap_bn, valuation_price, quality_tier, low, high = item
    try:
        _, rows = S.fetch_daily_rows(code, exchange, load_history.as_of, load_history.timeout)
    except Exception:                                          # noqa: BLE001
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


def scan_one(payload, signals: list[str], forwards: list[int], gates: list[str], since: str):
    """逐日重放一只票，返回 (命中记录, 基准记录, 评估日数, 首个评估日)。"""
    code, name, rows, cap_bn, valuation_price, quality_tier, low, high = payload
    n = len(rows)
    eligible_tiers = TIER_ELIGIBLE_VALUATIONS.get(quality_tier, set())
    limit_up = S.limit_up_threshold_pct(code, name)

    hits = {g: {sig: {f: [] for f in forwards} for sig in signals} for g in gates}
    base = {g: {f: [] for f in forwards} for g in gates}
    evaluated, first_day = 0, None

    # 指标已在 load_history 里算过一次；回放期间关掉重算（见模块 docstring 的前视说明）。
    original = S.add_indicators
    S.add_indicators = lambda _rows: None
    try:
        for i in range(80, n - min(forwards)):
            row_i = rows[i]
            if str(row_i["date"]) < since:                      # 窗前只作指标预热
                continue
            evaluated += 1
            if first_day is None:
                first_day = str(row_i["date"])
            close_i = float(row_i["close"])
            fwd = {f: (float(rows[i + f]["close"]) / close_i - 1.0) for f in forwards if i + f < n}
            if not fwd:
                continue

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
                        base[g][f].append((str(row_i["date"]), r))

            if not any(gate_ok[g] for g in gates):
                continue
            result = S.classify_signal(rows, limit_up, cap_bn, valuation_price, at_index=i)
            fired = f"{result.get('signals', '')}; {result.get('observation_tags', '')}"
            for sig in signals:
                if sig not in fired:
                    continue
                for g in gates:
                    if gate_ok[g]:
                        for f, r in fwd.items():
                            hits[g][sig][f].append((code, str(row_i["date"]), r))
    finally:
        S.add_indicators = original

    return hits, base, evaluated, first_day


def main() -> int:
    parser = argparse.ArgumentParser(description="§8.7 信号按 §12.7 流程口径重测（§12 回放，OI-029）")
    parser.add_argument("--as-of", required=True, help="回放截止交易日 YYYY-MM-DD")
    parser.add_argument("--since", default="2022-07-01",
                        help="评估窗起始日（含）。**固定它是可复现的前提**——行情源返回的历史长度不稳定；"
                             "窗前的 K 线仍用于指标预热，只是不参与评估。")
    parser.add_argument("--signals", default=DEFAULT_SIGNALS,
                        help=f"逗号分隔的信号编号（匹配 signals/observation_tags 文本），缺省 {DEFAULT_SIGNALS}")
    parser.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--forwards", default="20,60,120")
    parser.add_argument("--gate", choices=("price", "pipeline", "both"), default="both")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 只（冒烟用，0=全池）")
    args = parser.parse_args()

    signals = [s.strip() for s in args.signals.split(",") if s.strip()]
    forwards = [int(x) for x in args.forwards.split(",") if x.strip()]
    gates = ["price", "pipeline"] if args.gate == "both" else [args.gate]
    load_history.as_of, load_history.timeout = args.as_of, args.timeout

    targets = [(r["security_code"], r.get("exchange", ""), r["security_name"],
                S.to_float(r.get("total_market_cap_bn")), S.to_float(r.get("valuation_price")),
                (r.get("quality_tier") or "")[:2],
                S.to_float(r.get("fair_price_low")), S.to_float(r.get("fair_price_high")))
               for r in csv.DictReader(args.pool.open(encoding="utf-8"))]
    if args.limit:
        targets = targets[:args.limit]
    print(f"universe {len(targets)} 只｜as_of {args.as_of}｜信号 {signals}｜前瞻 {forwards} 日｜口径 {gates}")

    hits = {g: {sig: {f: [] for f in forwards} for sig in signals} for g in gates}
    base = {g: {f: [] for f in forwards} for g in gates}
    failed, evaluated, first_days = 0, 0, {}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for payload in pool.map(load_history, targets):
            if payload is None:
                failed += 1
                continue
            h, b, ev, fd = scan_one(payload, signals, forwards, gates, args.since)
            evaluated += ev
            if fd:
                first_days[payload[0]] = fd
            for g in gates:
                for f in forwards:
                    base[g][f].extend(b[g][f])
                for sig in signals:
                    for f in forwards:
                        hits[g][sig][f].extend(h[g][sig][f])

    if not first_days:
        print("没有可评估的交易日——检查行情源与 universe")
        return 1
    真实首日 = min(first_days.values())
    print(f"行情失败 {failed} 只｜--since {args.since}｜**实际评估窗 {真实首日} → {args.as_of}**"
          f"｜评估股票日 {evaluated:,}")

    for g in gates:
        label = ("**对照口径**：只判形态（无估值/过度延伸/流动性闸门）。§12.7 规定信号取舍不看这组数字"
                 if g == "price"
                 else "**判定口径（§12.7）**：严格按选股流程（矩阵资格 + §8.8 + §11.8）⚠含前视偏差，读超额不读水平")
        print(f"\n{'=' * 84}\n口径 {g}：{label}")
        for f in forwards:
            b = [x[1] for x in base[g][f]]
            if not b:
                continue
            bm = statistics.median(b)
            print(f"\n  ── 前瞻 {f} 日 ──  基准样本 {len(b):,}｜基准 {describe(b)}")
            print(f"  {'信号':>9} | {'触发':>6} | {'中位':>9} {'均值':>9} {'胜率':>7} | {'减基准中位':>11}")
            print("  " + "-" * 70)
            for sig in signals:
                rets = [x[2] for x in hits[g][sig][f]]
                excess = (f"{(statistics.median(rets) - bm) * 100:>+9.2f}pp" if rets else f"{'—':>11}")
                print(f"  {sig:>9} | {len(rets):>6} | {describe(rets)} |{excess}")

    # 按年份只对 pipeline 口径出（§12.7 判定口径），用第一个前瞻窗。
    if "pipeline" in gates:
        ref_f = forwards[0]
        base_by_year = defaultdict(list)
        for day, r in base["pipeline"][ref_f]:
            base_by_year[day[:4]].append(r)
        for sig in signals:
            by_year = defaultdict(list)
            for _, day, r in hits["pipeline"][sig][ref_f]:
                by_year[day[:4]].append(r)
            if not by_year:
                continue
            print(f"\n按年份（pipeline｜{sig}｜前瞻 {ref_f} 日）：")
            for year in sorted(by_year):
                rs, bs = by_year[year], base_by_year[year]
                med, bmed = statistics.median(rs) * 100, statistics.median(bs) * 100
                print(f"  {year}: 触发 {len(rs):>4}｜中位 {med:>6.2f}%"
                      f"｜胜率 {sum(1 for r in rs if r > 0) / len(rs) * 100:>5.1f}%"
                      f"｜基准 {bmed:>6.2f}%｜超额 {med - bmed:>+6.2f}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
