"""OI-232 保险估值候选（preregister.md「候选」与读数 1～5）：五家保险在每个月末按六个候选重算 V。

- 月末观测（日期、在册、前向回报、现行 `P/V`）取 `../exp_oi232_20260929/insurer_observations.csv`（v4.221 生产月末行，v4.224 未改保险）。
- I0 由生产函数 `screen_daily_volume_price_signals.bank_dividend_intrinsic` 重算，须与现行 `P/V` 一致（相对差 < 0.1%）。
- V_DDM：`bank_valuation.ddm_at`（COE 10%）；G：当日全部银行 `bank_valuation.h2_scale`（与实盘 `live_h2` 同法）。
- I3：`data/processed/roic_daily_raw.csv` 保险行（第 3 步覆盖前的 equity_fallback V）。

    python3 candidates.py    # → candidates.csv、current.json
"""
import bisect
import csv
import json
import statistics
import sys
from datetime import date
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import bank_valuation as bv  # noqa: E402
import build_historical_valuation_bands as bhv  # noqa: E402
import screen_daily_volume_price_signals as scan  # noqa: E402
from divspread_names import INSURER_CODES  # noqa: E402

OBS = ROOT / 'data/experiments/exp_oi232_20260929/insurer_observations.csv'
RAW = ROOT / 'data/processed/roic_daily_raw.csv'
BANDS = ROOT / 'data/processed/roic_bands.csv'
SIGNAL = '2026-09-30'
INS = sorted(INSURER_CODES)
CANDS = ('I0', 'I0c', 'I1', 'I1c', 'I2', 'I3')

RFS = []
with (ROOT / 'data/reference/cost_of_equity_inputs.csv').open(encoding='utf-8') as fh:
    for r in csv.DictReader(fh):
        try:
            RFS.append((r['observed_on'], float(r['risk_free_rate'])))
        except (KeyError, TypeError, ValueError):
            pass
RFS.sort()
RFD = [d for d, _ in RFS]


def rf_at(day):
    """与 `_default_rf` 同义：observed_on ≤ day 的最新一条。"""
    i = bisect.bisect_right(RFD, day) - 1
    return RFS[i][1] if i >= 0 else None


def rf_bar(day):
    """当日之前 10 年（严格早于当日）全部观测的均值。"""
    d = date.fromisoformat(day)
    lo = bisect.bisect_left(RFD, date(d.year - 10, d.month, min(d.day, 28) if d.month == 2 else d.day).isoformat())
    hi = bisect.bisect_left(RFD, day)
    vals = [v for _, v in RFS[lo:hi]]
    return sum(vals) / len(vals) if vals else None


BANKS = sorted(bv.bank_codes(ROOT / 'data/raw/a_share_securities.csv'))
FUND = bv.BankFundamentals(BANDS, set(BANKS) | set(INS))
ACTS = scan._corporate_actions()
_G = {}


def bank_g(day):
    if day not in _G:
        rf = rf_at(day)
        pairs = [(scan.bank_dividend_intrinsic(b, day, rf) if rf is not None else None, bv.ddm_at(FUND, ACTS.get(b, []), b, day))
                 for b in BANKS]
        _G[day] = bv.h2_scale(pairs)
    return _G[day]


def raw_equity_values():
    """roic_daily_raw.csv 保险行：(代码, 日期) → equity_fallback V。"""
    prefixes = tuple(c + ',' for c in INS)
    out = {}
    with RAW.open(newline='', encoding='utf-8') as f:
        header = next(csv.reader([f.readline()]))
        ic, idt, iv = (header.index(k) for k in ('security_code', 'date', 'intrinsic_value'))
        for line in f:
            if line.startswith(prefixes):
                row = next(csv.reader([line]))
                if row[iv]:
                    out[(row[ic], row[idt])] = float(row[iv])
    return out


def equity_value_now(code, day):
    """现值：最新 ok 的 equity_fallback 带（可得日 ≤ day）按除权参考价折到 day（同 roic_daily_raw 的现金与送转调整）。"""
    best = None
    with BANDS.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['security_code'] == code and r['status'] == 'ok' and r['roic_path'] == 'equity_fallback' \
                    and len(r['available_at']) == 10 and r['available_at'] <= day:
                if best is None or (r['available_at'], r['report_date']) > (best['available_at'], best['report_date']):
                    best = r
    if best is None or not best['intrinsic_value']:
        return None, None
    (adj,), _f, _c = bhv.exright_adjust(ACTS.get(code, []), best['available_at'], day, (float(best['intrinsic_value']),),
                                        split_since=best.get('bps_basis_date') or best['available_at'])
    return adj, dict(report_date=best['report_date'], available_at=best['available_at'], band_v=float(best['intrinsic_value']))


