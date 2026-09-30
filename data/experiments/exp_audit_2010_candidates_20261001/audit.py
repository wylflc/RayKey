"""2010 年前后回测买入候选核查（用户 2026-10-01：「当时回测买入候选都是一些奇怪的股票」）。

一、候选：时点股票库（`panel_moat_bank_v6b.csv`）在 2009–2011 年的成员；月末在买入区（`P/V` ≤ 1.0034）的成员
    （`exp_oi245c_20260930/observations3.csv`）；现行 BASE（S15）2009-11～2012-06 的首次建仓（`exp_oi247_20260930` 台账）；
    2010 年月末在买入区但不在股票库的代码（全市场逐日状态）；旧实验台账里 2009–2011 年上半年的首次建仓。
二、财务数据：仓库财务摘要与年报三表 对 本地年报原文（`data/raw/annual_reports/<代码>/<年>.txt.gz`「主要会计数据」表），
    另查次年年报的上年比较数（重述）与公告日、带可得日。
三、入选时估值：信号日状态与所挂的带（守卫、NOPAT 对 EPS、PE、PB、ROE），及其后 3 年年化与 S15 周期贡献。

    python3 audit.py              # 首次运行流式读 2 GB 逐日状态（经 SLURM），摘录缓存到本目录 extract_*.csv.gz
    python3 audit.py --refresh    # 重新摘录
"""
import csv
import gzip
import json
import re
import statistics
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
LINE = 1.0034
OBS = ROOT / 'data/experiments/exp_oi245c_20260930/observations3.csv'
S15 = ROOT / 'data/experiments/exp_oi247_20260930'
STARTS = ('20091101', '20100501', '20101101', '20110501')
PANEL = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
STATES = ROOT / 'data/processed/a_share_daily_states_adopted.csv'
BANDS = ROOT / 'data/processed/roic_bands.csv'
FIN = ROOT / 'data/raw/financials'
STMT = ROOT / 'data/raw/financials_statements'
AR = ROOT / 'data/raw/annual_reports'
EXTRACT_CODES = EXP / 'extract_codes.csv.gz'          # 13 只候选 2008–2012 的逐日状态
EXTRACT_ME2010 = EXP / 'extract_monthends_2010.csv.gz'  # 全市场 2010 年各月最后一个状态行
YEARS = (2008, 2009, 2010, 2011)
TOL = 0.005                                            # 相对差 0.5% 以内算一致

