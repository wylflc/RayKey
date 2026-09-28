"""Optional companion proposal: statement-side restatement dates for ANNUAL three-statement rows
(data/raw/financials_statements/*.csv, used by roic_inputs / growth path). The panel originals
registry does not reach these rows. Format = data/interim/statement_restatements.csv, which
roic_inputs.load_restatement_dates reads (new_update_date → RoicYear.delayed_until when no
statement archive covers the date). Values: old = original annual report, new = current vendor row."""
import csv
OUT = '/gpfs/scratch1/nodespecific/tcn441/zwang.27284302/claude-66633/-gpfs-scratch1-shared-zwang-mm-quant-RayKey/be4702a1-b00c-45e2-9cec-3beb6af4945d/scratchpad/oi214'
F = ['security_code', 'report_date', 'field', 'old_value', 'new_value', 'change_pct', 'old_update_date', 'new_update_date', 'detected_at_utc']
rows = []


def add(code, rd, field, old, new, old_d, new_d):
    o, n = float(old), float(new)
    rows.append(dict(security_code=code, report_date=rd, field=field, old_value=old, new_value=new,
                     change_pct=f'{(n / o - 1) * 100:.2f}', old_update_date=old_d, new_update_date=new_d,
                     detected_at_utc='2026-09-28T12:00:00+00:00'))


add('000895', '2010-12-31', 'TOTAL_PARENT_EQUITY', '3422646302.18', '3670449087.24', '2011-04-29', '2012-03-02')
add('000895', '2010-12-31', 'PARENT_NETPROFIT', '1089281494.22', '1159206378.09', '2011-04-29', '2012-03-02')
add('000895', '2011-12-31', 'TOTAL_PARENT_EQUITY', '3681682275.43', '9111101629.79', '2012-03-02', '2013-03-26')
add('000895', '2011-12-31', 'PARENT_NETPROFIT', '564893042.07', '1334201313.00', '2012-03-02', '2013-03-26')
add('600315', '2012-12-31', 'TOTAL_PARENT_EQUITY', '2710056138.53', '2240363094.86', '2013-03-15', '2015-03-19')
add('600315', '2012-12-31', 'PARENT_NETPROFIT', '614632224.94', '621435187.18', '2013-03-15', '2015-03-19')
add('600315', '2013-12-31', 'TOTAL_PARENT_EQUITY', '3325319389.36', '3076264819.36', '2014-04-26', '2015-03-19')
add('600315', '2016-12-31', 'PARENT_NETPROFIT', '216016693.93', '200980658.86', '2017-03-22', '2018-03-21')
add('600315', '2016-12-31', 'TOTAL_OPERATE_INCOME', '5321198258.49', '5962270929.26', '2017-03-22', '2018-03-21')
add('002128', '2009-12-31', 'TOTAL_PARENT_EQUITY', '3213603166.13', '3560616033.24', '2010-03-09', '2011-03-10')
with open(OUT + '/oi214_proposed_statement_delays.csv', 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=F)
    w.writeheader()
    w.writerows(rows)
print(len(rows))
