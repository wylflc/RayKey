"""OI-209 首批差距复核（2026-09-24）：五粮液、亚钾国际、天齐锂业、牧原股份。

在 backfill.py（v4.203 股权桥换算）之后运行，写档案复核四列，并按复核结论修订亚钾国际研究数（改按现有已投产产能，§6.5.2.2）
与牧原股份可证伪条件（跨周期数改按三年平均）。研究口径敏感度：把生产带每股 NOPAT 换成研究数（投入资本不变 → ROIC0 同比例），
其余参数与股权桥照生产带，价格取 09-23 收盘。证据：2026 半年报（巨潮）与东方财富盈利预测（2026-09-24 抓取，`forecast_0924.json`）。
    python3 review.py [--dry-run]
"""
import csv
import json
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import minority_claims  # noqa: E402
from build_report_update_queue import research_divergence  # noqa: E402
from intrinsic_value import intrinsic_value  # noqa: E402

DOSSIERS = ROOT / 'data/processed/a_share_valuation_dossiers.csv'
BANDS = ROOT / 'data/processed/a_share_pool_model_bands_adopted.csv'
REVIEWED_AT = '2026-09-24'
CLOSE = {'000858': 70.34, '000893': 38.98, '002466': 42.42, '002714': 41.40}   # 2026-09-23 收盘
BUY_LINE = 0.9524

# 亚钾国际 2026 半年报（2026-08-28）：合并利润表与经营回顾
KCL = dict(sold_wt=131.25, produced_wt=149.49, capacity_wt=300.0, revenue=38.21523344, cogs=15.31819448, surcharges=2.58665364,
           period_costs=0.25607022 + 2.88736714 + 0.13004763, associates=0.87093051, pretax=17.10616321, tax=3.59121608)


def potash_nopat(price: float) -> float:
    """现有 300 万吨 × 研究中枢价：单位营业成本、税金及附加占收入比、期间费用与联营收益（年化）取半年报，税率取半年报实际。"""
    unit_cogs = KCL['cogs'] / KCL['sold_wt'] * 1e4                       # 元/吨
    surcharge_rate = KCL['surcharges'] / KCL['revenue']
    ebit = (price * (1 - surcharge_rate) - unit_cogs) * KCL['capacity_wt'] / 1e4 - 2 * KCL['period_costs'] + 2 * KCL['associates']
    return ebit * (1 - KCL['tax'] / KCL['pretax'])


def research_value(band: dict, research_yi: float) -> float:
    f = lambda k: float(band[k]) if band[k] else 0.0
    k = research_yi * 1e8 / f('shares_est') / f('nopat_ps')
    nps, roic0, w = f('nopat_ps') * k, f('roic0') * k, f('wacc')
    res = intrinsic_value(nps, roic0, f('g0'), w, roe_terminal=min(w + 0.02, roic0), g_terminal=0.03, n=10, n1=0,
                          consistent=True, roe_lam=0.12, horizon=50)
    nd, _ = minority_claims.equity_bridge(res.intrinsic_value, f('fin_net_debt_ps'), f('minority_book_ps'), f('minority_share'),
                                          f('external_equity_ps'), f('minority_fixed_claim_ps'), f('minority_dividend_floor_ps'))
    return res.intrinsic_value - nd


def potash_source() -> str:
    lo, mid, hi = (potash_nopat(p) for p in (2500, 2650, 2800))
    unit_cogs = KCL['cogs'] / KCL['sold_wt'] * 1e4
    return ('复核重述（2026-09-24，§6.5.2.2 同一产能口径）：原文「正常化锚=中枢钾价2500-2800元/吨×2027产量归母30-38亿」按 2027 年产量'
            '（约 390 万吨，含未建成的第二个百万吨项目）计，扩产由模型增速腿计价，改按现有已投产产能重述。2026 半年报（公告日 2026-08-28）：'
            f'300 万吨/年产能已稳定生产，上半年产量 {KCL["produced_wt"]} 万吨、销量 {KCL["sold_wt"]} 万吨；单位营业成本 {unit_cogs:,.0f} 元/吨、'
            f'税金及附加占收入 {KCL["surcharges"] / KCL["revenue"]:.2%}、期间费用年化 {2 * KCL["period_costs"]:.2f} 亿、联营收益年化 '
            f'{2 * KCL["associates"]:.2f} 亿、所得税率 {KCL["tax"] / KCL["pretax"]:.1%}。中枢价 2,650 元/吨 × 300 万吨 → NOPAT {mid:.2f} 亿'
            f'（2,500～2,800 元/吨对应 {lo:.2f}～{hi:.2f} 亿）')


