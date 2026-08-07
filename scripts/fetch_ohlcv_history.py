#!/usr/bin/env python3
"""逐票历史日线（**不复权原始价**）+ 除权除息事件，作为回测数据底座（结 OI-035）。

用户 2026-08-07 裁定
--------------------
> 池 + 持仓，拉取每个股票**上市后的所有数据**，然后请一定要明确取数据的方式，我建议采用
> **不复权原始价格 + 分红送转/配股等除权除息信息**，方便后续回测分析，计算 return。

**这个取法是对的，而且实测证明前复权在长历史上根本不能用**：腾讯 `qfq` 序列对贵州茅台
2015-01-05 返回的开盘价是 **−129.35**——累计分红在向后摊回时超过了当年的股价，前复权序列
直接变成负数。用它算收益率会得到无意义的结果，而这类失效**不会报错**，只会安静地给出错的数
（§15.2 第 3 条）。故本模块只存原始价，复权在**计算时**按事件重建。

产出
----
* ``data/raw/ohlcv/<代码>.csv``——不复权日线：``date,open,close,high,low,volume``（逐票一文件，增量追加）
* ``data/raw/corporate_actions/a_share_corporate_actions.csv``——全部除权除息事件：
  ``security_code,ex_dividend_date,cash_per_share,share_ratio,plan,report_date``

两者分开存是有意的：**价格是观测，事件是事实**，前者天天变、后者只在除权日新增一行。
合起来才能算总收益率，任何一份单独都不够。

数据源与边界
------------
* 腾讯 `web.ifzq.gtimg.cn/appstock/app/fqkline/get`，`param=<secid>,day,<起>,<止>,<条数>,`
  末位留空即**不复权**。**单次最多返回 640 根**（实测：请求 1000 返回 640，请求 3000 返回空），
  故按日期窗分页回溯，直到某窗返回空即认为到达上市日。
* 除权除息取东财 `RPT_SHAREBONUS_DET` 的 `EX_DIVIDEND_DATE`／`PRETAX_BONUS_RMB`（每 10 股税前派息）
  ／`BONUS_RATIO`（每 10 股送股）／`IT_RATIO`（每 10 股转增）。**配股不在该表**——这是已知缺口，
  受影响的票须人工补，不得当作"没有配股"。
* **幸存者偏差未解决**：universe 取自当前的池与持仓，退市与更名股票不在其中（§12.4 已登记）。
  本模块不假装解决它，只把它写在这里。

用法::

    python3 scripts/fetch_ohlcv_history.py --as-of 2026-08-07                 # 池+持仓，全历史，增量
    python3 scripts/fetch_ohlcv_history.py --as-of 2026-08-07 --limit 5       # 冒烟
    python3 scripts/fetch_ohlcv_history.py --as-of 2026-08-07 --actions-only  # 只刷除权事件
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
OHLCV_DIR = ROOT / "data/raw/ohlcv"
ACTIONS_CSV = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"

KLINE_API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={secid},day,{start},{end},{count},"
EM_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}

MAX_BARS_PER_CALL = 640          # 实测上限，见模块 docstring
OHLCV_FIELDS = ["date", "open", "close", "high", "low", "volume"]
ACTION_FIELDS = ["security_code", "security_name", "ex_dividend_date",
                 "cash_per_share", "share_ratio", "plan", "report_date"]


def secid(code: str, exchange: str) -> str:
    code = code.zfill(6)
    if exchange:
        return ("sh" if exchange.upper().startswith("SS") or exchange.upper() == "SSE" else "sz") + code
    return ("sh" if code[0] == "6" else ("bj" if code[0] in "48" else "sz")) + code


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def fetch_window(sid: str, start: str, end: str, timeout: float) -> list[list]:
    url = KLINE_API.format(secid=sid, start=start, end=end, count=MAX_BARS_PER_CALL)
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    data = (payload.get("data") or {}).get(sid) or {}
    return data.get("day") or []


def fetch_full_history(sid: str, until: date, since: date | None, timeout: float,
                       pause: float) -> list[dict[str, str]]:
    """按日期窗向前分页，直到某窗返回空（= 到达上市日或 `since`）。

    每窗取约 2.5 年（640 根 ÷ 244 交易日/年 ≈ 2.6 年），留一点余量防边界丢根。
    窗与窗之间按 `date` 去重合并——分页边界重叠是正常的，重叠比漏根安全。
    """
    seen: dict[str, list] = {}
    end = until
    while True:
        start = end - timedelta(days=900)
        if since and start < since:
            start = since
        rows = fetch_window(sid, start.isoformat(), end.isoformat(), timeout)
        time.sleep(pause)
        if not rows:
            break
        for row in rows:
            seen.setdefault(str(row[0]), row)
        oldest = min(str(row[0]) for row in rows)
        if since and oldest <= since.isoformat():
            break
        new_end = date.fromisoformat(oldest) - timedelta(days=1)
        if new_end >= end:                      # 没有前进 = 到底了，防死循环
            break
        end = new_end

    out = []
    for key in sorted(seen):
        row = seen[key]
        out.append({
            "date": str(row[0]), "open": str(row[1]), "close": str(row[2]),
            "high": str(row[3]), "low": str(row[4]),
            "volume": str(row[5]) if len(row) > 5 else "",
        })
    return out


def fetch_actions(code: str, timeout: float) -> list[dict[str, str]]:
    query = urllib.parse.urlencode({
        "reportName": "RPT_SHAREBONUS_DET",
        "columns": ("SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,EX_DIVIDEND_DATE,"
                    "PRETAX_BONUS_RMB,BONUS_RATIO,IT_RATIO,IMPL_PLAN_PROFILE,ASSIGN_PROGRESS"),
        "pageSize": "200",
        "sortColumns": "EX_DIVIDEND_DATE",
        "sortTypes": "1",
        "filter": f'(SECURITY_CODE="{code}")',
    })
    request = urllib.request.Request(f"{EM_API}?{query}", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = ((payload.get("result") or {}).get("data")) or []

    out = []
    for row in rows:
        ex = (row.get("EX_DIVIDEND_DATE") or "")[:10]
        if not ex:
            continue                            # 只有预案、尚未实施：没有除权日就不是事件
        cash = float(row.get("PRETAX_BONUS_RMB") or 0) / 10
        share = (float(row.get("BONUS_RATIO") or 0) + float(row.get("IT_RATIO") or 0)) / 10
        if not cash and not share:
            continue
        out.append({
            "security_code": code.zfill(6),
            "security_name": row.get("SECURITY_NAME_ABBR", ""),
            "ex_dividend_date": ex,
            "cash_per_share": f"{cash:.6f}",
            "share_ratio": f"{share:.6f}",
            "plan": row.get("IMPL_PLAN_PROFILE", ""),
            "report_date": (row.get("REPORT_DATE") or "")[:10],
        })
    return out


# --------------------------------------------------------------- 复权与收益率
def cumulative_factors(bars: list[dict[str, str]], actions: list[dict[str, str]]) -> dict[str, float]:
    """由原始价 + 除权事件重建**后复权累计因子** `A(t)`：复权价 = 原始价 × A(t)。

    除权日 D 的理论开盘参考价 `P_ex = (P_前收 − 每股现金) / (1 + 每股送转)`，故价格序列在 D
    处有一个不代表损益的跳空。令 `f_D = P_ex / P_前收`，把 D 及其之后的所有价格乘以 `1/f_D`
    的累计积，跳空即被抹平，**相邻两点的比值就是真实的总收益率**（含分红再投资）。

    用后复权而不是前复权：前复权要把历史价往下摊，累计分红超过早年股价时会摊成负数
    （实测茅台 2015 年前复权开盘价 −129.35），而后复权只会把近端放大，永远为正。

    >>> bars = [{"date": "2026-01-01", "close": "10"}, {"date": "2026-01-02", "close": "9"}]
    >>> acts = [{"ex_dividend_date": "2026-01-02", "cash_per_share": "1", "share_ratio": "0"}]
    >>> f = cumulative_factors(bars, acts)
    >>> round(f["2026-01-02"] * 9 / (f["2026-01-01"] * 10) - 1, 10)   # 除权当天真实收益为 0
    0.0
    """
    closes = {bar["date"]: float(bar["close"]) for bar in bars if bar.get("close")}
    dates = sorted(closes)
    by_ex: dict[str, tuple[float, float]] = {}
    for action in actions:
        ex = action["ex_dividend_date"]
        by_ex[ex] = (float(action.get("cash_per_share") or 0), float(action.get("share_ratio") or 0))

    factors: dict[str, float] = {}
    running = 1.0
    prev_date = None
    for day in dates:
        if day in by_ex and prev_date is not None:
            cash, share = by_ex[day]
            prev_close = closes[prev_date]
            p_ex = (prev_close - cash) / (1 + share)
            if p_ex > 0:
                running *= prev_close / p_ex
        factors[day] = running
        prev_date = day
    return factors


def total_return(bars: list[dict[str, str]], actions: list[dict[str, str]],
                 start: str, end: str) -> float | None:
    """`start → end` 的总收益率（已含分红与送转）。两端须都有 bar，否则返回 None。"""
    closes = {bar["date"]: float(bar["close"]) for bar in bars if bar.get("close")}
    if start not in closes or end not in closes:
        return None
    factors = cumulative_factors(bars, actions)
    return (closes[end] * factors[end]) / (closes[start] * factors[start]) - 1


# --------------------------------------------------------------- 主流程
def universe() -> list[tuple[str, str, str]]:
    rows = {r["security_code"].zfill(6): (r.get("security_name", ""), r.get("exchange", ""))
            for r in load_csv(POOL)}
    for r in load_csv(HOLDINGS):
        rows.setdefault(r["security_code"].zfill(6), (r.get("security_name", ""), ""))
    return [(code, name, exchange) for code, (name, exchange) in sorted(rows.items())]


def main() -> int:
    parser = argparse.ArgumentParser(description="逐票不复权日线 + 除权除息事件（OI-035）")
    parser.add_argument("--as-of", required=True, help="截止交易日 YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 只（冒烟用）")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--pause", type=float, default=0.12)
    parser.add_argument("--actions-only", action="store_true", help="只刷除权事件，不动日线")
    parser.add_argument("--full", action="store_true", help="忽略已有文件，重下全历史")
    args = parser.parse_args()

    until = date.fromisoformat(args.as_of)
    targets = universe()
    if args.limit:
        targets = targets[:args.limit]
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    ACTIONS_CSV.parent.mkdir(parents=True, exist_ok=True)
    print(f"universe {len(targets)} 只（池 + 持仓）｜截止 {until}｜不复权原始价 + 除权事件")

    all_actions: list[dict[str, str]] = []
    bar_counts, failed, skipped = [], [], 0
    for index, (code, name, exchange) in enumerate(targets, 1):
        path = OHLCV_DIR / f"{code}.csv"
        existing = load_csv(path) if not args.full else []
        since = None
        if existing:
            last = max(row["date"] for row in existing)
            if last >= args.as_of:
                skipped += 1
            since = date.fromisoformat(last) + timedelta(days=1)

        try:
            actions = fetch_actions(code, args.timeout)
            all_actions.extend(actions)
            time.sleep(args.pause)
        except Exception as exc:                               # noqa: BLE001
            failed.append(f"{code} 除权({type(exc).__name__})")

        if args.actions_only:
            continue
        if existing and since and since > until:
            bar_counts.append(len(existing))
            continue
        try:
            fresh = fetch_full_history(secid(code, exchange), until, since, args.timeout, args.pause)
        except Exception as exc:                               # noqa: BLE001
            failed.append(f"{code} 日线({type(exc).__name__})")
            continue

        merged = {row["date"]: row for row in existing}
        merged.update({row["date"]: row for row in fresh})
        rows = [merged[key] for key in sorted(merged)]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OHLCV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        bar_counts.append(len(rows))
        if index % 25 == 0 or index == len(targets):
            print(f"  [{index}/{len(targets)}] {name}({code}) 累计 {len(rows)} 根")

    if all_actions:
        merged_actions = {(a["security_code"], a["ex_dividend_date"]): a for a in load_csv(ACTIONS_CSV)
                          if a.get("security_code")}
        merged_actions.update({(a["security_code"], a["ex_dividend_date"]): a for a in all_actions})
        with ACTIONS_CSV.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=ACTION_FIELDS)
            writer.writeheader()
            writer.writerows([merged_actions[k] for k in sorted(merged_actions)])
        print(f"除权除息事件 {len(merged_actions)} 行 → {ACTIONS_CSV.relative_to(ROOT)}")

    # §15.2 第 3 条硬自检：新增数据源必须核对非空行数与覆盖面。
    if bar_counts:
        print(f"日线覆盖 {len(bar_counts)}/{len(targets)} 只｜合计 {sum(bar_counts):,} 根"
              f"｜单票中位 {sorted(bar_counts)[len(bar_counts) // 2]:,} 根"
              f"｜最短 {min(bar_counts):,}｜最长 {max(bar_counts):,}")
    if skipped:
        print(f"  已是最新、未重取 {skipped} 只")
    if failed:
        print(f"  **失败 {len(failed)} 项**：{'、'.join(failed[:10])}" + ("…" if len(failed) > 10 else ""))
    print("  ⚠ 已知缺口：①配股不在 RPT_SHAREBONUS_DET，受影响票须人工补；"
          "②universe 取自当前池与持仓，**退市/更名股票不在其中（幸存者偏差，§12.4）**")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
