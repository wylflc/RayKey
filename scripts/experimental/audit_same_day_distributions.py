#!/usr/bin/env python3
"""OI-196: archive a complete public dividend-table query before repairing lost components."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fetch_ohlcv_history import EM_API, HEADERS

COLUMNS = ('SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,EX_DIVIDEND_DATE,PLAN_NOTICE_DATE,'
           'PRETAX_BONUS_RMB,BONUS_RATIO,IT_RATIO,IMPL_PLAN_PROFILE,ASSIGN_PROGRESS')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    assert args.workers <= int(os.environ.get('SLURM_CPUS_PER_TASK', '1'))
    pages_dir = args.out / 'raw_pages'
    pages_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()

    def page(number):
        path = pages_dir / f'{number:04d}.json'
        query = dict(reportName='RPT_SHAREBONUS_DET', columns=COLUMNS, pageSize='500',
                     pageNumber=str(number), sortColumns='SECURITY_CODE,REPORT_DATE,PLAN_NOTICE_DATE,EX_DIVIDEND_DATE',
                     sortTypes='1,1,1,1')
        url = EM_API + '?' + urllib.parse.urlencode(query)
        if not path.exists():
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as response:
                        raw = response.read()
                    payload = json.loads(raw)
                    assert payload.get('success') and isinstance(payload.get('result', {}).get('data'), list), payload
                    path.write_bytes(raw)
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(attempt + 1)
        raw = path.read_bytes()
        result = json.loads(raw)['result']
        return dict(page=number, pages=result['pages'], count=result['count'], rows=len(result['data']),
                    sha256=hashlib.sha256(raw).hexdigest(), source_url=url)

    first = page(1)
    print('Source rows/pages:', first['count'], first['pages'], flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = [first] + list(pool.map(page, range(2, first['pages'] + 1)))
    assert all(r['count'] == first['count'] and r['pages'] == first['pages'] for r in records), 'Source changed during paging'
    assert sum(r['rows'] for r in records) == first['count']
    manifest = dict(started_beijing=started, completed_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                    job_id=os.getenv('SLURM_JOB_ID'), query_rows=first['count'], pages=records)
    (args.out / 'source_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print('Complete source archive:', first['count'], 'rows', flush=True)


if __name__ == '__main__':
    main()