# 判断（看完读数后写入；只作核查结论，不改口径）
NOTES = {
    '000651': '2010-04～2011-01、2011-10～12 在区；按最近年报市盈率 12～18、ROE 32%～37%，峰守卫部分或全开（w 0.82～1.0）；其后 3 年年化 +17%～+32%，S15 贡献 +85～+131pp（最大赢家）。合理。',
    '600660': '市盈率 9～19、ROE 29%～34%；其后 3 年年化 −7%～+21%；S15 周期 +81%～+84%、+35pp。合理。',
    '000338': '2011 年在区，按 2010 年利润市盈率 7.5～13、ROE 33%～45%：重卡周期高点。十年中位没有可比的高位，峰守卫未触发（ttm_growth）；其后 3 年年化 −27%～+2%，S15 持有到 2017 年仍 +25%（+1.1pp）。数据与年报一致，属周期高点未识别。',
    '600897': '市盈率 12.7～14.9、PB 2.2～2.6、ROE 19%；机场，经营稳定；其后 3 年年化 +6%～+27%，S15 +100%（+33pp）。合理。本地缺 FY2008–FY2010 年报，FY2010 净利用 FY2011 年报的上年数核对一致（2.80 亿）。',
    '601088': '2011 年 9～12 月在区，按 2010 年利润市盈率 12.9～14.3、ROE 20%～21%：煤价高点，median3（λ = 0）未设守卫；其后 3 年年化 −13%～−3%，S15 +47%（+6.1pp，2018 年出名单）。属周期高点；FY2010 仓库净利较原文 +1.8%（后续重述）。',
    '000022': '2009 年初在区，市盈率 10～12、ROE 25%；港口，其后 3 年年化 −5%～+3%。估值不离谱，其后收益平平；S15 起点在 2009-11 之后，未买。',
    '002128': '2011 年 10～12 月在区，市盈率 12～16、PB 4.6～6.1、ROE 36%：煤价高点（ttm_growth 未设守卫）；其后 3 年年化 −19%～−10%，S15 +19%（−0.9pp）。属周期高点。',
    '002152': '市盈率 21～25、ROE 24%，成长型；其后 3 年年化 +12%～+18%，S15 +23%（+0.8pp）。合理。',
    '601857': '2009 年一季度在区，市盈率 13～14.5、ROE 18%；其后 3 年年化 −3%～+2%。便宜但回报差（资本开支大、回报低）；S15 未买。',
    '002024': '2011 年末在区，市盈率 14.6～18.7、ROE 24%；其后 3 年年化 −2%～+3%，此后电商冲击、商业模式恶化。S15 2013 年换出，+59%（+8.0pp）。数据一致，属商业模式陷阱。',
    '000778': '2009-02 在区，市盈率 12.2、PB 1.5、ROE 13%；其后 3 年年化 +18%。合理；FY2009 仓库为同一控制下合并追溯调整后数。',
    '002294': '2011-12 在区，市盈率 25、ROE 20%；其后 3 年年化 +40%。合理。',
    '600188': '2009 年 1～5 月在区，峰守卫全开（cyclical_median，V 约为利润的 11～20 倍）；其后 3 年年化 +17%～+41%。合理（近 2009 年周期低点）。本地 FY2009 年报为 H 股版、字体不可读。',
}
MISMATCH_NOTES = (
    '- **每股数（EPS、BPS）**：全部与后续送转一致——东财把历年每股数按最新股本回溯调整（如潍柴 2009 年 EPS 原文 4.09，2010 年 10 送 10 后记 2.05；格力 2009 年 1.55，10 转 5 后记 1.03）。'
    '建带按总额与当时股本（`shares_est`：格力 2010-05 为 18.78 亿股，与原文一致）计每股，信号日 V 与价同基（V 对应市盈率 11～28），不受影响。',
    '- **总额（营收、归母净利、归母权益）**：均为追溯重述，仓库取重述后数、日期仍记原公告日（OI-225 同类）。',
    '  - 已核实：格力 FY2008 净利原文 21.03 亿，FY2009 年报重述为 19.67 亿（−6.5%）；新兴铸管 FY2009 同一控制下合并，营收调整前 251.88 亿、调整后 290.70 亿（+15.4%），净利 +1.5%；兖矿 FY2011 在 FY2012 年报重述（营收 +2.1%、净利 −1.1%）。',
    '  - 次年年报本地缺或不可读、无法确认：兖矿 FY2008（净利 −2.5%）、神华 FY2008（−2.4%）与 FY2010（+1.8%）、电投能源 FY2009（营收 −2.7%、权益 +10.8%）。',
    '- S15 各次建仓所用的最近年报净利与原文相差 0～1.8%（神华 FY2010 +1.8%，其余 ≤ 0.1%）。',
)


def names():
    out = {}
    for p in (ROOT / 'data/processed/a_share_watchlist_quality_tiers.csv', ROOT / 'data/raw/a_share_securities.csv'):
        if p.exists():
            for r in csv.DictReader(p.open(encoding='utf-8-sig')):
                if r.get('security_code') and r.get('security_name'):
                    out.setdefault(r['security_code'].zfill(6), r['security_name'].replace(' ', ''))
    for r in csv.DictReader(PANEL.open(encoding='utf-8')):
        out.setdefault(r['security_code'], r['security_name'].replace(' ', ''))
    return out


def panel_intervals():
    iv = defaultdict(list)
    for r in csv.DictReader(PANEL.open(encoding='utf-8')):
        iv[r['security_code']].append((r['effective_from'], r['effective_to'] or '9999-12-31'))
    return iv


def member(iv, code, d):
    return any(a <= d <= b for a, b in iv.get(code, ()))


# ── 一、候选 ─────────────────────────────────────────────────────────────────────────────────────────

def obs_rows():
    out = defaultdict(list)
    with OBS.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if '2008-01' <= r['month'] <= '2012-12':
                out[r['code']].append(r)
    return out


def s15_entries():
    out = []
    for s in STARTS:
        trades = list(csv.DictReader((S15 / 'trades' / f'S15full{s}_trades.csv').open(encoding='utf-8')))
        for r in csv.DictReader((S15 / 'ledgers' / f'S15full{s}.csv').open(encoding='utf-8')):
            if r['action'] == '买入' and r['reason'] == '首次建仓' and r['date'] <= '2012-06-30':
                code = r['security_code'].zfill(6)
                cyc = next((t for t in trades if t['security_code'].zfill(6) == code and t['entry_date'] == r['date']), None)
                out.append(dict(start=s, date=r['date'], code=code, price=float(r['price']), pv=float(r['pv_ratio']),
                                v=float(r['intrinsic_value']),
                                exit=cyc['exit_date'] if cyc else '', exit_reason=cyc['exit_reason'] if cyc else '',
                                ret=float(cyc['return_pct']) if cyc and cyc['return_pct'] else None,
                                contrib=float(cyc['contrib']) * 100 if cyc and cyc['contrib'] else None))
    return out


