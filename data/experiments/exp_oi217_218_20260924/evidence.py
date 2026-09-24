"""OI-217／OI-218 登记证据：09-24 候选侧带（a_share_pool_model_bands_adopted.csv，提交 b2d2b2fc）上的逐项反事实。
EV 按生产参数（指数整本衰减 λ 0.12、50 年、g_T 3%、ROIC_T = min(WACC + 2pp, ROIC0)）由引擎重算，带 EV 的微差按比例保留；
只作归因，不构成新估值。
    python3 data/experiments/exp_oi217_218_20260924/evidence.py
"""
import csv
import json
import statistics
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import roic_inputs as ri  # noqa: E402
from intrinsic_value import intrinsic_value  # noqa: E402

CLOSE = {"603529": 20.88, "000651": 38.50}   # 09-24 收盘


def num(r, k):
    return float(r[k]) if r.get(k) not in (None, "") else None


def ev(path, nps, roic0, g0, w):
    if path == "zero_growth":
        return nps / w
    return intrinsic_value(nps, roic0, g0, w, roe_terminal=min(w + 0.02, roic0), g_terminal=0.03, n=10, n1=0,
                           consistent=True, roe_lam=0.12, horizon=50)


def ev_value(path, nps, roic0, g0, w):
    res = ev(path, nps, roic0, g0, w)
    return res if isinstance(res, float) else res.intrinsic_value


rows = [r for r in csv.DictReader((ROOT / "data/processed/a_share_pool_model_bands_adopted.csv").open(encoding="utf-8-sig"))
        if r["status"] == "ok" and r["roic_path"] in ("growth", "zero_growth")]
years = ri.load_statements({r["security_code"] for r in rows}, ic_floor=0.1)
out = {"bands": len(rows), "wacc_net_cash": [], "ic_floor": [], "cases": {}}
for r in rows:
    code, path, V = r["security_code"], r["roic_path"], num(r, "intrinsic_value")
    nps, roic0, g0, w, r_eq = (num(r, k) for k in ("nopat_ps", "roic0", "g0", "wacc", "r"))
    g0 = g0 or 0.0
    cash = -num(r, "net_debt_ps") if path == "zero_growth" or num(r, "ev_ps") is None else V - num(r, "ev_ps")
    base = ev_value(path, nps, roic0, g0, w)
    scale = (V - cash) / base
    if w < r_eq - 1e-4 and num(r, "net_debt_ps") < 0:   # OI-217：净现金，WACC 却因毛有息负债低于 r
        v_net = ev_value(path, nps, roic0, g0, r_eq) * scale + cash
        out["wacc_net_cash"].append({"code": code, "name": r["security_name"], "wacc": round(w, 4),
                                     "V": round(V, 2), "V_wacc_r": round(v_net, 2), "dV": round(v_net / V - 1, 4)})
    hist = sorted((y for y in years.get(code, {}).values() if y.notice_date <= r["available_at"]), key=lambda y: y.period)
    if not hist:
        continue
    y = hist[-1]
    raw_ic = y.interest_debt + (y.total_equity or 0.0) - y.excess_cash
    floor = 0.1 * (y.total_equity or 0.0)
    if raw_ic < floor:                                     # OI-218：投入资本由下限给出
        shares = num(r, "shares_est")
        rec = {"code": code, "name": r["security_name"], "period": y.period, "raw_ic_yi": round(raw_ic / 1e8, 1),
               "floor_yi": round(floor / 1e8, 1), "wc_yi": round((y.working_capital or 0.0) / 1e8, 1),
               "lift_ps": round((floor - raw_ic) / shares, 2), "g0": g0, "g_source": r["roic_g_source"],
               "reinvestment_rate": num(r, "reinvestment_rate"), "incremental_roic": num(r, "incremental_roic"),
               "roic0": roic0, "V": round(V, 2)}
        if path == "growth" and g0 > 0:
            res = ev(path, nps, roic0, g0, w)
            cap = min(roic0, 0.40)
            rec["model_retention_y1_5"] = round(1 - statistics.mean(res.payout_path[:5]), 3)
            rec["V_g0_zero"] = round(ev_value(path, nps, roic0, 0.0, w) * scale + cash, 2)
            rec["V_retention_at_40pct"] = round(ev_value(path, nps, cap, g0, w) * scale + cash, 2)
        out["ic_floor"].append(rec)
    if code in CLOSE:
        px, ttm, wc_ps = CLOSE[code], num(r, "ttm_factor"), (y.working_capital or 0.0) / num(r, "shares_est")
        zg = ev_value(path, nps, roic0, 0.0, w) * scale
        cf = {"现行": V,
              "WACC 取 r": ev_value(path, nps, roic0, g0, r_eq) * scale + cash,
              "g0 = 0": zg + cash,
              "NOPAT 取 TTM 水平": ev_value(path, nps * ttm, roic0 * ttm, g0, w) * scale + cash,
              "扣除负营运资本对应现金": V + wc_ps,
              "扣除下限抬升的投入资本": V - (floor - raw_ic) / num(r, "shares_est"),
              "前四项同时": ev_value(path, nps * ttm, roic0 * ttm, 0.0, r_eq) * scale + cash + wc_ps}
        out["cases"][code] = {
            "name": r["security_name"], "close": px, "nopat_mode": r["roic_nopat_mode"], "ttm_factor": ttm,
            "anchor_nopat_yi": round(nps * num(r, "shares_est") / 1e8, 1), "wacc": w, "cost_of_debt": num(r, "cost_of_debt"),
            "split_ps": {"零增长 EV": round(zg, 2), "增长": round(V - cash - zg, 2), "净现金": round(cash, 2)},
            "market_ev_multiple": round((px - cash) / nps, 1), "model_ev_multiple": round((V - cash) / nps, 1),
            "counterfactual": {k: {"V": round(v, 2), "P/V": round(px / v, 3)} for k, v in cf.items()},
            "annual": [{"period": h.period[:4], "nopat_yi": round(h.nopat / 1e8, 1),
                        "raw_ic_yi": round((h.interest_debt + h.total_equity - h.excess_cash) / 1e8, 1),
                        "ic_yi": round(h.invested_capital / 1e8, 1) if h.invested_capital else None,
                        "debt_yi": round(h.interest_debt / 1e8, 1), "excess_cash_yi": round(h.excess_cash / 1e8, 1),
                        "equity_yi": round(h.total_equity / 1e8, 1), "wc_yi": round(h.working_capital / 1e8, 1),
                        "capex_less_da_yi": round((h.capex - h.dep_amort) / 1e8, 1)} for h in hist[-5:]]}
d = [x["dV"] for x in out["wacc_net_cash"]]
out["wacc_summary"] = {"count": len(d), "dV_median": round(statistics.median(d), 4),
                       "dV_p10": round(sorted(d)[len(d) // 10], 4)}
out["wacc_net_cash"].sort(key=lambda x: x["dV"])
(EXP / "evidence.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({"wacc_summary": out["wacc_summary"], "ic_floor": out["ic_floor"], "cases": out["cases"]},
                 ensure_ascii=False, indent=1))
