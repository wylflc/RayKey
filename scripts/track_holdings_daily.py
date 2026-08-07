#!/usr/bin/env python3
"""每日持仓跟踪（工作流 §14，v2.05）。

取代 `scan_holdings_sell_signals.py`。该脚本自 v2.05 起只做三件事：

1. 读五列持仓清单（代码/名称/股数/成本价/割肉价）；
2. 取当日现价，对照核心估值合格池刷新现档（§6.2.1.6）与带内位置；
3. 现价 <= 割肉价时置 `割肉提醒`，否则 `持有`。

**刻意不做**的事（§14.6 退役清单）——盈亏、权重、仓位占比、单笔风险、
大趋势走坏判定（MA60/MA120/启动结构/MA20）、估值卖出资格与减仓梯、
加仓资格、账户回撤与杠杆。这些不是"暂时没实现"，是用户 2026-08-03
明确要求移除的；若将来要加回来，先改 §14 再改这里（§15 第 3 条）。

`重大事项` 由大模型在逐票公告/新闻检索后判定，脚本不产出该取值。
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from a_share_quotes import fetch_spot_quotes
from workflow_decision_log import WORKFLOW_VERSION, append_decision_log

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
DEFAULT_VALUATION_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/daily_holdings_tracking.csv"
DEFAULT_DECISION_LOG = ROOT / "data/processed/a_share_workflow_decision_log.csv"

FIELDNAMES = [
    "as_of",
    "security_code",
    "security_name",
    "current_shares",
    "cost_basis",
    "stop_loss_price",
    "close",
    "quality_tier",
    # §9.2.1 参考分（v2.14）：只透传分层表经池 CSV 带过来的 quality_score，供报告显示同档内排序；
    # 不参与任何判定，也不在此重算。
    "quality_score",
    "effective_valuation_tier",
    "fair_price_low",
    "fair_price_high",
    "upside",
    # 参考读数，不进 §14.3 判定（v2.16 起割肉价只比收盘价）；留列是为了让「盘中曾低于割肉价、
    # 收盘收回」这类日子在 CSV 里可见，而不是判定完就查不到。
    "day_low",
    "stop_hit",
    "action",
    "note",
    "scanned_at_utc",
]


def to_float(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def load_pool(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["security_code"]: row for row in csv.DictReader(handle)}


def effective_tier(close: float, low: float | None, high: float | None) -> tuple[str, str]:
    """§6.2.1.6 价格自动定档 + 空间（区间中值/现价 − 1）。带缺失时返回空档与空空间。

    v2.11（用户指令）：第五列由「带位」改为「空间」。带位（带内X%／低于带底-X%／越带顶+X%）
    与空间是同一件事的两种写法，而空间与池阅读版、§9.6 名单同口径且可直接比较——池 MD 早在
    v1.10 就以同样理由删掉了带位列，持仓表此前一直没跟上。
    """
    if low is None or high is None or high <= 0 or close <= 0:
        return "", ""
    pct = round(((low + high) / 2 / close - 1) * 100)
    upside = "0%" if pct == 0 else f"{pct:+d}%"
    if close > 1.2 * high:
        return "高估", upside
    if close > high:
        return "较高估", upside
    if close >= low:
        return "中性", upside
    return ("低估" if (low + high) / 2 / close - 1 >= 0.40 else "较低估"), upside


def track(holdings_file: Path, pool_file: Path, as_of: date, symbols: str, timeout: float) -> list[dict[str, object]]:
    with holdings_file.open(newline="", encoding="utf-8") as handle:
        holdings = list(csv.DictReader(handle))
    wanted = {s.strip().zfill(6) for s in symbols.split(",") if s.strip()}
    if wanted:
        holdings = [h for h in holdings if h["security_code"].zfill(6) in wanted]

    pool = load_pool(pool_file)
    quotes = fetch_spot_quotes([(h["security_code"], "") for h in holdings], timeout=timeout)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows: list[dict[str, object]] = []
    for h in holdings:
        code = h["security_code"].zfill(6)
        quote = quotes.get(code) or {}
        close = to_float(quote.get("price"))
        stop = to_float(h.get("stop_loss_price"))
        pool_row = pool.get(code)
        low = to_float(pool_row.get("fair_price_low")) if pool_row else None
        high = to_float(pool_row.get("fair_price_high")) if pool_row else None

        tier, upside = ("", "")
        if close is not None:
            tier, upside = effective_tier(close, low, high)

        notes: list[str] = []
        if close is None:
            notes.append("**未取到当日行情**（停牌或接口失败）：割肉价未判定，请人工核对（§14.5）")
        if pool_row is None:
            notes.append("不在核心估值合格池内，无带")
        elif low is None or high is None:
            notes.append("池内无合理价区间（无法估值）")
        if stop is None:
            notes.append("**未设定割肉价**：该仓无机械提醒，请尽快补定（§14.3 第 3 条）")

        # §14.3 第 1 条（v2.16 用户裁定「盘中的波动，不作为判定标准」）：**只比收盘价**。
        # `day_low` 仍逐行输出，但只作参考读数，不进判定——盘中最低价一度低于割肉价而收盘收回的，
        # 判 `持有`（判例：九号公司 2026-08-07 割肉价 39.78，最低 39.39、收盘 40.09 → 持有）。
        day_low = to_float(quote.get("day_low"))
        stop_hit = bool(close is not None and stop is not None and close <= stop)
        # §14.5 四取值。无行情时必须落 `数据缺失` 而非 `持有`：`持有` 是唯一读起来像
        # "已检查、没事" 的取值，而没有现价恰恰意味着割肉价没判过。旧版在此落 `持有`
        # 并写 "沿用上一交易日结论"，但脚本从不读上一日文件——一只已破割肉价的停牌股
        # 会显示为持有，在 Tier-0 规则上制造静默失效（§15.2 第 3 条）。
        if stop_hit:
            action = "割肉提醒"
        elif close is None:
            action = "数据缺失"
        else:
            action = "持有"

        rows.append(
            {
                "as_of": as_of.isoformat(),
                "security_code": code,
                "security_name": h.get("security_name", ""),
                "current_shares": h.get("current_shares", ""),
                "cost_basis": h.get("cost_basis", ""),
                "stop_loss_price": h.get("stop_loss_price", ""),
                "close": "" if close is None else f"{close:g}",
                "quality_tier": (pool_row or {}).get("quality_tier", ""),
                "quality_score": (pool_row or {}).get("quality_score", ""),
                "effective_valuation_tier": tier,
                "fair_price_low": "" if low is None else f"{low:g}",
                "fair_price_high": "" if high is None else f"{high:g}",
                "upside": upside,
                "day_low": "" if day_low is None else f"{day_low:g}",
                "stop_hit": stop_hit,
                "action": action,
                "note": "；".join(notes),
                "scanned_at_utc": now,
            }
        )
    return rows


def log_decisions(
    log_file: Path,
    rows: list[dict[str, object]],
    as_of: date,
    holdings_file: Path,
    output_csv: Path,
    pool_file: Path = DEFAULT_VALUATION_POOL,
) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = [
        {
            "logged_at_utc": now,
            "workflow_stage": "holdings_tracking",
            "run_id": f"holdings_tracking_{as_of.isoformat()}",
            "as_of": as_of.isoformat(),
            "security_code": row["security_code"],
            "security_name": row["security_name"],
            "decision_type": "daily_holdings_tracking",
            "decision_result": row["action"],
            "summary_reason": (
                f"现价 {row['close'] or 'NA'}｜{row['quality_tier'] or 'NA'}×{row['effective_valuation_tier'] or 'NA'}"
                f"｜带 {row['fair_price_low'] or 'NA'}-{row['fair_price_high'] or 'NA'}｜空间 {row['upside'] or 'NA'}"
                f"｜割肉价 {row['stop_loss_price'] or '未设定'}"
                + (f"｜{row['note']}" if row["note"] else "")
            ),
            # 溯源写实际用到的池文件；旧版硬写 DEFAULT_VALUATION_POOL，`--valuation-pool`
            # 指向别处时日志会记下一个本次没读过的路径。
            "input_files": f"{holdings_file}; {pool_file}",
            "source_urls": "",
            "output_file": str(output_csv),
            "operator_or_script": "track_holdings_daily.py",
            "workflow_version": WORKFLOW_VERSION,
            "decision_id": f"holdings_tracking:{as_of.isoformat()}:{row['security_code']}:01",
            "supersedes_decision_id": "",
        }
        for row in rows
    ]
    append_decision_log(log_file, records)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="每日持仓跟踪（§14，v2.05）")
    parser.add_argument("--as-of", required=True, help="交易日 YYYY-MM-DD")
    parser.add_argument("--holdings", type=Path, default=DEFAULT_HOLDINGS)
    parser.add_argument("--valuation-pool", type=Path, default=DEFAULT_VALUATION_POOL)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    parser.add_argument("--symbols", default="", help="可选：逗号分隔的代码过滤")
    parser.add_argument("--timeout", type=float, default=8.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    as_of = date.fromisoformat(args.as_of)
    rows = track(args.holdings, args.valuation_pool, as_of, args.symbols, args.timeout)

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    log_decisions(args.log_file, rows, as_of, args.holdings, args.output_csv, args.valuation_pool)

    hit = [r for r in rows if r["stop_hit"]]
    no_stop = [r for r in rows if not str(r["stop_loss_price"]).strip()]
    no_band = [r for r in rows if not r["fair_price_low"]]
    print(f"tracked {len(rows)} holdings as of {as_of}")
    hit_names = "、".join(str(r["security_name"]) for r in hit)
    print(f"  割肉提醒 {len(hit)} 只" + (f"：{hit_names}" if hit else ""))
    if no_stop:
        print(f"  **未设定割肉价 {len(no_stop)} 只**：{'、'.join(str(r['security_name']) for r in no_stop)}（§14.3 第 3 条，置顶提示）")
    if no_band:
        print(f"  无带（出池或无法估值）{len(no_band)} 只：{'、'.join(str(r['security_name']) for r in no_band)}")
    # §9.2.1 落地校验：新增列必须核对非空行数（§15.2 第 3 条已复发四次的静默失效签名就是「整列为空而无人察觉」）。
    scored = [r for r in rows if str(r["quality_score"]).strip()]
    print(f"  参考分（§9.2.1）非空 {len(scored)}/{len(rows)} 行")
    if rows and not scored:
        print("  **告警：quality_score 整列为空** —— 池 CSV 未透传参考分，报告不得手填，先修脚本/池物化")


if __name__ == "__main__":
    main()