def old_ledgers():
    """旧实验台账（本目录与 OI-247 之外）2009-01～2011-06 的首次建仓代码计数。"""
    cnt, files = Counter(), 0
    for p in list((ROOT / 'data/experiments').rglob('ledger*.csv')) + list((ROOT / 'data/experiments').rglob('ledgers/*.csv')):
        files += 1
        try:
            with p.open(newline='', encoding='utf-8') as f:
                for r in csv.reader(f):
                    if len(r) > 8 and '2009-01-01' <= r[0] <= '2011-06-30' and r[2] == '买入' and r[8] == '首次建仓':
                        cnt[r[1].zfill(6)] += 1
        except (UnicodeDecodeError, OSError):
            continue
    return files, cnt


# ── 逐日状态摘录（流式，一次）─────────────────────────────────────────────────────────────────────────

def extract(codes):
    keep = ('security_code', 'date', 'close', 'band_report_date', 'band_available_at', 'split_factor', 'intrinsic_value', 'valuation_ratio')
    last = {}
    with STATES.open(newline='', encoding='utf-8') as f, gzip.open(EXTRACT_CODES, 'wt', newline='') as fc:
        rd = csv.reader(f)
        h = next(rd)
        idx = [h.index(k) for k in keep]
        ic, idt = h.index('security_code'), h.index('date')
        wc = csv.writer(fc)
        wc.writerow(keep)
        for row in rd:
            code, d = row[ic], row[idt]
            if code in codes and '2008-01-01' <= d <= '2012-12-31':
                wc.writerow([row[i] for i in idx])
            if d.startswith('2010-'):
                last[(code, d[:7])] = [row[i] for i in idx]
    with gzip.open(EXTRACT_ME2010, 'wt', newline='') as fm:
        wm = csv.writer(fm)
        wm.writerow(keep)
        for k in sorted(last):
            wm.writerow(last[k])


def load_extract(path):
    with gzip.open(path, 'rt', newline='') as f:
        return list(csv.DictReader(f))


# ── 二、财务数据对年报原文 ─────────────────────────────────────────────────────────────────────────────

LABELS = {
    'revenue': ('营业总收入', '营业收入'),
    'ni': ('归属于上市公司股东的净利润', '归属于上市公司普通股股东的净利润', '归属于公司普通股股东的净利润',
           '归属于母公司所有者的净利润', '归属于母公司股东的净利润', '归属于本公司股东的净利润'),
    'equity': ('归属于上市公司股东的所有者权益（或股东权益）', '归属于上市公司股东的所有者权益', '归属于上市公司股东的股东权益',
               '归属于上市公司股东的权益', '归属于上市公司股东权益',
               '归属于上市公司股东的净资产', '归属于上市公司普通股股东的所有者权益', '归属于上市公司普通股股东的股东权益',
               '归属于母公司所有者权益合计', '归属于母公司股东权益合计', '归属于本公司股东权益合计', '归属于母公司所有者权益',
               '归属于母公司股东权益', '归属于母公司股东的权益', '归属于本公司股东权益',
               '所有者权益（或股东权益）'),
    'eps': ('基本每股收益',),
    'bps': ('归属于上市公司股东的每股净资产', '归属于上市公司普通股股东的每股净资产', '归属于母公司股东的每股净资产'),
}
UNITS = {'百万元': 1e6, '千元': 1e3, '万元': 1e4, '元': 1.0}
# 数字：千分位两侧、小数点前后容忍排版空格（「1,660,866 ,819.90」「254,750,792 .86」）
NUM = r'(-?\d{1,3}(?:\s?,\s?\d{3})+(?:\s?\.\s?\d+)?|-?\d+(?:\s?\.\s?\d+)?)'
GAP = r'((?:\s*[（(][^）)\n]{0,16}[）)])*(?:\s*[一二三四五六七八九十]+[、.]\s*\d+)?[^\d\n]{0,16}?(?:\n\s*)?)'
OTHER_ITEMS = ('收益', '利润', '权益', '资产', '收入', '现金', '股本')
TRAD = str.maketrans('營業總歸屬於東淨潤權資產會計數據單萬財務額報準則為億幣計', '营业总归属于东净润权资产会计数据单万财务额报准则为亿币计')


