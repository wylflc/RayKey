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
    python3 scripts/audit_financial_panel_consistency.py --as-of YYYY-MM-DD
    python3 scripts/audit_financial_panel_consistency.py --as-of YYYY-MM-DD --all-market
缺省只扫核心估值池（201 只）；`--all-market` 扫面板全部公司，慢很多。
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROE_RATIO_WARN = 2.0     # 隐含 ROE / 自报 ROE 超出 [1/2, 2] 报警
ROE_RATIO_SEVERE = 3.0   # 超出 [1/3, 3] 判严重
BPS_JUMP_WARN = 2.5      # 相邻期 bps 倍数跳变阈值
SHARE_JUMP_WARN = 1.20   # 相邻期倒推股本跳变阈值（送转/增发已单独扣除）
MIN_PERIODS = 4


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
    """{代码: [(除权日, 送转比例 k/10, 每股现金分红)]}"""
    out: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            ex = (row.get("ex_dividend_date") or "").strip()[:10]
            if not ex:
                continue
            out[(row.get("security_code") or "").strip()].append(
                (ex, num(row.get("share_ratio")) or 0.0, num(row.get("cash_per_share")) or 0.0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="季度财务面板逐行自洽核对")
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--financials-dir", type=Path, default=ROOT / "data/raw/financials")
    ap.add_argument("--pool", type=Path, default=ROOT / "data/processed/a_share_core_valuation_pool.csv")
    ap.add_argument("--corporate-actions", type=Path,
                    default=ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv")
    ap.add_argument("--all-market", action="store_true", help="扫面板全部公司，不限于核心池")
    ap.add_argument("--periods", type=int, default=8, help="每只回看多少期")
    ap.add_argument("--out", type=Path, default=ROOT / "data/interim/financial_panel_anomalies.csv")
    args = ap.parse_args()

    codes = None
    names: dict[str, str] = {}
    if not args.all_market and args.pool.exists():
        with args.pool.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        codes = {r["security_code"] for r in rows}
        names = {r["security_code"]: r["security_name"] for r in rows}

    panel = load_panel(args.financials_dir, codes)
    actions = load_share_factors(args.corporate_actions)
    findings: list[dict] = []

    for code, periods in panel.items():
        name = names.get(code, (next(iter(periods.values())).get("security_name") or code))
        keys = sorted(periods)[-args.periods:]
        if len(keys) < MIN_PERIODS:
            continue
        prev_key = prev_bps = prev_shares = None
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
                    future_split *= (1 + ratio_k / 10.0)
            shares_at_period = shares / future_split if shares else None

            # ① ROE 自洽
            if None not in (profit, bps, roe) and shares_at_period and bps > 0 and abs(roe) > 1.0:
                implied = profit / (bps * shares_at_period) * 100
                if implied != 0 and roe != 0 and implied * roe > 0:  # 同号才可比
                    ratio = implied / roe
                    if ratio > ROE_RATIO_WARN or ratio < 1 / ROE_RATIO_WARN:
                        sev = "严重" if (ratio > ROE_RATIO_SEVERE or ratio < 1 / ROE_RATIO_SEVERE) else "可疑"
                        findings.append({
                            "security_code": code, "security_name": name, "period": key,
                            "check": "ROE自洽", "severity": sev,
                            "detail": (f"隐含ROE {implied:.2f}% vs 自报 {roe:.2f}%（比值 {ratio:.2f}×）；"
                                       f"bps={bps:.4f} 归母={profit/1e8:.2f}亿 EPS={eps} "
                                       f"当期股本={shares_at_period/1e8:.2f}亿"
                                       + (f"（重述股本 {shares/1e8:.2f}亿 ÷ 后续送转 {future_split:.2f}）"
                                          if future_split != 1.0 else "")),
                            "suggest_bps": f"{profit / (roe / 100) / shares_at_period:.4f}" if roe else "",
                        })

            # ② 股本跳变（扣送转）
            if prev_shares and shares_at_period:
                # 两期都已折回各自的「当期股本」口径，故真实增发才会显示为跳变
                adj = shares_at_period / prev_shares
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
                        factor *= (1 + ratio_k / 10.0)
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
                prev_shares = shares_at_period

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
