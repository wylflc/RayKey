"""OI-215 附注现金类重解析（候选规则，不写生产文件）：缓存年报文本 → 本目录 cash_note_items.csv，与现行逐行对照。

候选规则（其余判定——合计相符、明细相符、现金类关键词——不变）：
  R1 附注标题的序号在 PDF 文本层丢失、只剩独占一行的行名时（2025 年报多见），在附注正文起点之后按
     「独占一行的行名 + 其后 300 字内出现表头」定位该节；
  R2 表头只写两个年份（「2025年 2024年」，A+H 与港式版式）或「账面余额」时也认作表头。

    python3 reparse.py [--codes 002463,002594]
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import fetch_cash_note_items as fcn  # noqa: E402

PRODUCTION = fcn.OUT
fcn.OUT = EXP / 'cash_note_items.csv'          # write() 只写本目录
original_section = fcn.section


HEADER = re.compile(r"项\s*目|单位|适用|期末|年末|\d{4}\s*年\s*\d{1,2}\s*月"
                    r"|(?:19|20)\d{2}\s*年\s+(?:19|20)\d{2}\s*年|账\s*面\s*余\s*额")                # R2


def section(text: str, label: str, start: int):
    found = original_section(text, label, start)
    if found is not None:
        return found
    numbered = re.compile(r"(?:^|\n)[ \t]*(?:\d{1,3}\s*[、．.]|[（(](?:[一二三四五六七八九十百]+|\d{1,3})[)）])\s*"
                          + re.escape(label) + r"(?![\u4e00-\u9fa5”\"])")
    patterns = [numbered]                                                                   # R2：带序号的标题
    if start > 0:
        patterns.append(re.compile(r"(?:^|\n)[ \t]*" + re.escape(label) + r"[ \t]*(?=\n)"))   # R1：只剩行名
    for pattern in patterns:
        for m in pattern.finditer(text, start):
            if HEADER.search(text[m.end():m.end() + 300]):
                return text[m.end():m.end() + 4000]
    return None


fcn.section = section


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--codes')
    a = ap.parse_args()
    codes = {c.strip().zfill(6) for c in a.codes.split(',')} if a.codes else None
    tasks = fcn.plan(codes, None)
    old = {}
    with PRODUCTION.open(encoding='utf-8') as f:
        for r in csv.DictReader(f):
            old[(r['security_code'], int(r['fiscal_year']), r['line'])] = r
    results = {}
    for t in tasks:
        path = fcn.CACHE / t['code'] / f"{t['year']}.json"
        meta = json.loads(path.read_text()) if path.exists() else dict(status='not_fetched')
        results[(t['code'], t['year'])] = fcn.parse_task(t, meta)
    new = {(r['security_code'], int(r['fiscal_year']), r['line']): r for rs in results.values() for r in rs}
    if codes is None:
        fcn.write(results)
    moves, changed = Counter(), []
    for key, r in new.items():
        o = old.get(key)
        before = o['status'] if o else 'absent'
        moves[(before, r['status'])] += 1
        if o is None or o['cash_like_amount'] != r['cash_like_amount'] or o['status'] != r['status']:
            changed.append((key, before, r['status'], float(o['cash_like_amount']) if o else 0.0, float(r['cash_like_amount'] or 0), r['items'][:90]))
    ok_old = sum(float(o['statement_amount'] or 0) for k, o in old.items() if o['status'] == 'ok' and k in new)
    ok_new = sum(float(r['statement_amount'] or 0) for r in new.values() if r['status'] == 'ok')
    total = sum(float(r['statement_amount'] or 0) for r in new.values()) or 1
    summary = dict(tasks=len(tasks), rows=len(new), moves={f'{a}→{b}': n for (a, b), n in moves.most_common()},
                   coverage_old=ok_old / total, coverage_new=ok_new / total,
                   cash_old=sum(float(old[k]['cash_like_amount'] or 0) for k in new if k in old),
                   cash_new=sum(float(r['cash_like_amount'] or 0) for r in new.values()),
                   changed_rows=len(changed))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for key, b, s, co, cn, items in sorted(changed, key=lambda x: -(x[4] - x[3]))[:40]:
        print(key, b, '→', s, f'{co / 1e8:.2f}亿 → {cn / 1e8:.2f}亿', items)
    if codes is None:
        (EXP / 'reparse_summary.json').write_text(json.dumps(dict(summary, changed=[
            dict(code=k[0], year=k[1], line=k[2], before=b, after=s, cash_before=co, cash_after=cn, items=i)
            for k, b, s, co, cn, i in changed]), ensure_ascii=False, indent=1) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
