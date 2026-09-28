"""Scan the US historical SEC cache (read-only) for periods where both DebtSecuritiesCurrent and EquitySecuritiesFvNi exist,
and quantify how the composite candidate would change current securities vs the existing group (max rule).
Also flags periods where EquitySecuritiesFvNi may already sit in a non-current group (umbrella picked)."""
import glob, json, os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, '/gpfs/scratch1/shared/zwang/mm_quant/RayKey/scripts')
import fetch_overseas_statements as F  # noqa: E402
NEED = set(F.SEC_FIN_CONCEPTS) | {'EquitySecuritiesFvNi', 'DebtSecuritiesCurrent', 'EquitySecuritiesFvNiCurrent', 'EquitySecuritiesFvNiNoncurrent'}
rows = []
files = sorted(glob.glob('/gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_us_sp500_port/raw/sec/*.json'))
for fp in files:
    try:
        facts = json.load(open(fp)).get('facts', {})
    except Exception:
        continue
    g = facts.get('us-gaap') or {}
    if 'EquitySecuritiesFvNi' not in g or 'DebtSecuritiesCurrent' not in g:
        continue
    def inst(c):
        out = {}
        for e in g.get(c, {}).get('units', {}).get('USD', []):
            if e.get('start') or not str(e.get('form', '')).startswith(('10-K', '10-Q')):
                continue
            if e['end'] not in out or e['filed'] > out[e['end']][1]:
                out[e['end']] = (e['val'], e['filed'])
        return {k: v[0] for k, v in out.items()}
    each = {c: inst(c) for c in NEED if c in g}
    for end in sorted(set(each['EquitySecuritiesFvNi']) & set(each['DebtSecuritiesCurrent'])):
        vo = lambda c: each.get(c, {}).get(end)  # noqa: E731
        old = F.sec_financial_assets('us-gaap', vo)
        grp, tag = F._group(vo, F.US_SECURITIES_CURRENT)
        comp = vo('DebtSecuritiesCurrent') + vo('EquitySecuritiesFvNi')
        delta = max(grp or 0.0, comp) - (grp or 0.0)
        if delta > 0:
            rows.append((os.path.basename(fp)[:-5], end, (grp or 0) / 1e9, tag, comp / 1e9, delta / 1e9,
                         old['tags'].get('investments_total'), old['tags'].get('equity_noncurrent'),
                         vo('EquitySecuritiesFvNiCurrent'), vo('EquitySecuritiesFvNiNoncurrent')))
print('files', len(files), 'periods changed', len(rows), 'companies', len({r[0] for r in rows}))
for r in rows:
    print('%-8s %s grp=%8.3f(%s) comp=%8.3f d=+%7.3f umbrella=%s eq_nc=%s FvNiCur=%s FvNiNc=%s' % r)
