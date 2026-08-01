#!/usr/bin/env python3
"""Compute the §6.6 建带卡 draft for every worth_attention name from local evidence.

工作流 §15 第 1 条：能由脚本稳定完成的必须用脚本。锚定量取数、TTM 差分、
一致预期中位数、股本口径校验、倍数取数、带复算——全部是机械步骤，逐票手算
只会引入 v1.28 刚修掉的那种口径漂移。

This script does NOT create valuation opinions. It computes the mechanical part
of the card (§6.5.2.1) and marks explicitly what still needs外部取证 or judgment:

* `anchor_value`  — per §6.5.2.1 取数口径表 (TTM 差分 / 一致预期中位数 / 周期中枢)
* `multiple_or_rate` — 自身历史中位 (`valuation_band`) 或隐含 PB (J)
* `band_low/high` — per §6.5.2 类型表系数, recomputed by validate_valuation_bands
* `band_sensitivity` — 锚 ±15% 对应的带

Strategy tags come from `--tags` (代码,strategy_tag). Types whose anchor needs
外部取证 (F/K/M/N/P and A-1/H-ebitda) are emitted with `needs_external` set and
an empty anchor — per §6.5.2.1 they are 无法估值 until the evidence is fetched.

Usage::

    python3 scripts/build_valuation_band_cards.py \
      --tags data/interim/strategy_tag_map.csv \
      --out data/interim/valuation_band_cards.csv \
      --as-of 2026-08-01
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "data/interim/valuation_evidence"

# §6.5.2 类型表：tag -> (anchor_metric, shape, (low_coef, high_coef), 本地可算?)
TYPE_SPEC = {
    "A": ("normalized_profit", 1, None, True),                # A-2；系数按分层，见 A2_COEFS
    "C": ("forward_normalized_profit", 1, (1.0, 1.5), True),  # 系数即 PEG 带
    "D": ("normalized_profit_2_3y", 1, (0.80, 1.00), True),
    "E": ("repaired_normalized_profit", 1, (0.85, 1.00), True),
    "F": ("resource_nav", 1, (0.85, 1.00), True),             # primary 需储量；F-2 兜底本地可算
    "H": ("mid_cycle_profit", 1, (0.85, 1.00), True),
    "J": ("bvps", 1, (0.90, 1.10), True),
    "K": ("dps", 2, (1.0, 1.0), True),                        # primary 需分红率；K-2 兜底同 A-2
    "M": ("sotp_value", 1, (0.80, 1.00), True),               # primary 需管线；M-2 为不含管线的下限带
    "N": ("epv_profit", 1, (0.85, 1.00), True),               # primary 需同业利润率；N-2 用自身峰值
    "P": ("backlog_annual_profit", 1, (0.80, 1.00), True),    # primary 需订单；P-2 为不含订单的下限带
}

# §6.5.2 A-2 带系数按质量分层分档（v1.30，OI-004）
A2_COEFS = {"L1": (0.90, 1.15), "L2": (0.85, 1.05), "L3": (0.80, 1.00)}

# §6.5.3 C → A 迁出判据（v1.30，OI-005），带 12%/15% 迟滞
# 阈值按近三年最低 ROE 分档：ROE 越高，价值中来自存量特许经营权的比重越大，
# PEG（不含资本效率）越早失效，故越早迁出 C。
C_TO_A_CAGR_BY_ROE = ((20.0, 0.15), (12.0, 0.12))   # (ROE 下限, CAGR 阈值)
C_TO_A_MIN_ROE = 12.0
C_TO_A_MIN_CASH_CONV = 0.8

RISK_FREE = 0.018          # 10Y 国债，初始校准；修订先改工作流 §6.5.4
COE_BANK = 0.018 + 0.095   # 银行 ERP 8.0%-11.0% 取中值
MAX_G = 0.035

# §6.5.2.1 锚与倍数的同期约束（v1.30）：远期利润锚必须配终值倍数。
# PE = 1/(r − g_终值)，r 按质量分层（风险越高要求回报越高）。
TERMINAL_R_BY_TIER = {"L1": 0.09, "L2": 0.10, "L3": 0.11}
TERMINAL_G = 0.03

# §6.5.4 中枢窗口结构断点检验（v1.32，OI-007）：近 5 年净利率中位与前 5 年中位
# 偏离 >50% 即判存在结构断点，窗口收缩到近 5 年——否则结构性成长会被当成周期波动。
STRUCTURAL_BREAK_THRESHOLD = 0.50
PEER_MULTIPLE_MIN_GROUP = 3      # 同业组最少家数
PEER_MULTIPLE_LEVELS = (3, 2)    # 只用三级/二级行业；退到一级会把整个板块当同业
AS_OF_YEAR = 2026                # 折现基准年（现值口径的 T0）


_PEER_CACHE: dict[str, tuple[dict[str, str], dict[str, float]]] = {}


def _peer_universe() -> tuple[dict[str, str], dict[str, float]]:
    """行业映射 + 各票自身 5 年 PE 中位（同业中枢倍数的样本池）。"""
    if "data" in _PEER_CACHE:
        return _PEER_CACHE["data"]
    industries: dict[str, str] = {}
    profiles = ROOT / "data/interim/a_share_company_profiles.csv"
    if profiles.exists():
        with profiles.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                code = row.get("security_code") or row.get("\ufeffsecurity_code")
                if code:
                    industries[code] = row.get("eastmoney_industry", "") or ""
    medians: dict[str, float] = {}
    for path in EVIDENCE_DIR.glob("*.json"):
        try:
            band = (json.loads(path.read_text(encoding="utf-8")).get("valuation_band") or {})
        except Exception:
            continue
        value = band.get("pe_ttm_median")
        if value and 0 < value < 200:      # 剔除亏损年造成的极端 PE
            medians[path.stem] = float(value)
    _PEER_CACHE["data"] = (industries, medians)
    return _PEER_CACHE["data"]


def peer_multiple(code: str) -> tuple[float | None, str]:
    """§6.5.4（v1.32，OI-006）：同业中枢 PE = 同业各票「自身 5 年 PE 中位」的中位数。

    只用三级/二级行业分组且组内 ≥3 家。退到一级会把整个板块当同业——判例：
    紫金矿业退到「有色金属」16 家得 29.6x（混入锂/稀土），京东方退到「电子设备」
    55 家得 48.8x，两者对各自细分行业都无意义。
    """
    industries, medians = _peer_universe()
    own = industries.get(code, "")
    if not own:
        return None, ""
    for level in PEER_MULTIPLE_LEVELS:
        key = "-".join(own.split("-")[:level])
        peers = [v for c, v in medians.items()
                 if c != code and "-".join(industries.get(c, "").split("-")[:level]) == key
                 and industries.get(c)]
        if len(peers) >= PEER_MULTIPLE_MIN_GROUP:
            trimmed = sorted(peers)[1:-1] if len(peers) >= 5 else sorted(peers)
            return round(statistics.median(trimmed), 2), f"{key}（{len(peers)} 家同业，{level} 级）"
    return None, ""


def load_evidence(code: str) -> dict | None:
    path = EVIDENCE_DIR / f"{code}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def annual_rows(periods: list[dict]) -> list[dict]:
    """年报行，按报告期倒序。"""
    return [p for p in periods if p.get("REPORT_TYPE") == "年报"]


def ttm(periods: list[dict], field: str) -> float | None:
    """§6.5.2.1 取数陷阱一：finance_periods 是累计口径，须差分成单季再求 TTM。

    单季 = 本期累计 − 同年上期累计（一季报本身即单季）。TTM = 最近四个单季之和。
    """
    rows = [p for p in periods if p.get(field) is not None]
    rows.sort(key=lambda p: p["REPORT_DATE"], reverse=True)
    by_date = {p["REPORT_DATE"][:10]: p for p in rows}

    def quarter_value(period: dict) -> float | None:
        date = period["REPORT_DATE"][:10]
        year, mmdd = date[:4], date[5:10]
        order = ["03-31", "06-30", "09-30", "12-31"]
        if mmdd not in order:
            return None
        idx = order.index(mmdd)
        cur = period.get(field)
        if cur is None:
            return None
        if idx == 0:
            return float(cur)
        prev = by_date.get(f"{year}-{order[idx - 1]}")
        if prev is None or prev.get(field) is None:
            return None
        return float(cur) - float(prev[field])

    quarters = []
    for period in rows:
        value = quarter_value(period)
        if value is not None:
            quarters.append(value)
        if len(quarters) == 4:
            return sum(quarters)
    return None


def consensus_median(evidence: dict, year_offset: int = 0) -> tuple[float | None, int, int | None]:
    """§6.5.2.1 取数陷阱二：一致预期取 ycmx 逐份研报归母的**中位数**，不用 yctj_list 均值。

    Returns (归母中位数(元), 覆盖机构数, 预测年份).
    """
    detail = (evidence.get("profit_forecast") or {}).get("ycmx") or []
    stats = (evidence.get("profit_forecast") or {}).get("yctj_list") or []
    forecast_years = sorted({int(r["YEAR"]) for r in stats if r.get("YEAR_MARK") == "E"})
    if not forecast_years:
        return None, 0, None
    idx = min(year_offset, len(forecast_years) - 1)
    target = forecast_years[idx]

    values = []
    for report in detail:
        for slot in (1, 2, 3, 4):
            if report.get(f"YEAR{slot}") == target and report.get(f"YEAR_MARK{slot}") == "E":
                value = report.get(f"PARENT_NETPROFIT{slot}")
                if value:
                    values.append(float(value))
    if not values:
        return None, 0, target
    return statistics.median(values), len(values), target


def best_consensus(evidence: dict, offsets: tuple[int, ...], min_coverage: int = 3):
    """在给定的预测年偏移中，取**覆盖达标的最远年份**。

    §6.5.2 D 类的锚是"未来 2-3 年正常化归母"——硬取第 3 年会在覆盖薄的中小盘上
    整片落空，而第 2 年同样落在标准区间内。返回 (归母中位数, 覆盖数, 年份)；
    全部不达标返回 (None, 0, None)。
    """
    for offset in offsets:
        value, count, year = consensus_median(evidence, offset)
        if value and count >= min_coverage:
            return value, count, year
    return None, 0, None


def share_count_check(evidence: dict, shares_out: float | None) -> str:
    """§6.6.1.2a 股本口径校验：研报归母 ÷ 研报 EPS 反算隐含股本，与现股本比对。"""
    detail = (evidence.get("profit_forecast") or {}).get("ycmx") or []
    implied = []
    for report in detail:
        for slot in (1, 2, 3, 4):
            eps, profit = report.get(f"EPS{slot}"), report.get(f"PARENT_NETPROFIT{slot}")
            if eps and profit and float(eps) != 0:
                implied.append(float(profit) / float(eps) / 1e8)
    if not implied or not shares_out:
        return "无法校验（缺研报 EPS 或股本）"
    med = statistics.median(implied)
    ratio = med / shares_out
    if abs(ratio - 1) <= 0.02:
        return f"通过（隐含股本 {med:.4f}亿 ≈ 现股本 {shares_out:.4f}亿）"
    return (f"⚠️不一致（隐含 {med:.4f}亿 vs 现 {shares_out:.4f}亿，比值 {ratio:.3f}）"
            f"——研报 EPS 为送转/增发前口径，一律用归母建带")


def c_to_a_signal(evidence: dict) -> tuple[bool, str]:
    """§6.5.3 C → A 迁出判据（v1.30）：三条须全部成立。

    ① 三年一致预期归母 CAGR < 12%  ② 近三年 ROE 均 ≥ 12%  ③ 经营现金流/净利润 ≥ 0.8
    只满足 ① 的不迁 A——那是质量下滑，须回 §6.5.0 重走判定顺序。
    「连续两次复核」由估值执行侧跨轮判断，本函数只给单轮读数。
    """
    profits = [consensus_median(evidence, i)[0] for i in range(3)]
    if not all(profits) or profits[0] <= 0:
        return False, "增速不可算"
    cagr = (profits[-1] / profits[0]) ** 0.5 - 1

    rows = annual_rows(evidence.get("finance_periods") or [])[:3]
    roes = [float(r["ROEJQ"]) for r in rows if r.get("ROEJQ") is not None]
    revenue = ttm(evidence.get("finance_periods") or [], "TOTALOPERATEREVE")
    # §6.5.2.1 取数陷阱三：JYXJLYYSR 是**小数比率**（0.3644 = 36.44%），
    # 与同记录内的 XSJLL/ROEJQ（百分数）单位不同，不得再除以 100。
    ratios = [float(r["JYXJLYYSR"]) for r in rows if r.get("JYXJLYYSR") is not None]
    profit_ttm = ttm(evidence.get("finance_periods") or [], "PARENTNETPROFIT")
    cash_conv = None
    if ratios and revenue and profit_ttm and profit_ttm > 0:
        cash_conv = (statistics.median(ratios) * revenue) / profit_ttm

    min_roe = min(roes) if len(roes) >= 3 else None
    threshold = next((t for floor, t in C_TO_A_CAGR_BY_ROE if min_roe is not None and min_roe >= floor), None)
    cond1 = threshold is not None and cagr < threshold
    cond2 = min_roe is not None and min_roe >= C_TO_A_MIN_ROE
    cond3 = cash_conv is not None and cash_conv >= C_TO_A_MIN_CASH_CONV
    threshold_text = f"<{threshold:.0%}" if threshold is not None else "本判据不适用（ROE<12%）"
    roe_text = f"{min_roe:.1f}%" if min_roe is not None else "不可算"
    detail = (f"三年一致预期 CAGR {cagr:.1%}（判据① {threshold_text} {'✓' if cond1 else '✗'}"
              f"，阈值按近三年最低 ROE {roe_text} 分档）；"
              f"近三年 ROE {'/'.join(f'{r:.1f}' for r in roes[:3])}（②均≥12% {'✓' if cond2 else '✗'}）；"
              f"经营现金流/净利润 {cash_conv:.2f}（③≥0.8 {'✓' if cond3 else '✗'}）"
              if cash_conv is not None else
              f"三年一致预期 CAGR {cagr:.1%}；现金转化不可算")
    return (cond1 and cond2 and cond3), detail


def forward_present_value(code: str, anchor: float, year: int | None, as_of_year: int,
                          rate: float | None, terminal_pe: float | None) -> tuple[float | None, str]:
    """远期利润锚 → **现值**（v1.32，结 OI-006）。

    `PV = E(T+n) × PE终值 ÷ (1+r)^n`。两处纠正：

    1. **必须折现**。`E(T+n) × PE` 得到的是 T+n 时点的价值，不是现值；v1.30/v1.31
       漏了折现，等于把 2-3 年后的价格当成今天该付的价格。
    2. **倍数只能取终值口径**。自身历史 PE 中位嵌着当年的增长预期（v1.30 已认定），
       **同业历史 PE 中位嵌着同一个年代的行业增长预期，毛病完全相同**——判例：
       宁德时代同业中枢 33.77x 用在 2028E 归母上，隐含市值 4.8 万亿、为当时市值
       18289 亿的 2.6 倍。故同业中枢只作交叉校验写入敏感度，不作建带倍数。

    窗口之后的增长不进 base 带，按 §6.5.6 成长期权有界补入——这正是该机制存在的理由。
    """
    if not (rate and terminal_pe and anchor and year):
        return None, ""
    years = max(1, year - as_of_year)
    present = anchor * terminal_pe / (1 + rate) ** years
    peer, peer_note = peer_multiple(code)
    note = (f"终值 PE {terminal_pe}x = 1/({rate:.0%}−{TERMINAL_G:.0%})，"
            f"折现 {years} 年回现值（÷{(1 + rate) ** years:.3f}）"
            + (f"；交叉校验：同业中枢 PE {peer}x（{peer_note}），仅作对照不入带——"
               f"行业历史倍数同样嵌有当年的增长预期" if peer else ""))
    return present, note


def build_card(code: str, name: str, tag_letter: str, quality_tier: str) -> dict:
    evidence = load_evidence(code)
    card = {
        "security_code": code,
        "security_name": name,
        "quality_tier": quality_tier,
        "strategy_tag_letter": tag_letter,
        "anchor_metric": "",
        "anchor_value": "",
        "anchor_scope": "",
        "anchor_basis": "",
        "multiple_or_rate": "",
        "multiple_source": "",
        "band_low_coef": "",
        "band_high_coef": "",
        "shares_out": "",
        "band_derivation": "model",
        "anchor_quality": "primary",
        "upgrade_path": "",
        "band_is_floor": "",
        "band_sensitivity": "",
        "band_fragile": "false",
        "fair_price_low": "",
        "fair_price_high": "",
        "needs_external": "",
        "note": "",
    }
    spec = TYPE_SPEC.get(tag_letter)
    if spec is None:
        card["note"] = f"未知标签 {tag_letter}"
        return card
    anchor_metric, shape, coefs, local = spec
    if coefs is None:                                  # A-2：系数按质量分层（§6.5.2，v1.30）
        coefs = A2_COEFS.get(str(quality_tier).strip().upper())
        if coefs is None:
            card["note"] = f"A-2 需要 L1/L2/L3 分层定系数，实得 '{quality_tier}'"
            return card
    low_coef, high_coef = coefs
    card.update(anchor_metric=anchor_metric, band_low_coef=low_coef, band_high_coef=high_coef)

    if evidence is None:
        card["note"] = "缺证据文件"
        return card

    quote = evidence.get("quote") or {}
    price = quote.get("price")
    cap = quote.get("total_market_cap")
    shares = (cap / price / 1e8) if (price and cap) else None   # 亿股；比值与价格无关
    if shares:
        card["shares_out"] = f"{shares:.4f}"

    periods = evidence.get("finance_periods") or []
    band = evidence.get("valuation_band") or {}

    anchor = None
    basis = ""
    multiple = None
    source = ""
    tier_key = str(quality_tier).strip().upper()
    terminal_rate = TERMINAL_R_BY_TIER.get(tier_key)
    terminal_pe = round(1 / (terminal_rate - TERMINAL_G), 2) if terminal_rate else None
    pb_median = band.get("pb_median")
    current_pb = band.get("current_pb") or (quote.get("pb") if quote else None)
    bvps = (float(quote["price"]) / float(current_pb)) if (quote.get("price") and current_pb) else None
    annuals = annual_rows(periods)

    def mid_cycle_profit() -> tuple[float | None, str]:
        """§6.5.4（v1.32）：中枢归母 = TTM 营收 × 窗口净利率中位。

        规模取自**当期营收**、周期取自**历史利润率**——把结构性成长与周期波动分开。
        原「近 7 个年报归母算术均值」会把十年间的结构性扩张当成周期低点（紫金矿业
        判例：均值 216 亿 vs 规模口径 338 亿），且被单一重整年击穿（盐湖股份 −459 亿
        使均值为负）。中位数天然抗离群年，营收缩放天然吸收规模变化。
        """
        margins = [float(r["XSJLL"]) for r in annuals if r.get("XSJLL") is not None]
        revenue = ttm(periods, "TOTALOPERATEREVE")
        if len(margins) < 5 or not revenue:
            return None, ""
        recent = statistics.median(margins[:5])
        window, label = margins[:10], "近 10 年"
        if len(margins) >= 10:
            prior = statistics.median(margins[5:10])
            if prior and abs(recent / prior - 1) > STRUCTURAL_BREAK_THRESHOLD:
                window, label = margins[:5], "近 5 年（结构断点检验命中）"
        margin = statistics.median(window)
        if margin <= 0:
            return None, ""
        return revenue * margin / 100, (
            f"TTM 营收 {revenue/1e8:.2f}亿 × {label}净利率中位 {margin:.2f}%")

    def cyclical_fallback(label: str) -> None:
        """F-2 / H-2：中枢归母 × 终值 PE 与 BVPS × 自身 PB 中位，取孰低（§6.5.5.1）。"""
        nonlocal anchor, multiple, source, basis
        mid, mid_basis = mid_cycle_profit()
        own_pe = band.get("pe_ttm_median")
        # 锚是「当期规模下的正常化盈利」→ 倍数取同期口径（自身 5 年 PE 中位），
        # 不用终值公式（那是给远期利润锚配的，§6.5.2.1 锚与倍数同期约束）。
        cycle_multiple = own_pe if own_pe and own_pe > 0 else terminal_pe
        if not (mid and cycle_multiple and shares):
            card["note"] = f"{label} 兜底不可算（年报期数不足或缺分层/股本）"
            return
        earnings_price = mid * cycle_multiple / 1e8 * low_coef / shares
        book_price = bvps * pb_median * low_coef if (bvps and pb_median) else None
        use_book = book_price is not None and book_price < earnings_price
        card["anchor_quality"] = "fallback"
        if use_book:
            anchor, multiple, source = bvps, pb_median, "own_history_median"
            card["anchor_scope"] = "per_share"
            card["anchor_metric"] = "bvps"
            basis = (f"{label} 兜底（取孰低→PB 口径）：每股净资产 {bvps:.2f} 元 × 自身 5 年 PB 中位 {pb_median}"
                     f"；对照口径 中枢归母 {mid/1e8:.2f}亿 × 自身 PE 中位 {cycle_multiple}（更高，未采用）")
        else:
            anchor, multiple, source = mid, cycle_multiple, ("own_history_median" if own_pe else "required_return")
            card["anchor_metric"] = "mid_cycle_profit"
            basis = (f"{label} 兜底（取孰低→中枢盈利口径）：中枢归母 = {mid_basis} = {mid/1e8:.2f}亿"
                     f"；× 自身 5 年 PE 中位 {cycle_multiple}（同期口径）"
                     + (f"；对照口径 BVPS×PB中位 更高，未采用" if book_price else ""))
        card["upgrade_path"] = ("资源储量与 NAV（储量报告/年报储量披露）" if label == "F-2"
                                else "中枢 EBITDA 与同业成熟期 EV/EBITDA")


    if tag_letter == "A":
        anchor = ttm(periods, "KCFJCXSYJLR")
        multiple = band.get("pe_ttm_median")
        source = "own_history_median"
        basis = (f"扣非归母 TTM（四单季差分）{anchor/1e8:.2f}亿；"
                 f"5年 PE 中位 {multiple}（窗口 {band.get('window_start','')[:10]}~{band.get('window_end','')[:10]}，"
                 f"现分位 {band.get('pe_ttm_pct_rank')}%）") if anchor and multiple else ""
    elif tag_letter == "C":
        value, count, year = best_consensus(evidence, (0, 1), min_coverage=2)
        if value and count == 2:
            card["band_fragile"] = "true"
            card["anchor_quality"] = "fallback"
            card["upgrade_path"] = "研报覆盖补至 ≥3 家"
        if value:
            anchor = value
            # g 取覆盖达标的最长可算区间（优先三年，退而两年），按实际年数年化
            far_value, far_count, far_year = best_consensus(evidence, (2, 1))
            if far_value and far_year and far_year > year and anchor > 0:
                span = far_year - year
                cagr = (far_value / anchor) ** (1 / span) - 1
                multiple = round(cagr * 100, 2)
                source = "required_return"
                basis = (f"{year}E 归母中位数 {anchor/1e8:.2f}亿（{count} 家研报）；"
                         f"g = {year}E→{far_year}E 一致预期归母 CAGR {multiple}%"
                         f"（{span} 年，{far_count} 家覆盖；带系数即 PEG 1.0-1.5）")
        if not anchor or not multiple:
            # 覆盖 ≤1 家：改用自算口径——TTM 实际扣非归母 × 历史实现 3 年 CAGR（§6.5.5.1）
            profit_ttm = ttm(periods, "KCFJCXSYJLR")
            realized = [float(r["PARENTNETPROFIT"]) for r in annuals if r.get("PARENTNETPROFIT") is not None]
            if profit_ttm and profit_ttm > 0 and len(realized) >= 4 and realized[3] > 0:
                realized_cagr = (realized[0] / realized[3]) ** (1 / 3) - 1
                capped = max(0.0, min(realized_cagr, 0.30))
                anchor, multiple, source = profit_ttm, round(capped * 100, 2), "required_return"
                card["anchor_quality"] = "fallback"
                # 与 A-2 口径区分：同为 TTM 扣非归母，但倍数是自算增速、系数是 PEG 带
                card["anchor_metric"] = "realized_growth_profit"
                card["upgrade_path"] = "研报覆盖补至 ≥3 家 → 前瞻一致预期口径"
                basis = (f"C 兜底（覆盖 ≤1 家，改自算口径）：扣非归母 TTM {anchor/1e8:.2f}亿"
                         f"；g = 历史实现 3 年归母 CAGR {realized_cagr:.1%}（封顶 30% 后取 {capped:.1%}）"
                         f"；带系数即 PEG 1.0-1.5")
                if capped <= 0:
                    # 增长前提不成立 → 按 §6.5.0 重走判定顺序：净利率低于历史中枢=困境(E 口径)，
                    # 否则=无增长但盈利稳定(A-2 口径)。两者都不要求增长。
                    anchor = multiple = None
                    margins = [float(r["XSJLL"]) for r in annuals if r.get("XSJLL") is not None]
                    revenue = ttm(periods, "TOTALOPERATEREVE")
                    pe_med = band.get("pe_ttm_median")
                    current_margin = (profit_ttm / revenue * 100) if revenue else None
                    mid_margin = statistics.median(margins) if margins else None
                    if mid_margin and current_margin is not None and pe_med and revenue:
                        if current_margin < mid_margin * 0.8:
                            anchor = revenue * mid_margin / 100
                            multiple, source = pe_med, "own_history_median"
                            card["anchor_quality"] = "fallback"
                            card["anchor_metric"] = "repaired_normalized_profit"
                            card["band_low_coef"], card["band_high_coef"] = (0.85, 1.00)
                            low_coef, high_coef = (0.85, 1.00)
                            card["upgrade_path"] = "增长证伪，按 §6.5.0 复核应否改判 E 落难白马"
                            basis = (f"C 增长前提不成立（历史实现 3 年 CAGR {realized_cagr:.1%} ≤0）→ 改按 E 修复口径："
                                     f"TTM 营收 {revenue/1e8:.2f}亿 × 历史中枢净利率 {mid_margin:.2f}%"
                                     f"（现净利率 {current_margin:.2f}%，处中枢 80% 以下=困境）"
                                     f"= {anchor/1e8:.2f}亿 × 自身 5 年 PE 中位 {pe_med}")
                        else:
                            anchor = profit_ttm
                            multiple, source = pe_med, "own_history_median"
                            card["anchor_quality"] = "fallback"
                            card["anchor_metric"] = "normalized_profit"
                            low_coef, high_coef = A2_COEFS.get(tier_key, (0.85, 1.05))
                            card["band_low_coef"], card["band_high_coef"] = low_coef, high_coef
                            card["upgrade_path"] = "增长证伪，按 §6.5.0 复核应否改判 A 现金流复利"
                            basis = (f"C 增长前提不成立（历史实现 3 年 CAGR {realized_cagr:.1%} ≤0）→ 改按 A-2 口径："
                                     f"扣非归母 TTM {profit_ttm/1e8:.2f}亿 × 自身 5 年 PE 中位 {pe_med}"
                                     f"（现净利率 {current_margin:.2f}% 未低于中枢 {mid_margin:.2f}% 的 80%，属无增长而非困境）")
                    else:
                        card["note"] = "C 增长前提不成立且净利率/PE 中位不可得"
            else:
                card["note"] = "C 兜底不可算（缺 TTM 扣非或年报期数 <4）"
    elif tag_letter == "D":
        # §6.5.2「未来 2-3 年正常化归母」：取覆盖达标的最远年份（第 3 年优先，退第 2 年）
        value, count, year = best_consensus(evidence, (2, 1), min_coverage=2)
        rate = terminal_rate
        if value and count == 2:
            card["band_fragile"] = "true"
            card["anchor_quality"] = "fallback"
            card["upgrade_path"] = "研报覆盖补至 ≥3 家"
        present, pv_note = forward_present_value(code, value or 0, year, AS_OF_YEAR, rate, terminal_pe)
        if value and present:
            years = max(1, (year or AS_OF_YEAR) - AS_OF_YEAR)
            anchor, source = value, "required_return"
            multiple = round(terminal_pe / (1 + rate) ** years, 4)   # 倍数含折现，保证可复算
            card["band_is_floor"] = "true"   # 窗口后增长不入 base 带，按 §6.5.6 期权补
            basis = (f"{year}E 正常化归母中位数 {anchor/1e8:.2f}亿（{count} 家覆盖）× {multiple} "
                     f"= 现值口径；{pv_note}。**窗口后增长不计入 base 带**，为下限")
        elif rate:
            # 覆盖 ≤1 家：base 带只按已兑现盈利建，成长部分走 §6.5.6 成长期权
            profit_ttm = ttm(periods, "KCFJCXSYJLR")
            if profit_ttm and profit_ttm > 0:
                anchor, multiple, source = profit_ttm, terminal_pe, "required_return"
                card["anchor_quality"] = "fallback"
                card["anchor_metric"] = "normalized_profit"
                card["band_is_floor"] = "true"   # D ≤1 家覆盖：成长不计入 base 带
                card["upgrade_path"] = "研报覆盖补至 ≥3 家 → 2-3 年正常化归母口径；成长部分按 §6.5.6 成长期权补入"
                basis = (f"D 兜底（覆盖 ≤1 家，base 带只按已兑现盈利）：扣非归母 TTM {profit_ttm/1e8:.2f}亿"
                         f" × 终值 PE {terminal_pe}x——**成长不计入 base 带**，为下限；"
                         f"完整价值须经 §6.5.6 成长期权或补齐覆盖后上修")
            else:
                card["note"] = "D 兜底不可算（TTM 扣非归母 ≤0）"
        else:
            card["note"] = f"D 类终值倍数需 L1/L2/L3 分层，实得 '{quality_tier}'"
    elif tag_letter == "E":
        rows = annual_rows(periods)
        margins = [float(r["XSJLL"]) for r in rows if r.get("XSJLL") is not None]
        revenue = ttm(periods, "TOTALOPERATEREVE")
        if margins and revenue:
            normal_margin = statistics.median(margins)
            anchor = revenue * normal_margin / 100
            multiple = band.get("pe_ttm_median")
            source = "own_history_median"
            basis = (f"修复后归母 = TTM 营收 {revenue/1e8:.2f}亿 × 历史中枢净利率 {normal_margin:.2f}%"
                     f"（{len(margins)} 个年报期中位）= {anchor/1e8:.2f}亿；PE 取 5 年中位 {multiple}")
    elif tag_letter == "H":
        cyclical_fallback("H-2")
    elif tag_letter == "F":
        cyclical_fallback("F-2")
    elif tag_letter in ("K",):
        # K-2 兜底：稳态公司的 PE 中枢回归（同 A-2）
        anchor = ttm(periods, "KCFJCXSYJLR")
        multiple = band.get("pe_ttm_median")
        source = "own_history_median"
        card["anchor_quality"] = "fallback"
        card["anchor_metric"] = "normalized_profit"
        low_coef, high_coef = A2_COEFS.get(tier_key, (0.85, 1.05))
        card["band_low_coef"], card["band_high_coef"] = low_coef, high_coef
        card["upgrade_path"] = "可持续分红率（分红预案/章程承诺/近三年实际）→ Gordon DPS/(r−g)"
        basis = (f"K-2 兜底：扣非归母 TTM {anchor/1e8:.2f}亿 × 自身 5 年 PE 中位 {multiple}"
                 f"（稳态公司的 PE 中枢回归；primary 的 DDM 待补分红率）") if anchor and multiple else ""
    elif tag_letter == "N":
        revenue = ttm(periods, "TOTALOPERATEREVE")
        margins = [float(r["XSJLL"]) for r in annuals if r.get("XSJLL") is not None]
        if revenue and margins and terminal_pe:
            peak = max(margins)
            normalized = peak * 0.85
            anchor = revenue * normalized / 100
            multiple, source = terminal_pe, "required_return"
            card["anchor_quality"] = "fallback"
            card["band_is_floor"] = "true"   # EPV 按定义剥离增长，为下限
            card["upgrade_path"] = "同业成熟期归一化经营利润率、合同负债占比"
            basis = (f"N-2 兜底 EPV：TTM 营收 {revenue/1e8:.2f}亿 × 归一化净利率 {normalized:.2f}%"
                     f"（自身历史峰值 {peak:.2f}% × 85%，§6.5.4 授权）= {anchor/1e8:.2f}亿"
                     f"；× 终值 PE {terminal_pe}x")
        else:
            card["note"] = "N-2 兜底不可算（缺营收/净利率历史或分层）"
    elif tag_letter in ("M", "P"):
        value, count, year = best_consensus(evidence, (0, 1), min_coverage=2)
        present, pv_note = forward_present_value(code, value or 0, year, AS_OF_YEAR, terminal_rate, terminal_pe)
        if value and present:
            years = max(1, (year or AS_OF_YEAR) - AS_OF_YEAR)
            anchor, source = value, "required_return"
            multiple = round(terminal_pe / (1 + terminal_rate) ** years, 4)
            card["anchor_quality"] = "fallback"
            card["anchor_metric"] = "forward_normalized_profit"
            card["band_is_floor"] = "true"   # M-2/P-2 明确不含管线/订单价值
            label = "管线价值" if tag_letter == "M" else "在手订单溢价"
            card["upgrade_path"] = ("管线阶段、适应症空间、BD 条款 → SOTP + rNPV" if tag_letter == "M"
                                    else "在手订单额与交付排期 → backlog 年化归母")
            basis = (f"{tag_letter}-2 下限带：{year}E 归母中位数 {anchor/1e8:.2f}亿（{count} 家覆盖）"
                     f"× {multiple}（现值口径；{pv_note}）——**{label}记 0**，为不含未兑现价值的下限；"
                     f"完整价值须经 §6.5.6 成长期权或补齐外部取证后上修")
        else:
            card["note"] = f"{tag_letter}-2 下限带不可算（研报覆盖 <2 家或缺分层）"
    elif tag_letter == "J":
        stats = (evidence.get("profit_forecast") or {}).get("yctj_list") or []
        forecast = [r for r in stats if r.get("YEAR_MARK") == "E" and r.get("BVPS") and r.get("ROE")]
        if forecast:
            row = forecast[0]
            bvps, roe = float(row["BVPS"]), float(row["ROE"]) / 100
            g = min(MAX_G, roe)          # 分红率未知时取上限；有分红率须改用 ROE×(1−分红率)
            implied_pb = (roe - g) / (COE_BANK - g)
            pb_median = band.get("pb_median")
            chosen, source = (implied_pb, "implied_pb")
            if pb_median and pb_median < implied_pb:
                chosen, source = (pb_median, "own_history_median")
            anchor, multiple = bvps, chosen
            card["anchor_scope"] = "per_share"
            deviation = abs(implied_pb / pb_median - 1) if pb_median else 0
            if deviation > 0.30:
                card["band_fragile"] = "true"
            implied_coe = (roe - g) / band["current_pb"] + g if band.get("current_pb") else None
            basis = (f"{row['YEAR']}E BVPS {bvps:.2f} 元（{row.get('BVPS_COUNT')} 家）；"
                     f"J-1 隐含 PB {implied_pb:.3f}（ROE {roe:.2%}，g {g:.2%}，COE {COE_BANK:.2%}）vs "
                     f"J-2 自身 5 年 PB 中位 {pb_median} → **取孰低 {chosen:.3f}**；"
                     + (f"反解当前隐含 COE {implied_coe:.2%}（现 PB {band['current_pb']:.3f}）"
                        if implied_coe else ""))

    if not (anchor and multiple) and bvps and pb_median:
        # §6.5.5.1 最终兜底：净资产口径。PE 系口径全部失效（亏损、上市不足 4 年、
        # 增速不可算）时，账面价值仍是可计量的锚；周期与亏损公司的标准做法。
        anchor, multiple, source = bvps, pb_median, "own_history_median"
        card["anchor_scope"] = "per_share"
        card["anchor_metric"] = "bvps"
        low_coef, high_coef = (0.85, 1.00)
        card["band_low_coef"], card["band_high_coef"] = low_coef, high_coef
        card["anchor_quality"] = "fallback"
        card["upgrade_path"] = card["upgrade_path"] or "盈利转正或研报覆盖补齐后改用盈利口径"
        basis = (f"最终兜底（净资产口径）：每股净资产 {bvps:.2f} 元 × 自身 5 年 PB 中位 {pb_median}"
                 f"——盈利口径失效（{card.get('note') or '亏损/历史不足/增速不可算'}），"
                 f"账面价值为唯一可计量锚；须按 §6.5.3 通用校验一核对清算价值地板")
        card["note"] = ""

    if anchor and multiple:
        card["anchor_value"] = f"{anchor/1e8:.4f}" if card["anchor_scope"] != "per_share" else f"{anchor:.4f}"
        card["anchor_scope"] = card["anchor_scope"] or "market_cap"
        card["anchor_basis"] = basis
        card["multiple_or_rate"] = f"{multiple}"
        card["multiple_source"] = source
        divisor = shares if card["anchor_scope"] == "market_cap" else 1.0
        if divisor:
            value = float(card["anchor_value"]) * float(multiple)
            low, high = value * low_coef / divisor, value * high_coef / divisor
            card["fair_price_low"], card["fair_price_high"] = f"{low:.4g}", f"{high:.4g}"
            sens_low = value * 0.85 * low_coef / divisor
            sens_high = value * 1.15 * high_coef / divisor
            card["band_sensitivity"] = (f"锚±15% → 带 {sens_low:.4g}~{sens_high:.4g}"
                                        f"（基准 {low:.4g}~{high:.4g}）；"
                                        + share_count_check(evidence, shares))
    elif not card["note"] and not card["needs_external"]:
        card["note"] = "锚定量或倍数取数失败，须人工补"

    return card


def main() -> int:
    parser = argparse.ArgumentParser(description="按 §6.5.2.1 口径计算建带卡草稿")
    parser.add_argument("--tags", type=Path, required=True, help="CSV: security_code,strategy_tag_letter")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()

    with args.tags.open(encoding="utf-8-sig") as handle:
        tags = list(csv.DictReader(handle))

    cards = [
        build_card(
            row["security_code"].zfill(6),
            row.get("security_name", ""),
            row["strategy_tag_letter"].strip().upper(),
            row.get("quality_tier", ""),
        )
        for row in tags
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(cards[0].keys()))
        writer.writeheader()
        writer.writerows(cards)

    computed = sum(1 for c in cards if c["fair_price_low"])
    external = sum(1 for c in cards if c["needs_external"])
    failed = sum(1 for c in cards if c["note"] and not c["needs_external"])
    print(f"建带卡草稿 {args.as_of}：{len(cards)} 家")
    print(f"  带已算出           {computed}")
    print(f"  待外部取证         {external}")
    print(f"  取数失败/须人工补  {failed}")
    print(f"  输出：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
