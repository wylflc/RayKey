"""当前池在各臂状态上重算（暂存，不落生产）：候选侧、B2、持仓侧带，按交易口径 `P/V`（pv_ratio.trading_pv）
对比现行生产带，并按各臂对齐线（容差内保留现行线 1.0495）列买入区进出与新增「无法估值」。
`EXP_CURRENT_STAGE=0` 只用已暂存的带重出报告。"""
import json
import os
import subprocess
import sys

from common import ARMS, EXP, ROOT, load, read, save
sys.path.insert(0, str(ROOT / 'scripts'))
from pv_ratio import trading_pv  # noqa: E402
from screen_daily_volume_price_signals import MODEL_BAND_MIN_AVAILABLE  # noqa: E402

SIGNAL = json.loads((EXP / 'old_inputs/data/processed/daily_execution_publication.json').read_text())['as_of']   # 冻结时最新发布日


def usable(band: dict) -> bool:
    """与扫描器同一结论（§6.5.2.4）：非 ok 行、早于时点门槛的陈旧带（拒绝后回退到的旧 ok 带）无 `P/V`。"""
    return band.get('status') == 'ok' and (band.get('available_at') or '') >= MODEL_BAND_MIN_AVAILABLE


def pv(price, band: dict):
    return trading_pv(price, band) if usable(band) else None


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
        if os.environ.get('EXP_CURRENT_STAGE', '1') != '0':
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
            pv_o, pv_n = pv(px, o), pv(px, n)
            hv_o, hv_n = pv(px, old_hold[code]), pv(px, hold[code])
            ov, nv = (float(r['intrinsic_value']) if r.get('intrinsic_value') else None for r in (o, n))
            rows.append(dict(security_code=code, security_name=n.get('security_name'), path_old=o.get('roic_path'),
                             path_new=n.get('roic_path'), V_old=ov, V_new=nv, dV=(nv / ov - 1) if ov and nv else None,
                             PV_old=pv_o, PV_new=pv_n, hold_PV_old=hv_o, hold_PV_new=hv_n,
                             band_new=n.get('report_date'), usable_old=usable(o), usable_new=usable(n)))
        zone_old = {r['security_code'] for r in rows if r['PV_old'] is not None and r['PV_old'] <= align['current_line']}
        zone_new = {r['security_code'] for r in rows if r['PV_new'] is not None and r['PV_new'] <= line}
        names = {r['security_code']: r['security_name'] for r in rows}
        report[arm] = dict(line=line, rows=rows, zone_old=len(zone_old), zone_new=len(zone_new),
                           left=sorted(names[c] for c in zone_old - zone_new), entered=sorted(names[c] for c in zone_new - zone_old),
                           changed=sum(1 for r in rows if r['dV'] not in (None, 0.0)),
                           unvaluable_old=sorted(r['security_name'] for r in rows if not r['usable_old']),
                           unvaluable_entered=sorted(r['security_name'] for r in rows if r['usable_old'] and not r['usable_new']),
                           unvaluable_left=sorted(r['security_name'] for r in rows if r['usable_new'] and not r['usable_old']))
        print(arm, {k: v for k, v in report[arm].items() if k != 'rows'}, flush=True)
    save('current_changes.json', report)


if __name__ == '__main__':
    main()
