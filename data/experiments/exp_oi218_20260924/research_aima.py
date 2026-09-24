"""OI-218 转 OI-209：登记爱玛科技研究正常化盈利（用户 2026-09-24 选定归母 17.0 亿），按 §6.5.2.2 股权桥换算为 NOPAT。

2026E 归母 = 2026 年上半年实际 + 2024 年下半年（2024 年报 − 2024 中报），即首个新国标完整年、下半年回到补贴与提前备货之前的水平。
    python3 data/experiments/exp_oi218_20260924/research_aima.py [--dry-run]

决策日志在 09-24 执行计划的发布摘要内，登记行已从日志撤回、存于 `pending_decision_log_row.csv`，
须在 09-25 正式扫描之前原样追加到 `a_share_workflow_decision_log.csv`（§9.1：评审行先于发布）。
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
from build_report_update_queue import research_divergence, research_nopat_from_parent  # noqa: E402
from workflow_decision_log import append_decision_log  # noqa: E402

CODE = '603529'
DOSSIERS = ROOT / 'data/processed/a_share_valuation_dossiers.csv'
BANDS = ROOT / 'data/processed/a_share_pool_model_bands_adopted.csv'
LOG = ROOT / 'data/processed/a_share_workflow_decision_log.csv'
URLS = ('https://static.cninfo.com.cn/finalpage/2026-08-25/1225497807.PDF', 'https://static.cninfo.com.cn/finalpage/2026-04-23/1225150933.PDF')


def parent_profit(period: str) -> float:
    for r in csv.DictReader((ROOT / f'data/raw/financials/{period}.csv').open(encoding='utf-8-sig')):
        if r['security_code'].zfill(6) == CODE:
            return float(r['parent_netprofit']) / 1e8
    raise KeyError(period)


def main(dry_run: bool) -> None:
    h1_2026, fy2024, h1_2024 = parent_profit('2026-06-30'), parent_profit('2024-12-31'), parent_profit('2024-06-30')
    parent = round(h1_2026 + fy2024 - h1_2024, 1)
    annual = roic_inputs.load_statements({CODE}, ic_floor=0.1)[CODE]['2025-12-31']
    band = next(r for r in csv.DictReader(BANDS.open(encoding='utf-8-sig')) if r['security_code'] == CODE)
    m = float(band['minority_share'])
    fin = (annual.nopat - annual.net_profit) / 1e8
    value = research_nopat_from_parent(parent, m, annual.nopat / 1e8, annual.net_profit / 1e8)
    rows = list(csv.DictReader(DOSSIERS.open(encoding='utf-8-sig')))
    row = next(r for r in rows if r['security_code'] == CODE)
    row['research_nopat_yi'] = f'{value:.2f}'
    row['research_evidence_date'] = '2026-08-25'
    row['research_falsifier'] = '2026 年报归母 ≥ 19 亿，或 2027 年上半年归母 ≥ 9.5 亿（新国标下盈利已回到 2024～2025 年平台）'
    row['research_source'] = (f'2026 年半年报（公告日 2026-08-25）：上半年归母 {h1_2026:.2f} 亿（同比 −45.15%），二季度 4.69 亿与 2024 年同期 4.67 亿相当；'
                              f'下半年按 2024 年同期 {fy2024 - h1_2024:.2f} 亿（2025 年下半年含新国标切换前提前备货与以旧换新补贴，不作基准），2026E 归母 {parent:g} 亿；'
                              f'÷ (1 − 少数股东份额 {m:.3f}) {fin:+.2f} 亿（2025 年报 NOPAT − 合并净利）= {value:.2f} 亿（OI-209 股权桥换算；用户 2026-09-24 选定）')
    div = research_divergence(row, band)
    record = dict(parent_2026e=parent, h1_2026=round(h1_2026, 4), h2_2024=round(fy2024 - h1_2024, 4), minority_share=m,
                  nopat_less_net_profit_yi=round(fin, 4), research_nopat_yi=round(value, 2), divergence=div)
    (EXP / 'research_aima.json').write_text(json.dumps(record, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(record, ensure_ascii=False, indent=1, default=str))
    if dry_run:
        return
    with DOSSIERS.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader(); writer.writerows(rows)
    append_decision_log(LOG, [dict(
        logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage='valuation_review', run_id='oi218_research:2026-09-24',
        as_of='2026-09-24', security_code=CODE, security_name=row['security_name'], decision_type='research_normalized_earnings',
        decision_result='registered',
        summary_reason=(f"OI-218 机理检验不改引擎，爱玛盈利断层转 OI-209：登记研究正常化盈利 {value:.2f} 亿（归母 {parent:g} 亿 = 2026H1 {h1_2026:.2f} + 2024H2 "
                        f"{fy2024 - h1_2024:.2f}），模型锚 {div['model']:.2f} 亿，差距 {div['gap']:.1%}；研究数低于模型锚，依 §7.3／§7.5 入队并冻结新增买入，"
                        f"待差距复核（维持模型或采用研究数）。用户 2026-09-24 选定。") if div else '研究数已登记',
        input_files='data/experiments/exp_oi218_20260924/research_aima.json;data/processed/a_share_pool_model_bands_adopted.csv',
        source_urls=';'.join(URLS), output_file='data/processed/a_share_valuation_dossiers.csv',
        operator_or_script='exp_oi218_20260924/research_aima.py', workflow_version='a-share-selection-operation-v4.204')])
    print('wrote', DOSSIERS, 'and decision log')


if __name__ == '__main__':
    main('--dry-run' in sys.argv)
