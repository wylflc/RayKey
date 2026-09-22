#!/usr/bin/env python3
"""Causal temperature features, corporate-action audit and forward-return diagnostics."""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import calendar
import csv
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import corporate_actions as ca
from backtest_valuation_strategy import adjusted_moving_averages, quote_action_factors
from cbbi_temperature_data import read_csv, write_csv

EXP = ROOT / 'data/experiments/exp_cbbi_temperature_20260922'
NAMES_EN = {'000300': 'CSI 300', '600519': 'Kweichow Moutai', '000651': 'Gree Electric',
            '300750': 'CATL', '300308': 'Zhongji Innolight', '600036': 'China Merchants Bank',
            '601318': 'Ping An Insurance'}
BIN_NAMES = ['0–20', '20–40', '40–60', '60–80', '80–100']


def finite(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else float('nan')
    except (ValueError, TypeError):
        return float('nan')


def add_months(day, months):
    d = date.fromisoformat(day)
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1])).isoformat()


def total_return_frame(quotes, events):
    """Reinvest net actual distributions at the next available quote, including suspensions."""
    frame = pd.DataFrame(quotes).set_index('date').sort_index()
    for c in ['open', 'close', 'high', 'low', 'volume', 'turnover_pct']:
        frame[c] = pd.to_numeric(frame[c], errors='coerce')
    days = list(frame.index)
    close = frame['close'].to_numpy()
    if np.any(~np.isfinite(close)) or np.any(close <= 0) or frame.index.duplicated().any():
        raise ValueError('Nonpositive, duplicate, or missing raw close')
    factors = list(quote_action_factors(days, events))
    growth = np.ones(len(days))
    unit = np.ones(len(days))
    for i, (multiplier, netcash) in enumerate(factors):
        if i:
            growth[i] = (close[i] * multiplier + netcash) / close[i - 1]
            unit[i] = unit[i - 1] * multiplier
    if np.any(growth <= 0):
        raise ValueError('Nonpositive total-return factor')
    frame['total_return'] = 100 * np.cumprod(growth)
    frame['gross_return'] = growth - 1
    frame['volume_units'] = frame['volume'].to_numpy() / unit
    mas = adjusted_moving_averages(dict(zip(days, close)), events, windows=(60,))
    frame['ma60_price_basis'] = [mas.get(d, {}).get(60, np.nan) for d in days]
    return frame


def past_month_rank(values, lookback=60, minimum=36):
    """Midrank against past month-end observations; today's entire month is excluded."""
    series = pd.Series(values, dtype=float)
    periods = pd.to_datetime(series.index).to_period('M')
    month_last = series.groupby(periods, sort=True).last()
    # groupby.last skips missing values, so explicitly preserve the actual month-end value.
    month_last = pd.Series([series.iloc[np.flatnonzero(periods == p)[-1]] for p in month_last.index],
                           index=month_last.index)
    result = np.full(len(series), np.nan)
    for p in periods.unique():
        history = month_last[month_last.index < p].dropna().iloc[-lookback:].to_numpy()
        if len(history) < minimum:
            continue
        idx = np.flatnonzero(periods == p)
        current = series.iloc[idx].to_numpy()
        result[idx] = 100 * ((history[None, :] < current[:, None]).sum(axis=1)
                            + .5 * (history[None, :] == current[:, None]).sum(axis=1)) / len(history)
        result[idx[~np.isfinite(current)]] = np.nan
    return pd.Series(result, index=series.index)


