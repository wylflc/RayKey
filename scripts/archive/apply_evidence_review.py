#!/usr/bin/env python3
"""增量落盘证据复核结果。原子写入 + 追加日志，任务中断不丢中间结果。

用法：作为模块导入，调用 apply(updates, batch_label)
updates: {公司名: (Q2或None, Q1或None, status, note, sources)}
status: verified | verified_stronger | verified_with_caveat | corrected | reexamined_no_source
"""
import csv, os, re, tempfile, collections, datetime

CSV = 'data/processed/a_share_quality_scores_v2.csv'
LOG = 'data/archive/completed-queues/evidence_review_log.md'
W = (.25, .40, .20, .15)

def _ero_block(fl):
    m = re.search(r'erosion_path\(([^)]*)\)', fl)
    if not m: return False, ''
    s = m.group(1)
    pr = '高' if ('中高' in s or '高' in s) else ('中' if ('中' in s or '持续' in s) else '低')
    return pr in ('中', '高'), pr

def classify(r):
    g = lambda k: float(r[k])
    q1, q2 = g('q1_business_model_score'), g('q2_moat_score')
    fl = r['flags']; blk, pr = _ero_block(fl)
    if 'dominated' in fl: return 'L3', '被更强同行全面覆盖且无不可替代利基'
    if q2 < 66: return 'L3', f'护城河本身弱（Q2={q2:.0f}<66）'
    if q1 < 60 and q2 < 72: return 'L3', f'护城河仅及格（Q2={q2:.0f}）且生意模式塌陷（Q1={q1:.0f}），无可倚仗项'
    A = q2 >= 82 and q1 >= 66; B = q1 >= 80 and q2 >= 78
    if A or B:
        if blk: return 'L2', f'达强档水平但存在{pr}概率可见侵蚀路径'
        return 'L1', ('通道A 护城河型' if A else '通道B 生意模式型') + f'：Q2={q2:.0f} Q1={q1:.0f}'
    if q1 < 60: return 'L2', f'护城河强（Q2={q2:.0f}）足以倚仗，但生意模式塌陷（Q1={q1:.0f}）——降一档不越档'
    if q2 >= 82 and q1 < 66: return 'L2', f'护城河达强档（Q2={q2:.0f}）但生意模式不足（Q1={q1:.0f}<66）'
    return 'L2', '资本复制测试通过，但存在可见侵蚀路径或明确同业竞争'

def apply(updates, batch_label):
    rows = list(csv.DictReader(open(CSV, encoding='utf-8-sig')))
    by = {r['security_name']: r for r in rows}
    miss = [n for n in updates if n not in by]
    if miss: raise SystemExit(f'不在名单: {miss}')
    old_tier = {r['security_name']: r['quality_tier'] for r in rows}
    old_q2 = {r['security_name']: r['q2_moat_score'] for r in rows}
    for n, (q2, q1, st, note, src) in updates.items():
        r = by[n]
        if q2 is not None: r['q2_moat_score'] = str(q2)
        if q1 is not None: r['q1_business_model_score'] = str(q1)
        q = [float(r['q1_business_model_score']), float(r['q2_moat_score']),
             float(r['q3_capital_allocation_score']), float(r['q4_management_score'])]
        r['quality_score'] = str(round(sum(a*b for a, b in zip(q, W)) + float(r['credibility_deduction']), 2))
        r['evidence_status'] = st; r['evidence_note'] = note; r['evidence_sources'] = src
    for r in rows:
        t, why = classify(r); r['quality_tier'] = t; r['tier_reason'] = why
    rows.sort(key=lambda r: ({'L1':0,'L2':1,'L3':2}[r['quality_tier']], -float(r['quality_score'])))
    d = os.path.dirname(CSV); fd, tmp = tempfile.mkstemp(dir=d, suffix='.csv'); os.close(fd)
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    os.replace(tmp, CSV)
    moved = [(n, old_tier[n], by[n]['quality_tier']) for n in updates if old_tier[n] != by[n]['quality_tier']]
    lines = [f'\n## {batch_label}（{datetime.date.today()}）\n',
             f'本批 {len(updates)} 家；改档 {len(moved)} 家\n']
    for n, (q2, q1, st, note, src) in updates.items():
        r = by[n]
        chg = f"Q2 {old_q2[n]}→{r['q2_moat_score']}" if q2 is not None and str(q2) != old_q2[n] else 'Q2 不变'
        mv = f" **{old_tier[n]}→{r['quality_tier']}**" if old_tier[n] != r['quality_tier'] else ''
        lines.append(f"- **{n}** [{st}] {chg}{mv}｜{note}｜来源：{src}\n")
    with open(LOG, 'a', encoding='utf-8') as f: f.writelines(lines)
    c = collections.Counter(r['quality_tier'] for r in rows)
    done = sum(1 for r in rows if r['evidence_status'] != 'calibration_model_knowledge')
    print(f"[{batch_label}] 本批 {len(updates)} 家，改档 {len(moved)}: {moved or '无'}")
    print(f"  全池 L1 {c['L1']} | L2 {c['L2']} | L3 {c['L3']}  ｜ 已复核 {done}/261")
    return moved
