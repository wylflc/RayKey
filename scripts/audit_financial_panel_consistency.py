#!/usr/bin/env python3
"""逐行自洽核对季度财务面板，检出会静默改变估值带的数据错误。

为什么需要
----------
判例：宏桥控股（002379）FY2025 的 `bps` 记为 **40.1022**，而用同一行自报的加权 ROE
34.63% 反推应为 **3.9584**——偏大 10.1 倍。后果不是显示问题：错误的 `bps` 拖低了
归一化 `ratio0`，`nopat_ps = ratio0 × bps` 随之失真，生产带被压到 0.0974，
而 2026E 一致预期 EPS 2.47 对应现价 PE 仅 7.8。**一条 10 倍的数据错误把一只
可能合格的票判成「高估」并藏出扫描之外**，且全程无任何告警。

本脚本不改数，只报异常——数据修复须逐条人工确认来源后再动。

四项核对
--------
1. **ROE 自洽**：`归母 ÷ (bps × 股本)` 对 `加权ROE`。A 股定期报告的加权 ROE 是
   **累计不年化**口径，故各报告期都可直接比。分母用期末权益而非平均权益，
   成长期公司会系统性偏低，因此只在**倍数级**偏离时报警，不追小数。
2. **股本自洽**：`归母 ÷ EPS` 在相邻期之间应稳定，除非有送转或增发。
3. **bps 连续性**：相邻期 `bps` 的跳变，扣掉送转因子与每股分红后仍成倍变化的报警。
4. **累计单调性**：同一会计年度内累计归母出现「后一期绝对值小于前一期且符号相同」
   属正常（亏损收窄/盈利回吐），不报；只报**累计口径疑似被单季数替换**的形态。

用法
----
    python3 scripts/audit_financial_panel_consistency.py --signal-date YYYY-MM-DD
    python3 scripts/audit_financial_panel_consistency.py --signal-date YYYY-MM-DD --all-market
缺省只扫核心估值池（201 只）；`--all-market` 扫面板全部公司，慢很多。
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import math
from collections import defaultdict
from pathlib import Path

from a_share_signal_dates import evidence_iso_for_signal

ROOT = Path(__file__).resolve().parent.parent
ROE_RATIO_WARN = 2.0     # 隐含 ROE / 自报 ROE 超出 [1/2, 2] 报警
ROE_RATIO_SEVERE = 3.0   # 超出 [1/3, 3] 判严重
BPS_JUMP_WARN = 2.5      # 相邻期 bps 倍数跳变阈值
SHARE_JUMP_WARN = 1.20   # 相邻期倒推股本跳变阈值（送转/增发已单独扣除）
MIN_PERIODS = 4
SHARE_LIVE_WARN = 0.05   # 实时总股本 vs 面板股数 的相对偏差告警线
ISSUE_MIN_FRAC = 0.05    # 检查⑥：增发占发行前股本的最低比例，低于此不判
RESTATE_EQUITY_MIN = 0.01  # 检查⑥：重述日志里归母权益变动 ≥ 1% 才视为追溯重述
SHARE_EVENT_LOOKBACK_DAYS = 3 * 365   # 检查⑦：回看多久的股本事件
SHARE_EVENT_SKIP = ("送", "转增", "转股", "拆", "首发", "上市前", "股权分置", "限售", "解禁", "高管", "流通",
                    "股份性质", "回购", "限制性股票", "股权激励", "配售股份上市", "行权")   # 非增发类事件不判
SHARE_EVENT_REVIEWS = ROOT / "data/processed/share_event_reviews.csv"


def num(value) -> float | None:
    try:
        f = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def load_panel(fin_dir: Path, codes: set[str] | None) -> dict[str, dict[str, dict]]:
    panel: dict[str, dict[str, dict]] = defaultdict(dict)
    for path in sorted(fin_dir.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                code = (row.get("security_code") or "").strip()
                if code and (codes is None or code in codes):
                    panel[code][path.stem] = row
    return panel


def load_share_factors(path: Path) -> dict[str, list[tuple[str, float, float]]]:
    """{代码: [(除权日, 每股送转比例（分数，10 送 8 转 12 记 2.0）, 每股现金分红)]}"""
    out: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            ex = (row.get("ex_dividend_date") or "").strip()[:10]
            if not ex:
                continue
            out[(row.get("security_code") or "").strip()].append(
                (ex, (num(row.get("share_ratio")) or 0.0) + (num(row.get("rights_ratio")) or 0.0),
                 num(row.get("cash_per_share")) or 0.0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="季度财务面板逐行自洽核对")
    ap.add_argument("--signal-date", required=True, help="信号日；证据日自动取下一工作日")
    ap.add_argument("--financials-dir", type=Path, default=ROOT / "data/raw/financials")
    ap.add_argument("--pool", type=Path, default=ROOT / "data/processed/a_share_core_valuation_pool.csv")
    ap.add_argument("--corporate-actions", type=Path,
                    default=ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv")
    ap.add_argument("--all-market", action="store_true", help="扫面板全部公司，不限于核心池")
    ap.add_argument("--periods", type=int, default=8, help="每只回看多少期")
    ap.add_argument("--restatements", type=Path, default=ROOT / "data/interim/statement_restatements.csv",
                    help="取数探针写的重述日志（OI-126）；检查⑥只看其中归母权益实变的年报期")
    ap.add_argument("--share-changes", type=Path, default=ROOT / "data/raw/share_changes/a_share_share_changes.csv")
    ap.add_argument("--share-event-reviews", type=Path, default=SHARE_EVENT_REVIEWS,
                    help="检查⑦的复核登记（OI-129）：已登记 reset／no_reset 的事件不再报出")
    ap.add_argument("--out", type=Path, default=ROOT / "data/interim/financial_panel_anomalies.csv")
    args = ap.parse_args()
    args.as_of = evidence_iso_for_signal(args.signal_date)

    codes = None
    names: dict[str, str] = {}
    live_shares: dict[str, float] = {}
    if not args.all_market and args.pool.exists():
        with args.pool.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        codes = {r["security_code"] for r in rows}
        names = {r["security_code"]: r["security_name"] for r in rows}
        # 实时总股本 = 总市值 ÷ 现价（腾讯 qt.gtimg.cn 字段 45，`total_market_cap_bn` 单位十亿元）。
        # 池文件里已存好，本脚本不再联网。
        for r in rows:
            cap, price = num(r.get("total_market_cap_bn")), num(r.get("valuation_price"))
            if cap and price and price > 0:
                live_shares[r["security_code"]] = cap * 1e9 / price

    panel = load_panel(args.financials_dir, codes)
    # 订正层（OI-066）先于自洽核对生效：已登记的源侧错值不再逐轮报「严重」，
    # 登记失效（源侧已订正）时反向告警。
    from financials_corrections import apply_corrections, report as _corr_report
    _corr_report(*apply_corrections(panel))
    actions = load_share_factors(args.corporate_actions)
    findings: list[dict] = []

    for code, periods in panel.items():
        name = names.get(code, (next(iter(periods.values())).get("security_name") or code))
        keys = sorted(periods)[-args.periods:]
        if len(keys) < MIN_PERIODS:
            continue
        prev_key = prev_bps = prev_shares = prev_shares_raw = None
        for key in keys:
            row = periods[key]
            profit, eps = num(row.get("parent_netprofit")), num(row.get("basic_eps"))
            bps, roe = num(row.get("bps")), num(row.get("weightavg_roe"))

            shares = profit / eps if profit is not None and eps not in (None, 0) else None

            # **送转口径错配必须先扣掉，否则整段拆股前历史都会被误报。**
            # 数据源把 `basic_eps` **追溯重述**到最新股本口径，而 `bps` 按各期期末
            # 原样报告、不重述。于是拆股前的期次用重述 EPS 倒推出的股本是「现在的股本」，
            # 与同一行未重述的 bps 不同基。判例：比亚迪 2025-07-29 十送八转十二（股本×3），
            # 2024-06~2025-06 五期的隐含 ROE 恒为自报的 0.30~0.33 倍——**是口径错配不是错误**，
            # 且当期带用的是拆股后 bps，未受影响。
            future_split = 1.0
            for ex, ratio_k, _cash in actions.get(code, []):
                if ex > key and ratio_k:
                    future_split *= (1 + ratio_k)
            shares_at_period = shares / future_split if shares else None

            # ① ROE 自洽。**EPS 是否已被追溯重述到最新股本，逐票甚至逐期不一**（比亚迪重述、
            # 新易盛未重述），故两个口径都算，取更自洽的那个；两个口径都超阈值才报。
            if None not in (profit, bps, roe) and shares_at_period and bps > 0 and abs(roe) > 1.0:
                candidates = {"重述口径（÷后续送转）": shares_at_period}
                if future_split != 1.0:
                    candidates["原口径（未重述）"] = shares
                # **两侧同单位再比**：`implied` 与自报 `roe` 都是百分数。旧键写成
                # `profit / (bps * sh) / roe`（分数 ÷ 百分数），两个候选的键都≈1，`min` 退化成
                # 「恒取隐含 ROE 更大的一侧」，与「取更自洽的一侧」正相反。判例：新易盛 2024-12-31
                # 取重述口径 47.71%（2.20×）报可疑，原口径 24.34%（1.12×）本应放行。
                # 距离取**对数**：阈值是乘性带 [1/2, 2]，对数距离与它同几何，故「取到的一侧超阈」
                # 严格等价于上段所述的「两个口径都超阈值才报」。
                ratios = {k: profit / (bps * s) * 100 / roe for k, s in candidates.items()}
                if all(v > 0 for v in ratios.values()):      # 同号才可比（股本恒正，两侧必同号）
                    basis = min(ratios, key=lambda k: abs(math.log(ratios[k])))
                    sh, ratio = candidates[basis], ratios[basis]
                    implied = profit / (bps * sh) * 100
                    if ratio > ROE_RATIO_WARN or ratio < 1 / ROE_RATIO_WARN:
                        sev = "严重" if (ratio > ROE_RATIO_SEVERE or ratio < 1 / ROE_RATIO_SEVERE) else "可疑"
                        # 另一口径逐条实算，不再无条件断言「亦超阈」
                        other = "".join(
                            f"（{k} 比值 {v:.2f}×，"
                            + ("亦超阈" if (v > ROE_RATIO_WARN or v < 1 / ROE_RATIO_WARN) else "在阈内")
                            + f"；后续送转 {future_split:.2f}）"
                            for k, v in ratios.items() if k != basis)
                        findings.append({
                            "security_code": code, "security_name": name, "period": key,
                            "check": "ROE自洽", "severity": sev,
                            "detail": (f"隐含ROE {implied:.2f}% vs 自报 {roe:.2f}%（比值 {ratio:.2f}×，取自洽侧 {basis}）；"
                                       f"bps={bps:.4f} 归母={profit/1e8:.2f}亿 EPS={eps} "
                                       f"当期股本={sh/1e8:.2f}亿" + other),
                            "suggest_bps": f"{profit / (roe / 100) / sh:.4f}",
                        })

            # ② 股本跳变（扣送转）。同一重述不确定性：折回口径与原口径各比各的，
            # 取更接近 1 的那个——真实增发/注销在两个口径下都会显示为跳变。
            if prev_shares and shares_at_period:
                pairs = [shares_at_period / prev_shares]
                if prev_shares_raw and shares:
                    pairs.append(shares / prev_shares_raw)
                adj = min(pairs, key=lambda x: abs(x - 1) if x > 0 else 9e9)
                if adj > SHARE_JUMP_WARN or adj < 1 / SHARE_JUMP_WARN:
                    findings.append({
                        "security_code": code, "security_name": name, "period": key,
                        "check": "股本跳变", "severity": "可疑",
                        "detail": (f"当期股本 {prev_key} {prev_shares/1e8:.2f}亿 → {key} "
                                   f"{shares_at_period/1e8:.2f}亿（送转重述已折回，剩余 {adj:.2f}×）"),
                        "suggest_bps": "",
                    })

            # ③ bps 连续性（扣送转与分红）
            if prev_bps and bps and prev_bps > 0:
                factor, cash = 1.0, 0.0
                for ex, ratio_k, per_share in actions.get(code, []):
                    if prev_key < ex <= key:
                        factor *= (1 + ratio_k)
                        cash += per_share
                expect = (prev_bps - cash) / factor
                if expect > 0:
                    jump = bps / expect
                    if jump > BPS_JUMP_WARN or jump < 1 / BPS_JUMP_WARN:
                        findings.append({
                            "security_code": code, "security_name": name, "period": key,
                            "check": "bps跳变", "severity": "严重" if (jump > 5 or jump < 0.2) else "可疑",
                            "detail": (f"{prev_key} bps {prev_bps:.4f} →（扣送转{factor:.2f}/分红{cash:.4f}）"
                                       f"期望 {expect:.4f}，实际 {key} bps {bps:.4f}（{jump:.2f}×）"),
                            "suggest_bps": "",
                        })
            if bps:
                prev_bps, prev_key = bps, key
            if shares_at_period:
                prev_shares, prev_shares_raw = shares_at_period, shares

    # ⑤ 实时总股本对照。**定期报告滞后于股本变动**：报告期末之后的发行／回购注销要到下一份
    # 报告才进面板，而带的每股锚走面板。判例：电投能源（002128）2026-06-03 发行 7.1183 亿股
    # 收购白音华煤电、2026-07-17 配套定增 1.7308 亿股，总股本 22.416→31.2648 亿，中报行只到
    # 29.53 亿，实时口径高 5.7%（OI-125）。
    # 只报不改：面板股数取「归母净利 ÷ 基本EPS」＝**加权平均股数**，与实时的**期末时点股数**
    # 本就不同基，期内发行时前者必然偏小，故本项**不判「严重」、不闸住建带链**，只标出
    # 「面板每股口径可能滞后于最新股本」的票，供逐票确认。
    for code, live in sorted(live_shares.items()):
        periods = panel.get(code)
        if not periods:
            continue
        latest = None
        for key in sorted(periods):
            profit, eps = num(periods[key].get("parent_netprofit")), num(periods[key].get("basic_eps"))
            if profit is not None and eps not in (None, 0) and profit * eps > 0 and abs(eps) >= 0.01:
                latest = (key, abs(profit / eps))
        if latest is None:
            continue
        key, panel_shares = latest
        dev = live / panel_shares - 1
        if abs(dev) > SHARE_LIVE_WARN:
            findings.append({
                "security_code": code, "security_name": names.get(code, code), "period": key,
                "check": "实时股本对照", "severity": "可疑",
                "detail": (f"最新面板期 {key} 股数 {panel_shares/1e8:.4f}亿（归母÷EPS，加权平均口径）"
                           f" vs 实时总股本 {live/1e8:.4f}亿（总市值÷现价）＝{dev*100:+.2f}%；"
                           f"实时口径为最新，偏差含「期内发行的加权平均效应」与「报告期后股本变动」两部分，需逐票分辨"),
                "suggest_bps": "",
            })

    # ⑥ 重述后年报行的股本基。同一控制下企业合并（CAS 20）把**比较期**的权益追溯重述，东财随之更新年报行的
    # 归母权益与 `bps`，但 `bps` 的分母仍是**发行前**股本——权益是合并后的、股数是合并前的，混基。
    # 判例：电投能源 FY2025 bps 21.0472 = 471.79 亿（重述后）÷ 22.4157 亿（发行前），应为 ÷29.534 = 15.9744；
    # 中国神华 FY2025 25.7696 = 5120.16 ÷ 198.69，应为 ÷212.3177 = 24.1156。两者都让 `external_equity_intra`
    # 退回 `x_implausible_negative`、外生权益整条失效。
    # 判据：P 行归母权益在取数探针中**实变 ≥ RESTATE_EQUITY_MIN**（重述日志），且 P 之后有占发行前股本
    # ≥ ISSUE_MIN_FRAC 的「增发」事件（非送转），且 `重述后归母权益 ÷ bps` 落在发行前股本上（±3%）。
    # 建议 bps = 归母权益 ÷ 发行后股本（只算首笔合并对价股，配套募集另计）。只报「可疑」——
    # 员工持股、可转债转股等非合并增发也会命中前两条，第三条挡不住时须人工看公告分辨。
    # 只看重述日志里「归母权益实变 ≥ RESTATE_EQUITY_MIN」的年报期——这是取数探针留下的、有前后值对照的记录；
    # 单看 UPDATE_DATE 不行：旧年报行的 UPDATE_DATE 本来就是下一年年报的发布日，恒晚于其间的任何增发。
    stmt_equity: dict[tuple[str, str], tuple[float, str]] = {}
    if args.restatements.exists():
        with args.restatements.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                c = (row.get("security_code") or "").zfill(6)
                if row.get("field") != "TOTAL_PARENT_EQUITY" or (codes is not None and c not in codes):
                    continue
                pct, new = num(row.get("change_pct")), num(row.get("new_value"))
                if pct is not None and new and abs(pct) >= RESTATE_EQUITY_MIN * 100:
                    stmt_equity[(c, (row.get("report_date") or "")[:10])] = (new, (row.get("new_update_date") or "")[:10])
    issues: dict[str, list[dict]] = defaultdict(list)
    if args.share_changes.exists():
        with args.share_changes.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                issues[(row.get("security_code") or "").zfill(6)].append(row)
    corrected = set()
    try:
        from financials_corrections import load_corrections
        corrected = {(c, p) for (c, p), rs in load_corrections().items() if any(r.get("field") == "bps" for r in rs)}
    except Exception:
        pass
    for (code, period), (equity, updated) in sorted(stmt_equity.items()):
        if not period.endswith("-12-31") or (code, period) in corrected:
            continue
        row = (panel.get(code) or {}).get(period)
        bps = num(row.get("bps")) if row else None
        if not bps or bps <= 0:
            continue
        s_bps = equity / bps
        for ev in issues.get(code, []):
            ex = ev.get("effective_date") or ""
            delta, total = num(ev.get("shares_delta")), num(ev.get("total_shares"))
            reason = ev.get("change_reason") or ""
            if not (ex > period and delta and total and delta > 0 and "增发" in reason
                    and not any(x in reason for x in ("转增", "送股"))):
                continue
            pre = total - delta
            if pre <= 0 or delta / pre < ISSUE_MIN_FRAC:
                continue
            if abs(s_bps / pre - 1) <= 0.03:
                findings.append({
                    "security_code": code, "security_name": names.get(code, code), "period": period,
                    "check": "重述年报股本基", "severity": "可疑",
                    "detail": (f"{period} 归母权益 {equity/1e8:.2f}亿 ÷ bps {bps:.4f} = {s_bps/1e8:.4f}亿股，落在发行前股本 "
                               f"{pre/1e8:.4f}亿上；其后 {ex} {reason} +{delta/1e8:.4f}亿（{delta/pre:.1%}）→ {total/1e8:.4f}亿，"
                               f"且该年报行归母权益已在取数探针中实变（UPDATE_DATE {updated}）——疑似同一控制下合并追溯重述而 bps 未换基。"
                               f"须核对公告：若为合并对价股，建议 bps={equity/total:.4f}（÷发行后股本）并登记订正层"),
                    "suggest_bps": f"{equity/total:.4f}",
                })
            break

    # ---- 检查⑦「股本事件复核」（OI-129）：非送转的股本单次变动 ≥ ISSUE_MIN_FRAC 是主体重置的候选触发。
    # 只报「可疑」——现金增发、员工持股不改主体，发股收购／资产注入／吸收合并才需登记
    # `entity_reset_dates.csv`；复核结论（reset／no_reset）登记 `share_event_reviews.csv` 后不再报出。
    reviewed: set[tuple[str, str]] = set()
    if args.share_event_reviews.exists():
        with args.share_event_reviews.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                reviewed.add(((row.get("security_code") or "").zfill(6), (row.get("effective_date") or "")[:10]))
    resets: dict[str, str] = {}
    try:
        from roic_inputs import load_entity_reset
        resets = {c: r["reset"] for c, r in load_entity_reset().items()}
    except Exception:
        pass
    lookback = (date.fromisoformat(args.as_of) - timedelta(days=SHARE_EVENT_LOOKBACK_DAYS)).isoformat()
    for code in sorted(issues):
        if codes is not None and code not in codes:
            continue
        for ev in issues[code]:
            ex = (ev.get("effective_date") or "")[:10]
            reason = ev.get("change_reason") or ""
            delta, total = num(ev.get("shares_delta")), num(ev.get("total_shares"))
            if not (lookback <= ex <= args.as_of) or (code, ex) in reviewed or not delta or not total:
                continue
            if any(k in reason for k in SHARE_EVENT_SKIP):
                continue
            pre = total - delta
            if pre <= 0 or abs(delta) / pre < ISSUE_MIN_FRAC:
                continue
            # 事件表把送转记成「其他变动原因」时（比亚迪 2025-06-10 10 转 8）：除权表里 ±10 天内有同倍数送转即跳过
            if delta > 0 and any(abs((date.fromisoformat(ex) - date.fromisoformat(ax)).days) <= 10 and ratio > 0
                                 and delta / pre <= ratio * 1.02
                                 for ax, ratio, _ in actions.get(code, []) if len(ax) == 10):
                continue
            reset = resets.get(code)
            findings.append({
                "security_code": code, "security_name": names.get(code, ev.get("security_name") or code), "period": ex,
                "check": "股本事件复核", "severity": "可疑",
                "detail": (f"{ex} {reason}：{pre/1e8:.4f}亿 → {total/1e8:.4f}亿股（{delta/pre:+.1%}），"
                           f"未在 share_event_reviews.csv 登记复核"
                           + (f"；主体重置名册已有 reset_report_date {reset}" if reset else "；主体重置名册无此代码")
                           + f"。发股收购／资产注入／吸收合并等改变主体者：登记 entity_reset_dates.csv"
                             f"（建议 reset_report_date {ex[:4]}-12-31、known_from 取重述后首份定期报告的可得日）并在复核表记 reset；"
                             f"现金增发／员工持股等不改主体者记 no_reset"),
                "suggest_bps": "",
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["security_code", "security_name", "period", "check", "severity", "detail", "suggest_bps"]
    order = {"严重": 0, "可疑": 1}
    findings.sort(key=lambda f: (order.get(f["severity"], 9), f["security_name"], f["period"]))
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(findings)

    scope = "全市场" if args.all_market else f"核心池 {len(panel)} 只"
    severe = [f for f in findings if f["severity"] == "严重"]
    print(f"财务面板自洽核对 as-of {args.as_of}｜范围 {scope}｜每只回看 {args.periods} 期")
    print(f"  异常 {len(findings)} 条（严重 {len(severe)}｜可疑 {len(findings) - len(severe)}）→ {args.out}")
    by_check: dict[str, int] = defaultdict(int)
    for f in findings:
        by_check[f["check"]] += 1
    for k, v in sorted(by_check.items(), key=lambda x: -x[1]):
        print(f"    {k}: {v} 条")
    if severe:
        print("\n  === 严重（倍数级失真，会直接改变估值带）===")
        for f in severe:
            print(f"  · {f['security_name']}（{f['security_code']}）{f['period']} {f['check']}：{f['detail']}"
                  + (f"\n      建议 bps ≈ {f['suggest_bps']}" if f["suggest_bps"] else ""))
    print("\n  **本脚本不改数**。修复须逐条确认来源（重取该期财务或人工订正）后再动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
