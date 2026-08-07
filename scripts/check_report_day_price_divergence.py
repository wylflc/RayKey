#!/usr/bin/env python3
"""A 股财报日「价格与带背离 → 强制复带」检出（§7.5.5，结 OI-026）。

登记的不对称
------------
v2.10 给 §6.8 加了第 ③ 条：海外标的财报后首个价格相对披露前收盘 |Δ| ≥ 7% 且被推出带时，
T+1 内必须复带，不得只让价格改档。**该触发的成因与市场无关**——财报日是唯一一个「带与
价格从同一个事件更新」的日子：价格瞬时、完整地吸收它，而带走的是归一化、拆增速、定倍数
这条慢路径。两者一旦差出这个量级，现有机制只有「市场错了，等它回来」一个读法，**没有
任何机制把这个缺口当成对带的反证**。

而 A 股侧的 §7.3/§7.5.5 express 复核只由**披露事件**触发、同样不看价格反应，故同一盲区
在 261 家上原样存在——且 A 股的暴露面比海外大得多：海外 21 家一律不可买，A 股的档位
直接决定 §6.2.1 矩阵的买入资格。

用户 2026-08-07 裁定：**只对「持仓 + 当日可买」子集生效**（三个方向中的第②个）。

口径
----
* **子集**：全部持仓 ∪ 当日 `matrix_state = buyable` 的池内股票。理由是决策后果——
  持仓的卖出侧无冻结保护，可买股票的档位直接决定当天能不能下单；其余 200 余家逐日判定
  既不可执行，也没有对应的当日决策。
* **阈值 |Δ| ≥ 7%**：沿用 §6.8 第 ③ 条的海外初始校准值，**明标为未校准值**。A 股有
  10%/20% 涨跌停制度，7% 在此可能偏敏感；本脚本每次运行打印实际触发家数，跑一个
  披露季后按实测频次重定（改阈值先改 §7.5.5 正文）。
* **第二个条件不可省**：该价格必须把标的**推出当前带**（涨破带顶或跌穿带底）。只有
  |Δ| 大而仍在带内的，说明带本来就容得下这次重定价，不构成对带的反证。
* **结论是「带待复核」，不是改带**：命中即在当日报告标注并按 §7.4 express 口径在 T+1
  内完成一次带复核。复核结论可以是「带不变」，但必须显式做过。

用法::

    python3 scripts/check_report_day_price_divergence.py --as-of 2026-08-07
    python3 scripts/check_report_day_price_divergence.py --as-of 2026-08-07 --lookback 15
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import screen_daily_volume_price_signals as S  # noqa: E402

DEFAULT_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
DEFAULT_DISCLOSURES = ROOT / "data/interim/a_share_report_disclosures.csv"
DEFAULT_FORECASTS = ROOT / "data/interim/a_share_earnings_forecasts.csv"

# §6.8 第 ③ 条的初始校准值。**A 股侧未校准**——见模块 docstring。
DIVERGENCE_THRESHOLD_PCT = 7.0


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def to_float(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def latest_notice_dates(as_of: date, lookback_days: int) -> dict[str, tuple[str, str]]:
    """{代码: (公告日, 披露类型)}，只取回溯窗口内最近的一次披露。

    三档披露一律计入（预告/快报/定期报告），与 §7.3 同口径——「是否大幅超预期」是复核的
    结论，不是入队的门槛。
    """
    floor = (as_of - timedelta(days=lookback_days)).isoformat()
    latest: dict[str, tuple[str, str]] = {}
    for path, label in ((DEFAULT_DISCLOSURES, "定期报告/快报"), (DEFAULT_FORECASTS, "业绩预告")):
        for row in load_csv(path):
            code = (row.get("security_code") or "").zfill(6)
            notice = (row.get("notice_date") or "")[:10]
            if not code or not notice or notice < floor or notice > as_of.isoformat():
                continue
            kind = row.get("disclosure_type") or label
            if code not in latest or notice > latest[code][0]:
                latest[code] = (notice, str(kind))
    return latest


def divergence_for(code: str, exchange: str, notice: str, as_of: date,
                   low: float, high: float, timeout: float) -> dict[str, object] | None:
    """返回该票披露前收盘 → 披露后首个收盘的背离读数；不满足条件返回 None。"""
    try:
        _, rows = S.fetch_daily_rows(code, exchange, as_of.isoformat(), timeout)
    except Exception:                                          # noqa: BLE001
        return None
    if len(rows) < 2:
        return None

    # 披露后首个交易日 = 公告日当天或其后的第一个有 bar 的交易日。
    # 公告日盘后披露时当天的 bar 尚未吸收它，故取"公告日之后"的第一根；公告日盘前/盘中
    # 披露则当天即吸收——两种都存在，取"公告日当天或之后第一根且其前一根为披露前收盘"
    # 会把盘后披露算错一天。故一律取**公告日之后**的第一根，代价是盘前披露晚判一天。
    after_idx = next((i for i, r in enumerate(rows) if str(r.get("date", "")) > notice), None)
    if after_idx is None or after_idx == 0:
        return None
    before_close = to_float(rows[after_idx - 1].get("close"))
    after_close = to_float(rows[after_idx].get("close"))
    if not before_close or not after_close:
        return None

    delta_pct = (after_close / before_close - 1) * 100
    if abs(delta_pct) < DIVERGENCE_THRESHOLD_PCT:
        return None
    if low <= after_close <= high:
        return None                                            # 仍在带内 = 带容得下这次重定价

    # 「**推出**带」是一个位移，不是一个位置——必须是这次财报把价格推得**离带更远**。
    # 首轮全池校准（2026-08-07，45 日窗）实测：只判"收在带外"会把 14 只里的 12 只判成命中，
    # 而其中绝大多数是**早已远在带上方**的 `trim_alert` 行，财报当天反而是**向带收敛**——
    # 判例江丰电子 282.14 → 240（−14.9%），带 42.29-52.25，跌了 15% 仍在带顶之上 4.6 倍。
    # 那不是对带的反证，恰恰是对带的佐证。故判据取「到带的距离扩大」：
    #   d(p) = max(0, low − p, p − high)，要求 d(after) > d(before)。
    # 该定义同时覆盖两种真信号：①原在带内被推出（d 由 0 变正，即 §6.8 微软/Meta 判例）；
    # ②原已在带外、财报把缺口进一步拉大。
    def gap(price: float) -> float:
        return max(0.0, low - price, price - high)

    if gap(after_close) <= gap(before_close):
        return None

    return {
        "notice_date": notice,
        "before_close": before_close,
        "after_date": str(rows[after_idx].get("date", "")),
        "after_close": after_close,
        "delta_pct": delta_pct,
        "band": (low, high),
        "pushed": ("涨破带顶" if gap(before_close) == 0 else "上方缺口扩大") if after_close > high
                  else ("跌穿带底" if gap(before_close) == 0 else "下方缺口扩大"),
    }


def run(as_of: date, lookback: int, timeout: float, universe: str = "subset") -> list[dict[str, object]]:
    pool = {row["security_code"].zfill(6): row for row in load_csv(DEFAULT_POOL)}
    holdings = {row["security_code"].zfill(6) for row in load_csv(DEFAULT_HOLDINGS)}
    buyable = {code for code, row in pool.items() if row.get("matrix_state") == "buyable"}
    # `--universe pool` 只用于**阈值校准**（测全池触发频次），不是生效范围。
    # 生效范围由用户 2026-08-07 裁定为「持仓 + 当日可买」，见模块 docstring。
    subset = sorted(pool) if universe == "pool" else sorted(holdings | buyable)

    notices = latest_notice_dates(as_of, lookback)
    checked = 0
    hits: list[dict[str, object]] = []
    for code in subset:
        row = pool.get(code)
        if row is None:
            continue                                           # 持仓但已出池：无带可比
        notice = notices.get(code)
        low, high = to_float(row.get("fair_price_low")), to_float(row.get("fair_price_high"))
        if not notice or low is None or high is None:
            continue
        checked += 1
        result = divergence_for(code, row.get("exchange", ""), notice[0], as_of, low, high, timeout)
        if result:
            result.update({
                "security_code": code,
                "security_name": row.get("security_name", ""),
                "disclosure_kind": notice[1],
                "in_holdings": code in holdings,
                "matrix_state": row.get("matrix_state", ""),
            })
            hits.append(result)

    scope = (f"全池 {len(subset)} 只（**校准口径，非生效范围**）" if universe == "pool"
             else f"子集 {len(subset)} 只（持仓 {len(holdings)} + 当日可买 {len(buyable)}，去重后）")
    print(f"§7.5.5 财报日价格背离检出（{as_of}，OI-026）｜{scope}"
          f"｜其中 {lookback} 日内有披露且有带的 {checked} 只")
    if not hits:
        print(f"  无命中（阈值 |Δ| ≥ {DIVERGENCE_THRESHOLD_PCT:g}% 且被推出带）")
        return hits

    print(f"  **带待复核 {len(hits)} 只**（T+1 内按 §7.4 express 口径复带，不得只让价格改档）：")
    for hit in sorted(hits, key=lambda h: -abs(float(h["delta_pct"]))):
        low, high = hit["band"]                                # type: ignore[misc]
        tag = "持仓" if hit["in_holdings"] else hit["matrix_state"]
        print(f"    - {hit['security_name']}（{hit['security_code']}，{tag}）"
              f"{hit['disclosure_kind']} 公告日 {hit['notice_date']}："
              f"{hit['before_close']:g} → {hit['after_close']:g}（{hit['after_date']}）"
              f"**{float(hit['delta_pct']):+.2f}%**，{hit['pushed']}（带 {low:g}-{high:g}）")
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="A 股财报日价格背离强制复带检出（§7.5.5，OI-026）")
    parser.add_argument("--as-of", required=True, help="交易日 YYYY-MM-DD")
    parser.add_argument("--lookback", type=int, default=10, help="披露回溯窗口（自然日，缺省 10）")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--universe", choices=("subset", "pool"), default="subset",
                        help="subset=生效范围（持仓+当日可买）；pool=全池，仅供阈值校准")
    args = parser.parse_args()
    hits = run(date.fromisoformat(args.as_of), args.lookback, args.timeout, args.universe)
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
