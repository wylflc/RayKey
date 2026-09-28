"""q.py CODE [from_period] [to_period]  -> panel rows + statement rows"""
import csv, sys
OUT='/gpfs/scratch1/nodespecific/tcn441/zwang.27284302/claude-66633/-gpfs-scratch1-shared-zwang-mm-quant-RayKey/be4702a1-b00c-45e2-9cec-3beb6af4945d/scratchpad/oi214'
code=sys.argv[1]; lo=sys.argv[2] if len(sys.argv)>2 else '0000'; hi=sys.argv[3] if len(sys.argv)>3 else '9999'
print('PANEL: file | report_date notice_date | parent_np | revenue | eps | deduct_eps | bps | roe | np_yoy | rev_yoy | retrieved | superseded_at')
for r in csv.DictReader(open(OUT+'/panel_cache.csv',encoding='utf-8')):
    if r['security_code']==code and lo<=r['report_date']<=hi:
        print(r['_file'][:22].ljust(22), r['report_date'], r['notice_date'], r['parent_netprofit'], r['total_operate_income'], r['basic_eps'], r['deduct_basic_eps'], r['bps'][:8], r['weightavg_roe'], r['netprofit_yoy'], r['revenue_yoy'], r['retrieved_at_utc'][:10], r.get('superseded_at',''), sep=' | ')
print('STMT: kind src | report notice update | parent_eq | share_cap | parent_np | revenue | eps | sup_at')
for r in csv.DictReader(open(OUT+'/stmt_cache.csv',encoding='utf-8')):
    if r['SECURITY_CODE']==code and lo<=r['REPORT_DATE']<=hi and r['kind']!='cashflow':
        print(r['kind'][:3], r['src'], r['REPORT_DATE'], r['NOTICE_DATE'], r['UPDATE_DATE'], r['TOTAL_PARENT_EQUITY'], r['SHARE_CAPITAL'], r['PARENT_NETPROFIT'], r['TOTAL_OPERATE_INCOME'], r['BASIC_EPS'], r['superseded_at'], sep=' | ')