def stocks_valuation(days, closes, reports, share_rows, bond_rows):
    reports = sorted([r for r in reports if r.get('notice_date') and r.get('report_date')],
                     key=lambda r:(r['notice_date'], r['report_date']))
    shares = sorted(share_rows, key=lambda r:r['effective_date'])
    sd = [r['effective_date'] for r in shares]
    bonds = sorted(bond_rows, key=lambda r:r['observed_on'])
    bd = [r['observed_on'] for r in bonds]
    known, cursor, output = {}, 0, []
    for day, price in zip(days, closes):
        while cursor < len(reports) and reports[cursor]['notice_date'] < day:
            row = reports[cursor]
            if row['report_date'] < day:
                known[row['report_date']] = row
            cursor += 1
        si = bisect_right(sd, day) - 1
        bi = bisect_left(bd, day) - 1
        res = dict(valuation_raw=np.nan, earnings_yield=np.nan, ttm_profit=np.nan,
                   total_shares=np.nan, finance_period='', finance_notice='', bond_observed_on='')
        if not known or si < 0 or bi < 0:
            output.append(res)
            continue
        period = max(known)
        report = known[period]
        age = (date.fromisoformat(day) - date.fromisoformat(period)).days
        total = finite(shares[si]['total_shares'])
        bond = finite(bonds[bi]['bond_yield'])
        bond_age = (date.fromisoformat(day) - date.fromisoformat(bd[bi])).days
        y, md = int(period[:4]), period[5:]
        required = [period] if md == '12-31' else [period, f'{y-1}-12-31', f'{y-1}-{md}']
        if age > 550 or bond_age > 10 or not total > 0 or not np.isfinite(bond) or any(p not in known for p in required):
            output.append(res)
            continue
        nums = [finite(known[p]['parent_netprofit']) for p in required]
        ttm = nums[0] if len(nums) == 1 else nums[0] + nums[1] - nums[2]
        notices = [known[p]['notice_date'] for p in required]
        res.update(ttm_profit=ttm, total_shares=total, finance_period=period,
                   finance_notice=max(notices), bond_observed_on=bd[bi])
        if ttm > 0 and price > 0:
            earnings_yield = ttm / (total * price)
            res.update(earnings_yield=earnings_yield, valuation_raw=bond-earnings_yield)
        output.append(res)
    return pd.DataFrame(output, index=days)


def index_valuation(days, rows):
    rows = sorted(rows, key=lambda r:r['observed_on'])
    rd = [r['observed_on'] for r in rows]
    out = []
    for day in days:
        i = bisect_left(rd, day) - 1
        value, observed, ey = np.nan, '', np.nan
        if i >= 0:
            r = rows[i]
            age = (date.fromisoformat(day) - date.fromisoformat(rd[i])).days
            pe, bond = finite(r['pe_ttm']), finite(r['bond_yield'])
            if age <= 45 and pe > 0 and np.isfinite(bond):
                ey, observed = 1/pe, rd[i]
                value = bond-ey
        out.append(dict(valuation_raw=value, earnings_yield=ey, finance_notice=observed))
    return pd.DataFrame(out, index=days)


def features(frame, config, lookback=None, reset=None):
    df = frame.loc[reset:].copy() if reset else frame.copy()
    tr = df['total_return']
    q = config['rank_months'] if lookback is None else lookback
    kwargs = dict(lookback=q, minimum=config['rank_min_months'])
    df['score_valuation'] = past_month_rank(df['valuation_raw'], **kwargs)
    parts = []
    for window in config['price_windows']:
        raw = np.log(tr / tr.rolling(window, min_periods=window).mean())
        df[f'extension_{window}'] = raw
        parts.append(past_month_rank(raw, **kwargs))
    df['score_price'] = pd.concat(parts, axis=1).mean(axis=1, skipna=False)
    short, long = config['activity_windows']
    v = df['volume_units']
    df['activity_raw'] = np.log(v.rolling(short, min_periods=short).mean()
                                / v.rolling(long, min_periods=long).mean())
    df['activity_raw'] = df['activity_raw'].where(np.isfinite(df['activity_raw']))
    df['score_activity'] = past_month_rank(df['activity_raw'], **kwargs)
    df['heat'] = df[['score_valuation', 'score_price', 'score_activity']].mean(axis=1, skipna=False)
    df['price_activity'] = df[['score_price', 'score_activity']].mean(axis=1, skipna=False)
    return df


def measure_forward(frame, market_days, months):
    days = list(frame.index)
    tr = frame['total_return'].to_dict()
    output = []
    for signal in days:
        start_i = bisect_right(market_days, signal)
        row = dict(signal_date=signal, months=months, start='', end='', status='unmatured',
                   forward_return=np.nan, forward_mdd=np.nan)
        if start_i >= len(market_days):
            output.append(row)
            continue
        start = market_days[start_i]
        row['start'] = start
        if start not in tr or not np.isfinite(tr[start]):
            row['status'] = 'missing_execution_quote'
            output.append(row)
            continue
        target = add_months(start, months)
        end_i = bisect_left(market_days, target)
        if end_i >= len(market_days):
            output.append(row)
            continue
        end = market_days[end_i]
        row['end'] = end
        if end not in tr or not np.isfinite(tr[end]):
            row['status'] = 'missing_terminal_quote'
            output.append(row)
            continue
        i, j = bisect_left(days, start), bisect_right(days, end)
        path = frame['total_return'].iloc[i:j].dropna().to_numpy()
        dd = np.min(path / np.maximum.accumulate(path) - 1)
        row.update(status='complete', forward_return=tr[end]/tr[start]-1, forward_mdd=dd)
        output.append(row)
    return pd.DataFrame(output).set_index('signal_date')


