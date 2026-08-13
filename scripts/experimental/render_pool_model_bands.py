"""按工作流 v2.90 口径重出 `data/processed/000_a_share_core_valuation_pool.md`。

**与旧版的根本差别**：旧表的「合理价区间」出自 §6.5.7 的逐票估值档案（每家单独设计的方法）；
本版改用 **§6.5.7.1 的批量模型带**——`--uniform-tier L2 --roe-source onesided_max --roe-lift 2.0`，
银行另走 `V = 近 12 个月每股现金分红 ÷ (十年国债 + 2%)`。
理由：`docs/Ashare_backtest_log.md` §12.39 的全部回测读数都是在批量模型带上取得的，
生产若继续用档案带，实盘行为与回测不是同一件事。**两条带并列展示，差异极大者需 §7 复核。**
"""
import csv, json, statistics, collections

ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
S = "/private/tmp/claude-501/-Users-yaleiwang-WorkSpace-AgentLab-RayKey/81d2c992-2d15-4712-a049-e294cf756ff3/scratchpad"
TODAY = "2026-08-13"
BUY_LINE, SELL_LINE = 1.63, 1.10

rows = json.load(open(f"{S}/scan_rows2.json", encoding="utf-8"))
POOL = {r["security_code"]: r for r in
        csv.DictReader(open(f"{ROOT}/data/processed/a_share_core_valuation_pool.csv", encoding="utf-8"))}
plan = {p["code"]: p for p in json.load(open(f"{S}/plan.json", encoding="utf-8"))}

order = {"L1": 0, "L2": 1, "L3": 2}
rows.sort(key=lambda r: (order.get(r["tier"], 9), -float(POOL[r["code"]].get("quality_score") or 0)))

n_elig = sum(1 for r in rows if r["pv"] is not None and r["pv"] <= BUY_LINE)
n_both = sum(1 for r in rows if r["pv"] is not None and r["pv"] <= BUY_LINE and r["trend"] is True)
tc = collections.Counter(r["tier_now"] for r in rows)

L = []
A = L.append
A("# A股核心估值合格池")
A("")
A(f"生成日期：{TODAY}｜现价：**2026-08-13 收盘**（周四，公开行情快照，181/181 只成功）｜工作流 **v2.90**")
A("")
A("> **本版换了估值口径，与 2026-08-10 及以前各版不可直接对比。**「合理价区间」由 §6.5.7 的**逐票档案带**")
A("> 改为 §6.5.7.1 的**批量模型带**：`--uniform-tier L2 --roe-source onesided_max --roe-lift 2.0`；")
A("> 银行另走股利折现 `V = 近12个月每股现金分红 ÷ (十年国债 1.7114% + 2%)`。")
A("> 改的理由：`docs/Ashare_backtest_log.md` §12.39 的全部回测读数都取自批量模型带，")
A("> 生产若继续用档案带，**实盘行为与回测不是同一件事**。档案带并列保留在「档案带」列供比对。")
A("")
A(f"**买卖由 §9.7 唯一决定**（v2.90）：买入线 `P/V ≤ {BUY_LINE}` 且 `收盘 > MA20 > MA60`；"
  f"减持线 `P/V ≥ {SELL_LINE}` 且 `收盘 < MA20`；一档 = 当日净资产 × 1.0%；相关性 ≤ 0.85、下扫至多 40 名。")
A("")
A(f"**今日扫描**：`P/V ≤ {BUY_LINE}` 的 **{n_elig}** 只；其中同时满足 `收 > MA20 > MA60` 的 **{n_both}** 只（即当日合格集）。")
A("")
A("⚠ **档位标签与买入线已脱节，需用户裁定**：档位阈值仍锚在带上（>1.32×中值=高估），"
  "而 v2.90 的买入线是 `P/V ≤ 1.63`——**会出现标着「高估」却在买入清单里的行**。"
  "档位自 v2.56 起本就只是展示标签、不决定买卖（§6.2.1.6），但两者相差这么远容易误读。"
  "要么把档位阈值重锚到新买入线，要么改标签措辞，**本版不擅自改，先如实呈现**。")
A("")
A(f"**档位分布**：" + "｜".join(f"{k} {v}" for k, v in
                              sorted(tc.items(), key=lambda x: ["低估", "较低估", "中性", "较高估", "高估", "无法估值"].index(x[0]))))
A("")
A("- 现价为 2026-08-13 收盘（未复权）；`P/V` = 现价 ÷ 模型带中值。走势闸门用**前复权**序列计算（除息不产生假信号）。")
A("- 「买」列标 ✓ 的是次日（周五）买入清单内的标的，标 ✗走势 的是估值合格但走势不合格，标 ✗相关 的是被 0.85 相关性过滤剔除。")
A("- 「档案带」= 旧版逐票档案带，仅供比对，**不参与任何买卖判定**。两带偏离 >50% 的行已标 ⚠，建议进 §7 复核队列。")
A("")
A("| 代码 | 名称 | 质量 | 档位 | 策略 | 现价 | **模型带（λ=2.0）** | P/V | 走势 | 买 | 档案带 | 偏离 |")
A("| --- | --- | --- | --- | --- | ---: | ---: | ---: | :---: | :---: | ---: | ---: |")
warn = 0
for r in rows:
    p = POOL[r["code"]]
    lo, hi = (r["iv"] * 0.9, r["iv"] * 1.1) if r["iv"] else (None, None)
    dlo, dhi = p.get("fair_price_low"), p.get("fair_price_high")
    dev = ""
    if r["iv"] and dlo and dhi:
        try:
            dmid = (float(dlo) + float(dhi)) / 2
            d = r["iv"] / dmid - 1
            dev = f"{d*100:+.0f}%"
            if abs(d) > 0.5:
                dev = "⚠" + dev; warn += 1
        except ValueError:
            pass
    tr = "✓" if r["trend"] is True else ("✗" if r["trend"] is False else "—")
    if r["code"] in plan:
        buy = "**✓**"
    elif r["pv"] is not None and r["pv"] <= BUY_LINE and r["trend"] is True:
        buy = "✗相关"
    elif r["pv"] is not None and r["pv"] <= BUY_LINE:
        buy = "✗走势"
    else:
        buy = ""
    band = f"{lo:.2f}-{hi:.2f}" if lo else "—"
    dband = (f"{float(dlo):.2f}-{float(dhi):.2f}" if dlo and dhi else "—")
    A(f"| {r['code']} | {r['name']} | {r['tier']} | {r['tier_now']} | {(r['strat'] or '')[:14]} | "
      f"{r['px']:.2f} | **{band}** | {r['pv']:.2f} | {tr} | {buy} | {dband} | {dev} |")
A("")
A(f"**两带偏离 >50% 的有 {warn} 只**——批量模型与逐票档案对这些公司的判断分歧极大，"
  "在 §7 复核之前，对这些标的的买入建议应视为**模型口径的机械结论**，不等于已复核的投资判断。")
open(f"{ROOT}/data/processed/000_a_share_core_valuation_pool.md", "w", encoding="utf-8").write("\n".join(L) + "\n")
print(f"已重写 000_a_share_core_valuation_pool.md：{len(rows)} 行｜偏离>50% 的 {warn} 只｜合格集 {n_both} 只")
