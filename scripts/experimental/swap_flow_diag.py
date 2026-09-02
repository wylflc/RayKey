"""§12.178 换仓资金去向诊断：读引擎 --trade-log / --candidate-log 与两侧逐日状态子集，出 §12.141 同式读数。
用法：python3 swap_flow_diag.py <trades.csv> <cands.csv> <hold_states_subset.csv> <cand_states_subset.csv>
"""
import csv, re, sys, bisect, statistics
from collections import defaultdict

trades, cands, hold_sub, cand_sub = sys.argv[1:5]
rows = list(csv.DictReader(open(trades, encoding="utf-8")))
# 候选侧 P/V（合格集前十记录）
cand_pv = {}
for r in csv.DictReader(open(cands, encoding="utf-8")):
    cand_pv[(r["security_code"], r["exec_date"])] = float(r["pv"])
def load_states(path):
    d = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try: d[r["security_code"]].append((r["date"], float(r["valuation_ratio"])))
            except ValueError: pass
    for k in d: d[k].sort()
    return d
hold_st = load_states(hold_sub); cand_st = load_states(cand_sub)
def pv_before(st, code, day):
    """信号日 = 成交日之前最近一个有状态的日期"""
    lst = st.get(code, [])
    i = bisect.bisect_left(lst, (day, -1.0)) - 1
    return lst[i][1] if i >= 0 else None
by_day = defaultdict(list)
for r in rows: by_day[r["date"]].append(r)
days = sorted(by_day)
buy_days_by_code = defaultdict(list)
for r in rows:
    if r["action"] == "买入": buy_days_by_code[r["security_code"]].append(r["date"])
for k in buy_days_by_code: buy_days_by_code[k].sort()
pat = re.compile(r"换仓.*让位给(?:空间更大的)?(\d{6})")
n_pv = n_gain = 0; got = 0; got_amt = []; nobuy = 0
recip_pricier_trig = [0, 0]; recip_pricier_src = [0, 0]; src_rebuy = 0
delay = []; frag = 0; nbuys = 0; double_trim = 0
for r in rows:
    if r["action"] == "买入":
        nbuys += 1
        if float(r["amount"]) < 5000: frag += 1
for day in days:
    sells = [r for r in by_day[day] if r["action"] == "卖出" and pat.search(r["reason"])]
    buys = [r for r in by_day[day] if r["action"] == "买入"]
    buy_amt = defaultdict(float)
    for b in buys: buy_amt[b["security_code"]] += float(b["amount"])
    # 同日同一持仓被「涨幅减持」与「涨幅让位换仓」各减一档
    codes_gain = {r["security_code"] for r in by_day[day] if r["action"] == "卖出" and "涨幅≥" in r["reason"] and "换仓" not in r["reason"]}
    codes_let = {r["security_code"] for r in sells if "让位" in r["reason"] and "涨幅" in r["reason"]}
    double_trim += len(codes_gain & codes_let)
    for s in sells:
        trig = pat.search(s["reason"]).group(1); src = s["security_code"]
        is_gain = "涨幅" in s["reason"]
        if is_gain: n_gain += 1
        else: n_pv += 1
        if trig in buy_amt:
            got += 1; got_amt.append(buy_amt[trig] / float(s["amount"]))
        if not buys: nobuy += 1
        if src in buy_amt: src_rebuy += 1
        # 触发者延迟获配
        later = [d for d in buy_days_by_code.get(trig, []) if d >= day]
        delay.append((days.index(later[0]) - days.index(day)) if later and later[0] in by_day else None)
        if is_gain: continue
        tpv = cand_pv.get((trig, day)) or pv_before(cand_st, trig, day)
        spv = pv_before(hold_st, src, day)
        for b in buys:
            if b["security_code"] == trig: continue
            bpv = float(b["pv_ratio"])
            if tpv is not None:
                recip_pricier_trig[1] += 1
                if bpv > tpv: recip_pricier_trig[0] += 1
            if spv is not None:
                recip_pricier_src[1] += 1
                if bpv > spv: recip_pricier_src[0] += 1
n = n_pv + n_gain
dl = [d for d in delay if d is not None]
print(f"换仓卖出 {n} 笔（P/V 路径 {n_pv}、涨幅让位 {n_gain}）")
print(f"触发者当日获配：{got}/{n} = {got/n:.1%}；获配额÷卖出额 中位 {statistics.median(got_amt):.2f}" if got else f"触发者当日获配：0/{n}")
print(f"当日完全无买入：{nobuy}/{n} = {nobuy/n:.1%}")
print(f"接收方比触发者贵（P/V 路径，按接收笔）：{recip_pricier_trig[0]}/{recip_pricier_trig[1]}")
print(f"接收方比卖出源贵（源取持仓侧 P/V）：{recip_pricier_src[0]}/{recip_pricier_src[1]}")
print(f"同日卖出源又被买入：{src_rebuy}/{n}")
print(f"触发者首次获配延迟（交易日）：中位 {statistics.median(dl):.0f}，≤5 日 {sum(1 for d in dl if d<=5)}/{len(dl)}，从未获配 {sum(1 for d in delay if d is None)}/{n}")
print(f"碎单（买入 <5,000 元）：{frag}/{nbuys} = {frag/nbuys:.1%}")
print(f"同日「涨幅减持＋涨幅让位」同一持仓减两档：{double_trim} 次")
