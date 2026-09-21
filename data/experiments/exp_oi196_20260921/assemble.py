"""Check targeted rebuilds, preserve neutral metadata, assemble equivalent NEW subsets."""
import csv
from collections import Counter
from pathlib import Path
import sys
from prepare import EXP, ROOT, digest, read, save

FILES = ('roic_bands.csv', 'roic_bands_b2.csv', 'roic_daily_raw.csv', 'roic_daily_raw_b2.csv',
         'a_share_daily_states_adopted.csv', 'a_share_daily_states_b2.csv', 'a_share_daily_states_hold.csv')

def keys(row):
    return (row['security_code'], row['date']) if 'date' in row else (row['security_code'], row['report_date'], row['available_at'])

def splice(source, block, dest, codes):
    """Preserve all non-target rows byte-for-byte; write each target block once."""
    rows = read(block)
    groups = {c: [r for r in rows if r['security_code']==c] for c in codes}
    dest.parent.mkdir(parents=True, exist_ok=True)
    import hashlib
    old_other = hashlib.sha256(); new_other = hashlib.sha256()
    written = set(); removed = inserted = 0
    with source.open(newline='', encoding='utf-8') as src, dest.open('w', newline='', encoding='utf-8') as dst:
        header = src.readline(); fields=header.lstrip('\ufeff').rstrip('\r\n').split(','); dst.write(header)
        writer=csv.DictWriter(dst, fieldnames=fields, extrasaction='ignore', lineterminator='\r\n' if header.endswith('\r\n') else '\n')
        for line in src:
            code=line.split(',',1)[0]
            if code in codes:
                removed += 1
                if code not in written:
                    writer.writerows(groups[code]); inserted += len(groups[code]); written.add(code)
            else:
                old_other.update(line.encode()); dst.write(line)
    assert written == {c for c in codes if groups[c]}, (source, written, codes)
    with dest.open(newline='', encoding='utf-8') as f:
        f.readline()
        for line in f:
            if line.split(',',1)[0] not in codes: new_other.update(line.encode())
    assert old_other.digest()==new_other.digest()
    return dict(removed=removed, inserted=inserted, other_sha256=old_other.hexdigest())

def main():
    evidence={}
    for name in FILES:
        old=read(EXP/'states/old_blocks'/name)
        rebuild=read(EXP/'states/OLD_build'/name); new=read(EXP/'states/NEW_build'/name)
        old={keys(r):r for r in old}; rebuild={keys(r):r for r in rebuild}; new={keys(r):r for r in new}
        assert old.keys()==rebuild.keys()==new.keys(), name
        diffs=[]; changed=Counter(); changed_codes=Counter(); frozen_diff=Counter(); records=[]
        for key in sorted(old):
            o,b,n=old[key],rebuild[key],new[key]
            # Neutral columns introduced by an earlier code repair: keep stored blanks.
            for field in ('minority_fixed_claim_ps','minority_dividend_floor_ps'):
                if o.get(field)=='' and b.get(field)==n.get(field)=='0.0000': n[field]=''
            stored_diff={k:[o[k],b.get(k,'')] for k in o if o[k]!=b.get(k,'') and k not in ('minority_fixed_claim_ps','minority_dividend_floor_ps')}
            if stored_diff:
                assert key[0]=='300760', (name,key,stored_diff)
                frozen_diff.update(stored_diff.keys())
            d={k:[o[k],n.get(k,'')] for k in o if o[k]!=n.get(k,'')}
            if d:
                changed.update(d.keys()); changed_codes[key[0]]+=1
                diffs.append(dict(key=key, differences=d))
            records.append({k:n.get(k,'') for k in o})
        block=EXP/'states/new_blocks'/name; block.parent.mkdir(exist_ok=True)
        with block.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(records[0])); w.writeheader(); w.writerows(records)
        # Only panel codes may enter backtest subset.
        import json
        panel=set(json.loads((EXP/'state_extracts.json').read_text())['panel_codes'])
        codes={r['security_code'] for r in records}&panel
        spliced=splice(EXP/'states/OLD'/name,block,EXP/'states/NEW'/name,codes)
        evidence[name]=dict(changed_rows=len(diffs),changed_codes=changed_codes,changed_fields=changed,
                           old_rebuild_vs_stored=frozen_diff, splice=spliced, new_subset=digest(EXP/'states/NEW'/name))
        save(f'diff_{name}.json',diffs)
        print('ASSEMBLED',name,len(diffs),dict(changed_codes),flush=True)
    save('states_validation.json',evidence)

if __name__=='__main__': main()
