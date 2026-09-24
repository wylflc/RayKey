"""OI-210 正表核对：SEC 申报人最新年报的正表金融资产行与经营利润行，对照新规则取数（overseas_roic_years_new.csv）。"""
import csv
import json
import re
from pathlib import Path

EXP = Path(__file__).resolve().parent
FIN_LABEL = re.compile(r'cash|marketable|investment|securit|deposit|financial assets', re.I)
SKIP_LABEL = re.compile(r'total|receivable|restricted investments|equity[- ]method|associates', re.I)
ROWS = {(r['security_code'], r['period']): r for r in csv.DictReader(open(EXP.parents[2] / 'data/interim/overseas_roic_years.csv'))
        if r['period_type'] == 'annual'}


def scale(text: str) -> float:
    return 1e3 if 'Thousand' in text else 1e6 if ('Million' in text or '$' in text or '€' in text) else 1.0


def main():
    out = {}
    for path in sorted((EXP / 'faces').glob('*.json')):
        face = json.loads(path.read_text())
        sym, period = face['symbol'], face['period']
        row = ROWS.get((sym, period))
        bal, inc = face['statements']['balance'], face['statements']['income']
        k = scale(bal['scale'])
        lines = [(r['element'], r['label'], r['value'] * k / 1e9) for r in bal['rows']
                 if r['value'] is not None and FIN_LABEL.search(r['label']) and not SKIP_LABEL.search(r['label'])]
        face_fin = sum(v for _e, _l, v in lines)
        op = next((r['value'] * scale(inc['scale']) / 1e9 for r in inc['rows']
                   if r['element'] in ('OperatingIncomeLoss', 'ProfitLossFromOperatingActivities')), None)
        rec = dict(period=period, face_lines=[f'{l} [{e}] {v:.2f}' for e, l, v in lines], face_financial=round(face_fin, 2), face_operating=op and round(op, 2))
        if row:
            g = lambda c: float(row[c]) / 1e9 if row[c] else 0.0  # noqa: E731
            rec.update(rule_cash_like=round(g('cash_like'), 2), rule_other=round(g('other_financial_assets'), 2),
                       rule_total=round(g('cash_like') + g('other_financial_assets'), 2), rule_ebit=round(g('ebit'), 2),
                       ebit_source=row['ebit_source'], gap=round(g('cash_like') + g('other_financial_assets') - face_fin, 2))
        out[sym] = rec
        print(f"{sym:5} {period} face fin {face_fin:8.2f} rule {rec.get('rule_total', float('nan')):8.2f} gap {rec.get('gap', float('nan')):+7.2f} | "
              f"face op {op if op is None else round(op, 2)} rule ebit {rec.get('rule_ebit')} ({rec.get('ebit_source')})")
        for line in rec['face_lines']:
            print('      ', line)
    (EXP / 'face_check.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
