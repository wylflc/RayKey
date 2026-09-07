#!/usr/bin/env python3
"""成交量闸门（回测日志 §12.204）的逐笔诊断：读一条臂的逐笔流水与逐周期产物，回答两个问题——
① `ratio`：BASE 自己的建仓／加仓／止损动作落在什么量比上（各阈值会挡掉多大比例的动作），
   以及按入场信号日量比分桶的周期贡献（含五赢家各周期的量比与贡献）；
② `compare`：挑战臂与 BASE 同起点的周期集合差在哪——五赢家周期是否还在、按代码汇总的贡献差前几名、
   运行日志里「成交量·挡下」的次数。
量比与引擎同一函数（`volume_ratio_series`，除权折算同股本口径）；信号日 = 成交日前一交易日（该票行情序列内），
止损判据日 = 成交日本身。只读产物、不跑回测。
用法：
    volume_gate_diag.py ratio --fills <逐笔流水.csv> --lots <逐周期_trades.csv> [--winners 601088,...]
    volume_gate_diag.py compare --base-lots <BASE 逐周期> --arm-lots <臂 逐周期> [--arm-log run.log] [--winners ...]
"""
import argparse
import bisect
import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import backtest_valuation_strategy as B  # noqa: E402

DEFAULT_WINNERS = "601088,002128,000933,000651,000338"   # §12.1 第 3 款剔除集 A（BASE 2011-11-01）
EDGES = (0.8, 1.0, 1.2, 1.5, 2.0, 3.0)


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def bucket(x):
    if x is None:
        return "缺失"
    for e in EDGES:
        if x < e:
            return f"<{e}"
    return f"≥{EDGES[-1]}"


ORDER = ["缺失"] + [f"<{e}" for e in EDGES] + [f"≥{EDGES[-1]}"]


class Ratios:
    def __init__(self, codes: set[str], window: int = 20, short: int = 5):
        vol = B.load_volumes(codes)
        actions = B.load_actions(include_rights=True)
        self.r = {c: B.volume_ratio_series(vol[c], actions.get(c, {}), window, 0) for c in codes if c in vol}
        self.t = {c: B.volume_ratio_series(vol[c], actions.get(c, {}), window, short) for c in codes if c in vol}
        self.days = {c: sorted(vol[c]) for c in codes if c in vol}

    def sig_day(self, c: str, d: str):
        ds = self.days.get(c, [])
        i = bisect.bisect_left(ds, d)
        return ds[i - 1] if i > 0 else None

    def at_entry(self, c: str, exec_day: str):
        sd = self.sig_day(c, exec_day)
        return (self.r.get(c, {}).get(sd), self.t.get(c, {}).get(sd)) if sd else (None, None)


def share_ge(xs, e):
    return sum(1 for x in xs if x >= e) / len(xs) if xs else float("nan")


def cmd_ratio(a):
    fills, lots = read(a.fills), read(a.lots)
    winners = [w for w in a.winners.split(",") if w]
    rat = Ratios({f["security_code"] for f in fills} | {l["security_code"] for l in lots})
    print("== 买入逐笔（信号日 = 成交日前一交易日；量比 = 当日÷此前20日均量，趋势形 = MA5÷MA20）==")
    for reason in ("首次建仓", "定投加仓"):
        rs, ts, cnt = [], [], defaultdict(int)
        for f in fills:
            if f["action"] != "买入" or f["reason"] != reason:
                continue
            x, t = rat.at_entry(f["security_code"], f["date"])
            cnt[bucket(x)] += 1
            if x is not None:
                rs.append(x)
            if t is not None:
                ts.append(t)
        n = sum(cnt.values())
        q = statistics.quantiles(rs, n=4)
        print(f"{reason}: n={n} 量比中位 {statistics.median(rs):.2f} P25 {q[0]:.2f} P75 {q[2]:.2f}；趋势形中位 {statistics.median(ts):.2f}；"
              + " ".join(f"{k}:{cnt[k]/n:.0%}" for k in ORDER if cnt[k]))
        print("   量比 ≥ 阈值的动作占比：" + " ".join(f"≥{e} {share_ge(rs, e):.0%}" for e in (0.8, 1.0, 1.2, 1.5, 2.0))
              + "；趋势形 " + " ".join(f"≥{e} {share_ge(ts, e):.0%}" for e in (1.0, 1.2)))
    print("== 止损卖出（判据日 = 成交日）==")
    rs, cnt = [], defaultdict(int)
    for f in fills:
        if f["action"] != "卖出" or "止损" not in f["reason"]:
            continue
        x = rat.r.get(f["security_code"], {}).get(f["date"])
        cnt[bucket(x)] += 1
        if x is not None:
            rs.append(x)
    n = sum(cnt.values())
    print(f"止损: n={n} 量比中位 {statistics.median(rs):.2f}；" + " ".join(f"{k}:{cnt[k]/n:.0%}" for k in ORDER if cnt[k])
          + "；≥阈值占比 " + " ".join(f"≥{e} {share_ge(rs, e):.0%}" for e in (0.8, 1.0, 1.2)))
    print("== 周期贡献按入场信号日量比分桶（contrib = 盈亏 ÷ 前一日净资产 累计）==")
    tot = sum(float(l["contrib"]) for l in lots)
    by = defaultdict(lambda: [0, 0.0])
    byt = defaultdict(lambda: [0, 0.0])
    entry = {}
    for l in lots:
        x, t = rat.at_entry(l["security_code"], l["entry_date"])
        entry[id(l)] = (x, t)
        by[bucket(x)][0] += 1
        by[bucket(x)][1] += float(l["contrib"])
        k = "缺失" if t is None else ("趋势形≥1.2" if t >= 1.2 else "趋势形<1.2")
        byt[k][0] += 1
        byt[k][1] += float(l["contrib"])
    print(f"周期数 {len(lots)} 贡献合计 {tot:+.3f}")
    for k in ORDER:
        if k in by:
            print(f"  {k:>6}: 周期 {by[k][0]:3d} 贡献 {by[k][1]:+.3f} ({by[k][1]/tot:+.0%})")
    for k, v in byt.items():
        print(f"  {k}: 周期 {v[0]} 贡献 {v[1]:+.3f} ({v[1]/tot:+.0%})")
    for e in (0.8, 1.0, 1.2, 1.5, 2.0):
        s = sum(float(l["contrib"]) for l in lots if entry[id(l)][0] is not None and entry[id(l)][0] < e)
        print(f"  入场量比 <{e} 的周期贡献合计 {s:+.3f} ({s/tot:+.0%})")
    print("== 赢家各周期（入场信号日 量比 / 趋势形 / 贡献 / 出场原因）==")
    for w in winners:
        for l in lots:
            if l["security_code"] != w:
                continue
            x, t = entry[id(l)]
            fx = "缺失" if x is None else f"{x:.2f}"
            ft = "缺失" if t is None else f"{t:.2f}"
            print(f"  {w} {l['security_name']:<6} 入 {l['entry_date']} 出 {l['exit_date']} 持 {l['holding_days']:>4} 日 "
                  f"量比 {fx} 趋势 {ft} 贡献 {float(l['contrib']):+.3f} {l['exit_reason']}")


