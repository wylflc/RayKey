#!/usr/bin/env python3
"""OI-159：美股逐次申报的时点估值 → 逐日状态（与 `a_share_daily_states_adopted.csv` 同列）。

预登记：`docs/reports/us_sp500_backtest_prereg.zh.md` §3。
估值 = `build_overseas_roic_bands.value_company`（§6.8／§6.5.2.3 同式，全部 L2，r = rf + ERP，rf 取 FRED DGS10 在申报日前最新值）；
事实按 `filed ≤ F` 截断（`overseas_pv_forward.PitFacts`），F 取 companyfacts 里 10-K／10-Q（含 /A、20-F、40-F）的申报日。

带与逐日规则：
  * `band_available_at = F`；生效日 E = F 之前最后一个交易日（A 股 `--state-effective prev_trading_day` 同式）。
  * V 的股本口径：`value_company` 按最新报告期稀释股数折每股；报告期末之后、E 之前的拆股按比例折 V，
    但若申报已按拆股追溯重述股数（ASC 260：本期股数 ÷ 上次申报同期股数 ≈ 拆股比 ±20%）则不再折（逐条登记）。
  * 逐日：取 E ≤ 当日 的最新带（按报告期）；E 之后的事件按 §11.4 逐条施加：现金红利 `V − D`、拆股 `V ÷ r`；
    带被拒（无法估值）时该段无行（与 A 股薄权益守卫「无 P/V」同）。
  * `P/V = 未复权收盘 ÷ V`。

输出：
  data/processed/us_daily_states_adopted.csv                  逐日状态（候选侧；第一期持仓侧同文件）
  data/experiments/exp_us_sp500_port/us_valuation_bands.csv   逐 CIK 逐申报：状态、原因、V、报告期、rf、拆股处置
  data/experiments/exp_us_sp500_port/valuation_coverage.csv   逐年：有价成员·日中有 P/V 的占比与拒绝原因分布
用法：
    python3 scripts/build_us_daily_states.py [--workers 16] [--only CIK,CIK] [--since 2009-06-01]
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/experimental"))
import build_overseas_roic_bands as bor  # noqa: E402
import fetch_overseas_statements as fos  # noqa: E402
from overseas_pv_forward import PitFacts  # noqa: E402

EXP = ROOT / "data/experiments/exp_us_sp500_port"
SEC = EXP / "raw/sec"
MEMBERS = ROOT / "data/processed/us_sp500_members.csv"
OHLCV = ROOT / "data/raw/ohlcv_us"
ACTIONS = ROOT / "data/raw/corporate_actions/us_corporate_actions.csv"
RATES = ROOT / "data/reference/cost_of_equity_inputs_us.csv"
INPUTS = ROOT / "data/reference/overseas_valuation_inputs.csv"
STATES_OUT = ROOT / "data/processed/us_daily_states_adopted.csv"
BANDS_OUT = EXP / "us_valuation_bands.csv"
COVER_OUT = EXP / "valuation_coverage.csv"
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"}
STATE_FIELDS = ["security_code", "date", "close", "band_report_date", "band_available_at", "split_factor", "cash_adjustment",
                "intrinsic_value", "band_low", "band_high", "valuation_ratio", "upside_to_low", "valuation_label", "ev_ps", "pv_equity"]
BAND_FIELDS = ["cik", "filed", "effective", "status", "reason", "value", "period", "rf", "shares", "split_adj", "split_note"]
XBRL_FROM = "2009-06-01"


def label(ratio: float) -> str:
    if ratio <= 0.8:
        return "较大安全边际"
    if ratio <= 1.0:
        return "偏低估"
    if ratio <= 1.2:
        return "接近合理价值"
    return "需更乐观假设才支撑"


def load_rates() -> tuple[list[str], list[float]]:
    rows = sorted((r["observed_on"], float(r["risk_free_rate"])) for r in csv.DictReader(RATES.open(encoding="utf-8")))
    return [d for d, _ in rows], [v for _, v in rows]


def rf_at(dates: list[str], vals: list[float], t: str) -> float | None:
    i = bisect.bisect_right(dates, t) - 1
    return vals[i] if i >= 0 else None


def load_actions() -> dict[str, list[tuple[str, float, float]]]:
    """{cik: [(日, 现金, 拆股比)]}，按日升序。"""
    out: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    if not ACTIONS.exists():
        return out
    for r in csv.DictReader(ACTIONS.open(encoding="utf-8")):
        cash = float(r["cash_per_share"] or 0)
        ratio = 1.0 + float(r["share_ratio"] or 0)
        out[r["security_code"]].append((r["ex_dividend_date"], cash, ratio))
    for k in out:
        out[k].sort()
    return out


def filing_dates(facts: dict, since: str) -> list[str]:
    seen: set[str] = set()
    for tax in facts.values():
        for node in tax.values():
            for es in (node.get("units") or {}).values():
                for e in es:
                    f = e.get("filed") or ""
                    if e.get("form") in FORMS and f >= since:
                        seen.add(f)
    return sorted(seen)


def worker(job: dict) -> tuple[list[dict], list[dict]]:
    cik, since, erp, rf_dates, rf_vals, actions = job["cik"], job["since"], job["erp"], job["rf_dates"], job["rf_vals"], job["actions"]
    bands: list[dict] = []
    rows: list[dict] = []
    fp = SEC / f"CIK{cik}.json"
    pp = OHLCV / f"{cik}.csv"
    if not fp.exists() or not pp.exists():
        bands.append(dict(cik=cik, filed="", effective="", status="no_facts" if not fp.exists() else "no_price", reason="", value="",
                          period="", rf="", shares="", split_adj="", split_note=""))
        return rows, bands
    prices = [(r["date"], float(r["close"])) for r in csv.DictReader(pp.open(encoding="utf-8"))]
    pdates = [d for d, _ in prices]
    if not pdates:
        return rows, bands
    facts = json.loads(fp.read_text(encoding="utf-8")).get("facts", {})
    pit = PitFacts(facts)
    maps = fos.IFRS if pit.tax_name == "ifrs-full" else fos.GAAP
    dei_all = ((facts.get("dei") or {}).get("EntityCommonStockSharesOutstanding") or {}).get("units", {}).get("shares", [])

    def dei_at(t: str) -> dict:
        return {"EntityCommonStockSharesOutstanding": {"units": {"shares": [e for e in dei_all if str(e.get("filed") or "") <= t]}}}
    filings = [f for f in filing_dates(facts, since) if f <= pdates[-1]]
    events = actions.get(cik, [])
    ev_dates = [d for d, _, _ in events]

    def prev_trading_day(f: str) -> str | None:
        i = bisect.bisect_left(pdates, f) - 1
        return pdates[i] if i >= 0 else None

    band_list: list[tuple[str, str, str, float | None]] = []      # (effective, filed, period, V at E caliber or None)
    prev_shares: float | None = None
    for f in filings:
        eff = prev_trading_day(f)
        rec = dict(cik=cik, filed=f, effective=eff or "", status="", reason="", value="", period="", rf="", shares="", split_adj="", split_note="")
        if eff is None:
            rec["status"], rec["reason"] = "no_price", "申报日前无行情"
            bands.append(rec); continue
        tax = pit.at(f)
        dei = dei_at(f)
        annuals = fos.sec_extract(cik, cik, {"facts": {pit.tax_name: tax, "dei": dei}})
        if not annuals:
            rec["status"], rec["reason"] = "no_annual", "无 filed≤F 的年报行"
            bands.append(rec); band_list.append((eff, f, "", None)); continue
        current = fos.sec_current_extract(cik, cik, tax, maps, annuals, dei=dei)
        years = [bor.year_from_row(r) for r in annuals]
        cur = bor.year_from_row(current) if current else None
        rf = rf_at(rf_dates, rf_vals, f)
        rec["rf"] = f"{rf:.4f}" if rf is not None else ""
        if rf is None:
            rec["status"], rec["reason"] = "no_rf", ""
            bands.append(rec); band_list.append((eff, f, "", None)); continue
        latest = cur if (cur and cur.period > years[-1].period) else years[-1]
        rec["period"] = latest.period
        shares_now = getattr(latest, "shares", None)
        rec["shares"] = f"{shares_now:.0f}" if shares_now else ""
        try:
            res = bor.value_company(cik, "L2", years, {"rf_usd": rf, "erp_us": erp}, cur)
        except Exception as exc:  # noqa: BLE001
            rec["status"], rec["reason"] = "error", str(exc)[:80]
            bands.append(rec); band_list.append((eff, f, latest.period, None)); prev_shares = shares_now or prev_shares; continue
        if res.get("status") != "ok":
            rec["status"], rec["reason"] = "rejected", str(res.get("reason", ""))[:80]
            bands.append(rec); band_list.append((eff, f, latest.period, None)); prev_shares = shares_now or prev_shares; continue
        value = float(res["value"])
        # 报告期末之后、E 之前的拆股：股数已追溯重述则不折
        factor = 1.0
        notes = []
        for d, cash, ratio in events:
            if latest.period < d <= eff and abs(ratio - 1.0) > 1e-6:
                restated = bool(prev_shares and shares_now and abs((shares_now / prev_shares) / ratio - 1.0) <= 0.20)
                notes.append(f"{d}:{ratio:g}:{'restated' if restated else 'applied'}")
                if not restated:
                    factor *= ratio
        value /= factor
        rec.update(status="ok", value=f"{value:.4f}", split_adj=f"{factor:.6f}", split_note=";".join(notes))
        bands.append(rec)
        band_list.append((eff, f, latest.period, value))
        prev_shares = shares_now or prev_shares

    if not band_list:
        return rows, bands
    # 逐日：最新生效带；带后事件逐条施加
    band_list.sort()
    b_eff = [b[0] for b in band_list]
    j = -1
    v_cur: float | None = None
    split_f = 1.0
    cash_adj = 0.0
    ev_i = 0
    for d, close in prices:
        k = bisect.bisect_right(b_eff, d) - 1
        if k < 0:
            continue
        if k != j:
            j = k
            eff, filed, period, v0 = band_list[j]
            v_cur, split_f, cash_adj = v0, 1.0, 0.0
            ev_i = bisect.bisect_right(ev_dates, eff)     # 事件日 > E 才施加
        while ev_i < len(events) and events[ev_i][0] <= d:
            _, cash, ratio = events[ev_i]
            ev_i += 1
            if v_cur is None:
                continue
            if cash:
                v_cur -= cash; cash_adj += cash
            if abs(ratio - 1.0) > 1e-6:
                v_cur /= ratio; split_f *= ratio; cash_adj /= ratio
        if v_cur is None or v_cur <= 0:
            continue
        ratio_pv = close / v_cur
        eff, filed, period, _ = band_list[j]
        rows.append({"security_code": cik, "date": d, "close": f"{close:.4f}", "band_report_date": period, "band_available_at": filed,
                     "split_factor": f"{split_f:.6f}", "cash_adjustment": f"{cash_adj:.4f}", "intrinsic_value": f"{v_cur:.4f}",
                     "band_low": f"{v_cur:.4f}", "band_high": f"{v_cur:.4f}", "valuation_ratio": f"{ratio_pv:.4f}",
                     "upside_to_low": f"{v_cur / close - 1:.4f}", "valuation_label": label(ratio_pv), "ev_ps": "", "pv_equity": f"{ratio_pv:.4f}"})
    return rows, bands


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--only", default="")
    ap.add_argument("--since", default=XBRL_FROM)
    ap.add_argument("--out", type=Path, default=STATES_OUT)
    args = ap.parse_args()
    members = [r for r in csv.DictReader(MEMBERS.open(encoding="utf-8")) if r["cik"] and r["status"] in ("ok", "ok_sic_missing")]
    ciks = sorted({r["cik"] for r in members})
    if args.only:
        only = set(args.only.split(","))
        ciks = [c for c in ciks if c in only]
    erp = next(float(r["value"]) for r in csv.DictReader(INPUTS.open(encoding="utf-8")) if r["key"] == "erp_us")
    rf_dates, rf_vals = load_rates()
    actions = load_actions()
    jobs = [dict(cik=c, since=args.since, erp=erp, rf_dates=rf_dates, rf_vals=rf_vals, actions={c: actions.get(c, [])}) for c in ciks]
    print(f"逐次申报估值：{len(jobs)} 家（ERP {erp:.4f}，rf {rf_dates[0]}～{rf_dates[-1]}），{args.workers} 并发", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    BANDS_OUT.parent.mkdir(parents=True, exist_ok=True)
    n_rows = 0
    status: Counter = Counter()
    with args.out.open("w", newline="", encoding="utf-8") as fs, BANDS_OUT.open("w", newline="", encoding="utf-8") as fb:
        ws = csv.DictWriter(fs, fieldnames=STATE_FIELDS, lineterminator="\n"); ws.writeheader()
        wb = csv.DictWriter(fb, fieldnames=BAND_FIELDS, lineterminator="\n"); wb.writeheader()
        it = Pool(args.workers).imap_unordered(worker, jobs) if args.workers > 1 else map(worker, jobs)
        for i, (rows, bands) in enumerate(it, 1):
            ws.writerows(rows); wb.writerows(bands); n_rows += len(rows)
            for b in bands:
                status[b["status"]] += 1
            if i % 50 == 0:
                print(f"  {i}/{len(jobs)}，累计 {n_rows} 行", flush=True)
    print(f"逐日状态 {n_rows} 行 → {args.out}；带状态 {dict(status)} → {BANDS_OUT}")

    # 覆盖：逐年，成员段内有价交易日中有 P/V 的占比
    seg_by_cik: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in members:
        seg_by_cik[r["cik"]].append((r["from"], r["to"] or "9999-12-31"))
    have: dict[str, set[str]] = defaultdict(set)
    with args.out.open(encoding="utf-8") as fh:
        rd = csv.reader(fh); h = next(rd); ic, idt = h.index("security_code"), h.index("date")
        for row in rd:
            have[row[ic]].add(row[idt])
    tot: Counter = Counter(); ok: Counter = Counter()
    for c in ciks:
        pp = OHLCV / f"{c}.csv"
        if not pp.exists():
            continue
        for r in csv.DictReader(pp.open(encoding="utf-8")):
            d = r["date"]
            if d < "2012-05-01" or not any(a <= d <= b for a, b in seg_by_cik[c]):
                continue
            tot[d[:4]] += 1
            if d in have[c]:
                ok[d[:4]] += 1
    reasons: Counter = Counter()
    for b in csv.DictReader(BANDS_OUT.open(encoding="utf-8")):
        if b["status"] == "rejected":
            reasons[b["reason"][:30]] += 1
    with COVER_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n"); w.writerow(["year", "member_price_days", "with_pv_days", "share"])
        for y in sorted(tot):
            w.writerow([y, tot[y], ok[y], f"{ok[y] / tot[y]:.3f}"])
        w.writerow([]); w.writerow(["rejected_reason", "count"])
        for k, v in reasons.most_common():
            w.writerow([k, v])
    print("逐年有 P/V 占比：" + "，".join(f"{y} {ok[y] / tot[y]:.0%}" for y in sorted(tot)))
    print("拒绝原因：" + "；".join(f"{k} {v}" for k, v in reasons.most_common(6)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
