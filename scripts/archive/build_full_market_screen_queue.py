#!/usr/bin/env python3
"""全市场逐股重筛的取数与排队（OI-036，用户 2026-08-09 指令）。

要做的事
--------
`a_share_attention_triage.csv` 覆盖全部 5,653 只 A 股，但其中 **5,337 只是
`boundary_pending`——从未被真正判过**。本轮把它们落实为真判断：逐股建档、给参考分、
可标记「永不录用」，再据此重筛 `worth_attention`。

取数口径（用户指定）
--------------------
* **有 2026 中报的按中报**（截至 2026-08-09 仅 423 家已披露）；
* **没有的按 2026 一季报**，并置 `pending_h1=1` **标记待更新**，8 月底中报截止后重跑。

同比口径必须区分：中报的 `netprofit_yoy` 是半年对半年，一季报的是单季对单季，
**两者不可混排**，故 `basis` 列必须一并读出。

分层排队（不是分层判断）
------------------------
5,392 只逐一深判不现实，也不必要。本脚本按**可判性**排队，把判断力用在有可能进池的公司上。
三条判据一律读 **TTM（本期 + 上年年报 − 上年同期）**，与 §6.5.2 估值带同源；兜底链见
`tier_inputs`，所用口径逐行写 `tier_basis`，入参写 `revenue_ttm_yi`／`netprofit_ttm_yi`／
`roe_ttm_pct` 三列：

* `A_核心`：营收 ≥ 30 亿 或 ROE ≥ 12%——**必须逐家判**，进池候选都在这里
* `B_观察`：营收 5~30 亿 且 盈利——按行业成批判，个别有护城河签名的单拎
* `C_排除`：连续亏损 / 营收 < 5 亿 / ST——**按规则批量判「永不录用」并写明依据**，
  不逐家展开；任一后续年度突破门槛会自动回到 A 或 B

**这个分层只决定判断的粒度，不决定结论**：C 类里若有 §5.4.1 意义上的护城河（如小而美的
品类垄断），仍会被 B 类的行业扫描捞回来。分层依据写入 `tier_reason` 供复核。

用法::

    python3 scripts/archive/build_full_market_screen_queue.py
    python3 scripts/archive/build_full_market_screen_queue.py --batch 1 --size 120   # 打印一批待判事实
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_a_share_universe import has_status_prefix
from build_historical_valuation_bands import derive_roe, prior_periods, ttm

ROOT = Path(__file__).resolve().parents[1]
FIN = ROOT / "data/raw/financials"
SEC = ROOT / "data/raw/a_share_securities.csv"
TRIAGE = ROOT / "data/processed/a_share_attention_triage.csv"
TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
OUT = ROOT / "data/archive/full_market_screen/screen_queue.csv"
VERDICTS = ROOT / "data/archive/full_market_screen/verdicts.csv"

FIELDS = ["security_code", "security_name", "board", "listing_date", "queue_tier", "tier_reason",
          "basis", "pending_h1", "revenue_yi", "netprofit_yi", "roe_pct", "gross_pct",
          "net_margin_pct", "revenue_yoy", "netprofit_yoy", "ocf_ps", "bps",
          # 升级预筛的三列质量守卫（OI-036 2026-08-30 登记的预筛缺陷）：
          # 只看 `netprofit_yoy` 与 `weightavg_roe` 会把非经常损益驱动的单期高增长认成回报兑现，
          # 也会把 IPO 当年及次年的净资产跳升认成「回报腰斩」。
          "deduct_ratio_pct", "ocf_to_eps", "ipo_roe_window",
          # 分层入参（`queue_tier` 只由这三列＋名称算出，`revenue_yi` 等是当期披露值，口径不同）：
          "tier_basis", "revenue_ttm_yi", "netprofit_ttm_yi", "roe_ttm_pct",
          # 上一次建队列的层与本次移动方向：`tier_move=up` 就是「越线」，取代此前按当期折年
          # 现算的旗标——那种算法要自己重述 `classify` 的前置条件，漏一条就误报（漏「营收 ≥5 亿」
          # 时把折年营收 2.36 亿的公司也标成越过 A 线）。这里直接比两次 `classify` 的结果。
          "prior_queue_tier", "tier_move",
          # 单期毛利跳变 + 营收高增：几乎都是并表口径变化而非经营兑现，判定前必须核合并范围。
          "scope_check",
          "prior_class", "prior_quality_tier"]


def _num(text):
    try:
        return float((text or "").strip())
    except (TypeError, ValueError):
        return None


def load_period(name: str) -> dict[str, dict]:
    path = FIN / f"{name}.csv"
    if not path.exists():
        return {}
    out = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (row.get("notice_date") or "").strip():
                out[row["security_code"]] = row
    return out


def is_a_share(code: str) -> bool:
    """**只用于给名录补漏**：仅接受沪深 0/3/6 段，排除 B 股（20x/90x）。

    北交所与新三板共用 43/83/87/88 段，无法由代码区分，**名录里已有的 312 只北交所照常保留，
    名录外的 8x/9x 一律视为新三板不予补入**——首版误把它们放进来，全市场数从 5,653 涨到 6,148。
    """
    return code[:1] in ("0", "3", "6") and code[:2] not in ("20", "40", "42", "43", "90")


def board_of(code: str) -> str:
    return {"68": "star_market", "30": "chinext"}.get(code[:2], "main_board")


def classify(revenue, netprofit, roe, name: str, ipo_roe_window: bool = False) -> tuple[str, str]:
    """排队分层。**只决定判断粒度，不决定结论**——见文件头。

    **入参必须是滚动十二个月口径**（TTM = 本期 + 上年年报 − 上年同期，与 §6.5.2 估值带同源）。
    判据是年度阈值（5 亿/30 亿），传当期累计值等于按报告期长短浮动门槛：传一季报把门槛抬高
    四倍，传中报抬高两倍。TTM 不可得时按下文兜底链退到年报，仍不可得才折年。

    `ipo_roe_window=True`（年报期落在上市当年及次年）时**不走 ROE 单独进 A 的通道**：
    上市前净资产小，ROE 天然虚高，摊薄后普遍跌破 12% 线。营收够 30 亿的照常进 A。
    """
    if name.startswith(("*ST", "ST")):
        return "C_排除", "ST/退市风险警示"
    if revenue is None:
        return "C_排除", "无已披露财务数据"
    if netprofit is not None and netprofit < 0 and revenue < 30:
        return "C_排除", "亏损且营收<30亿"
    if revenue < 5:
        return "C_排除", "营收<5亿，规模不足以支撑可验证的护城河"
    if revenue >= 30:
        return "A_核心", f"营收{revenue:.0f}亿" + (f"／ROE{roe:.1f}%" if roe is not None else "")
    if roe is not None and roe >= 12:
        if ipo_roe_window:
            return "B_观察", f"营收{revenue:.0f}亿，ROE{roe:.1f}%为上市前小净资产口径，摊薄后待复核"
        return "A_核心", f"营收{revenue:.0f}亿／ROE{roe:.1f}%"
    return "B_观察", f"营收{revenue:.0f}亿，盈利"


def deduct_ratio(row: dict | None) -> float | None:
    """扣非归母 ÷ 归母（按每股口径），单位 %。低于 ~80% 表示当期利润里有相当比例非经常损益。"""
    if not row:
        return None
    basic, deduct = _num(row.get("basic_eps")), _num(row.get("deduct_basic_eps"))
    if basic in (None, 0) or deduct is None:
        return None
    return deduct / basic * 100


def ocf_to_eps(row: dict | None) -> float | None:
    """每股经营现金流 ÷ 每股收益。持续低于 1（尤其为负）说明利润没有变成现金。"""
    if not row:
        return None
    eps, ocf = _num(row.get("basic_eps")), _num(row.get("op_cashflow_ps"))
    if eps in (None, 0) or ocf is None:
        return None
    return ocf / eps


TIER_RANK = {"A_核心": 0, "B_观察": 1, "C_排除": 2}


def load_prior_tiers(path: Path | None = None) -> dict[str, str]:
    """上一次建队列时每只的层。文件不在（首次建）时返回空表，`tier_move` 全部留空。

    缺省读将被本次覆写的 `screen_queue.csv` 自身，故必须在写盘前调用。判据换代那一次要
    显式传上一代的队列文件（`--prior-queue`），否则基准已被新口径覆盖，移动方向会全空。
    """
    path = path or OUT
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {r["security_code"]: r.get("queue_tier", "") for r in csv.DictReader(handle)}


def tier_move(prior: str, current: str) -> str:
    """层的移动方向。升层（`up`）是本轮要送去逐家判的越线事件。"""
    if prior not in TIER_RANK or current not in TIER_RANK or prior == current:
        return ""
    return "up" if TIER_RANK[current] < TIER_RANK[prior] else "down"


SCOPE_MARGIN_PP = 8       # 毛利率较上年同期的位移，两个方向都算
SCOPE_REVENUE_YOY = 50    # 营收同比下限，%


def needs_scope_check(current: dict | None, prior_same: dict | None) -> bool:
    """毛利率较上年同期跳变 ≥8pp（**两个方向都算**）**且** 营收同比 ≥ +50%——先核合并范围。

    营收半年增五成的同时毛利率结构位移 8 个点，同口径经营几乎给不出这种组合，两个方向都
    指向并表：并入高毛利业务两者同升，并入低毛利贸易则营收暴涨而毛利率塌陷。只比上年同期，
    不比上年全年——半年对全年是两个窗口，季节性会自造假信号。命中只要求核对合并范围，不改
    分层，也不改结论。
    """
    if not current or not prior_same:
        return False
    now, before = _num(current.get("gross_margin")), _num(prior_same.get("gross_margin"))
    yoy = _num(current.get("revenue_yoy"))
    if now is None or before is None or yoy is None:
        return False
    return abs(now - before) >= SCOPE_MARGIN_PP and yoy >= SCOPE_REVENUE_YOY


def ytd_consistent(series: dict[str, dict], period: str, field: str) -> bool:
    """上年同期与上年年报是否同口径。

    报告期是**年初至今累计**，故同一年内 06-30／03-31 的累计值不可能超过该年 12-31。
    超过就说明两期之间改过口径（永安期货、浙江东方 2025 年把大宗商品销售移出营业总收入，
    25H1 55.6 亿 / 38.7 亿 大于 25 年报 18.5 亿 / 16.3 亿），此时 TTM 的减项与加项不是
    同一个量，滚出来的营收会为负。判不同口径就放弃 TTM，退到年报。

    年报本身为负（冲回）时这条判不出来，故调用侧另按「滚出的营收为负」兜一道。
    """
    prior = prior_periods(period)
    if prior is None:
        return True
    annual, same = (series.get(key) for key in prior)
    if annual is None or same is None:
        return True
    a, b = _num(annual.get(field)), _num(same.get(field))
    if a is None or b is None or a <= 0:
        return True
    return b <= a


def tier_inputs(panels: dict[str, dict[str, dict]], code: str, period: str
                ) -> tuple[float | None, float | None, float | None, str]:
    """分层用的年度口径三元组（营收亿、归母亿、ROE%）与所用口径名。

    兜底链 `ttm` → `annual` → `annualized`：TTM 需要本期、上年年报、上年同期三期齐全，
    上市不足一年的新股取不到减项；再退到上年年报；连年报都没有（当年上市）才折年。
    折年只在报告期长度上换算，季节性不做处理，故排在最后。ROE 走 `derive_roe`，它在
    `weightavg_roe` 出现伪 0 时退到 `EPS_TTM / BPS`，返回小数，这里换回百分数。
    """
    series = {name: table[code] for name, table in panels.items() if code in table}
    revenue = ttm(series, period, "total_operate_income") if period in series else None
    if revenue is not None and (revenue.value < 0
                                or not ytd_consistent(series, period, "total_operate_income")):
        revenue = None   # 减项与年报不同口径，滚出来的是差额不是营收
    if revenue is not None:
        profit = ttm(series, period, "parent_netprofit")
        roe, _ = derive_roe(series, period, ttm(series, period, "basic_eps"))
        return (revenue.value / 1e8,
                profit.value / 1e8 if profit else None,
                roe.value * 100 if roe else None,
                "ttm")
    annual = series.get("2025-12-31")
    if annual is not None:
        rev = _num(annual.get("total_operate_income"))
        if rev is not None:
            prof = _num(annual.get("parent_netprofit"))
            return (rev / 1e8, prof / 1e8 if prof is not None else None,
                    _num(annual.get("weightavg_roe")), "annual")
    current = series.get(period)
    if current is None:
        return None, None, None, ""
    rev = _num(current.get("total_operate_income"))
    if rev is None:
        return None, None, None, ""
    factor = 2 if period.endswith("06-30") else (1 if period.endswith("12-31") else 4)
    prof = _num(current.get("parent_netprofit"))
    roe = _num(current.get("weightavg_roe"))
    return (rev * factor / 1e8, prof * factor / 1e8 if prof is not None else None,
            roe * factor if roe is not None else None, "annualized")


def in_ipo_roe_window(listing_date: str, annual_period: str = "2025-12-31") -> bool:
    """年报期是否落在上市当年或次年——此时 ROE 分母含上市前的小净资产。"""
    if not listing_date or len(listing_date) < 4 or not listing_date[:4].isdigit():
        return False
    return int(annual_period[:4]) - int(listing_date[:4]) <= 1


def main() -> int:
    ap = argparse.ArgumentParser(description="全市场逐股重筛取数与排队")
    ap.add_argument("--batch", type=int, default=0, help="打印第几批待判事实（0=只建队列）")
    ap.add_argument("--size", type=int, default=120)
    ap.add_argument("--tier", default="A_核心", help="打印哪一层")
    ap.add_argument("--preview", action="store_true",
                    help="预审模式：以 2025 年报打底、叠加 2026Q1 与中报预告方向（用户 2026-08-09）")
    ap.add_argument("--prior-queue", default="",
                    help="拿哪个队列文件作 tier_move 的基准（缺省为待覆写的 screen_queue.csv 自身）")
    ap.add_argument("--h1-only", action="store_true",
                    help="只列已出 2026 中报的公司（用户 2026-08-09：先判这批，其余等中报）")
    args = ap.parse_args()

    h1, q1 = load_period("2026-06-30"), load_period("2026-03-31")
    ann25 = load_period("2025-12-31")
    # 分层入参走 TTM，故另载上年同期两期作滚动减项（见 classify 文档串与 tier_inputs）。
    panels = {"2026-06-30": h1, "2026-03-31": q1, "2025-12-31": ann25,
              "2025-06-30": load_period("2025-06-30"), "2025-03-31": load_period("2025-03-31")}
    prior_tiers = load_prior_tiers(Path(args.prior_queue) if args.prior_queue else None)
    securities = {r["security_code"]: r for r in csv.DictReader(SEC.open(encoding="utf-8-sig"))}
    # 财报面板里有、名录里没有的沪深代码只打印不入队：§5.3 要求开批前先刷新名录，刷新后仍缺的
    # 只剩两类——已发行未上市（待上市）与已终止上市后仍在老三板披露的旧代码（退市长油、乐视退
    # 一类）。二者都不是可判的在市 A 股；待上市者上市后随名录刷新自动进队。
    missing = sorted((code, row.get("security_name", "")) for code, row in {**q1, **h1}.items()
                     if code not in securities and is_a_share(code))
    if missing:
        print(f"名录外的沪深财报代码 {len(missing)} 只（待上市或已退市，不入队）："
              + "、".join(f"{c} {n}" for c, n in missing[:12]) + ("…" if len(missing) > 12 else ""))
    triage = {r["security_code"]: r for r in csv.DictReader(TRIAGE.open(encoding="utf-8"))}
    tiers = {r["security_code"]: r for r in csv.DictReader(TIERS.open(encoding="utf-8"))}

    rows = []
    for code, sec in securities.items():
        row = h1.get(code)
        basis, pending = "2026H1", 0
        if row is None:
            row, basis, pending = q1.get(code), "2026Q1", 1
        if row is None:
            row, basis, pending = {}, "无数据", 1
        revenue = (_num(row.get("total_operate_income")) or 0) / 1e8 if row else None
        profit = (_num(row.get("parent_netprofit")) or 0) / 1e8 if row else None
        roe = _num(row.get("weightavg_roe"))
        gross = _num(row.get("gross_margin"))
        # 名单简称带交易状态前缀（N 上市首日、C 上市 5 日内、XD/XR/DR 除权除息）时改用财报里的简称：
        # 前缀会把真名挤出简称字段的长度上限（`华大海天` → `N华大`），交易所又没有干净的备选字段。
        name = sec["security_name"]
        if has_status_prefix(name) and (row or {}).get("security_name"):
            name = row["security_name"]
        # **分层只能用 2025 年报的年度营收**。首版误用当期（一季报为单季）营收去比年度门槛，
        # 使年营收 20~33 亿的公司（泛微网络 22.9 亿、黔源电力 32.9 亿）被打进 C_排除，
        # 2026-08-09 扫描 C 层异常个案时发现。年报缺失时用当期值×4 折年，并在理由里标注。
        period = {"2026H1": "2026-06-30", "2026Q1": "2026-03-31"}.get(basis, "")
        rev_year, prof_year, roe_year, tier_basis = tier_inputs(panels, code, period)
        ipo_window = in_ipo_roe_window(sec.get("listing_date", "") or "")
        tier, reason = classify(rev_year, prof_year, roe_year, name, ipo_roe_window=ipo_window)
        if tier_basis == "annual":
            reason += "（按上年年报，TTM 不可用）"
        elif tier_basis == "annualized":
            reason += "（按当期折年，TTM 与年报均不可用）"
        rows.append({
            "security_code": code, "security_name": name, "board": sec["board"],
            "listing_date": sec.get("listing_date", "")[:10],
            "queue_tier": tier, "tier_reason": reason, "basis": basis, "pending_h1": pending,
            "revenue_yi": f"{revenue:.2f}" if revenue is not None else "",
            "netprofit_yi": f"{profit:.2f}" if profit is not None else "",
            "roe_pct": f"{roe:.2f}" if roe is not None else "",
            "gross_pct": f"{gross:.2f}" if gross is not None else "",
            "net_margin_pct": (f"{profit / revenue * 100:.1f}"
                               if revenue and profit is not None and revenue > 0 else ""),
            "revenue_yoy": row.get("revenue_yoy", "") if row else "",
            "netprofit_yoy": row.get("netprofit_yoy", "") if row else "",
            "ocf_ps": row.get("op_cashflow_ps", "") if row else "",
            "bps": row.get("bps", "") if row else "",
            "deduct_ratio_pct": (f"{dr:.0f}" if (dr := deduct_ratio(row)) is not None else ""),
            "ocf_to_eps": (f"{oe:.2f}" if (oe := ocf_to_eps(row)) is not None else ""),
            "ipo_roe_window": "1" if ipo_window else "",
            "tier_basis": tier_basis,
            "prior_queue_tier": prior_tiers.get(code, ""),
            "tier_move": tier_move(prior_tiers.get(code, ""), tier),
            "scope_check": ("1" if needs_scope_check(
                row, panels.get("2025-06-30" if basis == "2026H1" else "2025-03-31", {}).get(code)) else ""),
            "revenue_ttm_yi": f"{rev_year:.2f}" if rev_year is not None else "",
            "netprofit_ttm_yi": f"{prof_year:.2f}" if prof_year is not None else "",
            "roe_ttm_pct": f"{roe_year:.2f}" if roe_year is not None else "",
            "prior_class": triage.get(code, {}).get("attention_class", ""),
            "prior_quality_tier": tiers.get(code, {}).get("quality_tier", ""),
        })

    order = {"A_核心": 0, "B_观察": 1, "C_排除": 2}
    rows.sort(key=lambda r: (order[r["queue_tier"]], -float(r["revenue_yi"] or 0)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    counts = defaultdict(lambda: defaultdict(int))
    for r in rows:
        counts[r["queue_tier"]][r["basis"]] += 1
    print(f"全市场 {len(rows):,} 只｜{OUT.relative_to(ROOT)}")
    print(f'\n{"排队层":<10}{"合计":>7}{"2026H1":>9}{"2026Q1":>9}{"无数据":>8}{"已在池":>8}')
    print("-" * 52)
    for tier in ("A_核心", "B_观察", "C_排除"):
        group = [r for r in rows if r["queue_tier"] == tier]
        inpool = sum(1 for r in group if r["prior_class"] == "worth_attention")
        c = counts[tier]
        print(f'{tier:<10}{len(group):>7}{c["2026H1"]:>9}{c["2026Q1"]:>9}{c["无数据"]:>8}{inpool:>8}')
    pend = sum(1 for r in rows if r["pending_h1"])
    print(f'\n**待中报更新 {pend:,} 只**（8 月底中报截止后重跑本脚本并复核）')
    if not VERDICTS.exists():
        with VERDICTS.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=[
                "security_code", "security_name", "reference_score", "attention_class",
                "never_admit", "never_admit_reason", "moat_note", "rule", "basis", "reviewed_at",
                "pending_h1",
                # 复现性三列：判定所用模型 ID、工作流版本、`docs/Ashare_quality_rubric.md` 的 sha256 前 12 位
                "judged_by_model", "workflow_version", "rubric_sha256",
            ]).writeheader()
        print(f"已建空判定档 {VERDICTS.relative_to(ROOT)}")

    if args.batch:
        if args.preview:
            # 预审：**以 2025 年报为主证据**（完整审计年度，护城河判断依赖多年利润率结构，
            # 半年报不改变结论），2026Q1 与中报预告只用于定方向与标记需等中报的例外。
            ann = load_period("2025-12-31")
            pre = {}
            fc = ROOT / "data/interim/a_share_earnings_forecasts.csv"
            if fc.exists():
                for row in csv.DictReader(fc.open(encoding="utf-8")):
                    if row["report_date"].startswith("2026-06") and row["predict_finance_code"] == "004":
                        pre[row["security_code"]] = row
            group = []
            for r in rows:
                if r["queue_tier"] != args.tier or r["security_code"] not in pre:
                    continue
                a25 = ann.get(r["security_code"], {})
                f = lambda k: _num(a25.get(k))
                rev, npf = f("total_operate_income"), f("parent_netprofit")
                r = dict(r)
                r["y25_rev"] = f"{rev / 1e8:.1f}" if rev else ""
                r["y25_np"] = f"{npf / 1e8:.1f}" if npf is not None else ""
                r["y25_roe"] = a25.get("weightavg_roe", "")[:5]
                r["y25_gross"] = a25.get("gross_margin", "")[:5]
                r["pre_type"] = pre[r["security_code"]]["predict_type"]
                r["pre_amp"] = pre[r["security_code"]]["add_amp_lower"][:7]
                group.append(r)
        elif args.h1_only:
            group = [r for r in rows if r["basis"] == "2026H1"]
        else:
            group = [r for r in rows if r["queue_tier"] == args.tier]
        done = set()
        if VERDICTS.exists():
            done = {r["security_code"] for r in csv.DictReader(VERDICTS.open(encoding="utf-8"))}
        todo = [r for r in group if r["security_code"] not in done]
        lo = (args.batch - 1) * args.size
        batch = todo[lo:lo + args.size]
        print(f"\n# {'已出2026中报' if args.h1_only else args.tier} 待判 {len(todo):,}｜"
              f"本批 {len(batch)}（第 {args.batch} 批）")
        print("# 代码 名称 板块｜口径｜营收亿 净利亿 ROE% 毛利% 净利率% 营收同比 净利同比｜原分类")
        for r in batch:
            if args.preview:
                print(f'{r["security_code"]} {r["security_name"]:<8}｜25年报 收{r["y25_rev"]:>7}亿 '
                      f'净{r["y25_np"]:>7}亿 ROE{r["y25_roe"]:>6} 毛{r["y25_gross"]:>6}｜'
                      f'26Q1 收{r["revenue_yi"]:>7} ROE{r["roe_pct"]:>6}｜中报预告 {r["pre_type"]}{r["pre_amp"]}%')
                continue
            print(f'{r["security_code"]} {r["security_name"]:<8}{r["board"][:4]:<5}{r["basis"]}｜'
                  f'{r["revenue_yi"]:>8} {r["netprofit_yi"]:>8} {r["roe_pct"]:>6} {r["gross_pct"]:>6} '
                  f'{r["net_margin_pct"]:>6} {r["revenue_yoy"][:6]:>7} {r["netprofit_yoy"][:7]:>8}｜'
                  f'{r["prior_class"][:4]}{r["prior_quality_tier"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
