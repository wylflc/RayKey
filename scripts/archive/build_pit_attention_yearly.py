#!/usr/bin/env python3
"""逐年时点 worth_attention 名单（OI-034 第 6 步，用户 2026-08-08 指令「每年做一版」）。

与三期版（§12.9.11/12）的区别
-----------------------------
三期版每五年**整体重筛**，实测反而使年化降低 3.1pp（§12.9.12）——因为候选门槛
在周期低谷把好公司剔出去（2015 剔三一/潍柴、2020 剔东阿阿胶/云南白药/宇通），
**机械地低卖高买**。§5 本身不这么做：它问的是「护城河扛住了吗」，不是「ROE 还高吗」。

本版改为**区间制**，与真实的关注名单行为一致：

* **进池年**：首次出现护城河财务签名的那一年（四条并联门槛，见 §12.9.13）。
  这是可复现的——只用当年已披露的年报。
* **留池**：进了就留着，**不因周期低谷而剔除**。
* **出池**：只有被逐家判定「护城河已破」才移出，出池年由 `verdicts_exit.csv` 给出。

名单构成
--------
`worth(Y) = {今日 261 只中进池年 ≤ Y 的} ∪ {Set B 中区间覆盖 Y 的}`

第一项合法：今日名单里的公司若其护城河在 Y 年已可见，当年做 §5 就会选中它。
**第二项才是去偏差的关键**——当年够格、后来护城河丢失因而不在今日名单的公司
（张裕A、苏宁电器、海螺水泥、用友网络、航天信息、上海家化、老板电器、晨光股份、
古井贡酒、中公教育、中国中免……）。Set B 若枚举不足，偏差会被低估。

门槛（四条并联，任一命中即入，§12.9.13 校准至对今日名单召回 87%）::

    ①近5年均ROE≥15% 且最低≥8% 且营收≥10亿   —— 已兑现超额回报
    ②毛利率≥40% 且营收≥5亿                  —— 定价权签名（品类垄断/老字号）
    ③营收≥100亿                            —— 规模签名（资源/规制/资本周期型）
    ④近5年均ROE≥10% 且营收≥30亿             —— 中等回报+规模

用法::

    python3 scripts/build_pit_attention_yearly.py
    python3 scripts/build_pit_attention_yearly.py --from 2010 --to 2025
"""
from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIN = ROOT / "data/raw/financials"
OHLCV = ROOT / "data/raw/ohlcv"
TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
PIT = ROOT / "data/processed/pit_attention"
SETB = PIT / "setb_intervals.csv"          # 人工判定：当年够格、后来护城河丢失
OVERRIDE = PIT / "entry_overrides.csv"     # 人工判定：财务签名早于/晚于护城河成型
OUT = PIT / "universe_wa_yearly.csv"

FIELDS = ["effective_from", "effective_to", "screen_year", "security_code",
          "security_name", "avg_roe_3y", "rank"]


def _num(text):
    try:
        return float((text or "").strip())
    except (TypeError, ValueError):
        return None


def is_a_share(code: str) -> bool:
    return code[:1] in ("0", "3", "6") and code[:2] not in ("43", "83", "87", "88", "92")


def load_annuals():
    out = defaultdict(dict)
    for path in sorted(FIN.glob("*-12-31.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if (row.get("notice_date") or "").strip() and is_a_share(row["security_code"]):
                    out[row["security_code"]][row["report_date"][:4]] = row
    return out


def first_traded():
    out = {}
    for path in sorted(OHLCV.glob("*.csv")):
        if path.stem.startswith("INDEX_"):
            continue
        with path.open(encoding="utf-8") as handle:
            handle.readline()
            line = handle.readline()
            if line:
                out[path.stem] = line.split(",", 1)[0]
    return out


def profile(rows, year: int, window: int = 5):
    """截至 `year` 的财务画像；**只用上市之后的年报**（§12.9.10 的上市前报表坑）。"""
    vals = []
    for y in [str(x) for x in range(year - window + 1, year + 1)]:
        row = rows.get(y)
        if row is None:
            continue
        roe, profit = _num(row.get("weightavg_roe")), _num(row.get("parent_netprofit"))
        revenue, gross = _num(row.get("total_operate_income")), _num(row.get("gross_margin"))
        if roe is None or profit is None:
            continue
        vals.append((roe / 100.0, profit, (revenue or 0) / 1e8, (gross or 0) / 100.0))
    if len(vals) < 3:
        return None
    return {"roe": statistics.fmean(v[0] for v in vals), "roemin": min(v[0] for v in vals),
            "profit": vals[-1][1], "revenue": vals[-1][2], "gross": vals[-1][3]}


def signature(p) -> bool:
    """四条并联的护城河财务签名。**这不是 §5**——它只决定何时值得判，见文件头。"""
    if p is None or p["profit"] <= 0:
        return False
    return ((p["roe"] >= 0.15 and p["roemin"] >= 0.08 and p["revenue"] >= 10)
            or (p["gross"] >= 0.40 and p["revenue"] >= 5)
            or p["revenue"] >= 100
            or (p["roe"] >= 0.10 and p["revenue"] >= 30))


def load_manual(path: Path, key_fields):
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {r["security_code"]: r for r in csv.DictReader(handle)}


def main() -> int:
    ap = argparse.ArgumentParser(description="逐年时点 worth_attention 名单")
    ap.add_argument("--from", dest="y0", type=int, default=2009, help="第一个筛选财年")
    ap.add_argument("--to", dest="y1", type=int, default=2025)
    ap.add_argument("--window", type=int, default=5)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    annuals, listed = load_annuals(), first_traded()
    pool = {r["security_code"]: r["security_name"]
            for r in csv.DictReader(TIERS.open(encoding="utf-8"))}
    setb = load_manual(SETB, None)
    override = load_manual(OVERRIDE, None)

    # ---- Set A：今日 261 只的进池年 = 首次出现签名的年份（须已上市）
    entry = {}
    for code in pool:
        rows = annuals.get(code, {})
        day = listed.get(code)
        for year in range(args.y0, args.y1 + 1):
            if day is None or day > f"{year}-12-31":
                continue
            if signature(profile(rows, year, args.window)):
                entry[code] = year
                break
    for code, row in override.items():
        if code in pool:
            entry[code] = int(row["entry_year"])

    # ---- 逐年名单
    rows_out, history = [], []
    for year in range(args.y0, args.y1 + 1):
        members = {c: pool[c] for c, y in entry.items() if y <= year}
        for code, row in setb.items():
            if int(row["entry_year"]) <= year <= int(row["exit_year"]):
                members[code] = row["security_name"]
        eff_from, eff_to = f"{year + 1}-05-01", f"{year + 2}-04-30"
        for code, name in sorted(members.items()):
            rows_out.append({"effective_from": eff_from, "effective_to": eff_to,
                             "screen_year": year, "security_code": code,
                             "security_name": name, "avg_roe_3y": "", "rank": ""})
        nb = sum(1 for c in members if c not in pool)
        history.append((year, len(members), len(members) - nb, nb))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows_out)

    print("逐年时点 worth_attention 名单（区间制：进池按首次签名年，留池不因低谷剔除）")
    print(f'{"筛选年":<8}{"名单":>7}{"今日在池":>9}{"SetB":>7}{"生效自":>13}')
    print("-" * 46)
    for year, total, a, b in history:
        print(f"{year:<8}{total:>7}{a:>9}{b:>7}{year + 1:>9}-05-01")
    print(f"\n今日 261 只中定出进池年的 {len(entry)} 只｜Set B {len(setb)} 只")
    print(f"{args.out}｜{len(rows_out):,} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
