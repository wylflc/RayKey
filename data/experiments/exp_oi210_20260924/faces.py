"""OI-210：取 SEC 申报人最新年报的资产负债表与利润表正表（EDGAR R 页），记每行标签、XBRL 元素与最新一期金额。

只用于核对 companyfacts 标签与报表正表的对应关系（哪些元素是正表行、哪些是附注子项），不进估值。
    python3 faces.py [SYMBOL ...]   → faces/<SYMBOL>.json（原始 R 页缓存在 faces/raw/，不入库）
"""
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
SEC = ROOT / 'data/raw/overseas_statements/sec'
OUT = EXP / 'faces'
UA = {"User-Agent": "RayKey-AShareQuant research bot (personal research use)"}
ANNUAL = ('10-K', '20-F', '40-F')
WANT = {'balance': re.compile(r'BALANCE SHEETS?|FINANCIAL POSITION|FINANCIAL CONDITION', re.I),
        'income': re.compile(r'STATEMENTS? OF (CONSOLIDATED )?(INCOME|OPERATIONS|EARNINGS|PROFIT OR LOSS|COMPREHENSIVE INCOME)|INCOME STATEMENTS?', re.I)}


def get(url: str) -> str:
    cache = OUT / 'raw' / re.sub(r'[^A-Za-z0-9]+', '_', url.split('edgar/data/')[1])
    if cache.exists():
        return cache.read_text()
    time.sleep(0.2)
    text = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode('utf-8', 'replace')
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text)
    return text


def latest_annual_accn(facts: dict) -> tuple[str, str, str]:
    best = ('', '', '')
    for ns in ('us-gaap', 'ifrs-full'):
        for node in facts.get(ns, {}).values():
            for unit in node.get('units', {}).values():
                for e in unit:
                    if e.get('form') in ANNUAL and e.get('fp') == 'FY' and (e['filed'], e['end']) > (best[0], best[1]):
                        best = (e['filed'], e['end'], e['accn'])
    return best


def parse_r(text: str) -> dict:
    head = re.search(r'<th class="tl"[^>]*>(.*?)</th>', text, re.S)
    scale = html.unescape(re.sub('<[^>]+>', ' ', head.group(1))).strip() if head else ''
    rows = []
    for tr in re.findall(r'<tr class="r[eo]\w*">(.*?)</tr>', text, re.S):
        m = re.search(r"defref_([A-Za-z0-9-]+)_([A-Za-z0-9]+)'", tr)
        label = re.search(r'<td class="pl[^"]*"[^>]*>(.*?)</td>', tr, re.S)
        vals = re.findall(r'<td class="num[p]?"[^>]*>(.*?)</td>', tr, re.S)
        if not (m and label):
            continue
        first = None
        if vals:
            raw = html.unescape(re.sub('<[^>]+>', '', vals[0])).replace('$', '').replace(',', '').strip()
            neg = raw.startswith('(')
            raw = raw.strip('()').strip()
            try:
                first = -float(raw) if neg else float(raw)
            except ValueError:
                first = None
        rows.append(dict(ns=m.group(1), element=m.group(2), label=html.unescape(re.sub('<[^>]+>', '', label.group(1))).strip(), value=first))
    return dict(scale=scale, rows=rows)


def main(symbols):
    OUT.mkdir(exist_ok=True)
    for sym in symbols:
        data = json.loads((SEC / f'{sym}.json').read_text())
        cik = int(data['cik'])
        filed, end, accn = latest_annual_accn(data.get('facts', {}))
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/"
        summary = get(base + 'FilingSummary.xml')
        reports = re.findall(r'<HtmlFileName>(R\d+\.htm)</HtmlFileName>.*?<LongName>(.*?)</LongName>.*?<ShortName>(.*?)</ShortName>', summary, re.S)
        out = dict(symbol=sym, cik=cik, accn=accn, filed=filed, period=end, statements={})
        for fname, long, short in reports:
            short = html.unescape(short)
            if 'Parenthetical' in short or int(fname[1:-4]) > 12:
                continue
            for kind, pat in WANT.items():
                if kind not in out['statements'] and pat.search(short):
                    out['statements'][kind] = dict(report=fname, title=short, **parse_r(get(base + fname)))
        (OUT / f'{sym}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
        print(sym, end, accn, {k: (v['title'], len(v['rows'])) for k, v in out['statements'].items()}, flush=True)


if __name__ == '__main__':
    main(sys.argv[1:] or ['AAPL', 'ADBE', 'AMD', 'ASML', 'DIS', 'GLW', 'GOOGL', 'INTC', 'META', 'MSFT', 'MU', 'NVDA',
                          'ORCL', 'PDD', 'TSLA', 'TSM', 'UBER'])
