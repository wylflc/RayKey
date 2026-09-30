"""把实验代码清单与上证、沪深 300 指数的不复权日线续到 UNTIL，写入 `ohlcv/`（在册缓存只读不写）。

取数用 `fetch_ohlcv_history.fetch_full_history`（与生产同一接口）；源文件原样复制后只追加末日之后、不晚于
UNTIL 的新行。接口返回的重叠旧行逐根核对开高低收，出现不一致即报错，防止新旧口径混拼。

    python3 fetch.py
"""
import json
import shutil
import time
from datetime import date, timedelta

from common import EXP, INDEXES, OHLCV, SRC_OHLCV, UNTIL, build_codes, securities
import fetch_ohlcv_history as foh

FIELDS = ['date', 'open', 'close', 'high', 'low', 'volume']


def fetch(sid: str, since: date) -> list[dict]:
    for attempt in range(4):
        try:
            return foh.fetch_full_history(sid, date.fromisoformat(UNTIL), since, 20.0, 0.12)
        except Exception:                                        # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def extend(stem: str, sid: str) -> dict:
    src, dst = SRC_OHLCV / f'{stem}.csv', OHLCV / f'{stem}.csv'
    old = foh.load_csv(src)
    assert old and list(old[0]) == FIELDS, (stem, list(old[0]) if old else None)
    last = max(r['date'] for r in old)
    have = {r['date']: r for r in old}
    fresh = fetch(sid, date.fromisoformat(last) + timedelta(days=1)) if last < UNTIL else []
    mismatch = [r['date'] for r in fresh if r['date'] in have
                and any(abs(float(r[k]) - float(have[r['date']][k])) > 1e-6 for k in ('open', 'close', 'high', 'low'))]
    new = [r for r in fresh if last < r['date'] <= UNTIL]
    shutil.copyfile(src, dst)
    with dst.open('a', newline='', encoding='utf-8') as f:
        for r in new:
            f.write(','.join(r[k] for k in FIELDS) + '\n')
    return dict(stem=stem, sid=sid, last_before=last, added=len(new), last_after=new[-1]['date'] if new else last,
                overlap=sum(1 for r in fresh if r['date'] in have), overlap_mismatch=mismatch[:5], n_mismatch=len(mismatch))


def main():
    OHLCV.mkdir(parents=True, exist_ok=True)
    names = securities()
    jobs = [(c, foh.secid(c, names.get(c, ('', ''))[1])) for c in build_codes()] + list(INDEXES.items())
    out, failed = [], []
    for i, (stem, sid) in enumerate(jobs, 1):
        try:
            out.append(extend(stem, sid))
        except Exception as exc:                                 # noqa: BLE001
            failed.append(f'{stem}:{type(exc).__name__}:{exc}')
        if i % 50 == 0:
            print(f'[{i}/{len(jobs)}]', flush=True)
    ends = {}
    for r in out:
        ends[r['last_after']] = ends.get(r['last_after'], 0) + 1
    bad = [r for r in out if r['n_mismatch'] > 3]          # 个别旧根被源端修订只记录；成片不一致即新旧口径不同
    report = dict(until=UNTIL, files=len(out), failed=failed, last_after=ends,
                  overlap_mismatch={r['stem']: [r['n_mismatch'], r['overlap_mismatch']] for r in out if r['n_mismatch']}, rows=out)
    (EXP / 'fetch_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n')
    print('files', len(out), 'failed', len(failed), 'last_after', ends, 'mismatch', len(bad), flush=True)
    assert not failed and not bad, (failed[:5], [r['stem'] for r in bad][:5])


if __name__ == '__main__':
    main()
