#!/usr/bin/env python3
"""Regression tests for the band-card validator (工作流 §6.5/§6.6/§6.7).

Run: ``python3 scripts/test_validate_valuation_bands.py``

These lock down the rules that a future model or agent could quietly relax:
the band must be recomputable from declared inputs, and a tier-back-solved
band must never pass. One case exists because the first self-test caught a
real bug — a misleading severity on passing rows.

The nine §6.5.6 growth-option cases were deleted on 2026-08-03 along with the
mechanism itself (retired and *forbidden* since v2.00; all five
``growth_option_*`` columns empty across all 261 rows, so the guard had never
fired). They were 9 of 21 cases — 43% of the suite defending a banned branch
while no case covered the failures that actually happen. See
``test_failure_semantics.py`` for those.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_valuation_bands import check_row  # noqa: E402


ANCHOR, MULT, SHARES = 600.0, 20.0, 44.0          # 归母 600亿 × PE20 ÷ 44亿股
BASE_LOW = ANCHOR * MULT * 1.0 / SHARES           # PEG 1.0
BASE_HIGH = ANCHOR * MULT * 1.5 / SHARES          # PEG 1.5
BASE_MID = (BASE_LOW + BASE_HIGH) / 2


def model_row(**overrides) -> dict:
    row = {
        "security_code": "300750",
        "security_name": "测试",
        "quality_tier": "L1",
        "strategy_tag": "C-GARP成长型",
        "anchor_metric": "forward_normalized_profit",
        "anchor_value": str(ANCHOR),
        "anchor_scope": "market_cap",
        "anchor_basis": "ycmx 逐份研报归母中位数 2026E，覆盖 45 家",
        "multiple_or_rate": str(MULT),
        "multiple_source": "peer_median",
        "band_low_coef": "1.0",
        "band_high_coef": "1.5",
        "shares_out": str(SHARES),
        "band_derivation": "model",
        "band_sensitivity": "锚±15% → 带 ±15%",
        "band_fragile": "false",
        "fair_price_low": str(BASE_LOW),
        "fair_price_high": str(BASE_HIGH),
        "base_band_low": str(BASE_LOW),
        "base_band_high": str(BASE_HIGH),
        "growth_option_value": "",
        "fair_price_basis": "C 档 PEG 带 1.0-1.5",
    }
    row.update(overrides)
    return row



def a2_row(tier: str, low: float, high: float) -> dict:
    """A-2 行：锚为归一化归母 × 自身 5 年 PE 中位，系数按分层。"""
    value = ANCHOR * MULT
    return model_row(
        quality_tier=tier,
        strategy_tag="A-现金流复利型",
        anchor_metric="normalized_profit",
        multiple_source="own_history_median",
        band_low_coef=str(low),
        band_high_coef=str(high),
        fair_price_low=str(value * low / SHARES),
        fair_price_high=str(value * high / SHARES),
        base_band_low=str(value * low / SHARES),
        base_band_high=str(value * high / SHARES),
    )


CASES: list[tuple[str, callable, str | None]] = [
    # (名称, 取问题列表的函数, 期望命中的关键片段；None = 期望无问题)
    ("合法模型带通过", lambda: check_row(model_row())[0], None),
    # OI-004：A-2 带系数按质量分层分档（L1 0.90-1.15 / L2 0.85-1.05 / L3 0.80-1.00）
    ("A-2 L1 用 0.90-1.15 通过",
     lambda: check_row(a2_row("L1", 0.90, 1.15))[0], None),
    ("A-2 L3 用 0.80-1.00 通过",
     lambda: check_row(a2_row("L3", 0.80, 1.00))[0], None),
    ("A-2 L3 误用 L1 系数被拦",
     lambda: check_row(a2_row("L3", 0.90, 1.15))[0], "检查3"),
    ("A-2 L2 误用 L1 系数被拦",
     lambda: check_row(a2_row("L2", 0.90, 1.15))[0], "检查3"),
    ("合法模型带 severity=ok", lambda: [] if check_row(model_row())[1] == "ok" else ["severity 应为 ok"], None),
    ("非模型带被拦（检查6）",
     lambda: check_row(model_row(band_derivation="fallback"))[0], "检查6"),
    ("带系数偏离类型表被拦（检查3）",
     lambda: check_row(model_row(band_low_coef="0.9", band_high_coef="1.2"))[0], "检查3"),
    ("复算偏差 >2% 被拦（检查4）",
     lambda: check_row(model_row(fair_price_high=str(BASE_HIGH * 1.10)))[0], "检查4"),
    ("锚定量与标签不匹配被拦（检查2）",
     lambda: check_row(model_row(anchor_metric="resource_nav"))[0], "检查2"),
    ("已退役标签 G 被拦（检查2）",
     lambda: check_row(model_row(strategy_tag="G-股东回报型低估"))[0], "不是主标签"),
    ("缺建带卡 → backfill 而非 blocking",
     lambda: [] if check_row({k: ("" if k in {"anchor_metric", "anchor_value"} else v)
                              for k, v in model_row().items()})[1] == "backfill" else ["应判 backfill"], None),
]


def main() -> int:
    failed = 0
    for name, run, expect in CASES:
        problems = run()
        if expect is None:
            ok = not problems
            detail = f"期望无问题，实得 {problems}"
        else:
            ok = any(expect in p for p in problems)
            detail = f"期望命中 '{expect}'，实得 {problems}"
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"        {detail}")
            failed += 1
    print(f"\n{len(CASES) - failed}/{len(CASES)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