REVIEWS = {
    '000858': dict(
        evidence_date='2026-08-31',
        source_add='；复核 2026-09-24：中报后 7 家研报（08-29～08-31）归母中位 26E 155.1／27E 172.8／28E 189.3 亿，26-27E 较 07-15 一致预期'
                   '（178.4／196.7）下调约 13%，约 190 亿的正常化水平推迟到 2028E；中报归母 87.53 亿落在预告 87.30～92.00 亿下沿',
        note='维持模型（用户 2026-09-24 裁定）：模型谷底守卫取五年 NOPAT／经营账面中位（约 2021～2024 水平）回归，研究数按渠道重置后'
             '约 190 亿归母（较 2024 峰值 318.5 亿低约 40%），中报后一致预期 2028E 189.3 亿支持该水平；研究口径 V {rv:.2f}、P/V {rpv:.3f}，'
             '模型 P/V {mpv:.3f}，研究口径下现价约为公允而非高估；上一轮白酒下行归母 2012 99.3 → 2014 58.3 → 2017 96.7 亿，三年回到前高'),
    '000893': dict(
        research=lambda: potash_nopat(2650), evidence_date='2026-08-28', source=potash_source,
        falsifier='2026、2027 年报钾肥产量低于 270 万吨（现有产能九成），或氯化钾年均售价在 2,500～2,800 元/吨时年度 NOPAT 低于 23.8 亿',
        note='修订研究数、维持模型：原研究数按 2027 年产量计，与模型锚产能口径不同，按现有 300 万吨重述为 {r:.2f} 亿，仍高于模型锚 '
             '{m:.2f} 亿 {gap:.0%}（模型锚 = 五年 NOPAT／经营账面中位 × 经营账面，第三个百万吨项目 2025-12 投产的盈利待年报进入锚）；'
             '研究数高于模型锚，依 v4.203 不冻结；研究口径 V {rv:.2f}、P/V {rpv:.3f}，模型 P/V {mpv:.3f}，两者均在买入线之上'),
    '002466': dict(
        evidence_date='2026-08-28',
        source_add='；复核 2026-09-24：中报归母 42.42 亿（预告 28.5～42.5 亿上沿），东吴证券 08-28 预测归母 26E 83.9／27E 91.8 亿，现价锂价下盈利'
                   '高于中枢研究数，与「中枢」定义一致',
        note='修订研究数（换算）、维持模型：v4.202 按近五年 NOPAT／归母中位 2.53 换算失真——少数股东分走合并净利 0.20～0.85（格林布什经 '
             'TLEA 51% 并表），归母是母公司层面项目后的余数；按模型股权桥反解为 {r:.2f} 亿，与模型锚 {m:.2f} 亿差 {gap:.1%}，未超过 30%；'
             '研究口径 V {rv:.2f}、P/V {rpv:.3f}，模型 P/V {mpv:.3f}'),
    '002714': dict(
        evidence_date='2026-08-26',
        falsifier='2026～2028 年三个年报归母平均低于 175 亿，或完全成本与全国平均的差距收窄到 1 元/kg 以内（2026-03 为 11.6 对 14.1）',
        source_add='；复核 2026-09-24：半年报（08-21）6 月完全成本约 11.7 元/kg（3 月 11.6），上半年销售商品猪 3,861.5 万头；中报后 14 家研报'
                   '（08-21～08-26）一致预期归母 26E 7.5／27E 262.9／28E 244.1 亿，三年平均 171.5 亿',
        note='修订研究数（换算与可证伪条件）、维持模型：研究数是跨周期中枢，单年落在区间外是周期常态，可证伪条件改按三年平均；模型锚取 '
             '2021～2025 五年 NOPAT／经营账面中位（已实现周期，成本优势扩大前），研究数以现有成本优势外推，差距 {gap:.0%} 是前瞻假设之差；'
             '研究数高于模型锚，依 v4.203 不冻结；研究口径 V {rv:.2f}、P/V {rpv:.3f}，模型 P/V {mpv:.3f}'),
}


def main(dry_run: bool) -> None:
    bands = {r['security_code']: r for r in csv.DictReader(BANDS.open(encoding='utf-8-sig'))}
    rows = list(csv.DictReader(DOSSIERS.open(encoding='utf-8-sig')))
    V4202 = {c: r['research_nopat_v4202'] for c, r in json.loads((EXP / 'backfill.json').read_text()).items()}
    record = {}
    for row in rows:
        code = row['security_code']
        spec = REVIEWS.get(code)
        if spec is None:
            continue
        band = bands[code]
        before = research_divergence(row, band)
        if 'research' in spec:
            row['research_nopat_yi'] = f"{spec['research']():.2f}"
        if 'source' in spec:
            row['research_source'] = spec['source']()
        row['research_source'] += spec.get('source_add', '')
        row['research_evidence_date'] = spec['evidence_date']
        if 'falsifier' in spec:
            row['research_falsifier'] = spec['falsifier']
        div = research_divergence(row, band)
        research, model = div['research'], div['model']
        rv, iv = research_value(band, research), float(band['intrinsic_value'])
        fill = dict(r=research, m=model, gap=div['gap'], rv=rv, rpv=CLOSE[code] / rv, mpv=CLOSE[code] / iv)
        row['divergence_reviewed_at'] = REVIEWED_AT
        row['divergence_review_note'] = spec['note'].format(**fill)
        row['divergence_reviewed_model_yi'] = f'{model:.2f}'
        row['divergence_reviewed_research_yi'] = f'{research:.2f}'
        after = research_divergence(row, band)
        record[code] = dict(name=row['security_name'], research_v4202=V4202[code], research_before=before['research'], research=research, model=model,
                            gap=div['gap'], freeze_before_review=bool(div['freeze']), triggered_after_review=after['triggered'],
                            v_model=iv, v_research=rv, pv_model=fill['mpv'], pv_research=fill['rpv'], close=CLOSE[code],
                            research_below_buy_line=fill['rpv'] <= BUY_LINE, note=row['divergence_review_note'])
        print(f"{code} {row['security_name']} 研究 {before['research']:.2f}→{research:.2f} 模型 {model:.2f} 差距 {div['gap']:.1%} "
              f"冻结 {div['freeze']} | V 模型 {iv:.2f}／研究 {rv:.2f} P/V {fill['mpv']:.3f}／{fill['rpv']:.3f} | 复核后入队 {after['triggered']}")
    record['_potash_nopat'] = {str(p): round(potash_nopat(p), 2) for p in (2500, 2650, 2800)}
    (EXP / 'review.json').write_text(json.dumps(record, ensure_ascii=False, indent=1))
    if not dry_run:
        with DOSSIERS.open('w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader(); writer.writerows(rows)
        print('wrote', DOSSIERS)


if __name__ == '__main__':
    main('--dry-run' in sys.argv)
