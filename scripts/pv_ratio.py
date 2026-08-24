#!/usr/bin/env python3
"""§3／§9.3 的交易估值比率 `P/V`（v4.62）——**唯一实现**，扫描器／跟踪器／池阅读版／档案 README 同源；生产口径 `现价 ÷ V`。
薄权益（净负债 ≥ 50% 企业价值）的带在建带侧按 OI-091 守卫判无法估值、不会出现在生产带文件。`basis="ev"` 为研究口径。
"""
from __future__ import annotations

EV_PATHS = ("growth", "zero_growth")


def _num(value) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text not in ("", "None") else None
    except (TypeError, ValueError):
        return None


def trading_pv(price: float | None, band: dict, basis: str = "equity") -> float | None:
    """按带行算 `P/V`；价或 V 不可得返回 None。生产口径 `basis="equity"`＝现价÷V（§3）；`basis="ev"` 为 OI-091 实测否决的研究口径
    （(现价+每股净负债)÷每股企业价值：对净现金公司把小股东够不着的现金按面值记便宜、对中等杠杆公司压低真实的每股折价，回测日志 §12.120）。"""
    iv = _num(band.get("intrinsic_value"))
    if price is None or iv is None or iv <= 0 or price <= 0:
        return None
    if basis == "ev" and (band.get("roic_path") or "").strip() in EV_PATHS:
        ev = _num(band.get("ev_ps"))
        nd = _num(band.get("net_debt_ps"))
        if ev is None and nd is not None:
            ev = iv + nd
        if ev is not None and ev > 0:
            if nd is None:
                nd = ev - iv
            return (price + nd) / ev
    return price / iv


def load_model_bands(path=None, as_of: str = "") -> dict[str, dict]:
    """{代码: 生产带行}（`data/processed/a_share_pool_model_bands_adopted.csv`）；读不到返回空 dict。

    `as_of`（YYYY-MM-DD）非空时只取 `available_at ≤ as_of` 的行、逐票留最新一条（OI-095）：
    历史日期重放不得用当日之后才可得的带。"""
    import csv
    from pathlib import Path as _P
    target = _P(path) if path else _P(__file__).resolve().parents[1] / "data/processed/a_share_pool_model_bands_adopted.csv"
    out: dict[str, dict] = {}
    best_avail: dict[str, str] = {}
    try:
        with target.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                code = (row.get("security_code") or "").strip().zfill(6)
                if not code or (row.get("status") or "ok") not in ("", "ok"):
                    continue
                avail = (row.get("band_available_at") or row.get("available_at") or "").strip()
                if as_of and not (len(avail) == 10 and avail <= as_of):
                    continue
                if code not in out or avail >= best_avail[code]:
                    out[code] = row
                    best_avail[code] = avail
    except OSError:
        return {}
    return out


def pv_formula_note(band: dict, basis: str = "equity") -> str:
    """阅读用：该行 P/V 用的公式。"""
    if basis == "ev" and (band.get("roic_path") or "").strip() in EV_PATHS:
        return "(现价＋每股净负债)÷每股企业价值"
    return "现价÷V"
