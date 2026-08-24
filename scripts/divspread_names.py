#!/usr/bin/env python3
"""股利折现覆盖名单（工作流 §6.5.1 第 4 条：银行与保险）。

唯一判定实现：银行按名称（「银行」／以「行」结尾／「农商」），保险按 A 股上市保险公司代码清单
＋名称（「保险」／以「人寿」「人保」「太保」结尾）。**不按名称匹配「平安」**——平安电工(001359)会误中；
中国平安(601318)靠代码清单进入。`rebuild_bank_bands.py`／`build_pool_model_bands.py`／
`screen_daily_volume_price_signals.py`／`apply_model_bands_to_dossiers.py` 都从这里取同一判定。
"""
from __future__ import annotations

INSURER_CODES = {"601318", "601319", "601336", "601601", "601628"}   # 平安、人保、新华、太保、国寿


BANK_NAMES_WITHOUT_KEYWORD = {"张家港行"}   # 42 家 A 股上市银行里唯一名称既无「银行」也无「农商」者


def is_bank_name(name: str) -> bool:
    # 不按「以行结尾」判：世联行／任子行／华致酒行／喜悦智行／永安行／三人行都不是银行（OI-099 前误中）。
    n = name or ""
    return ("银行" in n) or ("农商" in n) or n in BANK_NAMES_WITHOUT_KEYWORD


def is_insurer(code: str, name: str = "") -> bool:
    n = name or ""
    return (code or "").zfill(6) in INSURER_CODES or ("保险" in n) or n.endswith(("人寿", "人保", "太保"))


def is_divspread_financial(code: str, name: str = "") -> bool:
    """银行或保险：估值走 V = 最近已知完整财年每股现金分红 ÷（十年国债 + 2%）（分子见 `divspread_dividend`）。"""
    return is_bank_name(name) or is_insurer(code, name)
