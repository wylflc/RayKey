#!/usr/bin/env python3
"""原始财务数据订正层（OI-066，用户 2026-08-19 裁定建层）。

`data/raw/financials/` 是取数产物：手改会被下一次强制重取覆盖，而数据源自身的错值
（判例：宏桥控股 FY2024/FY2025 的 `bps` 偏大约 10 倍，东财源侧复核仍错）会静默改变
估值带与买卖判定。订正登记在 `data/reference/financials_corrections.csv`，逐行记
代码、报告期、字段、错值、正值、依据；**消费方在读入面板后调用 `apply_corrections`
在内存中替换，取数产物本身永不改写**。

防错设计：只有当面板现值仍等于登记的 `wrong_value`（按 float 容差）才替换——
若源侧某天订正了，登记行自动失效并在返回值中报告，不会把正值改回错值。
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORRECTIONS = ROOT / "data/reference/financials_corrections.csv"


def load_corrections(path: Path = CORRECTIONS) -> dict[tuple[str, str], list[dict]]:
    """{(代码, 报告期): [订正行]}；文件缺失返回空。"""
    out: dict[tuple[str, str], list[dict]] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            code = (row.get("security_code") or "").strip().zfill(6)
            period = (row.get("report_date") or "").strip()
            if code and period:
                out.setdefault((code, period), []).append(row)
    return out


def apply_corrections(panel: dict[str, dict[str, dict]],
                      corrections: dict[tuple[str, str], list[dict]] | None = None,
                      ) -> tuple[list[str], list[str]]:
    """就地替换 {代码: {报告期: 行}} 面板中的登记错值。

    返回 (applied, stale)：applied 为已生效的订正描述；stale 为「面板现值已不等于
    登记错值」的失效登记（源侧可能已订正，须人工复核该登记行）。
    """
    if corrections is None:
        corrections = load_corrections()
    applied: list[str] = []
    stale: list[str] = []
    for (code, period), rows in corrections.items():
        series = panel.get(code) or panel.get(code.lstrip("0"))
        if not series or period not in series:
            continue
        target = series[period]
        for corr in rows:
            field = (corr.get("field") or "").strip()
            if not field or field not in target:
                continue
            try:
                current = float(target.get(field) or "nan")
                wrong = float(corr.get("wrong_value") or "nan")
                fixed = float(corr.get("corrected_value") or "nan")
            except (TypeError, ValueError):
                continue
            if fixed != fixed:
                continue
            if current == current and wrong == wrong and abs(current - wrong) <= abs(wrong) * 1e-6:
                target[field] = f"{fixed}"
                applied.append(f"{code} {period} {field} {wrong:g}→{fixed:g}")
            else:
                stale.append(f"{code} {period} {field}：面板现值 {target.get(field)} ≠ 登记错值 "
                             f"{corr.get('wrong_value')}（源侧或已订正，须复核登记行）")
    return applied, stale


def report(applied: list[str], stale: list[str]) -> None:
    if applied:
        print(f"  数据订正层（OI-066）生效 {len(applied)} 处：{'；'.join(applied)}")
    for line in stale:
        print(f"  ⚠ 订正登记已失效：{line}")
