"""爱玛增长复核（2026-09-25，v4.206 生产带之上）：资本腿各口径的 g0 与研究口径 V。

生产带已采用研究数 16.40 亿；这里只换 g0（及 OI-217 的 WACC），企业价值按同一引擎相对生产带取比例，
股权桥照带（与 apply_forecast_band_overlay 同法）。年度输入取 v4.206 口径 roic_inputs。
    python3 data/experiments/exp_aima_growth_20260925/scenarios.py
"""
import csv
import json
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import roic_inputs  # noqa: E402
from apply_forecast_band_overlay import FADE, TERMINAL_EXCESS, equity_from_ev  # noqa: E402
from intrinsic_value import intrinsic_value  # noqa: E402

CODE, CLOSE, CAP = '603529', 20.88, 0.40


def main():
    band = next(r for r in csv.DictReader((ROOT / 'data/processed/a_share_pool_model_bands_adopted.csv').open(encoding='utf-8-sig'))
                if r['security_code'] == CODE)
    f = lambda k: float(band[k])  # noqa: E731
    nps, roic0, g_band, w_band, g_t = f('nopat_ps'), f('roic0'), f('g0'), f('wacc'), f('g_terminal')
    years = {p: y for p, y in roic_inputs.load_statements({CODE}, ic_floor=0.1, caliber='nonop', restricted_cash='notes')[CODE].items()
             if p.endswith('12-31')}
    y = lambda p: years[f'{p}-12-31']  # noqa: E731
    rr = f('reinvestment_rate')
    shares = f('shares_est')
    research_yi = nps * shares / 1e8

    def ev(g, w):
        return intrinsic_value(nps, roic0, g, w, roe_terminal=min(w + TERMINAL_EXCESS, roic0), g_terminal=g_t, **FADE).intrinsic_value

    base_ev = ev(g_band, w_band)

    def value(g, w=w_band):
        # 带已除权归一化（§6.4）：同一现金与送转因子折到现价口径
        iv = equity_from_ev(band, f('ev_ps') * ev(g, w) / base_ev, f('net_debt_ps')) * f('exright_factor') - f('exright_cash')
        return round(iv, 2), round(CLOSE / iv, 3)

    def iroic(a, b, end_nopat=None):
        d_ic = y(b).invested_capital - y(a).invested_capital
        return ((end_nopat if end_nopat is not None else y(b).nopat) - y(a).nopat) / d_ic

    rows = []
    def add(name, g_iroic, note):
        g = min(max(g_iroic, 0.0), CAP) * rr
        rows.append(dict(scenario=name, iroic=round(g_iroic, 4), g0=round(g, 4), V=value(g)[0], PV=value(g)[1],
                         V_wacc10=value(g, 0.10)[0], PV_wacc10=value(g, 0.10)[1], note=note))
    add('生产（2021→2025 首尾）', iroic('2021', '2025'), '起点为 2021 年原材料涨价低谷（NOPAT 5.56 亿），2022 年修复到 16.87 亿、IC 只增 5.1 亿')
    add('终点换研究数（2021→研究 16.40）', iroic('2021', '2025', research_yi * 1e8), '研究数替换终点 NOPAT，起点仍为低谷')
    add('起点移到 2022（2022→2025）', iroic('2022', '2025'), '剔除低谷修复，只看修复后新投资本')
    add('起点 2022、终点研究数', iroic('2022', '2025', research_yi * 1e8), '研究数 16.40 低于 2022 年 16.87，新投资本回报为负，资本腿取 0')
    # v4.206 一致性：质押存单已按经营资产进投入资本，而营运资金含其担保的应付票据、不含存单；存单计入营运资金后的再投资率
    first, last = y(band['wc_first_period'][:4]), y(band['wc_last_period'][:4])
    ordered = [v for p, v in sorted(years.items()) if band['wc_first_period'] <= p <= band['wc_last_period']]
    nopat_sum = sum(v.nopat for v in ordered[1:])
    net_capex = sum(v.capex - v.dep_amort for v in ordered[1:])
    rr_pledged = (net_capex + (last.working_capital + last.restricted_cash) - (first.working_capital + first.restricted_cash)) / nopat_sum
    assert abs((net_capex + last.working_capital - first.working_capital) / nopat_sum - rr) < 1e-3
    for name, ir in (('再投资率含质押存单（2021→2025）', iroic('2021', '2025')), ('再投资率含质押存单、终点研究数', iroic('2021', '2025', research_yi * 1e8)),
                     ('再投资率含质押存单、起点 2022', iroic('2022', '2025'))):
        g = min(max(ir, 0.0), CAP) * rr_pledged
        rows.append(dict(scenario=name, iroic=round(ir, 4), g0=round(g, 4), rr=round(rr_pledged, 4), V=value(g)[0], PV=value(g)[1],
                         V_wacc10=value(g, 0.10)[0], PV_wacc10=value(g, 0.10)[1], note='营运资金 + 质押存单'))
    for g in (0.0, 0.03, 0.05, 0.08):
        rows.append(dict(scenario=f'g0 = {g:.0%}', iroic=None, g0=g, V=value(g)[0], PV=value(g)[1],
                         V_wacc10=value(g, 0.10)[0], PV_wacc10=value(g, 0.10)[1], note='固定 g0 对照'))
    series = {p[:4]: dict(nopat_yi=round(v.nopat / 1e8, 2), ic_yi=round(v.invested_capital / 1e8, 2),
                          net_capex_yi=round((v.capex - v.dep_amort) / 1e8, 2), wc_yi=round(v.working_capital / 1e8, 2),
                          pledged_yi=round(v.restricted_cash / 1e8, 2)) for p, v in sorted(years.items()) if p >= '2019'}
    out = dict(band=dict(nopat_ps=nps, research_nopat_yi=round(research_yi, 2), roic0=roic0, g0=g_band, iroic=f('incremental_roic'),
                         rr=rr, wacc=w_band, iv=f('intrinsic_value'), window=[band['wc_first_period'], band['wc_last_period']]),
               series=series, scenarios=rows)
    (EXP / 'scenarios.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    for r in rows:
        ir = '' if r['iroic'] is None else format(r['iroic'], '.1%')
        print(f"{r['scenario']:<28} iROIC {ir:>7} g0 {r['g0']:.2%}  V {r['V']:.2f} P/V {r['PV']:.3f}  | WACC10% V {r['V_wacc10']:.2f} P/V {r['PV_wacc10']:.3f}")


if __name__ == '__main__':
    main()
