#!/usr/bin/env python3
"""爱玛 09-24 生产 V 51.72 的逐项拆解，与外部正常化 PE 口径对照（用户 2026-09-25 提问）。"""
import csv, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import roic_inputs
from intrinsic_value import intrinsic_value

CODE = "603529"
OUT = Path(__file__).with_name("decompose.json")
band = next(r for r in csv.DictReader(open(ROOT / "data/processed/a_share_pool_model_bands_adopted.csv", encoding="utf-8-sig"))
            if r["security_code"] == CODE)
f = lambda k: float(band[k])
years = roic_inputs.load_statements({CODE}, ic_floor=0.1).get(CODE, {})
hist = []
for p in sorted(years):
    y = years[p]
    if not p.endswith("12-31"):
        continue
    hist.append({"period": p, "revenue_yi": (y.revenue or 0) / 1e8, "parent_np_yi": (y.parent_netprofit or 0) / 1e8,
                 "nopat_yi": (y.nopat or 0) / 1e8, "nonop_income_yi": y.nonop_income / 1e8,
                 "ic_yi": (y.invested_capital or 0) / 1e8, "equity_yi": (y.total_equity or 0) / 1e8,
                 "excess_cash_yi": y.excess_cash / 1e8, "interest_debt_yi": y.interest_debt / 1e8,
                 "note_cash_yi": y.note_cash / 1e8, "wc_yi": (y.working_capital or 0) / 1e8,
                 "capex_yi": y.capex / 1e8, "da_yi": y.dep_amort / 1e8, "cfo_yi": (y.cfo or 0) / 1e8})

nopat, roic0, g0, w, r = f("nopat_ps"), f("roic0"), f("g0"), f("wacc"), f("r")
nd = f("net_debt_ps")          # 负值 = 净现金（含少数股东扣减）
shares = f("shares_est")
kw = dict(g_terminal=0.03, n=10, n1=0, roe_lam=0.12, horizon=50, consistent=True)
def ev(nopat_ps=nopat, g=g0, wacc=w):
    roic_t = min(wacc + 0.02, roic0)
    return intrinsic_value(nopat_ps, roic0 * nopat_ps / nopat, g, wacc, roe_terminal=roic_t, **kw).intrinsic_value
price = 20.88
base = ev() - nd
rows = {"生产（研究数 NOPAT、g0 21.65%、WACC 8.84%）": base,
        "WACC 改为 r 10%（OI-217 净现金）": ev(wacc=r) - nd,
        "g0 = 0": ev(g=0.0) - nd,
        "g0 = 0，WACC 10%": ev(g=0.0, wacc=r) - nd,
        "g0 = 3%，WACC 10%": ev(g=0.03, wacc=r) - nd,
        "g0 = 8%，WACC 10%": ev(g=0.08, wacc=r) - nd}
# 质押存单：2025 年报受限资产 74.75 亿（三年期存单 70.02 亿、一年期存单 1.37 亿、票据保证金 3.35 亿），
# 全部为开具银行承兑汇票质押，同日应付票据 74.99 亿（2026 半年报 48.76 亿 ／ 52.91 亿）。
# 模型把它计入超额现金，同时把应付票据当经营负债（垫款）。按经营资产处理：扣出超额现金、加回投入资本，
# 其利息（按 2.5%）并回 NOPAT；比例尺与生产带相同（2025 年报结构 × 当前经营账面）。
a25 = years["2025-12-31"]
scale = f("fin_net_debt_ps") / ((a25.interest_debt - a25.excess_cash) / 1e8)
PLEDGED_YI, NOTES_YI = 74.75, 74.99
pledged_ps = PLEDGED_YI * scale
ic_ps = ((a25.interest_debt + a25.total_equity - a25.excess_cash) / 1e8 + PLEDGED_YI) * scale
nopat_p = nopat + PLEDGED_YI * 0.025 * (1 - f("tax_rate")) * scale
def ev_p(g, wacc):
    return intrinsic_value(nopat_p, nopat_p / ic_ps, g, wacc, roe_terminal=min(wacc + 0.02, nopat_p / ic_ps), **kw).intrinsic_value
rows.update({"质押存单按经营资产（其余同生产）": ev_p(g0, w) - nd - pledged_ps,
             "g0 = 3%（其余同生产）": ev(g=0.03) - nd,
             "WACC 10% + 质押存单按经营资产（g0 21.65% 不变）": ev_p(g0, r) - nd - pledged_ps,
             "WACC 10% + g0 8% + 质押存单按经营资产": ev_p(0.08, r) - nd - pledged_ps,
             "WACC 10% + g0 3% + 质押存单按经营资产": ev_p(0.03, r) - nd - pledged_ps,
             "WACC 10% + g0 0 + 质押存单按经营资产": ev_p(0.0, r) - nd - pledged_ps})
scen = {k: {"v": round(v, 2), "pv": round(price / v, 3)} for k, v in rows.items()}
external = {"外部正常化 PE 口径（归母 17～20 亿 × 10～12 倍，股本 8.64 亿）": [round(17 * 10 / 8.6425, 2), round(20 * 12 / 8.6425, 2)]}
parts = {"净现金（净金融资产扣少数股东）": round(-nd, 2),
         "零增长 EV（NOPAT ÷ 10%）": round(nopat / r, 2),
         "WACC 低于 r 的加成（零增长）": round(nopat / w - nopat / r, 2),
         "增长腿（g0 21.65% 与超额回报）": round(ev() - nopat / w, 2)}
json.dump({"band": {k: band[k] for k in ("nopat_ps", "roic0", "g0", "wacc", "r", "net_debt_ps", "fin_net_debt_ps",
                                        "reinvestment_rate", "incremental_roic", "ev_ps", "intrinsic_value", "shares_est")},
           "value_parts_ps": parts, "scenarios": scen, "external": external,
           "pledged": {"pledged_yi_2025": PLEDGED_YI, "notes_payable_yi_2025": NOTES_YI, "pledged_ps": round(pledged_ps, 2),
                       "ic_ps_with_pledged": round(ic_ps, 2), "roic0_with_pledged": round(nopat_p / ic_ps, 4)}, "annual": hist},
          open(OUT, "w"), ensure_ascii=False, indent=1)
print(json.dumps(parts, ensure_ascii=False, indent=1)); print(json.dumps(scen, ensure_ascii=False, indent=1))
print(json.dumps(external, ensure_ascii=False), round(pledged_ps, 2), round(ic_ps, 2), round(nopat_p / ic_ps, 4))
for h in hist[-8:]:
    print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in h.items()})
