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
5,392 只逐一深判不现实，也不必要。本脚本按**可判性**排队，把判断力用在有可能进池的公司上：

* `A_核心`：营收 ≥ 30 亿 或 ROE ≥ 12%——**必须逐家判**，进池候选都在这里
* `B_观察`：营收 5~30 亿 且 盈利——按行业成批判，个别有护城河签名的单拎
* `C_排除`：连续亏损 / 营收 < 5 亿 / ST——**按规则批量判「永不录用」并写明依据**，
  不逐家展开；任一后续年度突破门槛会自动回到 A 或 B

**这个分层只决定判断的粒度，不决定结论**：C 类里若有 §5.4.1 意义上的护城河（如小而美的
品类垄断），仍会被 B 类的行业扫描捞回来。分层依据写入 `tier_reason` 供复核。

用法::

    python3 scripts/build_full_market_screen_queue.py
    python3 scripts/build_full_market_screen_queue.py --batch 1 --size 120   # 打印一批待判事实
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_a_share_universe import has_status_prefix

ROOT = Path(__file__).resolve().parents[1]
FIN = ROOT / "data/raw/financials"
SEC = ROOT / "data/raw/a_share_securities.csv"
TRIAGE = ROOT / "data/processed/a_share_attention_triage.csv"
TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
OUT = ROOT / "data/processed/full_market_screen/screen_queue.csv"
VERDICTS = ROOT / "data/processed/full_market_screen/verdicts.csv"

FIELDS = ["security_code", "security_name", "board", "listing_date", "queue_tier", "tier_reason",
          "basis", "pending_h1", "revenue_yi", "netprofit_yi", "roe_pct", "gross_pct",
          "net_margin_pct", "revenue_yoy", "netprofit_yoy", "ocf_ps", "bps",
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


def classify(revenue, netprofit, roe, name: str) -> tuple[str, str]:
    """排队分层。**只决定判断粒度，不决定结论**——见文件头。

    **入参必须是年度口径**（2025 年报）。首版误传当期营收（一季报为单季）导致大量中型公司
    被错分到 C_排除——判据是年度阈值（5 亿/30 亿），拿单季数去比等于把门槛抬高了四倍。
    """
    if name.startswith(("*ST", "ST")):
        return "C_排除", "ST/退市风险警示"
    if revenue is None:
        return "C_排除", "无已披露财务数据"
    if netprofit is not None and netprofit < 0 and revenue < 30:
        return "C_排除", "亏损且营收<30亿"
    if revenue < 5:
        return "C_排除", "营收<5亿，规模不足以支撑可验证的护城河"
    if revenue >= 30 or (roe is not None and roe >= 12):
        return "A_核心", f"营收{revenue:.0f}亿" + (f"／ROE{roe:.1f}%" if roe is not None else "")
    return "B_观察", f"营收{revenue:.0f}亿，盈利"


def main() -> int:
    ap = argparse.ArgumentParser(description="全市场逐股重筛取数与排队")
    ap.add_argument("--batch", type=int, default=0, help="打印第几批待判事实（0=只建队列）")
    ap.add_argument("--size", type=int, default=120)
    ap.add_argument("--tier", default="A_核心", help="打印哪一层")
    ap.add_argument("--preview", action="store_true",
                    help="预审模式：以 2025 年报打底、叠加 2026Q1 与中报预告方向（用户 2026-08-09）")
    ap.add_argument("--h1-only", action="store_true",
                    help="只列已出 2026 中报的公司（用户 2026-08-09：先判这批，其余等中报）")
    args = ap.parse_args()

    h1, q1 = load_period("2026-06-30"), load_period("2026-03-31")
    ann25 = load_period("2025-12-31")   # 分层专用：**必须用年度口径**，见 classify 文档串
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
        a25 = ann25.get(code, {})
        rev_year = (_num(a25.get("total_operate_income")) or 0) / 1e8 if a25 else None
        prof_year = (_num(a25.get("parent_netprofit")) or 0) / 1e8 if a25 else None
        roe_year = _num(a25.get("weightavg_roe")) if a25 else None
        annualized = False
        if rev_year is None and revenue is not None:
            rev_year, prof_year, roe_year = revenue * (2 if basis == "2026H1" else 4), profit, roe
            annualized = True
        tier, reason = classify(rev_year, prof_year, roe_year, name)
        if annualized:
            reason += "（按当期折年，年报缺失）"
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
