"""v4.207 研究增长：爱玛登记 research_g0（用户 2026-09-25 裁定 3.60%）。

档案增 `research_g0`／`research_g0_basis` 两列（紧随 `research_source`），爱玛按 §6.5.2.2 研究增长同式：
2022→2025 年报增量 ROIC（2022 年毛利率台阶之后）× 生产带再投资率。写复核说明与决策日志（规则行＋复核行）。
    python3 register.py [--dry-run]
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import roic_inputs  # noqa: E402
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log  # noqa: E402

CODE, SIGNAL, RULED_AT, CAP = '603529', '2026-09-24', '2026-09-25', 0.40
DOSSIERS = ROOT / 'data/processed/a_share_valuation_dossiers.csv'
BANDS = ROOT / 'data/processed/a_share_pool_model_bands_adopted.csv'
RUN_ID = f'research_growth:{RULED_AT}'


def main(dry_run: bool) -> None:
    band = next(r for r in csv.DictReader(BANDS.open(encoding='utf-8-sig')) if r['security_code'] == CODE)
    assert not (band.get('model_g0') or '').strip(), '生产带已采用研究增长'
    years = roic_inputs.load_statements({CODE}, ic_floor=0.1, caliber='nonop', restricted_cash='notes')[CODE]
    a, b = years['2022-12-31'], years['2025-12-31']
    iroic = (b.nopat - a.nopat) / (b.invested_capital - a.invested_capital)
    rr = float(band['reinvestment_rate'])
    g0 = round(min(max(iroic, 0.0), CAP) * rr, 4)
    assert abs(g0 - 0.036) < 5e-4, g0
    basis = (f"增量 ROIC 按 2022→2025 年报：NOPAT {a.nopat / 1e8:.2f}→{b.nopat / 1e8:.2f} 亿、投入资本 {a.invested_capital / 1e8:.2f}→"
             f"{b.invested_capital / 1e8:.2f} 亿，= {iroic:.2%}（起点移到 2022 年毛利率 11.7%→16.4% 的台阶之后；2021→2025 首尾 "
             f"{float(band['incremental_roic']):.2%} 含该台阶）× 生产带再投资率 {rr:.2%} = {g0:.2%}（用户 {RULED_AT} 裁定）。"
             f"可证伪：新年报按同式重算的 2022 起点增量 ROIC ≥ 15%（新产能开始贡献回报）")
    rows = list(csv.DictReader(DOSSIERS.open(encoding='utf-8-sig')))
    header = list(rows[0].keys())
    if 'research_g0' not in header:
        i = header.index('research_source') + 1
        header[i:i] = ['research_g0', 'research_g0_basis']
    row = next(r for r in rows if r['security_code'] == CODE)
    assert row['divergence_review_conclusion'] == '采用研究数'
    for r in rows:
        r.setdefault('research_g0', ''); r.setdefault('research_g0_basis', '')
    row.update(research_g0=f'{g0:.4f}', research_g0_basis=basis)
    if '研究增长' not in row['divergence_review_note']:
        row['divergence_review_note'] += f"；{RULED_AT} 登记研究增长 g0 {g0:.2%}（v4.207，见 research_g0_basis）"
    record = dict(iroic=round(iroic, 4), rr=rr, g0=g0, basis=basis)
    (EXP / 'register.json').write_text(json.dumps(record, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(record, ensure_ascii=False, indent=1))
    log = list(csv.DictReader(DEFAULT_DECISION_LOG.open(encoding='utf-8')))
    if dry_run or any(r['run_id'] == RUN_ID for r in log):
        return
    with DOSSIERS.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader(); writer.writerows(rows)
    now = datetime.now(timezone.utc).isoformat()
    append_decision_log(DEFAULT_DECISION_LOG, [
        dict(logged_at_utc=now, workflow_stage='workflow_rule', run_id='v4.207-20260925', as_of=SIGNAL, security_code='ALL',
             decision_type='valuation_caliber', decision_result='adopted',
             summary_reason=('§6.5.2.2 增研究增长（v4.207）：采用研究数的 growth 路径行可登记 research_g0，只取本公司已实现的资本腿'
                             '（增量 ROIC 起点移到结构性变化之后的年报，再投资率照带），叠加时 EV(研究) 以研究 NOPAT 与研究增长同算。用户 2026-09-25 裁定。'),
             output_file='docs/000_Ashare_workflow.md', operator_or_script='manual', workflow_version=WORKFLOW_VERSION),
        dict(logged_at_utc=now, workflow_stage='valuation_review', run_id=RUN_ID, as_of=SIGNAL, security_code=CODE,
             security_name=row['security_name'], decision_type='research_model_divergence_review', decision_result='采用研究数',
             summary_reason=f"研究增长 g0 {g0:.2%}（机械 {float(band['g0']):.2%}）：{basis}",
             input_files='data/processed/a_share_valuation_dossiers.csv;data/experiments/exp_aima_growth_20260925/scenarios.json',
             output_file='data/processed/a_share_valuation_dossiers.csv', operator_or_script='exp_aima_growth_20260925/register.py',
             workflow_version=WORKFLOW_VERSION)])
    print('wrote dossier columns and 2 decision-log rows')


if __name__ == '__main__':
    main('--dry-run' in sys.argv)