def bin_number(values):
    a = np.asarray(values, dtype=float)
    b = np.searchsorted([20, 40, 60, 80], a, side='left')
    b[a >= 80] = 4  # 80 belongs to the prespecified hot tail; 20 to the cold tail.
    b[~np.isfinite(a)] = -1
    return b


def sample_masks(frame, scores, forward, market_days):
    days = list(frame.index)
    bins = bin_number(scores)
    available = np.isfinite(scores)
    market_ends = {d for i, d in enumerate(market_days[:-1]) if d[:7] != market_days[i+1][:7]}
    month = np.array([d in market_ends for d in days]) & available
    episode = np.zeros(len(days), dtype=bool)
    nonoverlap = np.zeros(len(days), dtype=bool)
    active = [False] * 5
    busy_until = [''] * 5
    for i, day in enumerate(days):
        b = bins[i]
        if b >= 0 and not active[b]:
            episode[i] = True
            active[b] = True
            if day > busy_until[b]:
                nonoverlap[i] = True
                # Even missing/unmatured observations reserve their intended horizon.
                end = forward.iloc[i]['end']
                start = forward.iloc[i]['start'] or day
                busy_until[b] = end or add_months(start, int(forward.iloc[i]['months']))
        ma = frame.iloc[i]['ma60_price_basis']
        if np.isfinite(ma) and frame.iloc[i]['close'] < ma:
            active = [False] * 5
    return dict(daily=available, month_end=month, MA60_episode_first=episode,
                MA60_episode_nonoverlap=nonoverlap)


def summarize(code, variant, scores, forward, masks):
    bins = bin_number(scores)
    out = []
    for sampling, mask in masks.items():
        for b in range(5):
            selected = forward.loc[mask & (bins == b)]
            complete = selected[selected['status'] == 'complete']
            ret = complete['forward_return']
            out.append(dict(code=code, variant=variant, sampling=sampling,
                months=int(forward['months'].iloc[0]), bin=b, bin_label=BIN_NAMES[b],
                signals=len(selected), complete=len(complete),
                unmatured=int((selected['status'] == 'unmatured').sum()),
                missing_execution=int((selected['status'] == 'missing_execution_quote').sum()),
                missing_terminal=int((selected['status'] == 'missing_terminal_quote').sum()),
                median_return=ret.median(), p25_return=ret.quantile(.25), p75_return=ret.quantile(.75),
                loss_rate=(ret < 0).mean() if len(ret) else np.nan,
                median_mdd=complete['forward_mdd'].median(),
                years=len(set(d[:4] for d in complete.index)),
                first=complete.index[0] if len(complete) else '', last=complete.index[-1] if len(complete) else ''))
    return out


