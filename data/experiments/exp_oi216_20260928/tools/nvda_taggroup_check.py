"""Side-effect check of the proposed composite current-securities candidate DebtSecuritiesCurrent + EquitySecuritiesFvNi
over the cached SEC companyfacts of the watchlist (read-only)."""
import glob, json, os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, '/gpfs/scratch1/shared/zwang/mm_quant/RayKey/scripts')
import fetch_overseas_statements as F  # noqa: E402

for fpath in sorted(glob.glob('/gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/raw/overseas_statements/sec/*.json')):
    sym = os.path.basename(fpath)[:-5]
    if '_em_' in sym:
        continue
    facts = json.load(open(fpath)).get('facts', {})
    g = facts.get('us-gaap')
    if not g or ('ifrs-full' in facts and 'ProfitLossBeforeTax' in facts['ifrs-full']):
        continue
    def inst(c):
        out = {}
        for e in g.get(c, {}).get('units', {}).get('USD', []):
            if e.get('start'):
                continue
            if e['end'] not in out or e['filed'] > out[e['end']][1]:
                out[e['end']] = (e['val'], e['filed'])
        return {k: v[0] for k, v in out.items()}
    each = {c: inst(c) for c in set(F.SEC_FIN_CONCEPTS) | {'EquitySecuritiesFvNi', 'DebtSecuritiesCurrent'}}
    ends = sorted(set(each['EquitySecuritiesFvNi']) & set(each['DebtSecuritiesCurrent']))
    for end in ends:
        if end < '2019-01-01':
            continue
        vo = lambda c: each.get(c, {}).get(end)  # noqa: E731
        old = F.sec_financial_assets('us-gaap', vo)
        grp, tag = F._group(vo, F.US_SECURITIES_CURRENT)
        comp = vo('DebtSecuritiesCurrent') + vo('EquitySecuritiesFvNi')
        new_sec = max(grp or 0.0, comp)
        print(f"{sym:6} {end} group={((grp or 0)/1e9):8.3f} ({tag}) composite={comp/1e9:8.3f} -> +{(new_sec-(grp or 0))/1e9:7.3f}bn; "
              f"other(old)={old['other']/1e9:7.3f} umbrella_tag={old['tags'].get('investments_total')} eq_nc_tag={old['tags'].get('equity_noncurrent')}")
