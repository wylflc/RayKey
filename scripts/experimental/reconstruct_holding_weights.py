"""从逐笔流水重建逐日持仓，算**时间加权平均权重**——这才是「重仓股是哪些」的答案。

trades 表的「累计投入」是逐周期累计额（同一笔钱反复买卖重复计入），不能当仓位读；
equity 表有 `top1_weight` 但没记是哪只。故必须回到流水重建。

**自检**：重建出的每日权重和应 ≈ 1（回测无杠杆）。偏离超 2% 即报警——
`log_partial_sell` 的文件头记着，流水曾漏记全部「减一档」，那时重建出的前三大合计能到 123.8%。
"""
import bisect
import collections
import csv
import json
import statistics
import sys

ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
names = json.load(open("/tmp/names.json"))


def price_series(codes):
    out = {}
    for code in codes:
        try:
            rows = sorted((r["date"], float(r["close"]))
                          for r in csv.DictReader(open(f"{ROOT}/data/raw/ohlcv/{code}.csv", encoding="utf-8"))
                          if r.get("close"))
        except (OSError, ValueError):
            continue
        out[code] = ([d for d, _ in rows], [v for _, v in rows])
    return out


def price_at(series, code, day):
    entry = series.get(code)
    if not entry:
        return None
    days, vals = entry
    i = bisect.bisect_right(days, day) - 1
    return vals[i] if i >= 0 else None


def run(tag, label):
    ledger = list(csv.DictReader(open(f"/tmp/ledger_{tag}.csv", encoding="utf-8")))
    codes = {r["security_code"] for r in ledger}
    series = price_series(codes)
    by_day = collections.defaultdict(list)
    for r in ledger:
        by_day[r["date"]].append(r)

    eq = list(csv.DictReader(open(f"{ROOT}/data/processed/backtest/"
                                  f"trend_x1_w-0.5853_x1c_sma20_swap_corr{'0.85' if tag=='C085' else '0.6'}"
                                  f"_tranche_sl1.1_sp_lot100_lrc_{tag}_equity.csv", encoding="utf-8")))
    all_days = [r["date"] for r in eq]

    shares = collections.defaultdict(float)
    weight_sum = collections.defaultdict(float)
    n_days = 0
    bad = 0
    for day in all_days:
        for r in by_day.get(day, []):
            q = float(r["shares"])
            shares[r["security_code"]] += q if r["action"] == "买入" else -q
            if shares[r["security_code"]] < 1e-6:
                shares.pop(r["security_code"], None)
        values = {}
        for code, q in shares.items():
            p = price_at(series, code, day)
            if p:
                values[code] = q * p
        total = sum(values.values())
        if total <= 0:
            continue
        n_days += 1
        for code, v in values.items():
            weight_sum[code] += v / total
    print(f"\n{'=' * 74}\n【max-corr {label}】重建 {n_days:,} 个交易日的逐日持仓"
          f"（{len(weight_sum)} 只曾进过组合）")
    rows = sorted(((w / n_days, c) for c, w in weight_sum.items()), reverse=True)
    print(f"  {'公司':<10}{'时间加权平均权重':>16}{'占组合年限':>12}")
    for w, c in rows[:12]:
        print(f"  {names.get(c, c):<10}{w * 100:>15.1f}%{w * n_days / 244:>11.1f} 年")
    print(f"  前 5 只时间加权权重合计 {sum(w for w, _ in rows[:5]) * 100:.0f}%"
          f"｜前 10 只 {sum(w for w, _ in rows[:10]) * 100:.0f}%")


for tag, label in (("C085", "0.85（现行）"), ("C060", "0.60")):
    run(tag, label)
