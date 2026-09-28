"""OI-207 H2 落地检验：生产逐日状态的银行行按 H2 改写，写出两臂的面板子集（回测用）与 H2 全市场候选侧状态（第 13 款用）。

    python3 make_states.py    # → states/{BASE,H2}/a_share_daily_states_{adopted,hold}.csv、states/H2_full/a_share_daily_states_adopted.csv
"""
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from divspread_names import INSURER_CODES  # noqa: E402
from intrinsic_value import valuation_label  # noqa: E402

SRC = ROOT / 'data/experiments/exp_oi207_20260928/states'
PANEL = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
MIN_BANKS = 5


def load(path):
    out = {}
    with path.open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            try:
                pv = float(r['valuation_ratio'])
            except ValueError:
                continue
            if pv > 0:
                out[(r['security_code'], r['date'])] = pv
    return out


def h2_map():
    d0, ddm = load(SRC / 'D0.csv'), load(SRC / 'DDM10.csv')
    by_day = defaultdict(list)
    for (code, day), pv in d0.items():
        if code not in INSURER_CODES and (code, day) in ddm:
            by_day[day].append((code, pv, ddm[(code, day)]))
    out, fallback = {}, 0
    for day, rows in by_day.items():
        if len(rows) < MIN_BANKS:
            fallback += 1
            continue
        m0 = sum(math.log(a) for _, a, _ in rows) / len(rows)
        m1 = sum(math.log(b) for _, _, b in rows) / len(rows)
        for code, _a, b in rows:
            out[(code, day)] = math.exp(m0 + math.log(b) - m1)
    return out, dict(days=len(by_day), fallback_days=fallback, rows=len(out))


def rewrite(src: Path, dst_panel: Path, dst_base: Path | None, dst_full: Path | None, h2: dict, panel: set) -> dict:
    stats = dict(rows=0, rewritten=0, panel_rows=0)
    handles = {}
    with src.open(encoding='utf-8', newline='') as fi:
        rd = csv.DictReader(fi)
        for key, path in (('panel', dst_panel), ('base', dst_base), ('full', dst_full)):
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                fh = path.open('w', encoding='utf-8', newline='')
                handles[key] = (fh, csv.DictWriter(fh, fieldnames=rd.fieldnames))
                handles[key][1].writeheader()
        for r in rd:
            stats['rows'] += 1
            code = r['security_code']
            if 'base' in handles and code in panel:
                handles['base'][1].writerow(r)
            pv = h2.get((code, r['date']))
            if pv is not None:
                close = float(r['close'])
                v = close / pv
                r.update(intrinsic_value=f'{v:.4f}', band_low=f'{v * 0.9:.4f}', band_high=f'{v * 1.1:.4f}',
                         valuation_ratio=f'{pv:.4f}', upside_to_low=f'{v * 0.9 / close - 1:.4f}')
                if 'pv_equity' in r:
                    r['pv_equity'] = f'{pv:.4f}'
                if 'valuation_label' in r:
                    r['valuation_label'] = valuation_label(close, v)
                stats['rewritten'] += 1
            if code in panel:
                handles['panel'][1].writerow(r); stats['panel_rows'] += 1
            if 'full' in handles:
                handles['full'][1].writerow(r)
    for fh, _w in handles.values():
        fh.close()
    return stats


def main():
    h2, info = h2_map()
    with PANEL.open(encoding='utf-8-sig', newline='') as f:
        panel = {r['security_code'].zfill(6) for r in csv.DictReader(f)}
    out = dict(h2=info)
    for name in ('adopted', 'hold'):
        src = ROOT / 'data/processed' / f'a_share_daily_states_{name}.csv'
        out[name] = rewrite(src, EXP / 'states/H2' / src.name, EXP / 'states/BASE' / src.name,
                            EXP / 'states/H2_full' / src.name if name == 'adopted' else None, h2, panel)
        print(name, out[name], flush=True)
    (EXP / 'make_states.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()
