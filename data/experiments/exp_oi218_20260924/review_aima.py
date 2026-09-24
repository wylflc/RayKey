"""OI-209 差距复核：爱玛科技，用户 2026-09-24 裁定「采用研究数」。

写档案复核五列；按 v4.205 把 09-24 已登记的研究数行（`pending_decision_log_row.csv`）、复核行与规则行先追加到决策日志，
随后跑 §6.7 第 4～6 步并重跑 09-24 扫描。研究口径 V 同 exp_oi209_20260924/review.py：每股 NOPAT 换研究数、投入资本不变、股权桥照带。
    python3 data/experiments/exp_oi218_20260924/review_aima.py [--dry-run]
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import minority_claims  # noqa: E402
from build_report_update_queue import research_divergence  # noqa: E402
from intrinsic_value import intrinsic_value  # noqa: E402
from workflow_decision_log import DECISION_LOG_FIELDS, WORKFLOW_VERSION, append_decision_log  # noqa: E402

CODE, CLOSE, REVIEWED_AT = '603529', 20.88, '2026-09-24'     # 09-24 收盘
DOSSIERS = ROOT / 'data/processed/a_share_valuation_dossiers.csv'
BANDS = ROOT / 'data/processed/a_share_pool_model_bands_adopted.csv'
LOG = ROOT / 'data/processed/a_share_workflow_decision_log.csv'
PENDING = EXP / 'pending_decision_log_row.csv'


def research_value(band: dict, research_yi: float) -> float:
    f = lambda k: float(band[k]) if band[k] else 0.0
    k = research_yi * 1e8 / f('shares_est') / f('nopat_ps')
    nps, roic0, w = f('nopat_ps') * k, f('roic0') * k, f('wacc')
    res = intrinsic_value(nps, roic0, f('g0'), w, roe_terminal=min(w + 0.02, roic0), g_terminal=0.03, n=10, n1=0,
                          consistent=True, roe_lam=0.12, horizon=50)
    nd, _ = minority_claims.equity_bridge(res.intrinsic_value, f('fin_net_debt_ps'), f('minority_book_ps'), f('minority_share'),
                                          f('external_equity_ps'), f('minority_fixed_claim_ps'), f('minority_dividend_floor_ps'))
    return res.intrinsic_value - nd


def main(dry_run: bool) -> None:
    band = next(r for r in csv.DictReader(BANDS.open(encoding='utf-8-sig')) if r['security_code'] == CODE)
    assert not (band.get('research_overlay') or '').strip(), '生产带已采用研究数'
    rows = list(csv.DictReader(DOSSIERS.open(encoding='utf-8-sig')))
    row = next(r for r in rows if r['security_code'] == CODE)
    div = research_divergence(row, band)
    research, model = div['research'], div['model']
    v_model, v_research = float(band['intrinsic_value']), research_value(band, research)
    note = (f"采用研究数（用户 {REVIEWED_AT} 裁定）：模型锚 {model:.2f} 亿 = 三年 NOPAT／经营账面中位（λ = 0，近两次年度变动均未上行）× 当前经营账面，"
            f"高于 2025 年报 NOPAT 18.40 亿，而 2025 年含以旧换新补贴与新国标切换前的提前备货；TTM 因子 0.73 只进守卫坡道、不进锚。"
            f"新国标 2025-09-01 实施后，2025 年四季度归母 1.27 亿、2026 年一季度 1.96 亿，二季度 4.69 亿与 2024 年同期 4.67 亿相当，"
            f"上半年毛利率 17.43%（2024 年同期 17.83%）。研究数 {research:.2f} 亿（归母 17.0 亿 = 2026H1 6.65 + 2024H2 10.37）。"
            f"研究口径 V {v_research:.2f}、P/V {CLOSE / v_research:.3f}，模型 V {v_model:.2f}、P/V {CLOSE / v_model:.3f}（09-24 收盘 {CLOSE}）；"
            f"研究数只换盈利锚，资本腿 g0 {float(band['g0']):.2%} 不变（OI-218 机理检验不改引擎，§12.262）")
    row.update(divergence_reviewed_at=REVIEWED_AT, divergence_review_conclusion='采用研究数', divergence_review_note=note,
               divergence_reviewed_model_yi=f'{model:.2f}', divergence_reviewed_research_yi=f'{research:.2f}')
    record = dict(research_yi=research, model_yi=model, gap=div['gap'], v_model=v_model, v_research=round(v_research, 4),
                  pv_model=round(CLOSE / v_model, 4), pv_research=round(CLOSE / v_research, 4), note=note)
    (EXP / 'review_aima.json').write_text(json.dumps(record, ensure_ascii=False, indent=1))
    print(json.dumps(record, ensure_ascii=False, indent=1))
    if dry_run:
        return
    with DOSSIERS.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader(); writer.writerows(rows)
    now = datetime.now(timezone.utc).isoformat()
    pending = list(csv.DictReader(PENDING.open(encoding='utf-8'), fieldnames=DECISION_LOG_FIELDS)) if PENDING.exists() else []
    append_decision_log(LOG, pending + [
        dict(logged_at_utc=now, workflow_stage='workflow_rule', run_id='v4.205-20260924', as_of=REVIEWED_AT, security_code='ALL',
             decision_type='review_trigger', decision_result='amended',
             summary_reason=('§7.3 研究与模型差距增时效（v4.205）：档案研究数或复核结论在当日执行清单发布后登记或改变的，当晚以同一信号日生效——'
                             '决策日志行先追加，再跑 §6.7 第 4～6 步（含队列重建与证据凭据），重跑当日扫描并重新发布。用户 2026-09-24 裁定。'),
             output_file='docs/000_Ashare_workflow.md', operator_or_script='manual', workflow_version=WORKFLOW_VERSION),
        dict(logged_at_utc=now, workflow_stage='valuation_review', run_id=f'oi209_divergence_review:{REVIEWED_AT}', as_of=REVIEWED_AT,
             security_code=CODE, security_name=row['security_name'], decision_type='research_model_divergence_review', decision_result='采用研究数',
             summary_reason=f"研究 {research:.2f} 亿、模型锚 {model:.2f} 亿、差距 {div['gap']:.1%}；{note}",
             input_files='data/processed/a_share_valuation_dossiers.csv;data/processed/a_share_pool_model_bands_adopted.csv',
             source_urls='https://static.cninfo.com.cn/finalpage/2026-08-25/1225497807.PDF;https://static.cninfo.com.cn/finalpage/2026-04-23/1225150933.PDF',
             output_file='data/processed/a_share_valuation_dossiers.csv', operator_or_script='exp_oi218_20260924/review_aima.py',
             workflow_version=WORKFLOW_VERSION)])
    if PENDING.exists():
        PENDING.unlink()
    print('wrote dossier review and', len(pending) + 2, 'decision-log rows')


if __name__ == '__main__':
    main('--dry-run' in sys.argv)
