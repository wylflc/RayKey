"""中际旭创（300308）2025 年 4 月是否低估：独立估值、模型拆解与事后核对（OI-249 个案；研究参考，不改口径）。

估值只用 2025-04-18 收盘后可得的信息：2024 年报与 2025 一季报当晚披露（戳日 04-21，§6.7 当晚吸收，
状态行 04-18 即用新带）。券商预测取当月公开的一份：国盛证券 2025–2027 年归母净利 81.8／105.5／125.1 亿元。
事后核对另列，不进估值。

口径：股权两段式折现（与比亚迪个案同）。股东现金流 = 归母净利 − 利润增量 ÷ 增量回报；显式期到 2034 年，
其后终值增长 3%、终值回报 12%（与模型 `ROIC_T = WACC + 2pp` 同）；折现率 10%（另报 9%）；加 2024-12-31
净现金（归母份额，三表只有年报），2025 年股东现金流全年计入。模型拆解用生产的 `intrinsic_value` 与建带脚本（生产参数，另跑关掉峰守卫的对照）。

    python3 value.py      # → value.json、value.md、bands_prod.csv、bands_nopeak.csv
"""
import csv
import glob
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from intrinsic_value import intrinsic_value  # noqa: E402

CODE = '300308'
PEERS = {'300308': '中际旭创', '300502': '新易盛', '300394': '天孚通信', '300750': '宁德时代'}
VAL_DATE = '2025-04-18'                 # 新带生效的状态日（收盘后已知 2024 年报与 2025 一季报）
PRE_DATE = '2025-04-09'                 # 关税冲击低点（年报未出，已知业绩预告）
BROKER = {2025: 81.8, 2026: 105.5, 2027: 125.1}   # 国盛证券 2025-04（亿元）
R, GT, ROE_T, ROE_NEW = 0.10, 0.03, 0.12, 0.25
YI = 1e8
PROD_FLAGS = ('--value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2002-01-01 '
              '--roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak --roic-cond-detect graded '
              '--roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 --roic-trail-weight 0 '
              '--minority-basis earnings --wc-aggregation operating --cash-caliber nonop --equity-anchor guarded '
              '--restricted-cash notes_wc --wacc-weights unlevered --reset-guard both --rd-capitalize on '
              '--fade-shape exponential --fade-lambda 0.12 --fade-horizon 50 --roic-ic-floor 0.1').split()   # §6.7 第 2 步


def fin_summary():
    out = {}
    for p in sorted(glob.glob(str(ROOT / 'data/raw/financials/20*.csv'))):
        for r in csv.DictReader(open(p, encoding='utf-8')):
            if r['security_code'] == CODE:
                out[r['report_date']] = r
    return out


