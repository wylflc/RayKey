#!/usr/bin/env python3
"""从 `data/raw/financials/` 逐季面板派生逐票最新财务指标（OI-094）。

替代已随港美管线退役的 `a_share_financial_indicators.csv` 快照抓取器：
`latest_report_date`/`latest_report_type` 与 §5.6 重大财务变化判据改由逐季面板现算。
面板由 `fetch_a_share_quarterly_financials.py` 增量刷新（§5.3／§6.7 第 1 步），
每期一个 `YYYY-MM-DD.csv`、全市场覆盖，故队列判据随披露自动跟进，不再冻结在某次快照上。

输出字段对齐原快照的消费面（两个队列脚本只读这几列）：
`latest_report_date` / `latest_report_type` / `revenue_yoy_pct` / `profit_yoy_pct` /
`gross_margin_pct` / `net_margin_pct`（归母净利÷营收，现算）/
`cashflow_to_revenue_pct`（经营现金流÷营收的**比值**，股数按 归母净利÷基本EPS 估算——
原快照该列虽名带 pct 实为比值，阈值 −0.05 语义保持不变）。
原快照的 `debt_asset_ratio_pct` 与 `research_expense_to_revenue_pct` 面板不提供，
对应判据已随 §5.6 改写移除。
"""

from __future__ import annotations

import csv
from pathlib import Path

# 只扫最近 12 个报告期（3 年）：3 年无任何披露的代码不参与队列判据（近似退市/长停）。
LOOKBACK_PERIODS = 12

REPORT_TYPE = {"03-31": "一季报", "06-30": "中报", "09-30": "三季报", "12-31": "年报"}


def _as_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def load_latest_indicators(fin_dir: Path, as_of: str = "") -> dict[str, dict[str, str]]:
    """{代码: 指标行}。按报告期从新到旧扫描，每码取其最新一期。

    `as_of` 给定时做时点过滤：报告期末 > as_of 的整期跳过；`notice_date` 晚于 as_of 的行
    跳过（公告日缺失的行按报告期末已过滤，不再二次判）。
    """
    files = sorted(
        (p for p in fin_dir.glob("????-??-??.csv") if not as_of or p.stem <= as_of),
        reverse=True,
    )[:LOOKBACK_PERIODS]
    out: dict[str, dict[str, str]] = {}
    for path in files:
        period = path.stem
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                code = (row.get("security_code") or "").zfill(6)
                if not code or code in out:
                    continue
                notice = (row.get("notice_date") or "").strip()
                if as_of and notice and notice > as_of:
                    continue
                revenue = _as_float(row.get("total_operate_income"))
                profit = _as_float(row.get("parent_netprofit"))
                eps = _as_float(row.get("basic_eps"))
                ocf_ps = _as_float(row.get("op_cashflow_ps"))
                net_margin = profit / revenue * 100 if profit is not None and revenue else None
                cf_ratio = None
                if profit is not None and eps and revenue and ocf_ps is not None:
                    cf_ratio = ocf_ps * (profit / eps) / revenue
                out[code] = {
                    "security_code": code,
                    "security_name": row.get("security_name", ""),
                    "latest_report_date": row.get("report_date") or period,
                    "latest_report_type": REPORT_TYPE.get(period[5:], ""),
                    "latest_notice_date": notice,
                    "revenue_yoy_pct": row.get("revenue_yoy", ""),
                    "profit_yoy_pct": row.get("netprofit_yoy", ""),
                    "gross_margin_pct": row.get("gross_margin", ""),
                    "net_margin_pct": f"{net_margin:.4f}" if net_margin is not None else "",
                    "cashflow_to_revenue_pct": f"{cf_ratio:.6f}" if cf_ratio is not None else "",
                }
    return out
