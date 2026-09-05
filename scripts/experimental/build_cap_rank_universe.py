#!/usr/bin/env python3
"""实验 A（无选股）：按**时点总市值排名**构造指数类股票库，格式与 `panel_moat_bank_v6b.csv` 相同。

为什么不用真实成分股
--------------------
沪深 300／中证 500／中证 1000 的**历史**成分股（含纳入/剔除日）没有免密钥、可稳定访问的来源
（中证官网 Excel 403、legulegu 400、akshare 1.14 已无 `index_stock_hist`）；只有**当前**成分股可得，
而"当前成分股 + 纳入日期"是幸存者名单（被剔除、退市的名字全不在），只能作偏高的参照。
指数本身按自由流通市值排名、半年调整，故这里用**总市值排名代理**：

* 排名日 R = 每年 6/12 月最后一个交易日（指数调样生效日附近）；新档自 R 的下一交易日生效，
  到下一个 R 当日为止（`effective_to` 含当日），最后一档开放。
* 总市值 = R 日收盘 × 股本；股本 = 最新一期（公告日 ≤ R）财报的 `归母净利润 ÷ 基本 EPS`
  （无股本字段；实测与东财总股本差 ±5% 以内，排序代理足够；`|EPS| < 0.005` 或净利润为 0 的期跳过）。
* 入选资格：R 日前 10 个自然日内有收盘（剔长期停牌）；上市满 250 个交易日；有股本。
  **不剔 ST**（无历史 ST 状态数据），与真实指数的差异之一。
* 数据含已退市股票（`data/raw/ohlcv/` 5,545 只 + 退市名册），**无幸存者偏差**；
  早年（2005 前后）覆盖面随上市公司数自然变小。

产出（`--out-dir`）
------------------
* `cap_top300.csv`     排名 1~300（≈沪深 300）
* `cap_301_800.csv`    排名 301~800（≈中证 500）
* `cap_801_1800.csv`   排名 801~1800（≈中证 1000）
* `cap_all.csv`        全部合格股票（"无选股"本义）
* `*_s<pct>[_<salt>].csv`  上述带的**哈希抽样子集**：`md5(salt+code) % 100 < pct` 的成员才入档。
  抽样是**按代码持久**的——同一只股票只要在带内就一直在子集里，故子集的历年并集≈带并集 × pct，
  用来把回测引擎的内存压进 8 GB（实测每只并集代码约 3.3 MB，详见实验文档）。
* `membership_stats.csv`  每档人数、换手率（相对上一档）。

用法：
    python3 scripts/experimental/build_cap_rank_universe.py --out-dir data/experiments/universes
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OHLCV = ROOT / "data/raw/ohlcv"
FIN = ROOT / "data/raw/financials"
SECURITIES = ROOT / "data/raw/a_share_securities.csv"
DELISTED = ROOT / "data/raw/a_share_delisted_roster.csv"
CALENDAR = OHLCV / "INDEX_000001.csv"

BANDS = {"cap_top300": (1, 300), "cap_301_800": (301, 800), "cap_801_1800": (801, 1800), "cap_all": (1, 10 ** 9)}
FIELDS = ["effective_from", "effective_to", "screen_year", "security_code", "security_name",
          "mcap_rank", "mcap_yi", "close", "shares_yi"]


def trading_days() -> list[str]:
    with CALENDAR.open(newline="", encoding="utf-8") as fh:
        return sorted(r["date"] for r in csv.DictReader(fh) if r.get("date"))


def rebalance_dates(days: list[str], first_year: int, last_day: str) -> list[str]:
    """每年 6/12 月最后一个交易日（≤ 当年 06-30 / 12-31 的最后一个交易日）。"""
    out = []
    for year in range(first_year, int(last_day[:4]) + 1):
        for md in ("06-30", "12-31"):
            target = f"{year}-{md}"
            if target > last_day:
                continue
            i = bisect.bisect_right(days, target) - 1
            if i >= 0:
                out.append(days[i])
    return out


def load_names() -> dict[str, str]:
    names: dict[str, str] = {}
    if DELISTED.exists():
        with DELISTED.open(newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                names[r["security_code"].zfill(6)] = r.get("official_name") or ""
    if SECURITIES.exists():
        with SECURITIES.open(newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                names[r["security_code"].zfill(6)] = r.get("security_name") or names.get(r["security_code"].zfill(6), "")
    return names


def load_shares() -> dict[str, list[tuple[str, float]]]:
    """{代码: [(公告日, 股本/亿股), …] 按公告日升序}。股本 = 归母净利润 ÷ 基本 EPS。"""
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for path in sorted(FIN.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    np_ = float(r["parent_netprofit"]); eps = float(r["basic_eps"])
                except (KeyError, TypeError, ValueError):
                    continue
                notice = (r.get("notice_date") or "").strip()
                if not notice or np_ == 0 or abs(eps) < 0.005:
                    continue
                shares = np_ / eps / 1e8
                if shares <= 0 or shares > 5000:          # 亿股；工行 3,564 亿为上限量级
                    continue
                out[r["security_code"].zfill(6)].append((notice, shares))
    for code in out:
        out[code].sort()
    return out


def shares_on(history: list[tuple[str, float]], day: str) -> float | None:
    i = bisect.bisect_right(history, (day, float("inf"))) - 1
    return history[i][1] if i >= 0 else None


def scan_prices(rebalances: list[str], min_age: int, grace_days: int):
    """逐票一遍：每个排名日的（最近收盘, 上市交易日数）。"""
    result: dict[str, dict[str, tuple[float, int]]] = {}
    lower = {r: (date.fromisoformat(r) - timedelta(days=grace_days)).isoformat() for r in rebalances}
    for path in sorted(OHLCV.glob("*.csv")):
        code = path.stem
        if not code.isdigit():
            continue
        rows: list[tuple[str, float]] = []
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if not header:
                continue
            i_d, i_c = header.index("date"), header.index("close")
            for row in reader:
                try:
                    c = float(row[i_c])
                except (ValueError, IndexError):
                    continue
                if c > 0:
                    rows.append((row[i_d], c))
        if not rows:
            continue
        rows.sort()
        dates = [d for d, _ in rows]
        per: dict[str, tuple[float, int]] = {}
        for r in rebalances:
            k = bisect.bisect_right(dates, r)          # 交易日数（≤ R）
            if k < min_age:
                continue
            d, c = rows[k - 1]
            if d < lower[r]:
                continue
            per[r] = (c, k)
        if per:
            result[code] = per
    return result


def sampled(code: str, pct: int, salt: str) -> bool:
    h = hashlib.md5(f"{salt}{code}".encode()).hexdigest()
    return int(h[:8], 16) % 100 < pct


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "data/experiments/universes")
    ap.add_argument("--first-year", type=int, default=2004, help="首个排名年（其 12 月档自次年首个交易日生效）")
    ap.add_argument("--min-age", type=int, default=250, help="上市满多少个交易日才可入选")
    ap.add_argument("--grace-days", type=int, default=10, help="排名日前多少个自然日内须有收盘")
    ap.add_argument("--samples", default="cap_301_800:40,cap_801_1800:30,cap_all:15",
                    help="哈希抽样子集：带名:百分比，逗号分隔")
    ap.add_argument("--salts", default="a", help="抽样盐，逗号分隔可出多套子集")
    args = ap.parse_args()

    days = trading_days()
    last_day = days[-1]
    rebalances = rebalance_dates(days, args.first_year, last_day)
    print(f"交易日历 {days[0]}~{last_day}｜排名日 {len(rebalances)} 个：{rebalances[0]} … {rebalances[-1]}")
    names = load_names()
    shares = load_shares()
    print(f"股本序列 {len(shares):,} 只（财报期文件 {len(list(FIN.glob('*.csv')))} 份）")
    prices = scan_prices(rebalances, args.min_age, args.grace_days)
    print(f"行情 {len(prices):,} 只通过上市年限/停牌筛")

    # 逐排名日排序
    ranked: dict[str, list[tuple[str, float, float, float]]] = {}   # R -> [(code, mcap, close, shares)] 按市值降序
    for r in rebalances:
        rows = []
        for code, per in prices.items():
            if r not in per:
                continue
            sh = shares_on(shares.get(code, []), r)
            if sh is None:
                continue
            close, _age = per[r]
            rows.append((code, close * sh, close, sh))
        rows.sort(key=lambda t: -t[1])
        ranked[r] = rows

    args.out_dir.mkdir(parents=True, exist_ok=True)
    samples = {}
    for item in args.samples.split(","):
        if item.strip():
            band, pct = item.split(":")
            samples[band.strip()] = int(pct)
    salts = [s.strip() for s in args.salts.split(",") if s.strip()]

    stats_rows = []
    for band, (lo, hi) in BANDS.items():
        # key -> (pct, salt)；全量带自身 pct=100
        variants: dict[str, tuple[int, str]] = {band: (100, "")}
        if band in samples:
            pct = samples[band]
            for salt in salts:
                key = f"{band}_s{pct}" + ("" if salt == "a" else f"_{salt}")
                variants[key] = (pct, salt)
        outputs = {key: [] for key in variants}
        prev_members: set[str] = set()
        for idx, r in enumerate(rebalances):
            j = bisect.bisect_right(days, r)
            if j >= len(days):
                continue
            eff_from = days[j]
            eff_to = rebalances[idx + 1] if idx + 1 < len(rebalances) else ""
            members = [(rank, code, mcap, close, sh) for rank, (code, mcap, close, sh) in enumerate(ranked[r], 1)
                       if lo <= rank <= hi]
            cur = {m[1] for m in members}
            churn = (len(cur - prev_members) / len(cur)) if cur and prev_members else 0.0
            stats_rows.append({"band": band, "rank_date": r, "effective_from": eff_from, "n": len(cur),
                               "new_share": f"{churn:.3f}",
                               "mcap_min_yi": f"{members[-1][2]:.1f}" if members else "",
                               "mcap_max_yi": f"{members[0][2]:.1f}" if members else ""})
            prev_members = cur
            for rank, code, mcap, close, sh in members:
                row = {"effective_from": eff_from, "effective_to": eff_to, "screen_year": r[:4],
                       "security_code": code, "security_name": names.get(code, ""),
                       "mcap_rank": rank, "mcap_yi": f"{mcap:.2f}", "close": f"{close:.2f}", "shares_yi": f"{sh:.3f}"}
                for key, (pct, salt) in variants.items():
                    if pct >= 100 or sampled(code, pct, salt):
                        outputs[key].append(row)
        for key, rows in outputs.items():
            path = args.out_dir / f"{key}.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(rows)
            union = {r["security_code"] for r in rows}
            per = defaultdict(int)
            for r in rows:
                per[r["effective_from"]] += 1
            sizes = sorted(per.values())
            print(f"  {key:<22} 区间行 {len(rows):>7,}｜并集 {len(union):>5,} 只｜每档 {sizes[0] if sizes else 0}~{sizes[-1] if sizes else 0}")
    with (args.out_dir / "membership_stats.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(stats_rows[0].keys()))
        w.writeheader()
        w.writerows(stats_rows)
    print(f"写入 {args.out_dir}")


if __name__ == "__main__":
    main()
