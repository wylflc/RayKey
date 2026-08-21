"""定期报告的可得日：`min(记录公告日, 法定披露截止日)`（OI-042，两侧共用的唯一实现）。

**为什么必须封顶**：东财 `RPT_LICO_FN_CPD` 与三大报表的 `NOTICE_DATE` 对大量报告期记的是
**次年同期报告的公告日**——年报中位滞后 1998-2009 为 456~473 天、2013-2015 为 451~456 天
（正常 113 天），判例 600104 的 2001／2002／2003 年报分别记为 2003-03-26／2004-03-03／2005-02-05；
2016 年起中位恢复正常，但仍有约 11% 的行偏移整一年（2026-08-21 量测：逐季财务 2016+ 四类报告期
被封顶 6.7%~12.3%，封顶量中位 182~362 天；三表年报 2016+ 6.0%）。

按法规该期数据在截止日必然已公开（年报次年 4/30、一季报当年 4/30、半年报 8/31、三季报 10/31），
故封顶**只纠正偏移、不引入前视**；代价是少数真实逾期披露者（多为 ST 类）与按境外规则披露的
红筹 CDR（判例：中芯国际 688981 的 2024 三季报 11-08 披露、被封到 10-31）被提前到截止日，
量级以天计、且这类行基本不在护城河面板内或已是陈旧带。

两个消费方：
* 判定侧 `build_judgment_input.py`（v3.x 起已用同一规则，此前本函数在该脚本内部）；
* 建带侧 `build_historical_valuation_bands.py` / `roic_inputs.py`（`--notice-cap statutory`，缺省）：
  逐季财务与三大报表在**装载时**就把 `notice_date` 改成可得日，下游的 `available_at =
  max(所用各期公告日)`、`fiscal_years_before`、`split_factor`／`exright_adjust` 的除权锚全部随之一致。
"""
from __future__ import annotations

# 报告期末 → (年份偏移, 截止月, 截止日)
_DEADLINE = {"12-31": (1, 4, 30), "03-31": (0, 4, 30), "06-30": (0, 8, 31), "09-30": (0, 10, 31)}


def statutory_deadline(report_date: str) -> str | None:
    """该报告期的法定披露截止日；非标准期末返回 None。"""
    spec = _DEADLINE.get(report_date[5:]) if len(report_date) == 10 else None
    if not spec:
        return None
    offset, month, day = spec
    return f"{int(report_date[:4]) + offset:04d}-{month:02d}-{day:02d}"


def available_at(report_date: str, notice_date: str) -> str:
    """可得日 = `min(记录公告日, 法定截止日)`；公告日缺失或报告期非标准时原样返回。"""
    deadline = statutory_deadline(report_date)
    if deadline is None or len(notice_date) != 10:
        return notice_date
    return min(notice_date, deadline)