def block_diagnostics(code, scores, forward, month_mask, config):
    sample = forward.loc[month_mask].copy()
    sample['heat'] = scores.loc[sample.index]
    sample = sample[sample['status'] == 'complete'].dropna(subset=['heat', 'forward_return'])
    n = len(sample)
    if n < 4:
        return dict(code=code, month_samples=n)
    x, y = sample['heat'].to_numpy(), sample['forward_return'].to_numpy()
    monthly = sample[['heat', 'forward_return']].copy()
    monthly.index = pd.to_datetime(monthly.index).to_period('M')
    monthly = monthly.reindex(pd.period_range(monthly.index.min(), monthly.index.max(), freq='M'))
    bx, by = monthly['heat'].to_numpy(), monthly['forward_return'].to_numpy()
    def corr(a, b):
        ar = pd.Series(a).rank().to_numpy(); br = pd.Series(b).rank().to_numpy()
        return np.corrcoef(ar, br)[0, 1] if ar.std() > 0 and br.std() > 0 else np.nan
    def gap(a, b):
        cold, hot = b[a <= 20], b[a >= 80]
        return np.median(cold)-np.median(hot) if len(cold) and len(hot) else np.nan
    rng = np.random.default_rng(config['bootstrap']['seed'])
    block = config['bootstrap']['month_block']
    correlations, gaps = [], []
    for _ in range(config['bootstrap']['replicates']):
        span = len(monthly)
        starts = rng.integers(0, max(1, span-block+1), size=math.ceil(span/block))
        idx = np.concatenate([np.arange(s, min(s+block, span)) for s in starts])[:span]
        valid = np.isfinite(bx[idx]) & np.isfinite(by[idx])
        correlations.append(corr(bx[idx][valid], by[idx][valid]))
        gaps.append(gap(bx[idx][valid], by[idx][valid]))
    def interval(v):
        v = np.asarray(v); v = v[np.isfinite(v)]
        return (*np.quantile(v, [.025, .975]), len(v)) if len(v) else (np.nan, np.nan, 0)
    clo, chi, cn = interval(correlations); glo, ghi, gn = interval(gaps)
    return dict(code=code, month_samples=n, spearman=corr(x,y), rho_ci_low=clo, rho_ci_high=chi,
                cold_months=int((x <= 20).sum()), hot_months=int((x >= 80).sum()),
                cold_minus_hot=gap(x,y), gap_ci_low=glo, gap_ci_high=ghi,
                bootstrap_valid_gap=gn, bootstrap_valid_rho=cn,
                calendar_month_span=len(monthly), sample_count_divided_by_block_length=n/block)


def action_audit(code, frame, events):
    days = list(frame.index)
    output = []
    for i in range(1, len(days)):
        start, end = days[i-1], days[i]
        included = [d for d in sorted(events) if start < d <= end]
        raw_ret = frame.iloc[i]['close']/frame.iloc[i-1]['close']-1
        corrected = frame.iloc[i]['gross_return']
        if included or abs(corrected) > .205:
            shares, cash = 1., 0.
            for d in included:
                dividend, bonus, rights, subscription = events[d]
                cash += shares*(dividend-rights*subscription)
                shares *= 1+bonus+rights
            explicit = (shares*frame.iloc[i]['close']+cash)/frame.iloc[i-1]['close']-1
            if not np.isclose(explicit, corrected, atol=1e-12):
                raise AssertionError('Independent action ledger mismatch')
            output.append(dict(code=code, previous_quote=start, quote_date=end,
                event_dates=';'.join(included), price_before=frame.iloc[i-1]['close'],
                price_after=frame.iloc[i]['close'], raw_return=raw_ret, gross_return=corrected,
                share_multiplier=shares, net_cash_per_old_share=cash,
                events_during_suspension=sum(d not in frame.index for d in included),
                flag='large_adjusted_move' if abs(corrected) > .205 else 'action'))
    return output


