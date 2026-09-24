"""OI-210 分步归因：S0 CONTROL（改码前引擎、现行输入）→ S1 A 股参数（r 10%、终值超额 2pp、g_T 3%）→ S2 指数整本衰减
→ S3 投入资本下限 → S4 新引擎、新输入（再加非经营金融资产与 EBIT 口径、类金融识别）。S1～S3 在改码前引擎上打补丁复现。"""
import copy
import csv
import functools
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import intrinsic_value as ivmod  # noqa: E402
import build_overseas_roic_bands as new  # noqa: E402


def old_engine():
    """改码前引擎与改码前三表（CONTROL 提交），三表写到临时文件供其读取。"""
    rev = json.loads((EXP / 'control_meta.json').read_text())['revision']
    src = subprocess.check_output(['git', 'show', f'{rev}:scripts/build_overseas_roic_bands.py'], cwd=ROOT, text=True)
    mod = types.ModuleType('old_bor'); mod.__file__ = str(ROOT / 'scripts/build_overseas_roic_bands.py')
    exec(compile(src, 'old_bor', 'exec'), mod.__dict__)
    years = tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False, encoding='utf-8')
    years.write(subprocess.check_output(['git', 'show', f'{rev}:data/interim/overseas_roic_years.csv'], cwd=ROOT, text=True))
    years.close()
    mod.YEARS_CSV = Path(years.name)
    return mod


def trade(mod, code, res, inp):
    cfg = mod.COMPANY_CFG.get(code, dict(ccy='USD', adr=1, fx=None, fx_inv=False))
    fx = 1.0
    if cfg.get('fx'):
        fx = inp[cfg['fx']]; fx = 1 / fx if cfg.get('fx_inv') else fx
    return res['value'] * fx * cfg['adr'] if res['status'] == 'ok' else None


def floored(ys):
    out = []
    for y in ys:
        y = copy.copy(y)
        if y.total_equity is not None:
            ic = max((y.interest_debt or 0) + y.total_equity - (y.excess_cash or 0), 0.1 * y.total_equity)
            y.invested_capital = ic if ic > 0 else None
        out.append(y)
    return out


def main():
    old = old_engine()
    inp = old.load_inputs()
    rows = list(csv.DictReader(open(new.WATCHLIST, encoding='utf-8-sig')))
    old_years, old_cur = old.load_years(), old.load_years.current
    new.YEARS_CSV = ROOT / 'data/interim/overseas_roic_years.csv'   # 本批提交的新口径三表（生成时与实验目录副本逐字节相同）
    new_years, new_cur = new.load_years(), new.load_years.current
    coe, iv, te = old.cost_of_equity, old.intrinsic_value, dict(old.TERMINAL_EXCESS_BY_TIER)
    out = {}
    for step in ('S0', 'S1', 'S2', 'S3', 'S4'):
        old.cost_of_equity, old.intrinsic_value, old.TERMINAL_EXCESS_BY_TIER = coe, iv, dict(te)
        old.terminal_growth_ceiling = ivmod.terminal_growth_ceiling
        if step in ('S1', 'S2', 'S3'):
            old.cost_of_equity = lambda rf, erp, beta=1.0, rp=0.0: 0.10
            old.terminal_growth_ceiling = lambda rf: 0.03
            old.TERMINAL_EXCESS_BY_TIER = {k: 0.02 for k in te}
        if step in ('S2', 'S3'):
            old.intrinsic_value = functools.partial(ivmod.intrinsic_value, consistent=True, roe_lam=0.12, horizon=50)
        for r in rows:
            code, tier = r['security_code'], str(r.get('quality_tier') or r.get('attention_class') or 'L2')
            if code in new.FINANCIAL_KEEP or code in new.NO_SOURCE or code not in old_years:
                continue
            if step == 'S4':
                res = new.value_company(code, tier, new_years[code], inp, new_cur.get(code)); mod = new
            else:
                ys, cur = old_years[code], old_cur.get(code)
                if step == 'S3':
                    ys, cur = floored(ys), (floored([cur])[0] if cur else None)
                res = old.value_company(code, tier, ys, inp, cur); mod = old
            v = trade(mod, code, res, inp)
            price = float(r['valuation_price']) if r.get('valuation_price') else None
            d = out.setdefault(code, dict(name=r['security_name'], tier=tier, price=price))
            d[step] = dict(status=res['status'], path=res.get('path'), V=v, PV=(price / v if price and v else None),
                           roic0=res.get('roic0'), wacc=res.get('wacc'), reason=res.get('reason', '')[:100])
    (EXP / 'steps.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"{'code':7}{'name':10}{'price':>9} " + ' '.join(f'{s:>15}' for s in ('S0', 'S1', 'S2', 'S3', 'S4')) + '   S4 P/V')
    for code, d in out.items():
        cells = [(f"{d[s]['V']:.1f}" if d[s]['V'] else d[s]['status'][:7]) + f"/{(d[s]['path'] or '')[:1]}" for s in ('S0', 'S1', 'S2', 'S3', 'S4')]
        pv = d['S4']['PV']
        print(f"{code:7}{d['name'][:8]:10}{d['price']!s:>9} " + ' '.join(f'{c:>15}' for c in cells) + f"   {pv and round(pv, 3)}  {d['S0']['PV'] and round(d['S0']['PV'], 3)}→")


if __name__ == '__main__':
    main()
