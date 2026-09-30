"""OI-250 试点：合并两份业务属性判定，按口径（rubric.md）核对标签与派生类别，并与财务读数（峰守卫、量驱动、入队）交叉。

    python3 pilot.py      # → attributes.csv、pilot.md、pilot.json
"""
import csv
import json
from collections import Counter
from pathlib import Path

EXP = Path(__file__).resolve().parent
ALLOWED = dict(pricing_mode={'商品价格接受者', '差异化定价'}, demand_runway={'存量', '结构扩张'}, replicability={'易复制', '难复制'},
               cost_position={'领先', '一般', '不适用'}, confidence={'高', '中', '低'})
CLASSES = ('价格周期型', '成本领先周期型', '结构成长型', '可复制成长型', '稳定型')
FIELDS = ['security_code', 'security_name', 'pricing_mode', 'demand_runway', 'replicability', 'cost_position', 'derived_class', 'guard_view',
          'evidence', 'evidence_date', 'falsifier', 'confidence', 'note']


def expected_class(r):
    """rubric.md 派生规则。"""
    if r['pricing_mode'] == '商品价格接受者':
        return '成本领先周期型' if r['cost_position'] == '领先' else '价格周期型'
    if r['demand_runway'] == '结构扩张':
        return '结构成长型' if r['replicability'] == '难复制' else '可复制成长型'
    return '稳定型'


def main():
    inputs = {r['security_code']: r for r in csv.DictReader((EXP / 'inputs.csv').open(encoding='utf-8'))}
    rows = []
    for part in ('attributes_part1.csv', 'attributes_part2.csv'):
        rows += list(csv.DictReader((EXP / part).open(encoding='utf-8-sig')))
    for r in rows:
        r['security_code'] = r['security_code'].strip().zfill(6)
    issues = []
    codes = [r['security_code'] for r in rows]
    missing = sorted(set(inputs) - set(codes))
    dupes = sorted(c for c, n in Counter(codes).items() if n > 1)
    if missing or dupes:
        issues.append(f'缺 {missing}，重复 {dupes}')
    for r in rows:
        for k, allowed in ALLOWED.items():
            if r.get(k, '').strip() not in allowed:
                issues.append(f"{r['security_code']} {k}={r.get(k)!r} 不在口径内")
        exp = expected_class(r)
        if r.get('derived_class', '').strip() != exp:
            issues.append(f"{r['security_code']} 派生类别 {r.get('derived_class')!r} 与规则 {exp!r} 不符")
        if r['pricing_mode'] == '差异化定价' and r['cost_position'] != '不适用':
            issues.append(f"{r['security_code']} 差异化定价却判成本地位 {r['cost_position']}")
        if (r.get('evidence_date') or '') > '2026-09-30':
            issues.append(f"{r['security_code']} 依据日 {r.get('evidence_date')} 晚于判定时点")
    rows.sort(key=lambda r: r['security_code'])
    with (EXP / 'attributes.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    by_class = Counter(r['derived_class'] for r in rows)
    cross = Counter((r['derived_class'], inputs[r['security_code']]['volume_driven'] == 'True', inputs[r['security_code']]['flagged'] == 'True')
                    for r in rows)
    res = dict(n=len(rows), issues=issues, by_class={c: by_class.get(c, 0) for c in CLASSES},
               cross=[dict(derived_class=c, volume_driven=v, flagged=f, n=n) for (c, v, f), n in sorted(cross.items())],
               confidence=dict(Counter(r['confidence'] for r in rows)))
    (EXP / 'pilot.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    out = ['# OI-250 试点：峰守卫生效的池内 57 只的业务属性（2026-09-30，交用户审阅口径）', '',
           f"口径见 `rubric.md`；逐只见 `attributes.csv`。核对问题 {len(issues)} 条" + ('：' + '；'.join(issues) if issues else '。'), '',
           '## 一、按类别', '', '| 类别 | 只数 | 其中量驱动 | 其中入队（§7.3） |', '| --- | ---: | ---: | ---: |']
    for c in CLASSES:
        members = [r for r in rows if r['derived_class'] == c]
        vol = sum(inputs[r['security_code']]['volume_driven'] == 'True' for r in members)
        flg = sum(inputs[r['security_code']]['flagged'] == 'True' for r in members)
        out.append(f'| {c} | {len(members)} | {vol} | {flg} |')
    out += ['', '## 二、逐只（按类别）', '', '| 类别 | 代码 | 名称 | 定价方式 | 需求空间 | 可复制性 | 成本地位 | 峰守卫 w | 量驱动 | 守卫砍掉 | 峰守卫看法 | 可证伪条件 | 把握 |',
            '| --- | --- | --- | --- | --- | --- | --- | ---: | --- | ---: | --- | --- | --- |']
    order = {c: i for i, c in enumerate(CLASSES)}
    for r in sorted(rows, key=lambda r: (order.get(r['derived_class'], 9), r['security_code'])):
        i = inputs[r['security_code']]
        cut = f"{float(i['guard_cut']):.0%}" if i['guard_cut'] else '—'
        out.append(f"| {r['derived_class']} | {r['security_code']} | {r['security_name']} | {r['pricing_mode']} | {r['demand_runway']} | {r['replicability']} | "
                   f"{r['cost_position']} | {float(i['peak_weight']):.2f} | {'是' if i['volume_driven'] == 'True' else '否'} | {cut} | {r['guard_view']} | "
                   f"{r['falsifier']} | {r['confidence']} |")
    (EXP / 'pilot.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