def statements():
    out = {}
    for name in ('income', 'balance', 'cashflow'):
        with (ROOT / f'data/raw/financials_statements/{name}.csv').open(newline='', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if r['SECURITY_CODE'] == CODE and r['REPORT_DATE'][:4] >= '2019':
                    out.setdefault(r['REPORT_DATE'][:10], {}).update({k: v for k, v in r.items() if v not in ('', None)})
    return out


def closes(code):
    with (ROOT / f'data/raw/ohlcv/{code}.csv').open(newline='', encoding='utf-8') as f:
        return {r['date']: float(r['close']) for r in csv.DictReader(f)}


def close_on(series, d):
    return series[max(k for k in series if k <= d)]


def yi(row, key):
    v = row.get(key)
    return float(v) / YI if v not in (None, '') else 0.0


# ── 独立估值 ─────────────────────────────────────────────────────────────────────────────────────

def path_from(start, growth):
    """start = {年: 利润}，其后按 growth[i] 逐年增长到 2034。"""
    ni = dict(start)
    y = max(ni)
    for g in growth:
        ni[y + 1] = ni[y] * (1 + g)
        y += 1
    assert y == 2034 and len(ni) == 2034 - min(ni) + 1, (y, len(ni))
    return ni


SCENARIOS = {
    'A': ('券商路径延续：2025–2027 年 81.8／105.5／125.1 亿，2028 年增 12% 后七年线性降到 3%',
          path_from(BROKER, [0.12 - 0.015 * i for i in range(7)])),
    'B': ('两年高增后走平：2025 年 81.8、2026 年 95 亿，此后 95 亿不增',
          path_from({2025: 81.8, 2026: 95.0}, [0.0] * 8)),
    'C': ('周期回落：2025 年 75、2026 年 60、2027 年 45 亿（净资产回报约 18%），此后年增 3%',
          path_from({2025: 75.0, 2026: 60.0, 2027: 45.0}, [GT] * 7)),
    'D': ('需求断崖：2025 年 70、2026 年 30、2027 年 25、2028 年 30 亿（回到 AI 前约 11% 的回报），此后年增 3%',
          path_from({2025: 70.0, 2026: 30.0, 2027: 25.0, 2028: 30.0}, [GT] * 6)),
}
WEIGHTS = {'A': 0.30, 'B': 0.30, 'C': 0.25, 'D': 0.15}        # 示例权重，见 value.md 说明


def equity_value(ni, r, net_cash, shares, roe_new=ROE_NEW, t0=VAL_DATE):
    """股东现金流折现（亿元 → 元／股）：起点现金取 2024-12-31，2025 年现金流全年计入。"""
    base = date.fromisoformat(t0)
    pv = 0.0
    years = sorted(ni)
    for y in years:
        nxt = ni.get(y + 1, ni[y] * (1 + GT))
        reinvest = max(0.0, nxt - ni[y]) / (roe_new if y < years[-1] else ROE_T)
        fcfe = ni[y] - reinvest
        t = (date(y, 12, 31) - base).days / 365.25
        pv += fcfe / (1 + r) ** t
    last = years[-1]
    tv = ni[last] * (1 + GT) * (1 - GT / ROE_T) / (r - GT)
    pv += tv / (1 + r) ** ((date(last, 12, 31) - base).days / 365.25)
    return (pv + net_cash) * YI / shares


def solve(f, lo, hi, target, n=80):
    for _ in range(n):
        mid = (lo + hi) / 2
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ── 模型拆解 ─────────────────────────────────────────────────────────────────────────────────────

def build_bands():
    out = {}
    for tag, extra in (('prod', []), ('nopeak', ['--roic-peak-k', '99'])):
        path = EXP / f'bands_{tag}.csv'
        env = dict(os.environ, RK_STMT_GAP_LOG=str(EXP / f'.gaps_{tag}.csv'))
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_historical_valuation_bands.py'), '--codes', ','.join(PEERS),
                        *PROD_FLAGS, *extra, '--out-bands', str(path), '--out-daily', str(EXP / f'.daily_{tag}.csv')],
                       cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        out[tag] = {(r['security_code'], r['report_date']): r for r in csv.DictReader(path.open(encoding='utf-8'))}
        for p in (EXP / f'.gaps_{tag}.csv', EXP / f'.daily_{tag}.csv'):
            p.unlink(missing_ok=True)
    return out


def model_value(nopat, roic0, g0, net_debt):
    res = intrinsic_value(nopat, roic0, g0, R, roe_terminal=min(0.12, roic0), g_terminal=GT, n=10, n1=0,
                          roe_lam=0.12, horizon=50, consistent=True, maintenance_ratio=0.0)
    return res.intrinsic_value - net_debt


