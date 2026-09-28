"""银行估值（§6.5.1 第 4 条，v4.215，OI-207 H2）：股利尺度 × DDM 排序的唯一实现。

历史逐日（`rebuild_bank_bands.py h2:RP:COE`）、实时扫描（`screen_daily_volume_price_signals.resolve_live_band`）
与池外档案（`apply_model_bands_to_dossiers.py`）共用本模块：

* **V_D0**：最近已知完整财年每股现金分红 ÷ (十年国债 + RP)（分子口径 `divspread_dividend`），按除权参考价折到当日；
* **V_DDM**：同一条 ROE／BV 路径上的股利贴现——ROE 自 roe0 十年线性衰减到 `ROE_T = min(roe0, COE + 2pp)`，
  BV 按留存滚存，`DPS_t = ROE_t × BV_{t−1} × 派息率`，终值 `DPS_11 ÷ (COE − g_T)`、`g_T = min(3%, ROE_T × 留存)`，
  基本面取 `roic_bands.csv` 可得日不晚于当日的最近一行（bps／roe0／payout），按除权参考价折到当日；
* **H2**：当日两者都可估的银行（保险除外）`G = exp(mean ln(V_D0 ÷ V_DDM))`，`V_H2 = V_DDM × G`；
  可估银行不足 `MIN_BANKS` 时当日退回 V_D0，保险恒为 V_D0。G 是估值之比的几何均值，价格不进 V（§6.3 第 1 条）。
* **同尺系数**（OI-227）：银行（保险除外）的 V（含退回的 V_D0）再乘 `BANK_SCALE`，使同 `P/V` 下银行与非金融的预期回报可比；
  系数由月末 `P/V` 对其后 3 年回报的同尺校准得出（`exp(−c/b)`，c 为银行偏差、b 为共同斜率）。
"""
from __future__ import annotations

import bisect
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable

COE = 0.10                  # DDM 的股权成本（与 §6.5.1 统一 r 同值）
FADE_YEARS = 10
TERMINAL_EXCESS = 0.02      # ROE_T = min(roe0, COE + 2pp)，与主模型 ROIC_T = WACC + 2pp 同规
G_CAP = 0.03                # 终值增长上限
DEFAULT_PAYOUT = 0.30
MIN_BANKS = 5
BANK_SCALE = 0.6951         # OI-227 同尺系数：面板 3 年全期校准，c = −0.0205、b = −0.0565（v4.216 口径，回测日志 §12.279）


def roe_bv_path(bps: float, roe0: float, payout: float | None, coe: float, fade_years: int = FADE_YEARS):
    """ROE 自 roe0 线性衰减到 ROE_T，BV 按留存滚存。返回 (逐年 (roe_t, bv_prev), roe_T, g_T, bv_N, 留存率)。"""
    b = 1.0 - (payout if payout is not None else DEFAULT_PAYOUT)
    b = min(max(b, 0.0), 1.0)
    roe_t_end = min(roe0, coe + TERMINAL_EXCESS)
    g_t = min(G_CAP, roe_t_end * b)
    path, bv = [], bps
    for t in range(1, fade_years + 1):
        roe_t = roe0 + (roe_t_end - roe0) * t / fade_years
        path.append((roe_t, bv))
        bv = bv * (1.0 + roe_t * b)
    return path, roe_t_end, g_t, bv, b


def ddm_value(bps: float, roe0: float, payout: float | None, coe: float = COE, fade_years: int = FADE_YEARS) -> float | None:
    """同一 ROE／BV 路径上的股利贴现；分母塌陷（COE − g_T < 2pp）或不派息返回 None。"""
    path, roe_t_end, g_t, bv_n, b = roe_bv_path(bps, roe0, payout, coe, fade_years)
    pay = 1.0 - b
    if coe - g_t < 0.02 or pay <= 0:
        return None
    pv = sum(roe_t * bv_prev * pay / (1.0 + coe) ** t for t, (roe_t, bv_prev) in enumerate(path, start=1))
    return pv + roe_t_end * bv_n * pay / (coe - g_t) / (1.0 + coe) ** fade_years


