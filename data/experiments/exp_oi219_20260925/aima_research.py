"""OI-219 落地：爱玛研究数随 v4.206 口径修订（用户 2026-09-25 裁定）。

研究数按 OI-209 股权桥换算 `归母 ÷ (1 − 少数股东份额) + (最新年报 NOPAT − 合并净利)`；新口径把质押开票存单的利息并回 EBIT，
2025 年报 NOPAT 随之增加该利息的税后额，研究数同额上调。模型锚取 R 状态重算的池带机械值。写档案五列与决策日志复核行。
    python3 aima_research.py [--dry-run]
"""
import csv
import json
import sys
from datetime import datetime, timezone

from common import EXP, ROOT, load, read
sys.path.insert(0, str(ROOT / 'scripts'))
import roic_inputs  # noqa: E402
from workflow_decision_log import WORKFLOW_VERSION, append_decision_log  # noqa: E402

CODE, CLOSE, SIGNAL, RULED_AT = '603529', 20.88, '2026-09-24', '2026-09-25'
DOSSIERS = ROOT / 'data/processed/a_share_valuation_dossiers.csv'
LOG = ROOT / 'data/processed/a_share_workflow_decision_log.csv'
RUN_ID = f'oi209_divergence_review:{RULED_AT}'


def main(dry_run: bool) -> None:
    rows = list(csv.DictReader(DOSSIERS.open(encoding='utf-8-sig')))
    row = next(r for r in rows if r['security_code'] == CODE)
    assert row['divergence_review_conclusion'] == '采用研究数'
    old = float(row['research_nopat_yi'])
    year = roic_inputs.load_statements({CODE}, ic_floor=0.1, caliber='nonop', restricted_cash='notes')[CODE]['2025-12-31']
    add = year.restricted_interest * (1 - year.tax_rate) / 1e8
    research = round(old + add, 2)
    assert abs(research - load('user_ruling.json')['aima_research_nopat_yi']) < 0.005, research
    band = next(r for r in read(EXP / 'states/current/R/a_share_pool_model_bands_adopted.csv') if r['security_code'] == CODE)
    model = float(band['model_nopat_ps']) * float(band['shares_est']) / 1e8
    staged = load('aima_research.json')
    v, pv = staged['research_iv']['R_16.40'], staged['pv']['R_16.40']
    note = (f"采用研究数（用户 2026-09-24 裁定；{RULED_AT} 随 OI-219 修订研究数）：v4.206 起为应付票据质押的存单按经营资产、其利息并回 EBIT，"
            f"2025 年报 NOPAT 增加质押利息税后 {add:.2f} 亿（扣除额 {year.restricted_cash / 1e8:.2f} 亿 × 利息收入率 "
            f"{year.restricted_interest / year.restricted_cash:.2%} × (1 − {year.tax_rate:.2%})），研究数按同一股权桥 {old:.2f} → {research:.2f} 亿，"
            f"归母 17.0 亿的依据不变（见 v4.205 复核：新国标实施后 2026 年二季度归母 4.69 亿与 2024 年同期相当）。"
            f"模型锚 {model:.2f} 亿（新口径三年 NOPAT／经营账面中位 × 当前经营账面）。研究口径 V {v:.2f}、P/V {pv:.3f}（09-24 收盘 {CLOSE}）；"
            f"投入资本转正后资本腿 g0 {float(band['g0']):.2%}（增量 ROIC {float(band['incremental_roic']):.1%}、再投资率 {float(band['reinvestment_rate']):.1%}），增长另行复核")
    row.update(research_nopat_yi=f'{research:.2f}', divergence_reviewed_at=RULED_AT, divergence_review_note=note,
               divergence_reviewed_model_yi=f'{model:.2f}', divergence_reviewed_research_yi=f'{research:.2f}',
               research_source=row['research_source'].replace(
                   '= 14.80 亿（OI-209 股权桥换算；用户 2026-09-24 选定）',
                   f'= 14.80 亿（OI-209 股权桥换算；用户 2026-09-24 选定）；v4.206 质押利息并回 EBIT 后 2025 年报 NOPAT 增 {add:.2f} 亿，'
                   f'研究数 {research:.2f} 亿（用户 {RULED_AT} 裁定）'))
    assert f'{research:.2f} 亿（用户' in row['research_source']
    record = dict(old=old, add=round(add, 4), research=research, model=round(model, 2), v=v, pv=pv, note=note)
    (EXP / 'aima_research_applied.json').write_text(json.dumps(record, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(record, ensure_ascii=False, indent=1))
    if dry_run or any(r['run_id'] == RUN_ID and r['security_code'] == CODE for r in read(LOG)):
        return
    with DOSSIERS.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader(); writer.writerows(rows)
    append_decision_log(LOG, [dict(
        logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage='valuation_review', run_id=RUN_ID, as_of=SIGNAL,
        security_code=CODE, security_name=row['security_name'], decision_type='research_model_divergence_review', decision_result='采用研究数',
        summary_reason=f"研究 {research:.2f} 亿（修订自 {old:.2f}）、模型锚 {model:.2f} 亿；{note}",
        input_files='data/processed/a_share_valuation_dossiers.csv;data/experiments/exp_oi219_20260925/aima_research.json',
        output_file='data/processed/a_share_valuation_dossiers.csv', operator_or_script='exp_oi219_20260925/aima_research.py',
        workflow_version=WORKFLOW_VERSION)])
    print('wrote dossier and decision-log row')


if __name__ == '__main__':
    main('--dry-run' in sys.argv)
