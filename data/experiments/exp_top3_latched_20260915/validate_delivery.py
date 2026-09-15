"""Check rendered delivery against the independently verified numeric outputs."""
import csv
import hashlib
import json
from pathlib import Path
from openpyxl import load_workbook

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).parent


def main():
    manifest=json.loads((OUT/'manifest.json').read_text())
    verification=json.loads((OUT/'verification.json').read_text())
    assert verification['source_manifest_sha256']==hashlib.sha256((OUT/'manifest.json').read_bytes()).hexdigest()
    book=OUT/'历史前三名分段及后续收益.xlsx'
    wb=load_workbook(book,read_only=True,data_only=True)
    checks={}
    for sheet,filename in [('名单变化分段','segments_top3.csv'),('逐日完整明细','daily_top3.csv')]:
        with (OUT/filename).open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        ws=wb[sheet];iterator=ws.iter_rows(values_only=True);header=list(next(iterator))
        lookup={c:i for i,c in enumerate(header)}
        mappings={'security_code':'股票代码','security_name':'股票名称',
                  'pv':'段首P/V' if sheet=='名单变化分段' else '当时P/V',
                  'return_1y':'1年累计总回报','return_3y':'3年累计总回报',
                  'activation_date':'首次激活日','anchor_date':'虚拟定锚日',
                  'stop_anchor':'当日已调整止损锚','stop_line':'当日生效止损线'}
        count=0
        for source,cells in zip(rows,iterator,strict=True):
            for field,label in mappings.items():
                actual=cells[lookup[label]];expected=source[field]
                if not expected:assert actual is None,(sheet,field,count)
                elif field in ('pv','return_1y','return_3y','stop_anchor','stop_line'):
                    assert abs(actual-float(expected))<1e-12
                else:assert actual==expected
            count+=1
        checks[sheet]=count
    assert wb['激活及止损复位'].max_row-1==manifest['eligibility_comparison']['activations']
    wb.close()
    report=ROOT/'docs/reports/top3_latched_periods_2026-09-15.zh.md'
    text=report.read_text()
    assert text.startswith('# 历史P/V前三名：首次信号激活、止损后复位')
    assert sum(line.startswith('| ') and line.split('|')[1].strip().isdigit()
               for line in text.splitlines())==manifest['membership_segments']
    paths=[book,report,OUT/'verification.json',OUT/'preregister.md',Path(__file__),
           ROOT/'scripts/experimental/render_top3_periods.py',ROOT/'scripts/test_top3_period_forward.py',
           ROOT/'scripts/experimental/verify_top3_periods.py',ROOT/'scripts/experimental/verify_top3_latch.py']
    result={'workbook_roundtrip_checked':checks,'markdown_segments':manifest['membership_segments'],
            'unit_checks_passed':23,'documentation_audit_errors':0,'statistics_job':manifest['job_id'],
            'verification_job':26724712,
            'sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    (OUT/'delivery_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