def h2_scale(pairs: Iterable[tuple[float | None, float | None]]) -> float | None:
    """当日银行截面 `G = exp(mean ln(V_D0 ÷ V_DDM))`；两者都为正的银行不足 MIN_BANKS 返回 None。"""
    logs = [math.log(d0 / dd) for d0, dd in pairs if d0 and dd and d0 > 0 and dd > 0]
    return math.exp(sum(logs) / len(logs)) if len(logs) >= MIN_BANKS else None


class BankFundamentals:
    """`roic_bands.csv` 中银行保险行的 (可得日, bps, roe0, payout, bps 基准日) 阶梯，按日取最近一行。"""

    def __init__(self, bands: Path, codes: set[str]):
        seq: dict[str, list] = defaultdict(list)
        with Path(bands).open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                code = r["security_code"].zfill(6)
                av = r.get("available_at") or ""
                if code not in codes or len(av) != 10:
                    continue
                seq[code].append((av, _num(r.get("bps")), _num(r.get("roe0")), _num(r.get("payout")),
                                  r.get("bps_basis_date") or av))
        self.seq = {c: sorted(v, key=lambda x: x[0]) for c, v in seq.items()}
        self.keys = {c: [x[0] for x in v] for c, v in self.seq.items()}

    def at(self, code: str, day: str):
        keys = self.keys.get(code)
        if not keys:
            return None
        i = bisect.bisect_right(keys, day) - 1
        return self.seq[code][i] if i >= 0 else None


def ddm_at(fund: BankFundamentals, actions: list[dict], code: str, day: str, coe: float = COE) -> float | None:
    """`day` 当日的 V_DDM（按除权参考价折到当日股本基准，锚取带可得日、送转自 bps 基准日）。"""
    from build_historical_valuation_bands import exright_adjust
    f = fund.at(code, day)
    if not f:
        return None
    band_av, bps, roe0, payout, basis = f
    if not bps or bps <= 0 or roe0 is None or roe0 <= 0:
        return None
    v = ddm_value(bps, roe0, payout, coe)
    if v is None or v <= 0:
        return None
    (adj,), _factor, _cash = exright_adjust(actions, band_av, day, (v,), split_since=basis)
    return adj if adj > 0 else None


def bank_codes(securities: Path) -> set[str]:
    """全市场证券名单中的银行（`divspread_names` 判定的银行保险减去保险）。"""
    from divspread_names import INSURER_CODES, is_divspread_financial
    with Path(securities).open(encoding="utf-8-sig", newline="") as fh:
        rows = [(r["security_code"].zfill(6), r.get("security_name", "")) for r in csv.DictReader(fh)]
    return {c for c, n in rows if is_divspread_financial(c, n) and c not in INSURER_CODES}


def live_h2(as_of: str, d0, bands: Path, actions: dict[str, list], securities: Path) -> dict[str, float]:
    """实时（信号日）：各银行 V_D0（调用方给的 `d0(code)`，与历史同一分子与除权）与 V_DDM → 截面 G → {代码: V_H2 × BANK_SCALE}。
    只含两者都可估的银行；截面不足 MIN_BANKS 返回空，调用方退回 V_D0（银行同样乘 BANK_SCALE）。"""
    codes = bank_codes(securities)
    fund = BankFundamentals(bands, codes)
    pairs = {c: (d0(c), ddm_at(fund, actions.get(c, []), c, as_of)) for c in sorted(codes)}
    g = h2_scale(pairs.values())
    if g is None:
        return {}
    return {c: dd * g * BANK_SCALE for c, (v0, dd) in pairs.items() if v0 and dd and v0 > 0 and dd > 0}


def _num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None