def main():
    fs, st = fin_summary(), statements()
    px = closes(CODE)
    p_val, p_pre = close_on(px, VAL_DATE), close_on(px, PRE_DATE)
    q1 = st['2024-12-31']
    shares = 1121166509                           # 生产带 shares_est（2024 年 10 转 4 后）
    parent_share = yi(q1, 'TOTAL_PARENT_EQUITY') / yi(q1, 'TOTAL_EQUITY')
    net_cash = (yi(q1, 'MONETARYFUNDS') + yi(q1, 'TRADE_FINASSET_NOTFVTPL') - yi(q1, 'SHORT_LOAN') - yi(q1, 'LONG_LOAN')
                - yi(q1, 'NONCURRENT_LIAB_1YEAR') - yi(q1, 'BOND_PAYABLE')) * parent_share

    # 一、当时可得的事实
    hist = []
    for y in range(2019, 2025):
        a, s = fs[f'{y}-12-31'], st[f'{y}-12-31']
        rev, cost = yi(s, 'TOTAL_OPERATE_INCOME'), yi(s, 'OPERATE_COST')
        hist.append(dict(year=y, revenue=rev, ni=float(a['parent_netprofit']) / YI, gm=(rev - cost) / rev, roe=float(a['weightavg_roe']) / 100,
                         ni_yoy=float(a['netprofit_yoy']) / 100, rev_yoy=float(a['revenue_yoy']) / 100,
                         ocf=yi(s, 'NETCASH_OPERATE'), capex=yi(s, 'CONSTRUCT_LONG_ASSET'), inventory=yi(s, 'INVENTORY'),
                         receivables=yi(s, 'ACCOUNTS_RECE'), equity=yi(s, 'TOTAL_PARENT_EQUITY')))
    q1s = fs['2025-03-31']
    ttm_ni = float(fs['2024-12-31']['parent_netprofit']) / YI + float(q1s['parent_netprofit']) / YI - float(fs['2024-03-31']['parent_netprofit']) / YI
    eps_ttm = ttm_ni * YI / shares
    eps_fwd = {y: v * YI / shares for y, v in BROKER.items()}
    cagr3 = (BROKER[2027] / hist[-1]['ni']) ** (1 / 3) - 1
    cagr2f = (BROKER[2027] / BROKER[2025]) ** 0.5 - 1
    market = dict(price_val=p_val, price_pre=p_pre, shares=shares, cap=p_val * shares / YI, net_cash=net_cash,
                  ttm_ni=ttm_ni, eps_ttm=eps_ttm, pe_ttm=p_val / eps_ttm, pe_2025e=p_val / eps_fwd[2025], pe_2026e=p_val / eps_fwd[2026],
                  g_2025e=BROKER[2025] / hist[-1]['ni'] - 1, cagr_2024_2027e=cagr3, cagr_2025_2027e=cagr2f,
                  peg_ttm_cagr3=p_val / eps_ttm / (cagr3 * 100), peg_fwd_cagr2=p_val / eps_fwd[2025] / (cagr2f * 100),
                  q1_ni=float(q1s['parent_netprofit']) / YI, q1_ni_yoy=float(q1s['netprofit_yoy']) / 100,
                  q1_rev_yoy=float(q1s['revenue_yoy']) / 100, q1_gm=float(q1s['gross_margin']) / 100)

    # 二、独立估值
    scen = {}
    for k, (desc, ni) in SCENARIOS.items():
        scen[k] = dict(desc=desc, ni={str(y): round(v, 1) for y, v in ni.items() if y <= 2029},
                       v10=equity_value(ni, 0.10, net_cash, shares), v09=equity_value(ni, 0.09, net_cash, shares),
                       v10_roe20=equity_value(ni, 0.10, net_cash, shares, roe_new=0.20))
    for k in scen:
        scen[k]['pv10'] = p_val / scen[k]['v10']
    wv = {r_: sum(WEIGHTS[k] * scen[k][f'v{r_}'] for k in scen) for r_ in ('10', '09')}
    up = {k: WEIGHTS[k] / (WEIGHTS['A'] + WEIGHTS['B']) for k in ('A', 'B')}
    dn = {k: WEIGHTS[k] / (WEIGHTS['C'] + WEIGHTS['D']) for k in ('C', 'D')}
    v_up = sum(up[k] * scen[k]['v10'] for k in up)
    v_dn = sum(dn[k] * scen[k]['v10'] for k in dn)
    breakeven_down = (v_up - p_val) / (v_up - v_dn)            # C+D 合计概率达到它时，期望值 = 现价
    flat = solve(lambda x: equity_value({2025: BROKER[2025], **{y: x for y in range(2026, 2035)}}, 0.10, net_cash, shares, roe_new=1e9),
                 1.0, 400.0, p_val)
    grow = solve(lambda g: equity_value(path_from({2025: BROKER[2025]},
                                                  [g] * 4 + [g - (g - GT) * i / 5 for i in range(1, 6)]), 0.10, net_cash, shares),
                 -0.5, 1.0, p_val)
    valuation = dict(scenarios=scen, weights=WEIGHTS, weighted=wv, upside_mix=v_up, downside_mix=v_dn,
                     breakeven_downside_prob=breakeven_down, implied_flat_ni=flat, implied_growth_2026_2029=grow)

    # 三、模型拆解
    bands = build_bands()
    prod = {r['report_date']: r for r in csv.DictReader((ROOT / 'data/processed/roic_bands.csv').open(encoding='utf-8'))
            if r['security_code'] == CODE}
    b, n = bands['prod'][(CODE, '2025-03-31')], bands['nopeak'][(CODE, '2025-03-31')]
    assert b['intrinsic_value'] == prod['2025-03-31']['intrinsic_value'], (b['intrinsic_value'], prod['2025-03-31']['intrinsic_value'])
    nd = float(b['net_debt_ps'])
    nopat_g, nopat_n, roic0, g0, iroic, rr = (float(b['nopat_ps']), float(n['nopat_ps']), float(b['roic0']), float(b['g0']),
                                              float(b['incremental_roic']), float(b['reinvestment_rate']))
    k = nopat_n / nopat_g
    steps = [('现行模型（峰守卫全开）', model_value(nopat_g, roic0, g0, nd)),
             ('关峰守卫：每股 NOPAT 取当期', model_value(nopat_n, roic0, g0, nd)),
             ('再把增长用的回报改为当期（roic0 同比例，即 §6.5.2.2 采用研究数的做法）', model_value(nopat_n, roic0 * k, g0, nd)),
             ('再把 g0 上限放到 40%（资本腿 min(增量 ROIC, 40%) × 再投资率）', model_value(nopat_n, roic0 * k, min(iroic, 0.40) * rr, nd))]
    decomposition = dict(band=dict(report_date=b['report_date'], available_at=b['available_at'], nopat_ps=nopat_g, nopat_ps_nopeak=nopat_n,
                                   eps_ttm=float(b['eps_ttm']), roic0=roic0, roic0_current=roic0 * k, g0=g0, incremental_roic=iroic,
                                   reinvestment_rate=rr, peak_weight=float(b['peak_weight']), growth_trust=float(b['growth_trust']),
                                   net_debt_ps=nd, v_band=float(b['intrinsic_value']), v_nopeak_band=float(n['intrinsic_value'])),
                         steps=[dict(step=s, v=v, pv=p_val / v) for s, v in steps])
    peers = []
    for code, name in PEERS.items():
        cl = closes(code)
        for (c, rd), row in sorted(bands['prod'].items()):
            if c != code or not ('2024-09-30' <= rd <= '2025-03-31' if code != '300750' else '2018-09-30' <= rd <= '2019-09-30'):
                continue
            nr = bands['nopeak'].get((c, rd))
            d = max(k_ for k_ in cl if k_ < row['available_at'])      # 带生效的状态日
            peers.append(dict(code=code, name=name, report_date=rd, available_at=row['available_at'], day=d, price=cl[d],
                              v=float(row['intrinsic_value']), v_nopeak=float(nr['intrinsic_value']) if nr else None,
                              peak_weight=float(row['peak_weight']), trough_weight=float(row['trough_weight']),
                              growth_trust=float(row['growth_trust']), eps_ttm=float(row['eps_ttm'] or 0),
                              nopat_ps=float(row['nopat_ps']), nopat_ps_nopeak=float(nr['nopat_ps']) if nr else None))

    # 四、事后核对（不进估值）
    fy25, h126 = fs['2025-12-31'], fs['2026-06-30']
    ttm_h126 = (float(fy25['parent_netprofit']) - float(fs['2025-06-30']['parent_netprofit']) + float(h126['parent_netprofit'])) / YI
    after = dict(ni_2025=float(fy25['parent_netprofit']) / YI, ni_2025_yoy=float(fy25['netprofit_yoy']) / 100,
                 rev_2025=float(fy25['total_operate_income']) / YI, gm_2025=float(fy25['gross_margin']) / 100,
                 ni_h1_2026=float(h126['parent_netprofit']) / YI, ni_h1_2026_yoy=float(h126['netprofit_yoy']) / 100, ttm_h1_2026=ttm_h126,
                 price_2025_12_31=close_on(px, '2025-12-31'), price_2026_08_28=close_on(px, '2026-08-28'),
                 v_band_latest=float(prod[max(prod)]['intrinsic_value']), latest_band=max(prod))
    res = dict(code=CODE, val_date=VAL_DATE, broker=BROKER, history=hist, market=market, valuation=valuation,
               decomposition=decomposition, peers=peers, after=after)
    (EXP / 'value.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    write_md(res)


def write_md(res):
    m, v, d, a = res['market'], res['valuation'], res['decomposition'], res['after']
    pct = lambda x, n=0: f'{x * 100:.{n}f}%'
    out = [f"# 中际旭创 2025 年 4 月：独立估值与模型拆解（估值日 {res['val_date']}）", '',
           '## 一、当时可得的事实（亿元）', '',
           '| 年 | 营收 | 营收增速 | 归母净利 | 净利增速 | 毛利率 | ROE | 经营现金流 | 资本开支 | 存货 | 应收 | 归母净资产 |',
           '| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for h in res['history']:
        out.append(f"| {h['year']} | {h['revenue']:.1f} | {pct(h['rev_yoy'])} | {h['ni']:.2f} | {pct(h['ni_yoy'])} | {pct(h['gm'], 1)} | "
                   f"{pct(h['roe'], 1)} | {h['ocf']:.1f} | {h['capex']:.1f} | {h['inventory']:.1f} | {h['receivables']:.1f} | {h['equity']:.1f} |")
    out += ['', f"2025 一季度：归母净利 {m['q1_ni']:.2f} 亿（{pct(m['q1_ni_yoy'], 1)}），营收 {pct(m['q1_rev_yoy'], 1)}，毛利率 {pct(m['q1_gm'], 1)}。"
            f"TTM 归母净利 {m['ttm_ni']:.1f} 亿；2024-12-31 净现金（归母份额）{m['net_cash']:.1f} 亿。", '',
            f"估值日收盘 {m['price_val']:.2f} 元（{PRE_DATE} 低点 {m['price_pre']:.2f} 元），市值 {m['cap']:.0f} 亿，股本 {m['shares'] / YI:.2f} 亿股。", '',
            '| 指标 | 数值 |', '| --- | ---: |',
            f"| 市盈率（TTM） | {m['pe_ttm']:.1f} |", f"| 市盈率（2025 年券商预测） | {m['pe_2025e']:.1f} |", f"| 市盈率（2026 年券商预测） | {m['pe_2026e']:.1f} |",
            f"| 2025 年预测增速 | {pct(m['g_2025e'])} |", f"| 2024→2027 年预测复合增速 | {pct(m['cagr_2024_2027e'], 1)} |",
            f"| PEG（TTM 市盈率 ÷ 2024→2027 复合增速） | {m['peg_ttm_cagr3']:.2f} |",
            f"| PEG（2025 年预测市盈率 ÷ 2025→2027 复合增速） | {m['peg_fwd_cagr2']:.2f} |", '',
            '## 二、独立估值（折现率 10%，另报 9%；增量回报 25%，另报 20%）', '',
            '| 情景 | 利润路径 | 每股价值 r 10% | r 9% | 增量回报 20% | 现价 ÷ 价值 |', '| --- | --- | ---: | ---: | ---: | ---: |']
    for k, s in v['scenarios'].items():
        out.append(f"| {k} | {s['desc']} | {s['v10']:.1f} | {s['v09']:.1f} | {s['v10_roe20']:.1f} | {s['pv10']:.2f} |")
    out += ['', f"示例权重 A {pct(v['weights']['A'])}、B {pct(v['weights']['B'])}、C {pct(v['weights']['C'])}、D {pct(v['weights']['D'])}："
            f"期望价值 {v['weighted']['10']:.1f} 元（r 9% 为 {v['weighted']['09']:.1f}），现价 ÷ 期望价值 {m['price_val'] / v['weighted']['10']:.2f}。", '',
            f"盈亏平衡：上行组（A、B 按示例比例）价值 {v['upside_mix']:.1f}、下行组（C、D）{v['downside_mix']:.1f}；"
            f"下行组概率达到 {pct(v['breakeven_downside_prob'])} 时期望价值才等于现价。", '',
            f"反推：2025 年 81.8 亿之后若利润持平到 2034 年、再按终值 3% 增长，现价对应的利润水平为 {v['implied_flat_ni']:.1f} 亿；"
            f"若按增长计，现价对应 2026–2029 年每年 {pct(v['implied_growth_2026_2029'], 1)}、其后五年线性降到 3%。", '',
            '## 三、模型拆解（2025-03-31 带，生效日 2025-04-18）', '',
            f"带内：每股 NOPAT {d['band']['nopat_ps']:.2f}（关峰守卫 {d['band']['nopat_ps_nopeak']:.2f}；TTM EPS {d['band']['eps_ttm']:.2f}），"
            f"峰守卫权重 {d['band']['peak_weight']:.2f}，增长态信任度 {d['band']['growth_trust']:.2f}，roic0 {pct(d['band']['roic0'], 2)}（当期约 {pct(d['band']['roic0_current'], 1)}），"
            f"g0 {pct(d['band']['g0'])}（增量 ROIC {pct(d['band']['incremental_roic'], 1)} × 再投资率 {d['band']['reinvestment_rate']:.2f}，上限 25%）。", '',
            '| 逐步放开 | V | `P/V`（现价） |', '| --- | ---: | ---: |']
    for s in d['steps']:
        out.append(f"| {s['step']} | {s['v']:.2f} | {s['pv']:.2f} |")
    out += ['', '## 四、同类与宁德时代（生效日收盘价；关峰守卫同上）', '',
            '| 代码 | 名称 | 报告期 | 生效日 | 收盘 | V | `P/V` | 关峰守卫 V | `P/V` | 峰守卫 w | 谷守卫 v | 信任度 λ | TTM EPS | 每股 NOPAT（关峰守卫） |',
            '| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for p in res['peers']:
        out.append(f"| {p['code']} | {p['name']} | {p['report_date']} | {p['day']} | {p['price']:.2f} | {p['v']:.2f} | {p['price'] / p['v']:.2f} | "
                   f"{p['v_nopeak']:.2f} | {p['price'] / p['v_nopeak']:.2f} | {p['peak_weight']:.2f} | {p['trough_weight']:.2f} | {p['growth_trust']:.2f} | "
                   f"{p['eps_ttm']:.2f} | {p['nopat_ps']:.2f}（{p['nopat_ps_nopeak']:.2f}） |")
    out += ['', '## 五、事后核对（不进估值）', '',
            f"2025 年归母净利 {a['ni_2025']:.1f} 亿（{pct(a['ni_2025_yoy'])}，券商 4 月预测 81.8 亿），营收 {a['rev_2025']:.0f} 亿，毛利率 {pct(a['gm_2025'], 1)}；"
            f"2026 上半年归母净利 {a['ni_h1_2026']:.1f} 亿（{pct(a['ni_h1_2026_yoy'])}），TTM {a['ttm_h1_2026']:.0f} 亿。"
            f"股价 2025-12-31 {a['price_2025_12_31']:.2f} 元、2026-08-28 {a['price_2026_08_28']:.2f} 元；最新带（{a['latest_band']}）V {a['v_band_latest']:.2f}。", '']
    (EXP / 'value.md').write_text('\n'.join(out), encoding='utf-8')


if __name__ == '__main__':
    main()
