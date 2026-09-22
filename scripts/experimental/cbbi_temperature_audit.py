#!/usr/bin/env python3
"""Audit frozen temperature outputs and export year/sample coverage, without refitting."""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / 'data/experiments/exp_cbbi_temperature_20260922'


def main():
    config = json.loads((EXP/'config.json').read_text())
    manifest = json.loads((EXP/'input_manifest.json').read_text())
    for name, digest in manifest['sha256'].items():
        assert hashlib.sha256((EXP/name).read_bytes()).hexdigest() == digest, name
    result = {'frozen_input_hashes_verified': len(manifest['sha256']), 'assets': []}
    for code in config['assets']:
        df = pd.read_csv(EXP/f'daily_{code}.csv', dtype={'date':str})
        cols = ['score_valuation','score_price','score_activity']
        expected = df[cols].mean(axis=1, skipna=False)
        np.testing.assert_allclose(df.heat, expected, atol=1e-12, equal_nan=True)
        assert df.heat.dropna().between(0,100).all()
        assert not df.date.duplicated().any()
        assert (df.total_return > 0).all()
        known = df.finance_notice.notna()
        assert (df.loc[known,'finance_notice'] < df.loc[known,'date']).all()
        result['assets'].append({'code':code,'daily_rows':len(df),
            'heat_rows':int(df.heat.notna().sum()),
            'ohlc_envelope_errors':int(((df.high+.011<df[['open','close']].max(axis=1)) |
                (df.low-.011>df[['open','close']].min(axis=1))).sum())})
    signals = pd.read_csv(EXP/'forward_signals.csv', dtype={'code':str})
    signals['year'] = signals.signal_date.str[:4]
    rows = [];nonoverlap_checks = 0
    for sampling in config['samples']:
        selected = signals[signals[sampling]]
        for (code,months,year,b), sample in selected.groupby(['code','months','year','bin']):
            complete = sample[sample.status=='complete']
            rows.append(dict(code=code,months=months,sampling=sampling,year=year,bin=b,
                signals=len(sample),complete=len(complete),
                unmatured=int((sample.status=='unmatured').sum()),
                missing_execution=int((sample.status=='missing_execution_quote').sum()),
                missing_terminal=int((sample.status=='missing_terminal_quote').sum()),
                median_return=complete.forward_return.median()))
        if sampling=='MA60_episode_nonoverlap':
            for key, sample in selected[selected.status=='complete'].groupby(['code','months','bin']):
                sample=sample.sort_values('start')
                assert (sample.start.iloc[1:].to_numpy() > sample.end.iloc[:-1].to_numpy()).all(), key
                nonoverlap_checks += len(sample)
    pd.DataFrame(rows).to_csv(EXP/'year_sample_distribution.csv',index=False)
    result['nonoverlap_complete_windows_checked'] = nonoverlap_checks
    summary=pd.read_csv(EXP/'bin_summary.csv',dtype={'code':str})
    for sampling in config['samples']:
        for (code,months,b),sample in signals[signals[sampling]].groupby(['code','months','bin']):
            expected=summary[(summary.code==code)&(summary.variant=='main')&
                (summary.sampling==sampling)&(summary.months==months)&(summary.bin==b)].iloc[0]
            complete=sample[sample.status=='complete']
            assert int(expected.signals)==len(sample)
            assert int(expected.complete)==len(complete)
            np.testing.assert_allclose(expected.median_return,complete.forward_return.median(),equal_nan=True)
    raw = pd.read_csv(EXP/'inputs/quotes/000300.csv')
    payload=json.loads((EXP/'inputs/csi_000300.json').read_text())['data']
    official=pd.DataFrame({'date':[pd.Timestamp(r['tradeDate']).strftime('%Y-%m-%d') for r in payload],
                           'official':[float(r['close']) for r in payload]})
    pair=raw.merge(official,on='date')
    result['csi_price_crosscheck']={'overlap':len(pair),'max_absolute_difference':float((pair.close-pair.official).abs().max()),
        'qq_dates_not_in_official_price':sorted(set(raw.date)-set(official.date))}
    audit=pd.read_csv(EXP/'corporate_action_audit.csv')
    result['action_ledger_rows']=len(audit)
    result['large_adjusted_move_flags']=int((audit.flag=='large_adjusted_move').sum())
    result['script_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [Path(__file__),Path(__file__).with_name('cbbi_temperature.py'),
                  Path(__file__).with_name('cbbi_temperature_data.py'),
                  ROOT/'scripts/corporate_actions.py',ROOT/'scripts/backtest_valuation_strategy.py']}
    (EXP/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
