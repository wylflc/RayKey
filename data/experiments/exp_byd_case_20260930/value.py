"""比亚迪（002594）独立估值：OI-245 水平守卫个案复核（研究参考，不改口径）。

数据：年报三表取 `data/raw/financials_statements/`；2025H1、2026Q1、2026H1 三表取东财 F10
（`byd_*.json`，2026-09-30 取数）；模型带取 `data/processed/roic_bands.csv`，现价与模型 P/V 取 09-30
候选表，LG1.3 取 `../exp_oi245b_20260930/cases2.csv`。

口径：股权口径两段式折现（归母利润 × (1 − g ÷ 增量回报) 为股东现金流，高增长 N 年后按终值增长 3%、
终值回报 12% 永续，与模型 `ROIC_T = WACC + 2pp` 同），折现率 10%（另报 9%）；净现金约为 0，
利息收支已在利润里，不另加。另用 `P/B = (ROE − g) ÷ (r − g)` 交叉核对。

    python3 value.py     # → value.json、value.md
"""
import csv
import json
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
CODE = '002594'
PRICE = 83.31                       # 2026-09-30 收盘
SHARES = 9_117_198_000              # 2026-06-30 股本
R, GT, ROE_T = 0.10, 0.03, 0.12
YI = 1e8


def annual():
    out = {}
    for name in ('income', 'balance', 'cashflow'):
        with (ROOT / f'data/raw/financials_statements/{name}.csv').open(newline='', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if r['SECURITY_CODE'] == CODE and r['REPORT_DATE'][:4] >= '2019':
                    out.setdefault(r['REPORT_DATE'][:10], {}).update({k: v for k, v in r.items() if v not in ('', None)})
    return out


def interim():
    out = {}
    for name in ('lrbAjaxNew', 'zcfzbAjaxNew', 'xjllbAjaxNew'):
        for r in json.loads((EXP / f'byd_{name}.json').read_text())['data']:
            out.setdefault(r['REPORT_DATE'][:10], {}).update({k: v for k, v in r.items() if v not in ('', None)})
    return out


def num(row, *keys):
    return sum(float(row.get(k) or 0) for k in keys) / YI


def nopat(row):
    """报表口径 NOPAT = (利润总额 + 利息支出 − 利息收入) × (1 − 实际税率)。"""
    pre = num(row, 'TOTAL_PROFIT')
    tax = num(row, 'INCOME_TAX') / pre if pre else 0.0
    return (pre + num(row, 'FE_INTEREST_EXPENSE') - num(row, 'FE_INTEREST_INCOME')) * (1 - tax)


def invested(row):
    """投入资本（融资侧）= 归母权益 + 少数股东 + 有息负债（含租赁）− 货币资金 − 交易性金融资产。"""
    debt = num(row, 'SHORT_LOAN', 'NONCURRENT_LIAB_1YEAR', 'LONG_LOAN', 'BOND_PAYABLE', 'LEASE_LIAB')
    cash = num(row, 'MONETARYFUNDS', 'TRADE_FINASSET_NOTFVTPL')
    return num(row, 'TOTAL_PARENT_EQUITY', 'MINORITY_EQUITY') + debt - cash, cash - debt


def dcf(e0, g, n, roe_inc, r=R):
    """股权价值（亿元）：前 n 年利润按 g 增长、留存 g ÷ roe_inc，其后按 GT／ROE_T 永续。"""
    pv, e = 0.0, e0
    for t in range(1, n + 1):
        pv += e * (1 - g / roe_inc) / (1 + r) ** t
        if t < n:
            e *= 1 + g
    e_next = e * (1 + g) if n else e0
    tv = e_next * (1 - GT / ROE_T) / (r - GT)
    return pv + tv / (1 + r) ** n


def solve_g(target, e0, n, roe_inc, r=R):
    lo, hi = 0.0, min(roe_inc, 0.6)
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if dcf(e0, mid, n, roe_inc, r) < target else (lo, mid)
    return (lo + hi) / 2


def main():
    a, q = annual(), interim()
    fy = {d[:4]: a[d] for d in a if d.endswith('12-31')}
    h1_25, h1_26 = q['2025-06-30'], q['2026-06-30']
    ttm = lambda k: num(fy['2025'], k) - num(h1_25, k) + num(h1_26, k)
    hist = []
    for y in ('2021', '2022', '2023', '2024', '2025'):
        row = fy[y]
        ic, net_cash = invested(row)
        hist.append(dict(year=y, revenue=num(row, 'TOTAL_OPERATE_INCOME'), parent_np=num(row, 'PARENT_NETPROFIT'),
                         deduct_np=num(row, 'DEDUCT_PARENT_NETPROFIT'), rd=num(row, 'RESEARCH_EXPENSE'), nopat=nopat(row),
                         ocf=num(row, 'NETCASH_OPERATE'), capex=num(row, 'CONSTRUCT_LONG_ASSET'), ic=ic, net_cash=net_cash,
                         equity=num(row, 'TOTAL_PARENT_EQUITY')))
    ic26, cash26 = invested(h1_26)
    nopat_ttm = nopat(fy['2025']) - nopat(h1_25) + nopat(h1_26)
    now = dict(revenue_ttm=ttm('TOTAL_OPERATE_INCOME'), parent_np_ttm=ttm('PARENT_NETPROFIT'), deduct_np_ttm=ttm('DEDUCT_PARENT_NETPROFIT'),
               rd_ttm=ttm('RESEARCH_EXPENSE'), nopat_ttm=nopat_ttm, ic=ic26, net_cash=cash26, equity=num(h1_26, 'TOTAL_PARENT_EQUITY'),
               fcf_ttm=(num(fy['2025'], 'NETCASH_OPERATE') - num(h1_25, 'NETCASH_OPERATE') + num(h1_26, 'NETCASH_OPERATE'))
               - (num(fy['2025'], 'CONSTRUCT_LONG_ASSET') - num(h1_25, 'CONSTRUCT_LONG_ASSET') + num(h1_26, 'CONSTRUCT_LONG_ASSET')),
               inventory=num(h1_26, 'INVENTORY'), inventory_prev=num(h1_25, 'INVENTORY'), notes_payable=num(h1_26, 'NOTE_PAYABLE'),
               contract_liab=num(h1_26, 'CONTRACT_LIAB'))
    cap = PRICE * SHARES / YI
    now.update(market_cap=cap, pe_ttm=cap / now['parent_np_ttm'], pb=cap / now['equity'], roe_ttm=now['parent_np_ttm'] / now['equity'],
               roic_ttm=nopat_ttm / ic26, incr_roic_2023_ttm=(nopat_ttm - hist[2]['nopat']) / (ic26 - hist[2]['ic']))
    scen = [('悲观：TTM 利润不再增长', now['parent_np_ttm'], 0.0, 0, ROE_T),
            ('基准：正常化 360 亿，5 年 6%，增量回报 15%', 360.0, 0.06, 5, 0.15),
            ('乐观：回到 2024 年 400 亿，5 年 10%，增量回报 20%', 400.0, 0.10, 5, 0.20)]
    rows = []
    for label, e0, g, n, roe in scen:
        v10, v9 = dcf(e0, g, n, roe) * YI / SHARES, dcf(e0, g, n, roe, 0.09) * YI / SHARES
        rows.append(dict(label=label, e0=e0, g=g, n=n, roe_inc=roe, v_r10=v10, pv_r10=PRICE / v10, v_r9=v9, pv_r9=PRICE / v9))
    pb_check = {}
    for roe in (now['roe_ttm'], 0.14, 0.16):
        v = (roe - GT) / (R - GT) * now['equity'] * YI / SHARES
        pb_check[f'{roe:.3f}'] = dict(v=v, pv=PRICE / v)
    implied = dict(g_10y_roe20_from_360=solve_g(cap, 360.0, 10, 0.20), g_10y_roe15_from_360=solve_g(cap, 360.0, 10, 0.15),
                   zero_growth_earnings=cap * (R - GT) / (1 - GT / ROE_T))
    bands = {}
    with (ROOT / 'data/processed/roic_bands.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['security_code'] == CODE and r['status'] == 'ok' and r['report_date'] == '2026-06-30':
                bands = {k: r[k] for k in ('nopat_ps', 'shares_est', 'g0', 'growth_damp', 'growth_trust', 'peak_weight', 'incremental_roic',
                                           'reinvestment_rate', 'terminal_share', 'intrinsic_value', 'net_debt_ps', 'roic_nopat_mode')}
    with (EXP.parent / 'exp_oi245b_20260930/cases2.csv').open(newline='', encoding='utf-8') as f:
        lg = next(r for r in csv.DictReader(f) if r['code'] == CODE)
    model = dict(v=float(bands['intrinsic_value']), pv=float(lg['pv']), nopat_ps=float(bands['nopat_ps']), band=bands,
                 v_lg13=float(lg['v_LG1.3']), pv_lg13=float(lg['pv_LG1.3']), base_over_m5=float(lg['ratio']))
    model['implied_pe_model'] = model['v'] * SHARES / YI / now['parent_np_ttm']
    model['implied_pe_lg13'] = model['v_lg13'] * SHARES / YI / now['parent_np_ttm']
    res = dict(price=PRICE, shares=SHARES, history=hist, now=now, scenarios=rows, pb_check=pb_check, implied=implied, model=model)
    (EXP / 'value.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    f1 = lambda x: f'{x:,.1f}'
    md = ['# 比亚迪独立估值（2026-09-30 收盘 83.31 元）', '', '## 财务（亿元）', '',
          '| 年度 | 营收 | 归母净利 | 扣非 | 研发费用 | NOPAT（报表） | 经营现金流 | 资本开支 | 投入资本 | 净现金 |',
          '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for h in hist:
        md.append(f"| {h['year']} | {f1(h['revenue'])} | {f1(h['parent_np'])} | {f1(h['deduct_np'])} | {f1(h['rd'])} | {f1(h['nopat'])} | "
                  f"{f1(h['ocf'])} | {f1(h['capex'])} | {f1(h['ic'])} | {f1(h['net_cash'])} |")
    md.append(f"| TTM 至 2026-06 | {f1(now['revenue_ttm'])} | {f1(now['parent_np_ttm'])} | {f1(now['deduct_np_ttm'])} | {f1(now['rd_ttm'])} | "
              f"{f1(now['nopat_ttm'])} | — | — | {f1(now['ic'])} | {f1(now['net_cash'])} |")
    md += ['', f"市值 {f1(cap)} 亿；TTM 市盈率 {now['pe_ttm']:.1f}、市净率 {now['pb']:.2f}、ROE {now['roe_ttm']:.1%}、ROIC {now['roic_ttm']:.1%}；"
               f"2023→TTM 增量 ROIC {now['incr_roic_2023_ttm']:.1%}；TTM 自由现金流 {f1(now['fcf_ttm'])} 亿；"
               f"存货 {f1(now['inventory_prev'])}→{f1(now['inventory'])} 亿（同比）。", '',
           '## 情景（每股，折现率 10%／9%）', '', '| 情景 | V（10%） | P/V | V（9%） | P/V |', '| --- | ---: | ---: | ---: | ---: |']
    for s in rows:
        md.append(f"| {s['label']} | {s['v_r10']:.1f} | {s['pv_r10']:.2f} | {s['v_r9']:.1f} | {s['pv_r9']:.2f} |")
    md += ['', 'P/B–ROE 核对（10%）：' + '；'.join(f"ROE {float(k):.1%} → V {v['v']:.1f}（P/V {v['pv']:.2f}）" for k, v in pb_check.items()), '',
           f"现价隐含：从 360 亿起、增量回报 20% 时 10 年年增 {implied['g_10y_roe20_from_360']:.1%}（增量回报 15% 时 {implied['g_10y_roe15_from_360']:.1%}）；"
           f"或不增长下的永续利润 {f1(implied['zero_growth_earnings'])} 亿。", '',
           f"模型：V {model['v']:.2f}（P/V {model['pv']:.2f}，TTM 利润的 {model['implied_pe_model']:.1f} 倍），每股 NOPAT {model['nopat_ps']:.2f}；"
           f"LG1.3：V {model['v_lg13']:.2f}（P/V {model['pv_lg13']:.2f}，{model['implied_pe_lg13']:.1f} 倍），基数 ÷ M5 = {model['base_over_m5']:.2f}。"]
    (EXP / 'value.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
