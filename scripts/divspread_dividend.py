#!/usr/bin/env python3
"""银行/保险股利折现的分子：**最近一个已知完整财年**的每股现金分红合计（OI-099）。

`V = 年度分红 ÷ (十年国债 + RP)`。`rebuild_bank_bands.py`（历史逐日）与
`screen_daily_volume_price_signals.bank_dividend_intrinsic`（实盘）都从这里取同一分子。

为什么不是「近 12 个月除权的分红之和」
--------------------------------------
2026-08-24 前两侧都按 `[t−365d, t]` 内的除权日求和。A 股年度分红除权日每年浮动一两周，
两次年度除权相隔不足 365 天时窗口同时装进两笔年度分红、旧笔退出后再腰斩——实测 42 只
银行/保险 2022 年起单日 |ΔV| 最大值全部 >30%（工商银行 2024-07-16 V 7.22→14.50→7.29，
招商银行 2023-07-13 32.84→70.33，宁波银行 2024-07-10 +120% 且当日恰好首次穿越买入线）。
2024 年起银行普遍加派中期分红，同一财年拆成两笔除权，滚动窗口更是把「拆分」当成「加倍」。

口径
----
1. **归属**：每笔分红按东财 `report_date`（分红所属报告期：06-30 中期、09-30 三季、12-31 年度、
   03-31 一季、特别分红亦带报告期）归入财年 = `report_date[:4]`。不解析公告文字。
2. **可得日**：`plan_notice_date`（董事会预案公告日，东财 `PLAN_NOTICE_DATE`，2003 年起齐全且
   恒 ≤ 除权日）；旧数据无该列时退到 `ex_dividend_date`。信息在预案公告时已完整，不等除权。
3. **财年何时算完整**：已知该财年的年度分配（`report_date` 为 12-31 的一笔），或时点已过次年
   4-30（年报法定截止：到期仍无年度分配 = 该年只有中期或不分红）。取满足其一的最新财年。
4. 该财年已知各笔合计 ≤ 0 → 无值（不退到更早财年：不分红就是不分红）。

除权归一化、止损锚、成本调整仍按除权日——那是价格机械变动，与本模块无关。
"""
from __future__ import annotations

import bisect
import csv
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIONS_CSV = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"
RISK_PREMIUM = 0.02                 # §12.31：股息率要比十年国债高出 2pp 才算合理价
ANNUAL_REPORT_DEADLINE_MD = "04-30"  # 年报法定截止（次年）


@dataclass(frozen=True)
class Distribution:
    available_at: str   # 预案公告日；无则除权日
    report_date: str    # 分红所属报告期末
    cash: float         # 每股税前现金（元）
    ex_date: str        # 除权日；预案阶段为空


def available_at_of(row: dict) -> str:
    plan = (row.get("plan_notice_date") or "").strip()[:10]
    ex = (row.get("ex_dividend_date") or "").strip()[:10]
    return plan if len(plan) == 10 else ex


def load_distributions(path: Path = ACTIONS_CSV,
                       codes: set[str] | None = None) -> dict[str, list[Distribution]]:
    """代码 → 现金分红列表（cash>0），按可得日升序。文件不存在返回空。"""
    out: dict[str, list[Distribution]] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            code = (row.get("security_code") or "").zfill(6)
            if codes is not None and code not in codes:
                continue
            try:
                cash = float(row.get("cash_per_share") or 0)
            except ValueError:
                cash = 0.0
            avail = available_at_of(row)
            report = (row.get("report_date") or "").strip()[:10]
            if cash <= 0 or len(avail) != 10 or len(report) != 10:
                continue
            out.setdefault(code, []).append(Distribution(
                avail, report, cash, (row.get("ex_dividend_date") or "").strip()[:10]))
    for items in out.values():
        items.sort(key=lambda d: (d.available_at, d.report_date))
    return out


def fiscal_year_closed_by_deadline(as_of: str) -> int:
    """时点已过年报截止日的最新财年：`as_of` 在 5-1 及之后 → 上一年，否则前两年。"""
    year = int(as_of[:4])
    return year - 1 if as_of[5:10] > ANNUAL_REPORT_DEADLINE_MD else year - 2


def annual_dividend(dists: list[Distribution], as_of: str) -> tuple[float, str] | None:
    """`as_of` 时点最近一个已知完整财年的每股现金分红合计 → `(合计, 财年)`；无则 None。"""
    known = dists[:bisect.bisect_right([d.available_at for d in dists], as_of)]
    if not known:
        return None
    annual_years = [int(d.report_date[:4]) for d in known if d.report_date[5:] == "12-31"]
    fiscal_year = max(max(annual_years, default=0), fiscal_year_closed_by_deadline(as_of))
    total = sum(d.cash for d in known if d.report_date[:4] == f"{fiscal_year:04d}")
    return (total, f"{fiscal_year:04d}") if total > 0 else None


def dividend_value(annual: float, rf: float, rp: float = RISK_PREMIUM) -> float | None:
    """`V = 年度分红 ÷ (rf + rp)`；分母非正返回 None。"""
    return annual / (rf + rp) if (rf + rp) > 0 else None
