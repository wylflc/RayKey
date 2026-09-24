"""OI-209 回填：池内 ROIC 路径档案中，fundamentals.md 已写明正常化盈利水平的 8 家，按 §6.5.2.2 登记研究正常化盈利（NOPAT 口径）。

研究原文均为归母净利口径（区间取中值），按 §6.5.2.2 的模型股权桥反解为 NOPAT（v4.203：`归母 ÷ (1 − 生产带 minority_share)
+ (最新年报 NOPAT − 合并净利)`，`build_report_update_queue.research_nopat_from_parent`；v4.202 的近五个年报 NOPAT ÷ 归母中位
另记于 backfill.json 的 `ratio_v4202` 备查）。
池外 8 家（中钨高新、锡业股份、大族激光、奔图科技、北方稀土、厦门钨业、赣锋锂业、天坛生物）无生产带，不回填。
    python3 backfill.py [--dry-run]
"""
import csv
import json
import statistics
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import roic_inputs  # noqa: E402
from build_report_update_queue import research_nopat_from_parent  # noqa: E402

DOSSIERS = ROOT / 'data/processed/a_share_valuation_dossiers.csv'
BANDS = ROOT / 'data/processed/a_share_pool_model_bands_adopted.csv'
NEW_FIELDS = ['research_nopat_yi', 'research_evidence_date', 'research_falsifier', 'research_source', 'divergence_reviewed_at',
              'divergence_review_note', 'divergence_reviewed_model_yi', 'divergence_reviewed_research_yi']
# 代码: (归母下限, 上限, 公告日, 原文, 中枢假设)
ITEMS = {
    '000858': (190, 190, '2026-07-15', '带锚=渠道重置后正常化中枢约190亿，26-27E口径', '渠道重置后批价与打款恢复'),
    '000893': (30, 38, '2026-07-15', '正常化锚=中枢钾价2500-2800元/吨×2027产量归母30-38亿', '中枢钾价 2,500～2,800 元/吨与 2027 年产量'),
    '002128': (55, 65, '2026-07-15', '带锚=中枢正常化归母55-65亿×PE11x', '煤炭与电解铝中枢价格'),
    '002466': (55, 70, '2026-07-15', '带锚=中枢锂价正常化归母55-70亿', '中枢锂价'),
    '002714': (175, 210, '2026-07-11', '带锚=跨周期中枢归母175-210亿', '跨周期猪价中枢与完全成本'),
    '600176': (45, 55, '2026-07-15', '正常化锚=玻纤主业+电子布中枢归母45-55亿', '玻纤主业与电子布中枢价格'),
    '600989': (130, 150, '2026-07-14', '带锚=中枢价差正常化归母130-150亿', '烯烃中枢价差'),
    '603806': (18, 22, '2026-07-14', '中枢归母18-22亿', '胶膜中枢价格与份额'),
}


def main(dry_run: bool) -> None:
    years = roic_inputs.load_statements(codes=set(ITEMS), ic_floor=0.1)
    bands = {r['security_code']: r for r in csv.DictReader(BANDS.open(encoding='utf-8-sig'))}
    rows = list(csv.DictReader(DOSSIERS.open(encoding='utf-8-sig')))
    header = list(rows[0].keys()) + [f for f in NEW_FIELDS if f not in rows[0]]
    record = {}
    for row in rows:
        for field in NEW_FIELDS:
            row.setdefault(field, '')
        code = row['security_code']
        if code not in ITEMS:
            continue
        lo, hi, date, quote, premise = ITEMS[code]
        annual = [years[code][p] for p in sorted(years[code]) if p.endswith('12-31')][-5:]
        ratios = [y.nopat / y.parent_netprofit for y in annual
                  if y.nopat is not None and y.parent_netprofit and y.parent_netprofit > 0]
        ratio = statistics.median(ratios)
        mid = (lo + hi) / 2
        m = float(bands[code]['minority_share'])
        fin = (annual[-1].nopat - annual[-1].net_profit) / 1e8
        value = research_nopat_from_parent(mid, m, annual[-1].nopat / 1e8, annual[-1].net_profit / 1e8)
        band = f'{lo}～{hi} 亿' if lo != hi else f'{lo} 亿 ±30%'
        row['research_nopat_yi'] = f'{value:.2f}'
        row['research_evidence_date'] = date
        row['research_falsifier'] = f'连续两个年报归母落在 {band} 之外，且「{premise}」未兑现'
        row['research_source'] = (f'fundamentals.md 2026H1 预告行（公告日 {date}）原文「{quote}」；归母中值 {mid:g} 亿 ÷ (1 − 少数股东份额 {m:.3f}) '
                                  f'{fin:+.2f} 亿（{annual[-1].period[:4]} 年报 NOPAT − 合并净利）= {value:.2f} 亿（OI-209 回填，v4.203 股权桥换算）')
        record[code] = dict(name=row['security_name'], parent_mid=mid, minority_share=m, nopat_less_net_profit_yi=round(fin, 4),
                            research_nopat_yi=round(value, 2), evidence_date=date, ratios_v4202=ratios, ratio_v4202=ratio,
                            research_nopat_v4202=round(mid * ratio, 2))
    (EXP / 'backfill.json').write_text(json.dumps(record, ensure_ascii=False, indent=1))
    for code, r in record.items():
        print(code, r['name'], r['parent_mid'], f"÷ (1 − {r['minority_share']:.3f}) {r['nopat_less_net_profit_yi']:+.2f} = {r['research_nopat_yi']}"
              f"（v4.202 {r['research_nopat_v4202']}）")
    if not dry_run:
        with DOSSIERS.open('w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=header)
            writer.writeheader(); writer.writerows(rows)
        print('wrote', DOSSIERS)


if __name__ == '__main__':
    main('--dry-run' in sys.argv)
