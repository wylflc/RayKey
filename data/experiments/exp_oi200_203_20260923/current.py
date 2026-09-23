"""当前池在 NEW 状态上重算（暂存，不落生产）：候选侧、B2、持仓侧带与 P/V 变化、买入区进出名单。"""
import subprocess
import sys

from common import EXP, ROOT, read, save


def main():
    signal = '2026-09-23'
    stage = EXP / 'states/current'; stage.mkdir(parents=True, exist_ok=True)
    build = EXP / 'states/NEW_build'
    for suffix, output, state in (('', 'adopted', 'adopted'), ('_b2', 'b2', 'b2')):
        out = stage / f'a_share_pool_model_bands_{output}.csv'
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_pool_model_bands.py'), '--signal-date', signal,
                        '--bands', str(build / f'roic_bands{suffix}.csv'), '--states', str(build / f'a_share_daily_states_{state}.csv'),
                        '--out', str(out)], cwd=ROOT, check=True)
        subprocess.run([sys.executable, str(ROOT / 'scripts/apply_forecast_band_overlay.py'), '--signal-date', signal,
                        '--bands', str(out)], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/build_hold_model_bands.py'), '--signal-date', signal,
                    '--base', str(stage / 'a_share_pool_model_bands_adopted.csv'), '--b2', str(stage / 'a_share_pool_model_bands_b2.csv'),
                    '--out', str(stage / 'a_share_pool_model_bands_hold.csv')], cwd=ROOT, check=True)
    quotes = {r['security_code']: r for r in read(EXP / 'old_inputs/data/processed/daily_buy_candidates.csv')}
    changes = {}
    for name in ('adopted', 'b2', 'hold'):
        old = {r['security_code']: r for r in read(EXP / f'old_inputs/data/processed/a_share_pool_model_bands_{name}.csv')}
        new = {r['security_code']: r for r in read(stage / f'a_share_pool_model_bands_{name}.csv')}
        assert old.keys() == new.keys(), name
        rows = []
        for code in sorted(old):
            o, n = old[code], new[code]
            q = quotes.get(code, {})
            close = float(q['close']) if q.get('close') else None

            def v(r):
                try:
                    return float(r.get('intrinsic_value') or 'nan')
                except ValueError:
                    return float('nan')
            ov, nv = v(o), v(n)
            rows.append(dict(security_code=code, security_name=n.get('security_name'), path_old=o.get('roic_path'),
                             path_new=n.get('roic_path'), V_old=ov, V_new=nv, dV=(nv / ov - 1) if ov and ov == ov and nv == nv else None,
                             PV_old=close / ov if close and ov and ov == ov else None,
                             PV_new=close / nv if close and nv and nv == nv else None))
        changes[name] = rows
    save('current_changes.json', changes)
    print('CURRENT', {k: sum(1 for r in v if r['dV'] not in (None, 0.0)) for k, v in changes.items()}, flush=True)


if __name__ == '__main__':
    main()
