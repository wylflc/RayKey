"""v4.209 重跑与 v4.208 原读数并列（只报差异，不改判定）：公允性读数（exp_oi217f → 本目录）与轨道 A 读数
（exp_oi217u → exp_oi217u2）。

    python3 compare.py   # → comparison.json
"""
import json
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
RUNS = {'v4.208': (ROOT / 'data/experiments/exp_oi217f_20260925', ROOT / 'data/experiments/exp_oi217u_20260925'),
        'v4.209': (EXP, ROOT / 'data/experiments/exp_oi217u2_20260925')}
SAMPLES = ('面板_3y', '面板_5y', '全部ROIC_3y', '全部ROIC_5y')


def fairness(folder: Path) -> dict:
    r = json.loads((folder / 'results.json').read_text())
    out = dict(observations=r['observations'], status_counts=r['status_counts'])
    for s in SAMPLES:
        x = r[s]
        cal = {g: {a: [x['calibration'][g][a], x['calibration'][g][f'{a}_ci']] for a in ('C', 'W', 'U')} | dict(n=x['calibration'][g]['n'], stocks=x['calibration'][g]['stocks'])
               for g in ('净负债型', '净现金型', '全部分歧')}
        enc = x['encompass']['三臂']
        out[s] = dict(calibration=cal, lambda_U=[enc['lambda_dU'], enc['lambda_dU_ci']], lambda_W=[enc['lambda_dW'], enc['lambda_dW_ci']],
                      rank={k: x['rank'][k] for k in ('C', 'W', 'U', 'U-C')},
                      by_stock={g: {k: x['calibration_by_stock'][g][k] for k in ('stocks', 'C_negative', 'U_negative', 'U_closer', 'loo_C', 'loo_U')}
                                for g in ('净负债型',)})
    return out


def track_a(folder: Path) -> dict:
    v = json.loads((folder / 'verification.json').read_text())
    align = json.loads((folder / 'align_check.json').read_text())
    current = json.loads((folder / 'current_changes.json').read_text())
    keys = ('P_pp', 'CAGR_pp', 'P25_pp', 'DD5_pp', 'MDD_pp', 'negative_flips', 'CAGR_positive', 'P_positive', 'track_a_pass')
    return dict(main=v['main'], track_a_pass=v['track_a_pass'],
                align={a: {k: align['arms'][a][k] for k in ('line', 'old_line_share', 'retained')} for a in align['arms']},
                guardrails=[{k: c.get(k) for k in ('candidate', 'control', 'group', *keys)} for c in v['guardrails'] if c['candidate'] != 'CONTROL'],
                current={a: {k: current[a][k] for k in ('line', 'zone_old', 'zone_new', 'left', 'entered', 'changed',
                                                        'unvaluable_entered', 'unvaluable_left')} for a in current if a != 'CONTROL'})


def main():
    report = {run: dict(fairness=fairness(f), track_a=track_a(t)) for run, (f, t) in RUNS.items()}
    (EXP / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n')
    for s in SAMPLES:
        for run in RUNS:
            x = report[run]['fairness'][s]
            nd = x['calibration']['净负债型']
            print(f"{s} {run}: 净负债 C {nd['C'][0]:+.3f} W {nd['W'][0]:+.3f} U {nd['U'][0]:+.3f} (n={nd['n']}, {nd['stocks']}只)"
                  f" | λ_U {x['lambda_U'][0]:.2f} {[round(v, 2) for v in x['lambda_U'][1]]} | rank U-C {x['rank']['U-C']['mean']:+.3f} t {x['rank']['U-C']['nw_t']:.2f}")
    for run in RUNS:
        t = report[run]['track_a']
        print(run, 'main', t['main'], 'align', t['align'].get('WU'), [ (g['candidate'], g['group'], round(g['P_pp'], 2), round(g['CAGR_pp'], 2)) for g in t['guardrails']])


if __name__ == '__main__':
    main()