def cmd_compare(a):
    base, arm = read(a.base_lots), read(a.arm_lots)
    winners = [w for w in a.winners.split(",") if w]
    name = a.arm_name or a.arm_lots.stem.rsplit("_", 2)[-2]
    tb, ta = sum(float(l["contrib"]) for l in base), sum(float(l["contrib"]) for l in arm)
    print(f"== {name} vs BASE（同起点逐周期产物）==")
    print(f"周期数 BASE {len(base)} / {name} {len(arm)}；贡献合计 BASE {tb:+.3f} / {name} {ta:+.3f}（Δ {ta-tb:+.3f}）")
    if a.arm_log and a.arm_log.exists():
        text = a.arm_log.read_text(encoding="utf-8", errors="replace")
        hits = re.findall(r"(成交量·[^\s:：]+|止损·缩量跌破不触发|量比缺失)[\s:：]*([\d,]+)", text)
        if hits:
            print("挡下计数（运行日志）：" + "；".join(f"{k} {v}" for k, v in hits))
    by_b, by_a = defaultdict(float), defaultdict(float)
    for l in base:
        by_b[l["security_code"]] += float(l["contrib"])
    for l in arm:
        by_a[l["security_code"]] += float(l["contrib"])
    diff = sorted(((by_a[c] - by_b[c], c) for c in set(by_b) | set(by_a)), key=lambda x: x[0])
    names = {l["security_code"]: l["security_name"] for l in base + arm if l["security_name"]}
    print("按代码汇总贡献差（臂 − BASE）最负 8 只：" + "；".join(f"{c} {names.get(c, '')} {d:+.3f}" for d, c in diff[:8]))
    print("最正 8 只：" + "；".join(f"{c} {names.get(c, '')} {d:+.3f}" for d, c in diff[-8:][::-1]))
    print("== 赢家周期对照（贡献 ≥ 0.05 的周期；入场日 → 出场日 贡献）==")
    for w in winners:
        big_b = [l for l in base if l["security_code"] == w and float(l["contrib"]) >= 0.05]
        big_a = [l for l in arm if l["security_code"] == w and float(l["contrib"]) >= 0.05]
        fmt = lambda ls: "、".join(f"{l['entry_date']}→{l['exit_date']} {float(l['contrib']):+.3f}" for l in ls) or "无"
        print(f"  {w} {names.get(w, ''):<6} 代码合计 BASE {by_b[w]:+.3f} / {name} {by_a[w]:+.3f}；BASE 大周期 {fmt(big_b)}；{name} 大周期 {fmt(big_a)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("ratio")
    r.add_argument("--fills", type=Path, required=True)
    r.add_argument("--lots", type=Path, required=True)
    r.add_argument("--winners", default=DEFAULT_WINNERS)
    r.set_defaults(func=cmd_ratio)
    c = sub.add_parser("compare")
    c.add_argument("--base-lots", type=Path, required=True)
    c.add_argument("--arm-lots", type=Path, required=True)
    c.add_argument("--arm-log", type=Path)
    c.add_argument("--arm-name", default="")
    c.add_argument("--winners", default=DEFAULT_WINNERS)
    c.set_defaults(func=cmd_compare)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
