"""决策日志：v4.225 落地行（须在重发扫描之前写入）。"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION  # noqa: E402

ROWS = [
    ('OI-232-20260930', 'mechanism_repair', 'valuation_caliber', 'adopted',
     'OI-232（v4.225）：保险 V 由股利利差 V_D0 改为 V_DDM × Ḡ，Ḡ = 当日所在月之前 36 个自然月末银行截面 G 的中位（各月末按当日国债、分红与带同法计算，'
     '保险不进截面），可算月末不足 12 个或 V_DDM 不可估时退回 V_D0；唯一实现 bank_valuation.smoothed_g／insurer_value，历史 rebuild_bank_bands.py h2 缺省、'
     '实盘 bank_live_value 与池外档案同读。原因（§12.297）：V_D0 只含分红与国债，同 P/V 下保险较非金融年化低 2.78pp（区间不含 0），保险内排序无效（秩相关 0.00），'
     '国债每降 1pp V 约升 23%。预登记六个候选中银行同法两式可取，按顺序推荐平滑 G（I1c）：c −0.59［−1.97, +1.11］、秩相关 −0.40、利率斜率约 −0.03。'
     '用户 2026-09-30 裁定按推荐方法修改，当晚落地并重发 09-30 计划。落地口径月末取自然月末（检验取交易月末），按落地值重算主读数 −0.89［−2.15, +0.46］仍含 0。'
     '买入线 1.0034 原线合格面 16.910%（在册 16.916%），容差内保留、不改写；BASE 14 起点全／A／U 读数与现行逐字段相同（平安只在 2022-03～04 进过区，路径未变）。',
     'data/experiments/exp_oi232_20260930/readings.md;data/experiments/exp_land_v4225_20260930/verify_new.md;data/experiments/exp_land_v4225_20260930/readings.md;data/experiments/exp_land_v4225_20260930/align.txt'),
]


def main():
    done = {r['run_id'] for r in csv.DictReader(open(DEFAULT_DECISION_LOG, encoding='utf-8'))}
    rows = [dict(logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage=stage, run_id=run_id, as_of='2026-09-30',
                 security_code='ALL', decision_type=kind, decision_result=result, summary_reason=reason, input_files=inputs,
                 output_file='data/experiments/exp_land_v4225_20260930/publication.json', operator_or_script='exp_land_v4225_20260930/log.py',
                 workflow_version=WORKFLOW_VERSION)
            for run_id, stage, kind, result, reason, inputs in ROWS if run_id not in done]
    if rows:
        append_decision_log(DEFAULT_DECISION_LOG, rows)
    print('decision log rows appended', len(rows))


if __name__ == '__main__':
    main()
