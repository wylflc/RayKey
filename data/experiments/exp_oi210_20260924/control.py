"""CONTROL：改码前引擎在当前输入上逐票复算，对照 `overseas_watchlist_valuation.csv` 现行带（带下限 = 0.9 × V）。

只在 `control_meta.json` 记录的改码前提交上运行才有意义（导入的是当前工作区的引擎）；结果见 `control.json`。"""
import csv
import json
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_overseas_roic_bands as bor  # noqa: E402


def trade_value(code, res, inp):
    cfg = bor.COMPANY_CFG.get(code, dict(erp='erp_us', ccy='USD', adr=1, fx=None, fx_inv=False))
    fx = 1.0
    if cfg.get('fx'):
        fx = inp[cfg['fx']]
        fx = 1 / fx if cfg.get('fx_inv') else fx
    return res['value'] * fx * cfg['adr'] if res['status'] == 'ok' else None


def run(label):
    inp, years = bor.load_inputs(), bor.load_years()
    current = bor.load_years.current
    out = {}
    for r in csv.DictReader(open(bor.WATCHLIST, encoding='utf-8-sig')):
        code, tier = r['security_code'], str(r.get('quality_tier') or r.get('attention_class') or 'L2')
        stored = float(r['fair_price_low']) / bor.BAND_LOW_COEF if r.get('fair_price_low') else None
        if code in bor.FINANCIAL_KEEP or code in bor.NO_SOURCE or code not in years:
            out[code] = dict(name=r['security_name'], status='skip', stored=stored)
            continue
        res = bor.value_company(code, tier, years[code], inp, current.get(code))
        v = trade_value(code, res, inp)
        out[code] = dict(name=r['security_name'], status=res['status'], path=res.get('path'), value=v, stored=stored,
                         price=float(r['valuation_price']) if r.get('valuation_price') else None,
                         reason=res.get('reason', '')[:120], roic0=res.get('roic0'), r=res.get('r'), wacc=res.get('wacc'))
    (EXP / f'{label}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == '__main__':
    out = run(sys.argv[1] if len(sys.argv) > 1 else 'control')
    bad = {c: (d.get('value'), d['stored']) for c, d in out.items()
           if d['status'] != 'skip' and not ((d.get('value') is None and d['stored'] is None)
                                             or (d.get('value') and d['stored'] and abs(d['value'] / d['stored'] - 1) < 6e-3))}
    print('reproduced', sum(1 for d in out.values() if d['status'] != 'skip') - len(bad), 'mismatch', bad)
