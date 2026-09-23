"""当前池在各臂状态上重算（暂存，不落生产）：候选侧、B2、持仓侧带，按交易口径 `P/V`（pv_ratio.trading_pv）
对比 v4.199 生产带，并按各臂对齐线（容差内保留 1.0562）列买入区进出。"""
import os
import subprocess
import sys

from common import ARMS, EXP, ROOT, load, read, save
sys.path.insert(0, str(ROOT / 'scripts'))
from pv_ratio import trading_pv  # noqa: E402

SIGNAL = '2026-09-23'


def stage(arm: str) -> None:
    out_dir = EXP / 'states/current' / arm
    out_dir.mkdir(parents=True, exist_ok=True)
    build = EXP / 'states' / f'{arm}_build'
    for suffix, name in (('', 'adopted'), ('_b2', 'b2')):
        out = out_dir / f'a_share_pool_model_bands_{name}.csv'
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_pool_model_bands.py'), '--signal-date', SIGNAL,
                        '--bands', str(build / f'roic_bands{suffix}.csv'), '--states', str(build / f'a_share_daily_states_{name}.csv'),
                        '--out', str(out)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        subprocess.run([sys.executable, str(ROOT / 'scripts/apply_forecast_band_overlay.py'), '--signal-date', SIGNAL,
                        '--bands', str(out)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, str(ROOT / 'scripts/build_hold_model_bands.py'), '--signal-date', SIGNAL,
                    '--base', str(out_dir / 'a_share_pool_model_bands_adopted.csv'), '--b2', str(out_dir / 'a_share_pool_model_bands_b2.csv'),
                    '--out', str(out_dir / 'a_share_pool_model_bands_hold.csv')], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


def main():
    arms = [a for a in os.environ.get('EXP_CURRENT_ARMS', '+'.join(ARMS)).split('+') if a]
    for arm in arms:
        stage(arm)
    align = load('align_check.json')
    close = {r['security_code']: float(r['close']) for r in read(EXP / 'old_inputs/data/processed/daily_buy_candidates.csv') if r.get('close')}
    old = {r['security_code']: r for r in read(EXP / 'old_inputs/data/processed/a_share_pool_model_bands_adopted.csv')}
    old_hold = {r['security_code']: r for r in read(EXP / 'old_inputs/data/processed/a_share_pool_model_bands_hold.csv')}
    report = {}
    for arm in arms:
        line = align['arms'][arm]['line']
        new = {r['security_code']: r for r in read(EXP / 'states/current' / arm / 'a_share_pool_model_bands_adopted.csv')}
        hold = {r['security_code']: r for r in read(EXP / 'states/current' / arm / 'a_share_pool_model_bands_hold.csv')}
        assert new.keys() == old.keys(), arm
        rows = []
        for code in sorted(old):
            o, n = old[code], new[code]
            px = close.get(code)
            pv_o, pv_n = trading_pv(px, o), trading_pv(px, n)
            hv_o, hv_n = trading_pv(px, old_hold[code]), trading_pv(px, hold[code])
            ov, nv = (float(r['intrinsic_value']) if r.get('intrinsic_value') else None for r in (o, n))
            rows.append(dict(security_code=code, security_name=n.get('security_name'), path_old=o.get('roic_path'),
                             path_new=n.get('roic_path'), V_old=ov, V_new=nv, dV=(nv / ov - 1) if ov and nv else None,
                             PV_old=pv_o, PV_new=pv_n, hold_PV_old=hv_o, hold_PV_new=hv_n))
        zone_old = {r['security_code'] for r in rows if r['PV_old'] is not None and r['PV_old'] <= align['current_line']}
        zone_new = {r['security_code'] for r in rows if r['PV_new'] is not None and r['PV_new'] <= line}
        names = {r['security_code']: r['security_name'] for r in rows}
        report[arm] = dict(line=line, rows=rows, zone_old=len(zone_old), zone_new=len(zone_new),
                           left=sorted(names[c] for c in zone_old - zone_new), entered=sorted(names[c] for c in zone_new - zone_old),
                           changed=sum(1 for r in rows if r['dV'] not in (None, 0.0)))
        print(arm, {k: v for k, v in report[arm].items() if k != 'rows'}, flush=True)
    save('current_changes.json', report)


if __name__ == '__main__':
    main()
