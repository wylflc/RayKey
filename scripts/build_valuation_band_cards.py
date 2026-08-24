#!/usr/bin/env python3
"""Compute the 建带卡 draft for the pool from per-name dossiers（工作流 §6.7 第 5 步）.

每行必须有 active 且 `bespoke=true` 的逐票估值档案（§6.5.2，
`data/processed/a_share_valuation_dossiers.csv`，其带由 §6.7 第 4 步的
`apply_model_bands_to_dossiers.py` 按生产模型带回写）。缺档案或 `bespoke != true`
的行直接硬失败退出——通用十类估值路径已整体删除，本脚本不产出任何估值意见，
只把档案带机械转抄成建带卡，并补可复算的自检：

* `runrate_check` — 运行率不变量：档案锚（`anchor_earnings_yi`）对照已披露
  TTM 归母（含已结束报告期的预告/快报，§6.4）
* `band_sensitivity` — 档案的跟踪指标/复核触发/定案信息 + 运行率读数

Usage::

    python3 scripts/build_valuation_band_cards.py \
      --tags data/interim/strategy_tag_map.csv \
      --out data/interim/valuation_band_cards.csv \
      --as-of 2026-08-01
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "data/interim/valuation_evidence"

AS_OF_YEAR = 2026                # `AS_OF_DATE` 缺省的年份
AS_OF_DATE = f"{AS_OF_YEAR}-12-31"   # 由 main() 按 --as-of 覆盖；决定哪些报告期算「已结束」

# §6.5.2 逐票估值档案（v1.47，用户决定）：带只由档案给出（`bespoke = true`）。
# 全池建档后通用十类模型成为不可达路径、已整体删除；非 bespoke 行在 `_build_card` 硬失败。
# 设立理由：紫金矿业在通用口径的 PE 腿与 PB 腿之间反复翻转，连改五版仍不稳定；
# 对这类公司继续套通用公式，只会按下葫芦起了瓢。
DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"
_DOSSIER_CACHE: dict[str, dict] | None = None


def dossier(code: str) -> dict | None:
    """逐票估值档案；`dossier_status != active` 的不生效。"""
    global _DOSSIER_CACHE
    if _DOSSIER_CACHE is None:
        _DOSSIER_CACHE = {}
        if DOSSIERS.exists():
            with DOSSIERS.open(encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    if (row.get("dossier_status") or "").strip() == "active":
                        _DOSSIER_CACHE[row["security_code"].zfill(6)] = row
    return _DOSSIER_CACHE.get(code)

# 运行率不变量阈值（`runrate_invariant`）
RUN_RATE_FLOOR = 0.85            # 锚 < TTM 归母 × 0.85 即触发周期假设标记


def load_evidence(code: str) -> dict | None:
    path = EVIDENCE_DIR / f"{code}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# §6.4（v1.46，结 OI-015 第 1 条，用户指令「对所有公司，都将业绩预告包含在业绩报告的范畴中」）
FORECAST_FIELD_BY_CODE = {"004": "PARENTNETPROFIT", "005": "KCFJCXSYJLR", "008": "TOTALOPERATEREVE"}
FORECAST_GROWTH_CODES = {"001": "TOTALOPERATEREVE", "006": "TOTALOPERATEREVE"}
FORECAST_MIN_ELAPSED = 0.5       # 公告日时报告期至少走完一半，否则算预测不算业绩


def _period_start(period_end: str) -> str:
    """报告期起点：A 股定期报告一律自然年内累计，故起点恒为当年 1 月 1 日。"""
    return f"{period_end[:4]}-01-01"


def _elapsed_fraction(period_end: str, notice: str) -> float:
    """公告日时该报告期已走完的比例。>1 表示期末之后才公告（绝大多数情形）。"""
    start, end, nd = _period_start(period_end), datetime.date.fromisoformat(period_end), None
    try:
        nd = datetime.date.fromisoformat(notice)
    except ValueError:
        return 0.0
    s = datetime.date.fromisoformat(start)
    span = (end - s).days or 1
    return (nd - s).days / span


def forecast_periods(evidence: dict, as_of: str) -> list[dict]:
    """把**尚无定期报告**的报告期，按业绩快报/业绩预告合成为期数行。

    运行率硬校验与各类 TTM 锚此前只读 `finance_periods`，预告与快报从不入参。
    直接后果（OI-015 判例高德红外）：锚为 2026Q1 口径 TTM 扣非 9.04 亿，而 7/9 预告的
    H1'26 扣非已达 12.35-14.15 亿——单个半年即超过全部 TTM——运行率比值按 0.93 通过
    0.85 阈值，真实比值 0.48。

    **取舍的分界线是「有没有对应的定期报告」，不是「报告期结不结束」**（v1.46 修订）：
    定期报告一旦披露，同期预告/快报即刻作废、直接丢弃（实测全池 1005 行预告属此类）；
    真正有价值的恰恰是**还没有定期报告的那一期**（实测 155 行）。报告期是否已过期末
    只是个次要的可靠性指标——A 股预告最早可提前 77 天发布（中位提前 36 天），届时
    报告期已走完大半，把它一律当「预测」丢掉会让锚白白落后一整期。

    三道门（须全部满足）：
      ① **未被定期报告取代**：`REPORT_DATE` 必须晚于最新已披露定期报告期；
      ② **披露已发生**：`NOTICE_DATE ≤ as_of`——回放口径，不得使用当日尚未公告的信息
         （此前误用 `REPORT_DATE ≤ as_of`，会把「期未结束但已公告」的预告错误排除）；
      ③ **报告期已实质走完**：公告日时该期已过 ≥50%，否则属真预测，走一致预期口径。

    取值：**区间中值**（v1.46 改，原取下限）。实测全池 1063 条盈利预告的相对区间宽度
    中位仅 **9.8%**、P90 22.2%、>50% 的仅 1 条——区间很窄，参考价值高；取下限等于给
    锚加一道约 5% 的**系统性下偏**，而安全边际本就由带系数承担（v1.33 已否决过同类
    二次保守）。这与一致预期取中位数是同一原则。
    """
    periods = evidence.get("finance_periods") or []
    latest = max((p["REPORT_DATE"][:10] for p in periods
                  if p.get("PARENTNETPROFIT") is not None), default="")
    rows: dict[str, dict] = {}

    def admissible(date: str, notice: str) -> bool:
        return bool(date) and date > latest and bool(notice) and notice <= as_of \
            and _elapsed_fraction(date, notice) >= FORECAST_MIN_ELAPSED

    def mid(lo, hi):
        """区间中值；单边给出时取给出的那一边。"""
        vals = [float(v) for v in (lo, hi) if v is not None]
        return sum(vals) / len(vals) if vals else None

    for item in (evidence.get("performance_predicts") or []):
        date, notice = str(item.get("REPORT_DATE") or "")[:10], str(item.get("NOTICE_DATE") or "")[:10]
        if not admissible(date, notice):
            continue
        code = item.get("PREDICT_FINANCE_CODE")
        row = rows.setdefault(date, {"REPORT_DATE": date, "REPORT_TYPE": "业绩预告",
                                     "_forecast_notice": notice,
                                     "_forecast_elapsed": _elapsed_fraction(date, notice)})
        if code in FORECAST_FIELD_BY_CODE:
            value = mid(item.get("PREDICT_AMT_LOWER"), item.get("PREDICT_AMT_UPPER"))
            if value is not None:
                row[FORECAST_FIELD_BY_CODE[code]] = value
        elif code in FORECAST_GROWTH_CODES:
            # 营收类预告多数只给增速（全池 134 条营收预告中 129 条是 006 增速式），
            # 按同期上年累计还原绝对额；增速同样取区间中值。
            rate = mid(item.get("ADD_AMP_LOWER"), item.get("ADD_AMP_UPPER"))
            prior = next((p.get(FORECAST_GROWTH_CODES[code]) for p in periods
                          if p["REPORT_DATE"][:10] == f"{int(date[:4]) - 1}{date[4:]}"), None)
            if rate is not None and prior:
                row[FORECAST_GROWTH_CODES[code]] = float(prior) * (1 + rate / 100)

    for item in (evidence.get("performance_express") or []):
        date, notice = str(item.get("REPORT_DATE") or "")[:10], str(item.get("NOTICE_DATE") or "")[:10]
        if not admissible(date, notice):
            continue
        # 快报覆盖同期预告：数值更接近终值。快报无扣非，该字段由同期预告补。
        row = {"REPORT_DATE": date, "REPORT_TYPE": "业绩快报", "_forecast_notice": notice,
               "_forecast_elapsed": _elapsed_fraction(date, notice)}
        if item.get("PARENT_NETPROFIT") is not None:
            row["PARENTNETPROFIT"] = float(item["PARENT_NETPROFIT"])
        if item.get("TOTAL_OPERATE_INCOME") is not None:
            row["TOTALOPERATEREVE"] = float(item["TOTAL_OPERATE_INCOME"])
        if len(row) > 4:
            prior = rows.get(date) or {}
            if prior.get("KCFJCXSYJLR") is not None:
                row["KCFJCXSYJLR"] = prior["KCFJCXSYJLR"]
            rows[date] = row

    return sorted(rows.values(), key=lambda r: r["REPORT_DATE"], reverse=True)


def augmented_periods(evidence: dict, as_of: str) -> list[dict]:
    """已披露期数 + 合成的预告/快报期数（§6.4）。"""
    return forecast_periods(evidence, as_of) + (evidence.get("finance_periods") or [])


def ttm(periods: list[dict], field: str) -> float | None:
    """取数陷阱一：finance_periods 是累计口径，须差分成单季再求 TTM。

    单季 = 本期累计 − 同年上期累计（一季报本身即单季）。TTM = 最近四个单季之和。

    §6.4 同口径保护：预告只给利润、不给营收是常态（实测 74 家有预告、仅 11 家
    带营收）。若最新的合成期缺本字段，则本次调用**整体退回已披露期数**——同一个
    字段的 TTM 绝不半新半旧。
    """
    if any(p.get("_forecast_notice") for p in periods):
        newest = max(periods, key=lambda p: p["REPORT_DATE"])
        if newest.get("_forecast_notice") and newest.get(field) is None:
            periods = [p for p in periods if not p.get("_forecast_notice")]
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
    # 兜底：**年报 + 本年累计 − 上年同期累计**（v1.58）。
    # 四单季差分要求四个季度连续可得，中间缺任一期即整体失败——次新股尤其常见：
    # 盛合晶微 2025 年上市，`finance_periods` 无 2025 三季报，TTM 因此返回 None，
    # 而它 FY2025 归母 9.21亿、Q1'26 1.91亿，TTM 明明可算（9.21+1.91−1.26 = 9.86亿）。
    # 该判例由 §13 第 3 条的列覆盖自检（无 TTM 行清单）抓出。
    annual = {p["REPORT_DATE"][:10]: p for p in rows if p["REPORT_DATE"][5:10] == "12-31"}
    ytd = [p for p in rows if p["REPORT_DATE"][5:10] != "12-31"]
    if annual and ytd:
        latest = max(ytd, key=lambda p: p["REPORT_DATE"])
        year, mmdd = latest["REPORT_DATE"][:4], latest["REPORT_DATE"][5:10]
        prior_annual = annual.get(f"{int(year) - 1}-12-31")
        prior_ytd = by_date.get(f"{int(year) - 1}-{mmdd}")
        if prior_annual and prior_ytd and prior_annual.get(field) is not None and prior_ytd.get(field) is not None:
            return float(prior_annual[field]) + float(latest[field]) - float(prior_ytd[field])
    return None


def ttm_augmented_profit(evidence: dict, as_of: str) -> float | None:
    """已披露口径的 TTM 归母（含已结束报告期的预告/快报，§6.4）。"""
    return ttm(augmented_periods(evidence, as_of), "PARENTNETPROFIT")


def runrate_invariant(evidence: dict, as_of: str, anchor_earnings_yi: float | None) -> tuple[str, str]:
    """运行率不变量（v1.52，结 OI-018）——**对每一条带生效，与锚的口径无关**。

    原实现把校验挂在 `anchor_scope == "market_cap"` 上，于是走 PB / DPS 路径的行
    从不进入校验；而逐票档案一律置 `per_share`，**每建一份档案就多一行脱离校验**
    ——OI-018 登记时 37 行，建档 31 家后升至 67 行，覆盖不增反减。校验本该挂在
    **事实**（带所依据的盈利 vs 已披露盈利）上，而不是挂在带由哪条路径产生上。

    锚不是盈利口径的（净资产锚、市销率锚）显式返回「不适用」而非静默跳过——
    静默跳过正是 §13 第 3 条点名的病。
    """
    t = ttm_augmented_profit(evidence, as_of)
    if not t or t <= 0:
        return "na_no_ttm", "运行率不变量：TTM 归母 ≤0 或不可算，不适用"
    ttm_yi = t / 1e8
    if anchor_earnings_yi is None:
        return "na_not_earnings", (f"运行率不变量：本档锚非盈利口径（净资产/市销率等），不适用；"
                                   f"对照已披露 TTM 归母 {ttm_yi:.2f}亿")
    ratio = anchor_earnings_yi / ttm_yi
    if ratio < RUN_RATE_FLOOR:
        return "below_runrate", (f"⚠运行率不变量触发：盈利锚 {anchor_earnings_yi:.2f}亿 仅为已披露 TTM 归母 "
                                 f"{ttm_yi:.2f}亿 的 {ratio:.2f} 倍（阈值 {RUN_RATE_FLOOR}）——"
                                 f"锚低于运行率须有明写理由（周期均值回归／一次性收益剔除），否则应上修")
    return "ok", f"运行率不变量：盈利锚 {anchor_earnings_yi:.2f}亿 ÷ 已披露 TTM 归母 {ttm_yi:.2f}亿 = {ratio:.2f}"


def build_card(code: str, name: str, tag_letter: str, quality_tier: str) -> dict:
    """建带卡。**运行率不变量在此统一兜底**（v1.53）——`_build_card` 有多个 return 分支，
    逐个挂校验必然漏（v1.52 首版即漏掉 K primary Gordon 分支的 4 行，苏泊尔/杭氧股份/
    长江电力/养元饮品 产出空的 `runrate_check`，属 §13 第 3 条的静默缺口）。
    改为在唯一出口统一补：任何分支未给出结论的，在这里按盈利锚重算一次。
    """
    card = _build_card(code, name, tag_letter, quality_tier)
    if not card.get("runrate_check"):
        evidence = load_evidence(code)
        if evidence is None:
            card["runrate_check"] = "na_no_evidence"
        else:
            scope = card.get("anchor_scope")
            try:
                anchor_yi = float(card.get("anchor_value") or "") if scope == "market_cap" else None
            except ValueError:
                anchor_yi = None
            card["runrate_check"], _ = runrate_invariant(evidence, AS_OF_DATE, anchor_yi)
    return card


def _build_card(code: str, name: str, tag_letter: str, quality_tier: str) -> dict:
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
        "anchor_vintage": "",        # §6.4：锚是否用到已结束报告期的预告/快报
        "method_divergence": "",     # 双口径中值背离比例（OI-016 的卖出抑制依据；通用路径遗留列）
        "runrate_check": "",         # 运行率不变量（v1.52，OI-018）
        "cycle_assumption": "",
        "scenario_band_low": "",
        "scenario_band_high": "",
        "cycle_note": "",
        "implied_excess_years": "",
        "excess_years_ladder": "",
        "cycle_gap_kind": "",
        "multiple_regime_flag": "",
        "implied_return": "",
        "implied_return_tier": "",
        "manual_verdict": "",
        "band_sensitivity": "",
        "band_fragile": "false",
        "fair_price_low": "",
        "fair_price_high": "",
        "needs_external": "",
        "note": "",
    }
    # §6.5.2（v1.47）：bespoke 档案**完全脱离通用模型**——带只由档案给出。
    # 用户决定：「对于反复处理不好的公司，标记为特殊公司，逐案例分析，
    # 不再使用相关行业的共用估值方法。」全池已全部建档，非 bespoke 行在下方硬失败。
    doc = dossier(code)
    if doc and str(doc.get("bespoke", "")).strip().lower() == "true":
        card.update(
            anchor_metric="dossier", anchor_scope="per_share", band_derivation="dossier",
            anchor_quality="primary", multiple_source="dossier",
            fair_price_low=doc.get("band_low", ""), fair_price_high=doc.get("band_high", ""),
            anchor_basis=f"逐票档案（§6.5.2，脱离通用模型）：{doc.get('band_method','')}。"
                         f"{doc.get('band_derivation','')}"[:1200],
            band_sensitivity=f"跟踪指标：{doc.get('key_metrics','')}｜复核触发：{doc.get('review_triggers','')}"
                             f"｜定案：{doc.get('decided_by','')}（{doc.get('reviewed_at','')}）",
            upgrade_path=doc.get("notes", "")[:400],
        )
        try:
            ae = float(doc.get("anchor_earnings_yi") or "")
        except ValueError:
            ae = None
        if evidence is not None:
            flag, note = runrate_invariant(evidence, AS_OF_DATE, ae)
            card["runrate_check"] = flag
            card["band_sensitivity"] = (card["band_sensitivity"] + "｜" + note)[:1600]
        return card

    reason = ("无 active 逐票档案" if doc is None
              else f"档案 bespoke={(doc.get('bespoke') or '').strip()!r} ≠ true")
    raise SystemExit(
        f"❌ {code} {name}：{reason}——通用估值路径已删除（§6.5.1 唯一生产模型），"
        f"先在 {DOSSIERS.relative_to(ROOT)} 补该票的 active 档案行（bespoke=true）再重跑"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="从逐票档案转抄建带卡草稿（§6.7 第 5 步）")
    parser.add_argument("--tags", type=Path, required=True, help="CSV: security_code,strategy_tag_letter")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()

    global AS_OF_DATE
    AS_OF_DATE = args.as_of          # §6.4：只有 REPORT_DATE ≤ as_of 的预告/快报才合成

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
    # §13 第 3 条强制自检（v1.58）：**凡新增列，跑完必须核对非空行数**。
    # 四次静默失效的共同签名都是「某列/某源整体为空而无人察觉」。全池走逐票档案
    # （非 bespoke 行在 `_build_card` 已硬失败），列覆盖自检挂 §6.5.2 档案必填列。
    total = len(cards)
    REQUIRED = ("fair_price_low", "fair_price_high", "anchor_basis", "band_sensitivity")
    incomplete = [(c, k) for c in cards for k in REQUIRED if not str(c.get(k, "")).strip()]
    print(f"  列覆盖自检        全池 {total} 行全部走逐票档案；档案必填列 "
          f"{len(REQUIRED)} 项 × {total} 家，缺项 {len(incomplete)}")
    if incomplete:
        print("    ❌**档案必填列缺项**："
              + "、".join(f"{c['security_code']}{c.get('security_name','')}:{k}" for c, k in incomplete[:10])
              + ("…" if len(incomplete) > 10 else ""))
    # 数据源自检：财务期数为 0 的行——北交所判例正是全体为 0 而无提示
    noperiod = [c for c in cards if c.get("runrate_check") == "na_no_ttm"]
    if noperiod:
        print(f"    ⚠无 TTM 归母（财务期数缺失或为负）{len(noperiod)} 行："
              + "、".join(f"{c['security_code']}{c.get('security_name','')}" for c in noperiod[:12])
              + ("…" if len(noperiod) > 12 else ""))
    # 档案推导里显式引用预告/快报的家数（§6.4）
    fc_dossier = sum(1 for c in cards if "预告" in (c.get("anchor_basis") or "") or "快报" in (c.get("anchor_basis") or ""))
    print(f"  锚含预告/快报      档案 {fc_dossier}（§6.4）")
    print(f"  输出：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
