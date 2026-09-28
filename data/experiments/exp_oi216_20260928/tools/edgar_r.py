"""Fetch EDGAR FilingSummary / R pages for an accession and print parsed rows (element, label, values).
usage: edgar_r.py list CIK ACCN            -> list reports
       edgar_r.py show CIK ACCN R5 [R6 ..]  -> parse and print rows
Cache: ../filings/sec/raw/<cik>_<accn>_<file>
"""
import html, re, sys, time, urllib.request
from pathlib import Path
UA = {"User-Agent": "RayKey-AShareQuant research bot (personal research use)"}
CACHE = Path(__file__).resolve().parents[1] / 'filings' / 'sec' / 'raw'


def get(cik, accn, fname):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{cik}_{accn.replace('-', '')}_{fname}"
    if p.exists() and p.stat().st_size > 0:
        return p.read_text(encoding='utf-8', errors='replace')
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/{fname}"
    time.sleep(0.3)
    t = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode('utf-8', 'replace')
    p.write_text(t, encoding='utf-8')
    return t


def parse(t):
    heads = [html.unescape(re.sub('<[^>]+>', ' ', h)).strip() for h in re.findall(r'<th class="t[lh]"[^>]*>(.*?)</th>', t, re.S)]
    rows = []
    for tr in re.findall(r'<tr class="r[eo]\w*">(.*?)</tr>', t, re.S):
        m = re.search(r"defref_([A-Za-z0-9-]+)_([A-Za-z0-9]+)'", tr)
        lab = re.search(r'<td class="pl[^"]*"[^>]*>(.*?)</td>', tr, re.S)
        vals = [html.unescape(re.sub('<[^>]+>', '', v)).strip() for v in re.findall(r'<td class="(?:num|nump|text)"[^>]*>(.*?)</td>', tr, re.S)]
        if m and lab:
            rows.append((m.group(1) + ':' + m.group(2), html.unescape(re.sub('<[^>]+>', '', lab.group(1))).strip(), vals))
    return heads, rows


if __name__ == '__main__':
    cmd, cik, accn = sys.argv[1:4]
    s = get(cik, accn, 'FilingSummary.xml')
    reps = re.findall(r'<HtmlFileName>(R\d+\.htm)</HtmlFileName>.*?<LongName>(.*?)</LongName>.*?<ShortName>(.*?)</ShortName>', s, re.S)
    if cmd == 'list':
        pat = re.compile(sys.argv[4], re.I) if len(sys.argv) > 4 else None
        for f, lng, sh in reps:
            if pat is None or pat.search(sh):
                print(f, html.unescape(sh))
    else:
        for f in sys.argv[4:]:
            heads, rows = parse(get(cik, accn, f))
            print('=====', f, ' | '.join(h[:40] for h in heads[:8]))
            for e, l, v in rows:
                print('  ', e, '|', l[:80], '|', v[:6])
