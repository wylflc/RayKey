"""OI-250 口径 v2（rubric.md）：把可复制性重判（`replicability_v2.csv`）并入 v1 判定，按规则重算类别与峰守卫看法，
写 `attributes_v2.csv` 与生产登记表 `data/processed/a_share_business_attributes.csv`（个人投资体系第 5.12 节）。

    python3 registry.py
"""
import csv
import json
from collections import Counter
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
REGISTRY = ROOT / 'data/processed/a_share_business_attributes.csv'
REGISTERED_AT = '2026-10-01'
VERSION = 'v2'
GUARD = {'价格周期型': '保留峰守卫；周期中枢可按概率加权的长期价格经 §6.5.2.2 研究数调整',
         '成本领先周期型': '保留峰守卫；周期中枢可按概率加权的长期价格经 §6.5.2.2 研究数调整',
         '结构成长型': '可个案放宽：经 §6.5.2.2 研究数复核',
         '可复制成长型': '保留：扩产与竞争会侵蚀回报',
         '稳定型': '保留：守卫作用多为消化一次性高位'}
FIELDS = ['security_code', 'security_name', 'pricing_mode', 'demand_runway', 'replicability', 'cost_position', 'derived_class', 'guard_view',
          'evidence', 'evidence_date', 'falsifier', 'confidence', 'note', 'rubric_version', 'registered_at']


def derived(r):
    if r['pricing_mode'] == '商品价格接受者':
        return '成本领先周期型' if r['cost_position'] == '领先' else '价格周期型'
    if r['demand_runway'] == '结构扩张':
        return '结构成长型' if r['replicability'] == '难复制' else '可复制成长型'
    return '稳定型'


def main():
    v1 = {r['security_code'].zfill(6): r for r in csv.DictReader((EXP / 'attributes.csv').open(encoding='utf-8'))}
    rep = {r['security_code'].strip().zfill(6): r for r in csv.DictReader((EXP / 'replicability_v2.csv').open(encoding='utf-8-sig'))}
    diff = [c for c, r in v1.items() if r['pricing_mode'] == '差异化定价' and c not in rep]
    assert not diff, ('差异化定价行缺重判', diff)
    changes, rows = [], []
    for code, r in sorted(v1.items()):
        r = dict(r)
        old_class = r['derived_class']
        if code in rep:
            q = rep[code]
            assert q['replicability_v2'] in ('易复制', '难复制'), (code, q['replicability_v2'])
            if q['replicability_v2'] != r['replicability']:
                r['replicability'] = q['replicability_v2']
                r['evidence'] = (q['replicability_evidence'] or '')[:120]
                r['confidence'] = q['confidence'] or r['confidence']
                r['note'] = (f"v1 可复制性 {q['replicability_v1']}，v2 改 {q['replicability_v2']}；毛利率 {q.get('gross_margin_trend', '')}；" + (r.get('note') or ''))[:200]
        r['derived_class'] = derived(r)
        r['guard_view'] = GUARD[r['derived_class']]
        if r['derived_class'] != old_class:
            changes.append(dict(code=code, name=r['security_name'], v1=old_class, v2=r['derived_class']))
        r['rubric_version'], r['registered_at'] = VERSION, REGISTERED_AT
        rows.append(r)
    for path in (EXP / 'attributes_v2.csv', REGISTRY):
        with path.open('w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)
    res = dict(n=len(rows), by_class=dict(Counter(r['derived_class'] for r in rows)), changes=changes)
    (EXP / 'registry.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