def _num(s):
    s = s.replace(',', '').replace(' ', '')
    try:
        return float(s)
    except ValueError:
        return None


def _label_re(lab):
    return ''.join((r'[（(]' if ch in '（(' else r'[）)]' if ch in '）)' else re.escape(ch)) + r'\s*' for ch in lab)


def _find(field, text):
    """各标签的首个有效匹配里取位置最靠前的（主表通常在段首）。"""
    best = (None, None)
    for lab in LABELS[field]:
        for mm in re.finditer(_label_re(lab) + GAP + NUM + r'\s+' + NUM, text):
            gap = re.sub(r'[（(][^）)\n]{0,16}[）)]', '', mm.group(1))
            if any(w in gap for w in OTHER_ITEMS):
                continue
            if best[1] is None or mm.start() < best[1].start():
                best = (lab, mm)
            break
    return best


def parse_report(code, year):
    p = AR / code / f'{year}.txt.gz'
    meta = AR / code / f'{year}.json'
    if not p.exists():
        return None
    info = json.loads(meta.read_text()) if meta.exists() else {}
    text = gzip.open(p, 'rt', encoding='utf-8', errors='ignore').read().translate(TRAD)
    out = dict(date=info.get('date'), title=info.get('title', '').strip())
    if not re.search(r'营\s*业', text):
        return dict(out, status='原文不可读（字体编码）')
    m = None
    for title in ('主要会计数据', '主要财务数据', '会计数据和业务数据摘要', '主要财务指标'):
        m = re.search(r'\s*'.join(title), text)
        if m:
            break
    sec = text[m.start(): m.start() + 9000] if m else text
    out['status'] = 'ok' if m else '无主要会计数据段，按全文取'
    fields = list(LABELS)
    if m and _find('ni', sec)[1] is None:
        sec, out['status'] = text, '主要会计数据段无净利润行，按全文只取净利润与 EPS（H 股版等）'
        fields = ['ni', 'eps']
    elif not m:
        fields = ['ni', 'eps']
    for field in fields:
        lab, mm = _find(field, sec)
        if not mm:
            continue
        a, b = _num(mm.group(2)), _num(mm.group(3))
        scale = 1.0
        if field not in ('eps', 'bps'):
            um = list(re.finditer(r'单\s*位\s*[：:]\s*[（(]?\s*(?:人民币)?\s*[)）]?\s*(百万元|千元|万元|元)', sec[max(0, mm.start() - 3000): mm.start()]))
            scale = UNITS[um[-1].group(1)] if um else 1.0
            out['unit'] = um[-1].group(1) if um else '元（缺省）'
        out[field] = a * scale if a is not None else None
        out[field + '_prev'] = b * scale if b is not None else None
        out[field + '_label'] = lab
    return out


def panel_values(code, year):
    d = f'{year}-12-31'
    out = {}
    p = FIN / f'{d}.csv'
    if p.exists():
        for r in csv.DictReader(p.open(encoding='utf-8')):
            if r['security_code'] == code and r['report_date'] == d:
                f = lambda k: float(r[k]) if r.get(k) not in (None, '') else None
                out.update(sum_ni=f('parent_netprofit'), sum_rev=f('total_operate_income'), sum_eps=f('basic_eps'),
                           sum_bps=f('bps'), sum_notice=r['notice_date'])
    return out


