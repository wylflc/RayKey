"""Retain source metadata and facts, with explicit limits on verified coverage."""
import csv
import json
import re
from collections import Counter
from pathlib import Path

EXP = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parsed = json.loads((EXP/'parsed_terms.json').read_text())
    terms = list(csv.DictReader((EXP/'price_terms_corrected.csv').open()))
    verified_keys = {(r['security_code'], r['ex_dividend_date']) for r in terms}
    unresolved = [r for r in parsed if r['status']=='needs_review' and
                  (r['event']['security_code'], r['event']['ex_dividend_date']) not in verified_keys]
    uniform, remaining = [], []
    for row in unresolved:
        code, date = row['code'], row['event']['ex_dividend_date']
        pages = json.loads((EXP/'raw_pages'/f"{row['art_code']}.txt").read_text())
        text = ''.join(re.sub(r'\s+', '', page) for page in pages)
        reason = ''
        if code in ('002179', '002275', '301498'):
            assert '已回购股份0股' in text or '股份为0股' in text
            reason = '实施公告明确回购账户为零；排除回购的条件未实际触发'
        elif (code, date) == ('000425', '2022-09-28'):
            assert '2,438,600股股份完成注销' in text
            reason = '回购股份已于2022-09-14注销，实施基数即注销后总股本'
        elif code == '000951':
            assert '1,168,994,951股为基数' in text and '已办理完毕回购股份注销' in text
            reason = '实施前已完成回购注销，实施基数即注销后总股本'
        elif code == '002475':
            assert '尚未通过回购' in text and '登记日期间不会进行回购' in text
            reason = '实施时尚未回购且承诺登记前不回购；每股金额仍保留旧库六位精度'
        compact = {k: row[k] for k in ('code', 'title', 'notice_date', 'art_code', 'url', 'source_sha256')}
        compact['event'] = row['event']
        if reason:
            compact.update(status='no_excluded_treasury_at_implementation', reason=reason,
                           source_pages=list(range(1, len(pages)+1)))
            uniform.append(compact)
        else:
            compact.update(status='unverified_actual_fallback', reason=(
                '公告每10股金额与最后价格公式的每股单位冲突，未自行纠正'
                if code == '002043' else '实施公告未提供可唯一确定且保留其舍入精度的交易所价格参数'))
            remaining.append(compact)
    assert len(uniform) == 13 and len(remaining) == 11
    audit = json.loads((EXP/'announcement_audit.json').read_text())
    # Full extracted text stays in the ignored source cache; commit metadata only.
    for item in audit['results']:
        for notice in item['announcements']:
            if 'excerpts' in notice:
                notice['matched_pages'] = sorted({r['page'] for r in notice.pop('excerpts')})
        save(EXP/'audit_codes'/f"{item['code']}.json", item)
    save(EXP/'announcement_audit.json', audit)
    for row in parsed:
        row.pop('cash_evidence', None)
        row.pop('share_evidence', None)
    save(EXP/'parsed_terms.json', parsed)
    save(EXP/'unresolved_terms.json', remaining)
    save(EXP/'coverage.json', dict(
        scope='BASE历史面板、当前核心池和持仓，加安集科技送转核验样本；非全市场核验',
        audited_codes=len(audit['codes']),
        profit_distribution_announcements=sum(r['total_announcements'] for r in audit['results']),
        selected_announcements=len(parsed), parser_classifications=Counter(r['status'] for r in parsed),
        verified_events=len(terms), verified_codes=len({r['security_code'] for r in terms}),
        price_differs_from_actual=sum(any(float(r[k]) != float(r['price_'+k]) for k in
            ('cash_per_share', 'share_ratio', 'rights_ratio', 'rights_price')) for r in terms),
        verified_uniform_without_override=uniform, unresolved_formula_events=remaining,
        unavailable_sources=[r for r in parsed if r['status']=='source_unavailable'],
        ambiguous_event_mapping=[r for r in parsed if r['status']=='ambiguous_or_missing_event'],
        limitations=['无差异关键词仅为检索结果，不等于逐页核验为同口径',
                     '625条之外，除明确零回购样本外均保持未核验回退；未推断除权舍入',
                     '行情缓存和财务输入未刷新；旧快照保留观测时点信号，不重述历史行情']
    ))


if __name__ == '__main__':
    main()