def plots(frames, summary, config, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.collections import LineCollection
    from matplotlib.colors import Normalize
    from matplotlib.font_manager import FontProperties
    from matplotlib.ticker import FuncFormatter, LogLocator
    font = Path('/usr/share/fonts/google-droid-sans-fonts/DroidSansFallbackFull.ttf')
    if font.exists():
        from matplotlib import font_manager
        font_manager.fontManager.addfont(str(font))
        family = FontProperties(fname=str(font)).get_name()
    else:
        family = 'DejaVu Sans'
    plt.rcParams.update({'font.family':[family, 'DejaVu Sans'], 'font.size':10,
        'axes.spines.top':False, 'axes.spines.right':False, 'axes.unicode_minus':False,
        'svg.fonttype':'none', 'pdf.fonttype':42, 'figure.facecolor':'white', 'savefig.facecolor':'white'})
    norm = Normalize(0,100); cmap = plt.get_cmap('coolwarm')
    out.mkdir(exist_ok=True)
    def line(ax, df):
        x = mdates.date2num(pd.to_datetime(df.index).to_pydatetime())
        y = df['total_return'].to_numpy(); h = df['heat'].to_numpy()
        ax.plot(x,y,color='#c4c8cc',lw=.7,zorder=1)
        p = np.column_stack([x,y]); segments = np.stack([p[:-1],p[1:]],axis=1)
        valid = np.isfinite(h[1:]) & np.all(np.isfinite(segments),axis=(1,2))
        lc = LineCollection(segments[valid],cmap=cmap,norm=norm,linewidth=1.55)
        lc.set_array(h[1:][valid]); ax.add_collection(lc)
        ax.set_yscale('log'); ax.autoscale_view(); ax.xaxis_date()
        ax.yaxis.set_major_locator(LogLocator(base=10,subs=(1,2,5)))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v,pos:f'{v:g}'))
        ax.grid(axis='y',alpha=.15); ax.set_ylabel('含分红总回报净值（对数）')
        return lc
    def save(fig,name):
        fig.savefig(out/f'{name}.png',dpi=180,bbox_inches='tight')
        svg=out/f'{name}.svg'
        fig.savefig(svg,bbox_inches='tight')
        svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
        plt.close(fig)
    for code,df in frames.items():
        fig,axes = plt.subplots(3,1,figsize=(12,8.4),sharex=True,
                                gridspec_kw={'height_ratios':[3,1.1,1.5]},layout='constrained')
        line(axes[0],df)
        valid = df['heat'].dropna(); latest = f'{valid.iloc[-1]:.1f}' if len(valid) else 'NA'
        axes[0].set_title(f"{config['assets'][code]} {code}  |  温度 {latest}/100  |  {df.index[-1]}",loc='left',fontweight='bold',fontsize=15)
        axes[0].text(.01,.96,'税前分红再投资；送转/拆股及配股已处理\n灰线 = 预热期或输入缺失',
                     transform=axes[0].transAxes,va='top',fontsize=9,color='#62676e')
        axes[1].plot(pd.to_datetime(df.index),df['heat'],color='#303b4a',lw=1)
        axes[1].axhspan(0,20,color=cmap(.05),alpha=.10); axes[1].axhspan(80,100,color=cmap(.95),alpha=.10)
        axes[1].set_ylim(0,100);axes[1].set_yticks([0,20,50,80,100]);axes[1].set_ylabel('综合温度')
        for col,label,color in [('score_valuation','估值','#7a6b9b'),('score_price','价格偏离','#d89049'),('score_activity','交易活跃','#4c8a93')]:
            axes[2].plot(pd.to_datetime(df.index),df[col],label=label,color=color,lw=.8,alpha=.9)
        axes[2].set_ylim(0,100);axes[2].set_ylabel('分项温度');axes[2].legend(ncol=3,loc='upper left',frameon=False)
        axes[2].xaxis.set_major_locator(mdates.YearLocator(2)); axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        cb=fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cmap),ax=axes[0],fraction=.025,pad=.015)
        cb.set_label('冷 ← 温度 → 热')
        fig.supxlabel('仅用此前月末分布；三类等权；高温不是见顶概率',fontsize=10)
        save(fig,f'temperature_{code}')
    stocks = [c for c in frames if c!='000300']
    fig,axes=plt.subplots(3,2,figsize=(14,11),layout='constrained')
    for ax,code in zip(axes.flat,stocks):
        df=frames[code];line(ax,df);v=df['heat'].dropna()
        ax.set_title(f"{config['assets'][code]}  {code} | {v.iloc[-1]:.1f}/100" if len(v) else code,loc='left',fontsize=12)
        ax.set_ylabel('总回报净值（对数）');ax.xaxis.set_major_locator(mdates.YearLocator(5));ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cmap),ax=list(axes.flat),fraction=.016,pad=.02,label='温度 0–100')
    fig.suptitle(f"六只个股：同一温度公式，不同业务与上市历史  |  {config['as_of']}",fontsize=17,fontweight='bold')
    fig.supxlabel('各自首日净值 = 100；税前分红再投资与送配股已计入；灰线为预热期或输入缺失',fontsize=11)
    save(fig,'temperature_stocks_overview')
    fig,axes=plt.subplots(2,4,figsize=(15,7.8),layout='constrained')
    for ax,code in zip(axes.flat,frames):
        rows=summary[(summary.code==code)&(summary.variant=='main')&(summary.sampling=='month_end')&(summary.months==12)].sort_values('bin')
        med=rows.median_return.to_numpy()*100;p25=rows.p25_return.to_numpy()*100;p75=rows.p75_return.to_numpy()*100
        x=np.arange(5);ax.axhline(0,color='#999999',lw=.7)
        for j in x:
            if np.isfinite(med[j]):
                ax.errorbar(j,med[j],yerr=[[med[j]-p25[j]],[p75[j]-med[j]]],fmt='o',color=cmap((j+.5)/5),capsize=4,ms=7)
            ax.text(j,.97,f'n={int(rows.iloc[j].complete)}',transform=ax.get_xaxis_transform(),ha='center',va='top',fontsize=8)
        ax.set_xlim(-.5,4.5);ax.set_xticks(x,['0–20','20–40','40–60','60–80','80–100'],rotation=30)
        lo,hi=ax.get_ylim();ax.set_ylim(lo,hi+(hi-lo)*.12)
        ax.set_title(config['assets'][code],loc='left',fontsize=12);ax.set_ylabel('后续12个月总回报（%）');ax.grid(axis='y',alpha=.12)
    axes.flat[-1].axis('off');axes.flat[-1].text(0,.85,'月末信号，次日收盘起算\n点：中位数\n线：25%–75%分位\nn：完整前向窗口数\n\n窗口重叠，n 不等于独立样本量\n未满12个月的数据不参与\n高温未必意味着后续下跌',va='top',fontsize=11,linespacing=1.7)
    fig.suptitle('温度是否区分后续收益？固定分档的历史验证',fontsize=17,fontweight='bold')
    save(fig,'temperature_forward_validation')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=EXP)
    ap.add_argument('--plots-only',action='store_true');args=ap.parse_args()
    out=args.out;config=json.loads((out/'config.json').read_text());inp=out/'inputs'
    if args.plots_only:
        frames={c:pd.read_csv(out/f'daily_{c}.csv',index_col='date') for c in config['assets']}
        summary=pd.read_csv(out/'bin_summary.csv',dtype={'code':str})
        plots(frames,summary,config,out/'figures')
        return
    ca.PRICE_TERMS_PATH=inp/'price_terms.csv'
    actions=ca.event_map(read_csv(inp/'actions.csv'))
    reports=read_csv(inp/'financials.csv');shares=read_csv(inp/'shares.csv');bonds=read_csv(inp/'bond_yields.csv')
    index_rows=json.loads((inp/'csi_H00300.json').read_text())['data']
    index_tr={pd.Timestamp(r['tradeDate']).strftime('%Y-%m-%d'):finite(r['close']) for r in index_rows}
    frames={};base_frames={};audit=[];coverage=[];quotes_by_code={}
    for code in config['assets']:
        quotes=read_csv(inp/'quotes'/f'{code}.csv')
        quotes=[r for r in quotes if r['date']<=config['as_of']]
        source_first=quotes[0]['date'];source_rows=len(quotes)
        if code!='000300':
            quotes=[r for r in quotes if r['date']>=config['stock_history_start']]
        quotes_by_code[code]=quotes
        df=total_return_frame(quotes,actions.get(code,{}))
        if code=='000300':
            market_days=list(df.index)
            missing=[d for d in market_days if d not in index_tr or not index_tr[d]>0]
            if missing:
                raise ValueError(f'Official total return missing market dates: {missing[:30]} ({len(missing)})')
            df['total_return']=[index_tr[d] for d in df.index]
            df['total_return']*=100/df['total_return'].iloc[0]
            df['gross_return']=df['total_return'].pct_change().fillna(0)
            valuation=index_valuation(df.index,read_csv(inp/'equity_bond_csi300.csv'))
            df=df.join(valuation)
            extra=sorted(set(index_tr)-set(market_days))
            (out/'index_calendar_audit.json').write_text(json.dumps({'source_only_dates_removed':extra,'missing':missing},indent=2)+'\n')
        else:
            df=df.join(stocks_valuation(df.index,df['close'],[r for r in reports if r['security_code']==code],
                       [r for r in shares if r['security_code']==code],bonds))
            audit.extend(action_audit(code,df,actions.get(code,{})))
        base_frames[code]=df
        feature=features(df,config);frames[code]=feature
        feature.to_csv(out/f'daily_{code}.csv',index_label='date')
        valid=feature['heat'].dropna()
        coverage.append(dict(code=code,name=config['assets'][code],source_first=source_first,
            excluded_early_quotes=source_rows-len(quotes),quote_first=df.index[0],quote_last=df.index[-1],
            quote_rows=len(df),heat_first=valid.index[0] if len(valid) else '',heat_rows=len(valid),
            last_heat=valid.iloc[-1] if len(valid) else np.nan,
            last_valuation=feature['score_valuation'].iloc[-1],last_price=feature['score_price'].iloc[-1],
            last_activity=feature['score_activity'].iloc[-1],
            action_dates=sum(df.index[0]<d<=df.index[-1] for d in actions.get(code,{}))))
        print('features',code,coverage[-1],flush=True)
    write_csv(out/'coverage.csv',coverage);write_csv(out/'corporate_action_audit.csv',audit)

    summaries=[];diagnostics=[];signal_outputs=[];comparisons=[]
    for code,df in frames.items():
        variants={'main':df['heat'],'valuation_only':df['score_valuation'],'price_activity':df['price_activity']}
        for window in config['rank_sensitivity_months']:
            variants[f'rank_{window}']=features(base_frames[code],config,lookback=window)['heat']
        if code=='300308':
            reset=features(base_frames[code],config,reset='2018-01-01')
            variants['post_2017_reset']=reset['heat'].reindex(df.index)
        for months in [config['primary_horizon_months'],*config['secondary_horizons_months']]:
            forward=measure_forward(df,market_days,months)
            for variant,scores in variants.items():
                masks=sample_masks(df,scores,forward,market_days)
                summaries.extend(summarize(code,variant,scores,forward,masks))
                if variant=='main':
                    rows=forward.copy();rows['code']=code;rows['heat']=scores;rows['bin']=bin_number(scores)
                    for k,mask in masks.items():rows[k]=mask
                    signal_outputs.append(rows.reset_index())
                    if months==12:
                        diagnostics.append(block_diagnostics(code,scores,forward,masks['month_end'],config))
                if months==12:
                    matched=masks['month_end'] & df['heat'].notna().to_numpy() & scores.notna().to_numpy()
                    pair_scores={'main_on_common':df['heat'],variant:scores} if variant!='main' else {'main':scores}
                    for label,pair in pair_scores.items():
                        result=block_diagnostics(code,pair,forward,matched,config)
                        result.update(comparison=variant,arm=label)
                        comparisons.append(result)
            print('forward',code,months,flush=True)
    summary=pd.DataFrame(summaries);summary.to_csv(out/'bin_summary.csv',index=False)
    pd.DataFrame(diagnostics).to_csv(out/'diagnostics.csv',index=False)
    pd.DataFrame(comparisons).to_csv(out/'matched_comparisons.csv',index=False)
    pd.concat(signal_outputs,ignore_index=True).to_csv(out/'forward_signals.csv',index=False)
    # Append-only causality verification: later quotes/events cannot change earlier scores.
    causality=[]
    for code,full in frames.items():
        base=base_frames[code];cut=len(base)-260
        if cut<1000:continue
        partial=features(base.iloc[:cut],config)
        err=np.nanmax(np.abs(partial['heat'].to_numpy()-full['heat'].iloc[:cut].to_numpy()))
        if err>1e-10:raise AssertionError(f'Feature prefix failure {code}: {err}')
        cutoff=base.index[cut-1]
        raw_prefix=total_return_frame(quotes_by_code[code][:cut],
            {d:a for d,a in actions.get(code,{}).items() if d<=cutoff})
        tr_err=0. if code=='000300' else float(np.max(np.abs(raw_prefix.total_return-base.total_return.iloc[:cut])))
        vol_err=float(np.max(np.abs(raw_prefix.volume_units-base.volume_units.iloc[:cut])))
        if code=='000300':
            val_prefix=index_valuation(raw_prefix.index,[r for r in read_csv(inp/'equity_bond_csi300.csv') if r['observed_on']<=cutoff])
        else:
            val_prefix=stocks_valuation(raw_prefix.index,raw_prefix.close,
                [r for r in reports if r['security_code']==code and r['notice_date']<=cutoff],
                [r for r in shares if r['security_code']==code and r['effective_date']<=cutoff],
                [r for r in bonds if r['observed_on']<=cutoff])
        val_err=float(np.nanmax(np.abs(val_prefix.valuation_raw-base.valuation_raw.iloc[:cut])))
        if max(tr_err,vol_err,val_err)>1e-10:raise AssertionError(f'Raw prefix failure {code}')
        causality.append(dict(code=code,cutoff=cutoff,max_heat_change=float(err),
            max_stock_total_return_change=tr_err,max_volume_change=vol_err,max_valuation_change=val_err))
    (out/'causality_checks.json').write_text(json.dumps(causality,indent=2)+'\n')
    plots(frames,summary,config,out/'figures')
    outputs={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file() and p.name!='output_manifest.json'}
    (out/'output_manifest.json').write_text(json.dumps(outputs,indent=2)+'\n')
    print('Completed temperature diagnostics and figures',flush=True)


if __name__=='__main__':main()
