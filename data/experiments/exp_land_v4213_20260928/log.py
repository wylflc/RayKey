"""决策日志：2026-09-28 用户裁定与 v4.213 落地行（须在重发扫描之前写入，发布摘要覆盖决策日志）。"""
import sys
from datetime import datetime, timezone
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION  # noqa: E402
import csv

ROWS = [
    ('OI-205-20260928', 'workflow_rule', 'valuation_caliber', 'not_adopted',
     'OI-205 v4.210 口径重测（exp_oi205b_20260928）：峰谷守卫只对 H／F 生效——公允性检验面板 3 年行业×月效应 λ峰 −3.47、λ谷 −2.64（区间均不含 0，方向错），分歧样本两侧均为现行更准；第 13 款陷阱段踩中率 +2.7pp；回测主读数 −2.34／−6.70pp（劣化）。用户 2026-09-28 裁定不采纳、结案，改正 09-24 的范围裁定；守卫维持对全部公司生效，研究开关保留。',
     'data/experiments/exp_oi205b_20260928/fairness.json'),
    ('OI-212-20260928', 'mechanism_repair', 'valuation_caliber', 'adopted',
     'OI-212（v4.213）：主体重置后不足三个年报的行按 data/reference/entity_reset_guard_anchor.csv 登记的参照恢复峰谷守卫（重置前主体 ROIC 或同业年报加权 ROE 的周期位置，坡道同 §6.5.1），建带 --reset-guard both。当前只改宏桥（同业周期高位，V 21.63→14.41）；回测面板无重置股，BASE 不受影响。用户 2026-09-28 裁定采纳峰谷两侧。',
     'data/experiments/exp_oi212_20260928/README.md'),
    ('OI-214-20260928', 'mechanism_repair', 'data_correction', 'adopted',
     'OI-214：150 条未配对更正公告逐条核对（79 个事件），东财对重述期原位覆盖、公告日不变；回测宇宙在册期内 18 个事件按 §6.3 第 2 条登记 25 行重述前原文版本（双汇 2009–2012、上海家化 2012–2017、露天煤业 2009、京东方、北方华创、养元），历史状态重建并按新状态重登 BASE。用户 2026-09-28 裁定落地；早年面板前视等系统性问题另登记 OI-225。',
     'data/experiments/exp_land_v4213_20260928/README.md'),
    ('OI-216-20260928', 'mechanism_repair', 'data_correction', 'adopted',
     'OI-216（v4.214）：海外取数字段级补录表（东方海外、海底捞经营溢利内利息收入，京东权益法份额与非权益法投资，优步投资，台积电非流动金融资产），英伟达公允价值股权证券入流动证券并防重计，台积电 2019–2024 补应付公司债，港股 F10 分页稳定排序；V：京东 +85%、东方海外 −20%、优步 +11%、台积电 −7.3%、海底捞 −4.4%、英伟达 +2.6%，其余 24 家不变。用户 2026-09-28 裁定落地；余项登记 OI-226。',
     'data/experiments/exp_oi216_20260928/oi216_summary.md'),
    ('OI-rulings-20260928', 'workflow_rule', 'research_plan', 'ruled',
     '用户 2026-09-28 裁定：推进顺序先守卫后折现率；OI-223 五档 8%～12%、风险为主质量为辅，设计草案照建议（护城河放人工调档层、70:30、10/20/40/20/10、年报不足 5 年取 11%）；OI-224 四个方向都测，陷阱约束先做识别检验，现金转换作为放宽臂的附加变体；OI-207 再测两个混合候选（利差尺度校正、股利尺度 × DDM 排序）；OI-206 每股口径、剔除并购、上限 8/12/16%；OI-216 海外取数修正落地；OI-213 排在最后做有限版。',
     'docs/reports/oi223_design_draft_2026-09-28.zh.md;docs/reports/oi224_research_plan_2026-09-28.zh.md'),
]


def main():
    done = {r['run_id'] for r in csv.DictReader(open(DEFAULT_DECISION_LOG, encoding='utf-8'))}
    rows = [dict(logged_at_utc=datetime.now(timezone.utc).isoformat(), workflow_stage=stage, run_id=run_id, as_of='2026-09-28',
                 security_code='ALL', decision_type=kind, decision_result=result, summary_reason=reason, input_files=inputs,
                 output_file='data/experiments/exp_land_v4213_20260928/publication.json', operator_or_script='exp_land_v4213_20260928/log.py',
                 workflow_version=WORKFLOW_VERSION)
            for run_id, stage, kind, result, reason, inputs in ROWS if run_id not in done]
    if rows:
        append_decision_log(DEFAULT_DECISION_LOG, rows)
    print('decision log rows appended', len(rows))


if __name__ == '__main__':
    main()