def main():
    with OBS.open(newline='', encoding='utf-8') as f:
        obs = list(csv.DictReader(f))
    raw = raw_equity_values()
    closes = {c: dict(bhv.load_ohlcv(c)) for c in INS}
    month_date = {}
    for day, _close in bhv.load_ohlcv('600036'):            # 观测首月之前的银行 G 历史（I1c 的前 36 个月）按招行交易日历取月末
        if '2007-01-01' <= day < min(r['date'] for r in obs):
            month_date[day[:7]] = max(month_date.get(day[:7], ''), day)
    for r in obs:
        month_date[r['month']] = max(month_date.get(r['month'], ''), r['date'])
    months = sorted(month_date)
    for m in months:
        bank_g(month_date[m])
    g_by_month = {m: _G[month_date[m]] for m in months}

    def g_bar(month):
        prev = [g_by_month[m] for m in months if m < month][-36:]
        prev = [g for g in prev if g]
        return statistics.median(prev) if len(prev) >= 12 else None

    rows, mismatch = [], []
    for r in obs:
        c, day = r['code'], r['date']
        close = closes[c].get(day)
        if close is None:
            continue
        rf, rfb = rf_at(day), rf_bar(day)
        v0 = scan.bank_dividend_intrinsic(c, day, rf) if rf is not None else None
        v_prod = close / float(r['pv'])
        if v0 is None or abs(v0 / v_prod - 1) > 1e-3:
            mismatch.append(dict(code=c, date=day, v_prod=v_prod, v0=v0))
        dd = bv.ddm_at(FUND, ACTS.get(c, []), c, day)
        g, gb = bank_g(day), g_bar(r['month'])
        vals = dict(I0=v0, I0c=scan.bank_dividend_intrinsic(c, day, rfb) if rfb is not None else None,
                    I1=dd * g if dd and g else None, I1c=dd * gb if dd and gb else None, I2=dd, I3=raw.get((c, day)))
        row = dict(code=c, month=r['month'], date=day, panel=r['panel'], close=close, rf=rf, rf_bar=rfb, g=g, g_bar=gb,
                   f3=r['f3'], f5=r['f5'])
        for k in CANDS:
            v = vals[k]
            row[f'v_{k}'] = v
            row[f'pv_{k}'] = close / v if v and v > 0 else None
        rows.append(row)
    with (EXP / 'candidates.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    # 09-30 现值
    rf, rfb = rf_at(SIGNAL), rf_bar(SIGNAL)
    g_now = bank_g(SIGNAL)
    gb_now = statistics.median([g for g in [g_by_month[m] for m in months][-36:] if g])
    with (ROOT / 'data/processed/daily_buy_candidates.csv').open(newline='', encoding='utf-8') as f:
        pool = {x['security_code']: float(x['close']) for x in csv.DictReader(f) if x['close']}
    cmb_dd = bv.ddm_at(FUND, ACTS.get('600036', []), '600036', SIGNAL)
    current = dict(signal=SIGNAL, rf=rf, rf_bar=rfb, bank_g=g_now, bank_g_bar=gb_now, cmb_check=dict(v_ddm=cmb_dd, v_h2=cmb_dd * g_now),
                   reproduction=dict(rows=len(rows), mismatch=len(mismatch), examples=mismatch[:10]), insurers={})
    for c in INS:
        if c in pool:
            price, price_date = pool[c], SIGNAL
        else:
            price_date = max(closes[c]) if closes[c] else None
            price = closes[c].get(price_date) if price_date else None
        dd = bv.ddm_at(FUND, ACTS.get(c, []), c, SIGNAL)
        v3, band = equity_value_now(c, SIGNAL)
        vals = dict(I0=scan.bank_dividend_intrinsic(c, SIGNAL, rf), I0c=scan.bank_dividend_intrinsic(c, SIGNAL, rfb),
                    I1=dd * g_now if dd else None, I1c=dd * gb_now if dd else None, I2=dd, I3=v3)
        f = FUND.at(c, SIGNAL)
        current['insurers'][c] = dict(price=price, price_date=price_date, fundamentals=dict(available_at=f[0], bps=f[1], roe0=f[2], payout=f[3]) if f else None,
                                      equity_band=band, v=vals, pv={k: (price / v if price and v else None) for k, v in vals.items()})
    (EXP / 'current.json').write_text(json.dumps(current, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({k: v for k, v in current.items() if k != 'insurers'}, ensure_ascii=False), flush=True)
    for c, e in current['insurers'].items():
        print(c, e['price'], e['price_date'], {k: (round(v, 2) if v else None) for k, v in e['v'].items()},
              {k: (round(v, 3) if v else None) for k, v in e['pv'].items()}, flush=True)


if __name__ == '__main__':
    main()