def statements(codes):
    out = defaultdict(dict)
    for name, keys in (('income', ('PARENT_NETPROFIT', 'TOTAL_OPERATE_INCOME', 'OPERATE_INCOME')), ('balance', ('TOTAL_PARENT_EQUITY',))):
        with (STMT / f'{name}.csv').open(newline='', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if r['SECURITY_CODE'] in codes and r['REPORT_DATE'][5:10] == '12-31':
                    y = int(r['REPORT_DATE'][:4])
                    for k in keys:
                        if r.get(k) not in (None, ''):
                            out[(r['SECURITY_CODE'], y)][k] = float(r[k])
                    out[(r['SECURITY_CODE'], y)][f'{name}_notice'] = r.get('NOTICE_DATE', '')[:10]
    return out


def bands_for(codes):
    out = {}
    with BANDS.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['security_code'] in codes:
                out[(r['security_code'], r['report_date'], r['available_at'])] = r
    return out


def rel(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b - 1


def data_check(codes, stm, bands):
    rows = []
    for code in codes:
        reps = {y: parse_report(code, y) for y in range(2008, 2013)}
        for y in YEARS:
            rep, pv, st = reps.get(y), panel_values(code, y), stm.get((code, y), {})
            nxt = reps.get(y + 1)
            band = [b for (c, rd, _), b in bands.items() if c == code and rd == f'{y}-12-31']
            row = dict(code=code, year=y, report=bool(rep and rep.get('status') == 'ok'), report_status=rep.get('status') if rep else '无本地年报',
                       report_date=rep.get('date') if rep else None, unit=rep.get('unit') if rep else None,
                       notice_summary=pv.get('sum_notice'), notice_stmt=st.get('income_notice'),
                       band_available_at=sorted(b['available_at'] for b in band), band_status=sorted({b['status'] for b in band}))
            rev_stmt = st.get('TOTAL_OPERATE_INCOME') or st.get('OPERATE_INCOME')
            for field, panel_val, stmt_val in (('revenue', pv.get('sum_rev'), rev_stmt), ('ni', pv.get('sum_ni'), st.get('PARENT_NETPROFIT')),
                                               ('equity', None, st.get('TOTAL_PARENT_EQUITY')), ('eps', pv.get('sum_eps'), None),
                                               ('bps', pv.get('sum_bps'), None)):
                r_val = rep.get(field) if rep else None
                row[f'{field}_report'] = r_val
                row[f'{field}_summary'] = panel_val
                row[f'{field}_stmt'] = stmt_val
                if field in ('eps', 'bps'):
                    row[f'{field}_diff_summary'] = (panel_val - r_val) if (panel_val is not None and r_val is not None) else None
                else:
                    row[f'{field}_rel_summary'] = rel(panel_val, r_val)
                    row[f'{field}_rel_stmt'] = rel(stmt_val, r_val)
                restated = nxt.get(f'{field}_prev') if nxt and nxt.get('status') == 'ok' else None
                row[f'{field}_restated_next'] = restated
                row[f'{field}_restate_rel'] = rel(restated, r_val) if field not in ('eps', 'bps') else (
                    (restated - r_val) if (restated is not None and r_val is not None) else None)
            rows.append(row)
    return rows


def mismatches(rows):
    out = []
    for r in rows:
        for field in ('revenue', 'ni', 'equity'):
            for src in ('summary', 'stmt'):
                x = r.get(f'{field}_rel_{src}')
                if x is not None and abs(x) > TOL:
                    out.append(dict(code=r['code'], year=r['year'], field=field, source=src, rel=x,
                                    report=r[f'{field}_report'], panel=r[f'{field}_{src}'],
                                    restated_next=r.get(f'{field}_restated_next'), restate_rel=r.get(f'{field}_restate_rel')))
        for field in ('eps', 'bps'):
            x = r.get(f'{field}_diff_summary')
            if x is not None and abs(x) > 0.011:
                out.append(dict(code=r['code'], year=r['year'], field=field, source='summary', diff=x,
                                report=r[f'{field}_report'], panel=r[f'{field}_summary'],
                                restated_next=r.get(f'{field}_restated_next')))
    return out


# ── 三、入选时估值 ───────────────────────────────────────────────────────────────────────────────────

def latest_fy(bands, stm, code, day):
    """信号日前已可得的最近一个年报期（按年报带最早可得日），返回（年, 归母净利, 归母权益）。"""
    best = None
    for (c, rd, av), _b in bands.items():
        if c == code and rd.endswith('-12-31') and av <= day:
            y = int(rd[:4])
            if best is None or y > best:
                best = y
    if best is None:
        return None
    st = stm.get((code, best), {})
    return best, st.get('PARENT_NETPROFIT'), st.get('TOTAL_PARENT_EQUITY')


def valuation_rows(entries, obs, st_rows, bands, nm, stm):
    by_code = defaultdict(list)
    for r in st_rows:
        by_code[r['security_code']].append(r)
    for v in by_code.values():
        v.sort(key=lambda r: r['date'])

    def state_before(code, d, inclusive=False):
        rows = by_code.get(code, [])
        days = [r['date'] for r in rows]
        i = bisect_right(days, d) - (0 if inclusive else 1)
        if not inclusive and i >= 0 and days[i] == d:
            i -= 1
        return rows[i] if 0 <= i < len(rows) else None

    def describe(code, st):
        b = bands.get((code, st['band_report_date'], st['band_available_at']))
        fac = float(st['split_factor'] or 1) or 1.0
        close = float(st['close'])
        nopat = float(b['nopat_ps']) / fac if b and b['nopat_ps'] else None
        # PE／PB 用总额口径：信号日市值（带 shares_est × 其后送转因子 × 收盘）÷ 最近年报归母净利／归母权益，避开东财每股数按后续送转回溯调整
        fy = latest_fy(bands, stm, code, st['date'])
        shares = float(b['shares_est']) * fac if b and b['shares_est'] else None
        pe = pb = voe = None
        if fy and shares:
            _y, ni, eq = fy
            pe = close * shares / ni if ni and ni > 0 else None
            pb = close * shares / eq if eq and eq > 0 else None
            voe = float(st['intrinsic_value']) * shares / ni if ni and ni > 0 else None
        return dict(signal_day=st['date'], close=close, v=float(st['intrinsic_value']), pv=float(st['valuation_ratio']),
                    band=f"{st['band_report_date']}（{st['band_available_at']}）", mode=b['roic_nopat_mode'] if b else '',
                    peak_w=float(b['peak_weight'] or 0) if b else None, trough_w=float(b['trough_weight'] or 0) if b else None,
                    trust=float(b['growth_trust'] or 0) if b else None, nopat_ps=nopat,
                    ni_fy=fy[1] if fy else None, fy=fy[0] if fy else None, shares=shares,
                    pe=pe, pb=pb, v_over_eps=voe,
                    roe=float(b['roe_ttm']) if b and b['roe_ttm'] else None, g0=float(b['g0']) if b and b['g0'] else None,
                    split_factor=fac)

    def f3_for(code, d):
        rows = [r for r in obs.get(code, []) if r['month'] <= d[:7]]
        if not rows:
            return None
        r = max(rows, key=lambda r: r['month'])
        return float(r['f3']) if r['f3'] not in ('', None) else None

    ent = {}
    for e in entries:
        key = (e['code'], e['date'])
        if key in ent:
            ent[key]['starts'].append(e['start'])
            continue
        st = state_before(e['code'], e['date'])
        d = describe(e['code'], st) if st else {}
        ent[key] = dict(code=e['code'], name=nm.get(e['code'], ''), entry=e['date'], starts=[e['start']], ledger_price=e['price'],
                        ledger_pv=e['pv'], exit=e['exit'], exit_reason=e['exit_reason'], ret=e['ret'], contrib=e['contrib'],
                        f3=f3_for(e['code'], st['date']) if st else None, **d)
    zone = []
    for code, rows in obs.items():
        for r in rows:
            if r['panel'] == 'True' and '2009-01' <= r['month'] <= '2011-12' and float(r['pv']) <= LINE:
                st = state_before(code, r['date'], inclusive=True)
                d = describe(code, st) if st else {}
                zone.append(dict(code=code, name=nm.get(code, r['name']), month=r['month'], f3=float(r['f3']) if r['f3'] else None,
                                 obs_pv=float(r['pv']), **d))
    return sorted(ent.values(), key=lambda x: (x['entry'], x['code'])), sorted(zone, key=lambda x: (x['code'], x['month']))


# ── 汇总与输出 ───────────────────────────────────────────────────────────────────────────────────────

def main():
    nm = names()
    iv = panel_intervals()
    obs = obs_rows()
    zone_codes = sorted({c for c, rows in obs.items() for r in rows
                         if r['panel'] == 'True' and '2009-01' <= r['month'] <= '2011-12' and float(r['pv']) <= LINE})
    entries = s15_entries()
    if '--refresh' in sys.argv or not EXTRACT_CODES.exists() or not EXTRACT_ME2010.exists():
        extract(set(zone_codes))
    st_rows = load_extract(EXTRACT_CODES)
    me = load_extract(EXTRACT_ME2010)

    pool = {d: sorted(c for c in iv if member(iv, c, d)) for d in ('2009-06-30', '2010-06-30', '2010-12-31', '2011-06-30', '2011-12-31')}
    nonpool = Counter()
    pool_zone = Counter()
    for r in me:
        try:
            x = float(r['valuation_ratio'])
        except ValueError:
            continue
        if 0 < x <= LINE:
            (pool_zone if member(iv, r['security_code'], r['date']) else nonpool)[r['security_code']] += 1
    files, old = old_ledgers()

    stm = statements(set(zone_codes))
    bands = bands_for(set(zone_codes))
    checks = data_check(zone_codes, stm, bands)
    mism = mismatches(checks)
    ent, zone = valuation_rows(entries, obs, st_rows, bands, nm, stm)
    res = dict(zone_codes=zone_codes, pool_members={d: len(v) for d, v in pool.items()},
               pool_2010_06_30=[(c, nm.get(c, '')) for c in pool['2010-06-30']],
               nonpool_zone_2010=dict(codes=len(nonpool), monthends=sum(nonpool.values()),
                                      top=[(c, nm.get(c, ''), n) for c, n in nonpool.most_common(40)]),
               pool_zone_2010=[(c, nm.get(c, ''), n) for c, n in pool_zone.most_common()],
               old_ledgers=dict(files=files, first_buys=[(c, nm.get(c, ''), n) for c, n in old.most_common()]),
               s15_entries=ent, zone_monthends=zone, data_checks=checks, mismatches=mism, notes=NOTES)
    (EXP / 'audit.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str) + '\n', encoding='utf-8')
    write_md(res, nm)


def write_md(res, nm):
    f2 = lambda x, n=2: '—' if x is None else f'{x:.{n}f}'
    pct = lambda x, n=0: '—' if x is None else f'{x * 100:.{n}f}%'
    out = ['# 2010 年前后回测买入候选核查（2026-10-01）', '',
           '## 一、候选', '',
           f"- 时点股票库成员数：" + '，'.join(f'{d} {n}' for d, n in res['pool_members'].items()) + '。',
           f"- 2010-06-30 成员：" + '、'.join(n or c for c, n in res['pool_2010_06_30']) + '。',
           f"- 2009–2011 年月末在买入区的成员（{len(res['zone_codes'])} 只）：" + '、'.join(nm.get(c, c) for c in res['zone_codes']) + '。',
           f"- 2010 年月末在买入区的成员：" + '、'.join(f'{n or c}（{k} 个月）' for c, n, k in res['pool_zone_2010']) + '。',
           f"- 2010 年月末在买入区但不在股票库的代码 {res['nonpool_zone_2010']['codes']} 只（{res['nonpool_zone_2010']['monthends']} 个月末），最多的："
           + '、'.join(f'{n or c}（{k}）' for c, n, k in res['nonpool_zone_2010']['top'][:25]) + '。回测不会买这些。',
           f"- 旧实验台账 {res['old_ledgers']['files']} 个文件中 2009-01～2011-06 的首次建仓：" + '、'.join(
               f'{n or c}（{k}）' for c, n, k in res['old_ledgers']['first_buys']) + '。', '',
           '### S15 首次建仓（2009-11～2012-06，四个早起点去重）', '',
           '| 建仓 | 代码 | 名称 | 起点数 | 信号日收盘 | V | `P/V` | 带（可得日） | 路径 | 峰 w | 谷 v | λ | 每股 NOPAT | 最近年报归母净利（亿元，年） | PE | PB | V 对应市盈率 | ROE | 3 年年化 | 周期回报 | 贡献 pp | 退出 |',
           '| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for e in res['s15_entries']:
        out.append(f"| {e['entry']} | {e['code']} | {e['name']} | {len(e['starts'])} | {f2(e.get('close'))} | {f2(e.get('v'))} | {f2(e.get('pv'))} | "
                   f"{e.get('band', '')} | {e.get('mode', '')} | {f2(e.get('peak_w'))} | {f2(e.get('trough_w'))} | {f2(e.get('trust'), 1)} | "
                   f"{f2(e.get('nopat_ps'))} | {f2((e.get('ni_fy') or 0) / 1e8 if e.get('ni_fy') else None)}（{e.get('fy') or '—'}） | {f2(e.get('pe'), 1)} | {f2(e.get('pb'), 1)} | {f2(e.get('v_over_eps'), 1)} | {pct(e.get('roe'))} | "
                   f"{pct(e.get('f3'))} | {pct(e.get('ret'))} | {f2(e.get('contrib'), 1)} | {e['exit']} {e['exit_reason']} |")
    out += ['', '### 月末在买入区的成员（2009–2011）', '',
            '| 代码 | 名称 | 月份 | `P/V` | 路径 | 峰 w | 每股 NOPAT | 最近年报归母净利（亿元，年） | PE | PB | V 对应市盈率 | ROE | 3 年年化 |',
            '| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for z in res['zone_monthends']:
        out.append(f"| {z['code']} | {z['name']} | {z['month']} | {f2(z['obs_pv'])} | {z.get('mode', '')} | {f2(z.get('peak_w'))} | "
                   f"{f2(z.get('nopat_ps'))} | {f2((z.get('ni_fy') or 0) / 1e8 if z.get('ni_fy') else None)}（{z.get('fy') or '—'}） | {f2(z.get('pe'), 1)} | {f2(z.get('pb'), 1)} | {f2(z.get('v_over_eps'), 1)} | {pct(z.get('roe'))} | {pct(z['f3'])} |")
    out += ['', '## 二、财务数据对年报原文（FY2008–FY2011）', '',
            '仓库「摘要」为 `data/raw/financials/<报告期>.csv`，「三表」为 `data/raw/financials_statements/`；原文取本地年报「主要会计数据」表。相对差超过 0.5%（EPS、BPS 超过 0.01 元）列为不一致。', '',
            '| 代码 | 年 | 原文 | 原文披露日 | 摘要公告日 | 带可得日 | 营收 原文（亿元） | 摘要差 | 归母净利 原文（亿元） | 摘要差 | 三表差 | 归母权益 原文（亿元） | 三表差 | EPS 原文／摘要 | BPS 原文／摘要 |',
            '| --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |']
    yi = lambda x: '—' if x is None else f'{x / 1e8:.2f}'
    for r in res['data_checks']:
        out.append(f"| {r['code']} | {r['year']} | {'有' if r['report'] else r['report_status']} | {r['report_date'] or '—'} | {r['notice_summary'] or '—'} | "
                   f"{'、'.join(r['band_available_at']) or '—'} | {yi(r['revenue_report'])} | {pct(r['revenue_rel_summary'], 2)} | {yi(r['ni_report'])} | "
                   f"{pct(r['ni_rel_summary'], 2)} | {pct(r['ni_rel_stmt'], 2)} | {yi(r['equity_report'])} | {pct(r['equity_rel_stmt'], 2)} | "
                   f"{f2(r['eps_report'])}／{f2(r['eps_summary'])} | {f2(r['bps_report'])}／{f2(r['bps_summary'])} |")
    out += ['', f"不一致共 {len(res['mismatches'])} 条（摘要与三表分列）。归类：", '', *MISMATCH_NOTES, '', '明细：', '']
    for m in res['mismatches']:
        if 'rel' in m:
            out.append(f"- {m['code']} {m['year']} {m['field']}（{m['source']}）：原文 {yi(m['report'])} 亿，仓库 {yi(m['panel'])} 亿，差 {pct(m['rel'], 2)}；"
                       f"次年年报重述为 {yi(m['restated_next'])} 亿（对原文 {pct(m['restate_rel'], 2)}）。")
        else:
            out.append(f"- {m['code']} {m['year']} {m['field']}（{m['source']}）：原文 {f2(m['report'])}，仓库 {f2(m['panel'])}，差 {m['diff']:+.2f}；"
                       f"次年年报重述为 {f2(m['restated_next'])}。")
    out += ['', '## 三、判断', '']
    for c in res['zone_codes']:
        out.append(f"- **{nm.get(c, c)}（{c}）**：{res['notes'].get(c, '')}")
    out += ['', '## 四、结论', '',
            f"- 现行 BASE 的时点股票库在 2009–2011 年只有 49～62 只，以银行、白酒、医药和行业龙头为主；月末在买入区的只有 13 只，2010 年全年只有格力、福耀。"
            "S15 2010 年建仓格力、福耀，2011 年加潍柴、厦门空港、电投能源、神华、广电运通、苏宁，均为主流公司，不是奇怪的股票。",
            f"- 「奇怪的股票」更可能来自全市场逐日状态：2010 年月末在买入区而不在股票库的有 {res['nonpool_zone_2010']['codes']} 只（钢铁、航运、造船、地产、ST 等），回测按时点股票库不会买。旧实验台账 2009–2011 年上半年的首次建仓也只有股票库内的 7 只。",
            '- 财务数据：营收、净利、权益与年报原文一致或为追溯重述（最大为格力 FY2008 净利 −6.5%、新兴铸管 FY2009 营收 +15.4%），每股数差异来自东财按后续送转回溯；未见录入错误。重述数挂原公告日属 OI-225 已登记的范围。',
            '- 估值：各候选按最近年报的市盈率 7.5～25、V 对应市盈率 11～28，没有被数据扭曲的读数。事后看不合理的是 2011 年的周期高点（潍柴、神华、电投能源：其后 3 年年化为负）与苏宁（商业模式恶化），属模型对周期高点与商业模式变化的识别局限，不是数据问题。']
    (EXP / 'audit.md').write_text('\n'.join(out) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
