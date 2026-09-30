"""爱玛差距复核 B2（用户 2026-09-30 裁定）：研究数与研究增长随 v4.216 研发资本化口径重述。

研究数：归母 17.0 亿判断不变，股权桥改用新口径 2025 年报 NOPAT（`research_nopat_from_parent`）；
研究增长：§6.5.2.2 同式，2022→2025 年报增量 ROIC（新口径）× 生产带再投资率。写档案与决策日志（两条复核行，接改判链）。
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
from build_report_update_queue import research_nopat_from_parent  # noqa: E402
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log  # noqa: E402

CODE, SIGNAL, RULED_AT, CAP, PARENT_YI = '603529', '2026-09-30', '2026-09-30', 0.40, 17.0
DOSSIERS = ROOT / 'data/processed/a_share_valuation_dossiers.csv'
BANDS = ROOT / 'data/processed/a_share_pool_model_bands_adopted.csv'
RUN_ID = f'oi209_divergence_review:{RULED_AT}'
PRIOR = {'nopat': 'valuation_review:2026-09-24:603529:45d91279', 'growth': 'valuation_review:2026-09-24:603529:e6a2f803'}


def main(dry_run: bool) -> None:
    band = next(r for r in csv.DictReader(BANDS.open(encoding='utf-8-sig')) if r['security_code'] == CODE)
    years = roic_inputs.load_statements({CODE}, ic_floor=0.1, caliber='nonop', restricted_cash='notes_wc')[CODE]
    rd = roic_inputs.load_rd_expense({CODE})[CODE]
    life = roic_inputs.rd_life('制造业-铁路、船舶、航空航天和其他运输设备制造业')
    cap, _since = roic_inputs.capitalize_rd(years, rd, life)
    old25, a, b = years['2025-12-31'], cap['2022-12-31'], cap['2025-12-31']
    minority = float(band['minority_share'])
    research = round(research_nopat_from_parent(PARENT_YI, minority, b.nopat / 1e8, b.net_profit / 1e8), 2)
    iroic = (b.nopat - a.nopat) / (b.invested_capital - a.invested_capital)
    rr = float(band['reinvestment_rate'])
    g0 = round(min(max(iroic, 0.0), CAP) * rr, 4)
    model = float(band['model_nopat_ps']) * float(band['shares_est']) / 1e8
    gap = max(model, research) / min(model, research) - 1
    assert abs(research - 18.96) < 0.01 and abs(g0 - 0.0562) < 5e-4, (research, g0)
    source = (f"2026 年半年报（公告日 2026-08-25）：上半年归母 6.65 亿（同比 −45.15%），二季度 4.69 亿与 2024 年同期 4.67 亿相当；"
              f"下半年按 2024 年同期 10.37 亿（2025 年下半年含新国标切换前提前备货与以旧换新补贴，不作基准），2026E 归母 {PARENT_YI:.0f} 亿；"
              f"÷ (1 − 少数股东份额 {minority:.3f}) + {(b.nopat - b.net_profit) / 1e8:.2f} 亿（2025 年报 NOPAT {b.nopat / 1e8:.2f} − 合并净利 "
              f"{b.net_profit / 1e8:.2f}，v4.216 研发资本化口径）= {research:.2f} 亿（OI-209 股权桥换算；用户 {RULED_AT} 裁定 B2：随 v4.216 口径重述股权桥，"
              f"归母判断不变）；前次 14.80 亿（用户 2026-09-24 选定）→ 16.40 亿（v4.206 质押利息并回，2026-09-25）")
    basis = (f"增量 ROIC 按 2022→2025 年报（v4.216 研发资本化口径，研发 {life} 年摊销）：NOPAT {a.nopat / 1e8:.2f}→{b.nopat / 1e8:.2f} 亿、"
             f"投入资本 {a.invested_capital / 1e8:.2f}→{b.invested_capital / 1e8:.2f} 亿，= {iroic:.2%}（起点仍在 2022 年毛利率 11.7%→16.4% "
             f"的台阶之后）× 生产带再投资率 {rr:.2%} = {g0:.2%}（用户 {RULED_AT} 裁定 B2；前次旧口径 7.28% × 49.42% = 3.60%）。"
             f"可证伪：新年报按同式重算的 2022 起点增量 ROIC ≥ 15%（新产能开始贡献回报）")
    note = (f"采用研究数（用户 {RULED_AT} 裁定 B2）：v4.216 研发资本化使模型锚 21.84→{model:.2f} 亿（+12.3%）重新入队；研究数与研究增长随新口径重述——"
            f"2025 年报 NOPAT {old25.nopat / 1e8:.2f}→{b.nopat / 1e8:.2f} 亿，股权桥 {(old25.nopat - old25.net_profit) / 1e8:+.2f}→"
            f"{(b.nopat - b.net_profit) / 1e8:+.2f} 亿，研究数 16.40→{research:.2f} 亿（归母 {PARENT_YI:.0f} 亿判断不变）；研究增长 3.60%→{g0:.2%}；"
            f"差距 {gap:.1%}。独立审视（零增长 EPV，正常化归母 16／18／20 亿、净现金约 37 亿、WACC 10%）合理价值约 22.2／24.5／26.9 元；"
            f"研究口径 V 约 25.6，高于基准约 4%，来自模型按平均 ROE 给增长定价（2022→2025 增量回报 6.4% 低于 WACC）。"
            f"前次：用户 2026-09-24 裁定采用研究数 14.80 亿，2026-09-25 随 OI-219 修订 16.40 亿并登记研究增长 3.60%")
    record = dict(research_nopat_yi=research, research_g0=g0, iroic=round(iroic, 4), reinvestment_rate=rr, model_yi=round(model, 2),
                  gap=round(gap, 4), nopat_2025_old=round(old25.nopat / 1e8, 2), nopat_2025_new=round(b.nopat / 1e8, 2),
                  net_profit_2025=round(b.net_profit / 1e8, 2), nopat_2022_new=round(a.nopat / 1e8, 2),
                  ic_2022_new=round(a.invested_capital / 1e8, 2), ic_2025_new=round(b.invested_capital / 1e8, 2), minority=minority)
    print(json.dumps(record, ensure_ascii=False, indent=1))
    (EXP / 'register.json').write_text(json.dumps(dict(record, source=source, basis=basis, note=note), ensure_ascii=False, indent=1) + '\n')
    if dry_run:
        return
    rows = list(csv.DictReader(DOSSIERS.open(encoding='utf-8-sig')))
    header = list(rows[0].keys())
    row = next(r for r in rows if r['security_code'] == CODE)
    assert row['divergence_review_conclusion'] == '采用研究数' and row['divergence_reviewed_at'] == '2026-09-25', row['divergence_reviewed_at']
    row.update(research_nopat_yi=f'{research:.2f}', research_source=source, research_g0=f'{g0:.4f}', research_g0_basis=basis,
               divergence_reviewed_at=RULED_AT, divergence_reviewed_model_yi=f'{model:.2f}', divergence_reviewed_research_yi=f'{research:.2f}',
               divergence_review_note=note)
    with DOSSIERS.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader(); writer.writerows(rows)
    now = datetime.now(timezone.utc).isoformat()
    common = dict(logged_at_utc=now, workflow_stage='valuation_review', run_id=RUN_ID, as_of=SIGNAL, security_code=CODE,
                  security_name=row['security_name'], decision_type='research_model_divergence_review', decision_result='采用研究数',
                  input_files='data/processed/a_share_valuation_dossiers.csv;data/experiments/exp_aima_b2_20260930/register.json',
                  output_file='data/processed/a_share_valuation_dossiers.csv', operator_or_script='exp_aima_b2_20260930/register.py',
                  workflow_version=WORKFLOW_VERSION)
    append_decision_log(DEFAULT_DECISION_LOG, [
        dict(common, summary_reason=f"研究 {research:.2f} 亿（修订自 16.40）、模型锚 {model:.2f} 亿、差距 {gap:.1%}；{note}",
             decision_id=f'valuation_review:{SIGNAL}:{CODE}:b2_nopat', supersedes_decision_id=PRIOR['nopat']),
        dict(common, summary_reason=f"研究增长 g0 {g0:.2%}（机械 {float(band['g0']):.2%}）：{basis}",
             decision_id=f'valuation_review:{SIGNAL}:{CODE}:b2_growth', supersedes_decision_id=PRIOR['growth'])])
    print('wrote dossier row and 2 decision-log rows')


if __name__ == '__main__':
    main('--dry-run' in sys.argv)
