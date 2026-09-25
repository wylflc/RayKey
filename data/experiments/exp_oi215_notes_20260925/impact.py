"""OI-215 候选附注表的影响（不写生产）：受影响的在池公司按 {现行 book, 第二候选 unlevered} × {现行附注表, 候选附注表}
四种口径各建一次带，列最新年报的投入资本、ROIC0 与最新带的 V；现价 P/V 按生产候选侧 P/V 等比折算。

    python3 impact.py
"""
import csv
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('oi217u_common', ROOT / 'data/experiments/exp_oi217u_20260925/common.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)

CODES = ('002594', '002463', '000725', '000999', '601899')
NOTES = {'现行附注': ROOT / 'data/reference/cash_note_items.csv', '候选附注': EXP / 'cash_note_items.csv'}
WACC = {'book': [], 'unlevered': ['--wacc-weights', 'unlevered']}
OUT = EXP / 'cache/impact'


def child(notes: str, wacc: str) -> None:
    import roic_inputs
    roic_inputs.NOTE_CASH_FILE = NOTES[notes]
    path = ROOT / 'scripts/build_historical_valuation_bands.py'
    module = types.ModuleType('exp_build'); module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
    out = OUT / f'{notes}_{wacc}'
    out.mkdir(parents=True, exist_ok=True)
    module.STMT_GAP_LOG = out / 'gaps.csv'
    flags = [f for f in u.PRODUCTION if f != '--all']
    sys.argv = ['build', *flags, '--codes', ','.join(CODES), *WACC[wacc],
                '--out-bands', str(out / 'roic_bands.csv'), '--out-daily', str(out / 'roic_daily_raw.csv')]
    raise SystemExit(module.main())


def invested_capital(notes: str) -> dict:
    import roic_inputs
    roic_inputs.NOTE_CASH_FILE = NOTES[notes]
    years = roic_inputs.load_statements(set(CODES), ic_floor=0.1, caliber='nonop', restricted_cash='notes_wc')
    out = {}
    for code, ys in years.items():
        for period in ('2024-12-31', '2025-12-31'):
            y, prev = ys.get(period), ys.get(f'{int(period[:4]) - 1}-12-31')
            if y is None:
                continue
            out[f'{code}_{period[:4]}'] = dict(IC=y.invested_capital, D=y.interest_debt, X=y.excess_cash, note_cash=y.note_cash,
                                               nopat=y.nopat, roic=roic_inputs.roic_of(y, prev))
    return out


def latest(path: Path) -> dict:
    rows = {}
    with path.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            key = (r['available_at'], r['report_date'])
            if r['security_code'] not in rows or key > (rows[r['security_code']]['available_at'], rows[r['security_code']]['report_date']):
                rows[r['security_code']] = r
    return rows


def main() -> None:
    for notes in NOTES:
        for wacc in WACC:
            log = OUT / f'{notes}_{wacc}.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open('w') as f:
                subprocess.run([sys.executable, __file__, notes, wacc], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, check=True)
    pv = {r['security_code']: r for r in csv.DictReader(open(ROOT / 'data/processed/daily_buy_candidates.csv', encoding='utf-8-sig'))}
    base = latest(OUT / '现行附注_book/roic_bands.csv')
    report = dict(ic={n: invested_capital(n) for n in NOTES}, bands={})
    for notes in NOTES:
        for wacc in WACC:
            rows = latest(OUT / f'{notes}_{wacc}/roic_bands.csv')
            for code in CODES:
                r, b = rows.get(code), base.get(code)
                v = float(r['intrinsic_value']) if r and r['status'] == 'ok' and r['intrinsic_value'] else None
                v0 = float(b['intrinsic_value']) if b and b['status'] == 'ok' and b['intrinsic_value'] else None
                p0 = pv.get(code, {}).get('model_pv') or pv.get(code, {}).get('hold_pv')
                report['bands'][f'{code}_{notes}_{wacc}'] = dict(
                    name=pv.get(code, {}).get('security_name'), report_date=r and r['report_date'], status=r and r['status'],
                    reason=r and r['reason'], V=v, roic0=r and r['roic0'], iroic=r and r['incremental_roic'], g0=r and r['g0'],
                    wacc=r and r['wacc'], V_vs_production=(v / v0 - 1) if v and v0 else None,
                    pv_production=float(p0) if p0 else None, pv=(float(p0) * v0 / v) if p0 and v and v0 else None)
    (EXP / 'impact.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    if len(sys.argv) > 2:
        child(sys.argv[1], sys.argv[2])
    else:
        main()
