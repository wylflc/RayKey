"""Identify stale report keys by exact old/native field equality, not rounded algebra."""
from collections import Counter
from prepare import EXP, read, save

NEUTRAL = ('minority_fixed_claim_ps', 'minority_dividend_floor_ps')


def keys(row):
    return row['security_code'], row['report_date'], row['available_at']


def differences(old, new):
    return {k: [v, new.get(k, '')] for k, v in old.items() if v != new.get(k, '')
            and not (k in NEUTRAL and v == '' and new.get(k) == '0.0000')}


def main():
    output = {}; details = {}; defects = []
    for side, name in (('base', 'roic_bands.csv'), ('b2', 'roic_bands_b2.csv')):
        rows = {arm: {keys(r): r for r in read(EXP/'states'/folder/name)} for arm, folder in
                (('stored','old_blocks'),('native','NEW_build'),('legacy','LEGACY_build'))}
        assert rows['stored'].keys() == rows['native'].keys() == rows['legacy'].keys(), name
        stale = []; changed = Counter()
        for key, old in rows['stored'].items():
            diff = differences(old, rows['native'][key])
            if not diff: continue
            other = differences(old, rows['legacy'][key])
            if other:
                defects.append(dict(file=name,key=key,native=diff,legacy=other))
            else:
                assert old['minority_book_ps'].startswith('-'), key
                stale.append(key); changed.update(diff.keys())
        old_keys = {k[:2] for k in stale}
        # A negative amount serialized as -0.0000 can leave every report field
        # equal yet change P/V after daily expansion. Classify using full daily
        # output too, so no rounding exceptions are needed in either arm.
        raw_name = 'roic_daily_raw_b2.csv' if side == 'b2' else 'roic_daily_raw.csv'
        daily = {arm: {(r['security_code'], r['date']): r for r in read(EXP/'states'/folder/raw_name)}
                 for arm, folder in (('stored','old_blocks'),('native','NEW_build'),('legacy','LEGACY_build'))}
        assert daily['stored'].keys() == daily['native'].keys() == daily['legacy'].keys(), raw_name
        daily_only = set()
        for key, old in daily['stored'].items():
            if not differences(old, daily['native'][key]): continue
            legacy_diff = differences(old, daily['legacy'][key])
            if legacy_diff:
                defects.append(dict(file=raw_name,key=key,legacy=legacy_diff))
            else:
                report_key = old['security_code'], old['band_report_date']
                if report_key not in old_keys: daily_only.add(report_key)
        output[side] = sorted(old_keys | daily_only)
        details[side] = dict(stale_report_rows=stale, changed_fields=changed,
                             native_matching_rows=len(rows['stored'])-len(stale),
                             daily_only_legacy_keys=sorted(daily_only))
    save('classification.json',dict(sides=details,unexplained=defects))
    assert not defects, f'{len(defects)} unexplained report differences; inspect classification.json'
    save('legacy_bridge_keys.json',output)
    print('CLASSIFIED', {s:len(v) for s,v in output.items()},flush=True)


if __name__ == '__main__': main()
