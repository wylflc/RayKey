"""Build oi214_review.csv: one row per unpaired announcement (paired == 0) of
data/interim/restatement_announcements.csv, with event-level findings (companion
documents of the same company/date share the event's findings)."""
import csv

R = '/gpfs/scratch1/shared/zwang/mm_quant/RayKey'
OUT = '/gpfs/scratch1/nodespecific/tcn441/zwang.27284302/claude-66633/-gpfs-scratch1-shared-zwang-mm-quant-RayKey/be4702a1-b00c-45e2-9cec-3beb6af4945d/scratchpad/oi214'
HOLD = {'000651', '002648', '603529', '600036', '601318'}
POOL = {r['security_code'] for r in csv.DictReader(open(R + '/data/processed/a_share_pool_model_bands_adopted.csv', encoding='utf-8'))}

# universe windows (panel_moat_bank_v6b effective_from..effective_to), backtest starts >= 2009-11-01
UNI = {}
for r in csv.DictReader(open(R + '/data/processed/pit_attention/panel_moat_bank_v6b.csv', encoding='utf-8')):
    UNI.setdefault(r['security_code'].zfill(6), []).append((r['effective_from'], r['effective_to'] or '9999-12-31'))


def uni(code):
    iv = sorted(UNI.get(code, []))
    m = []
    for a, b in iv:
        if m and a <= m[-1][1]:
            m[-1][1] = max(m[-1][1], b)
        else:
            m.append([a, b])
    return ' '.join(f'{a}~{b if b != "9999-12-31" else "open"}' for a, b in m)


# event key: (code, announcement_date) -> dict
E = {}


def ev(code, date, main, nature, periods, pct, state, cls, action, evidence, notes, overlap):
    E[(code, date)] = dict(main=main, nature=nature, restated_periods=periods, fields_changed_pct=pct, panel_state=state,
                           classification=cls, proposed_action=action, evidence=evidence, notes=notes, overlap=overlap)


OPT = 'optional/low priority: no backtest state inside a universe window is affected (row not drafted)'

# ============================ scope (a): pool codes ============================
ev('000408', '2013-04-27', '62439138', 'error_correction', '2011-12-31',
   'NP +17.41% (7,348,535.11→8,628,077.31); EPS 0.0291→0.0342; equity +0.77% (167,151,874.46→168,431,416.66); revenue 0',
   'restated', 'entity_reset_check',
   'Review 000408 reverse-merger (金谷源 shell → 藏格, consolidated from 2015 Q3; panel revenue 2014 56.6m → 2015 2,728m) against §6.5.2.4; candidate reset_report_date 2015-12-31. If no reset: FY2011 originals ' + OPT,
   '更正公告 p1-p2 数据追溯调整后主要会计指标对比表（2011 调整前/调整后）；面板 2011-12-31 行 NP 8,628,077.31、bps 0.667579=168,431,416.66÷252,301,500',
   '金谷源子公司 2011 所得税汇算差错；壳公司时期数据。000408 仅自 2021-04-30 进入回测宇宙，前视窗 2012-04-27→2013-04-27 不在宇宙内；但 2021 年后建带的十年窗口仍含 2011-2014 壳公司年报', 'no')
ev('000408', '2014-12-22', '1200480312', 'error_correction', '2013-12-31',
   'NP -6.58% (21,610,828.33→20,189,318.01); EPS 0.0857→0.0800; equity -1,421,510.32 (≈-0.7%)',
   'restated (later version: panel FY2013 NP 17,836,937.60 = 2015-02-06 re-correction / 2014 annual comparative)', 'entity_reset_check',
   'No registration needed for look-ahead: 2013-12-31 already delayed to 2015-02-06 by the paired updated 2013 annual report (台账 paired rows 2015-02-06). Same 借壳 reset review as 2013-04-27',
   '更正公告 p2-p3 合并利润表影响表（2013 年度 调整前/调整数/调整后）',
   '昆山宏图诉讼预计负债差错；2015-02-06 再次更正并发布更新后 2013 年报（已配对）', 'no')
for d, m, p, pct in [
        ('2015-04-30', '1200945234', '2013-12-31 (and 2012-12-31 equity)', 'FY2013 NP -2.34% (69,406,334.67→67,783,992.55); equity +0.32% (2,729,900,668.46→2,738,532,733.84); revenue 0; 2013-01-01 equity +0.61%'),
        ('2016-04-28', '1202257404', '2014-12-31 (and 2013-12-31 equity)', 'FY2014 NP -0.46% (161,807,438.01→161,059,816.91); equity +1.17% (2,752,836,620.25→2,784,994,421.64); revenue 0')]:
    ev('000426', d, m, 'same_control_merger', p, pct, 'restated', 'register_originals',
       OPT + '; statement-side restated too (three-statement UPDATE_DATE = announcement date)',
       '追溯调整公告 p2-p3 合并所有者权益/合并利润表影响表（追溯调整后/前）；面板与三表该年报行为调整后值',
       '兴业矿业现金收购控股股东所持矿业公司（唐河时代 1.2 亿 / 荣邦矿业 0.37 亿）；000426 自 2024-04-30 才进入宇宙', 'no')
ev('000426', '2017-04-29', '1203425081', 'same_control_merger', '2015-12-31 (and 2014-12-31 equity)',
   'FY2015 NP -15.9% (-24,844,335.40→-28,796,824.16); equity +1.72% (2,697,949,754.46→2,744,245,177.43); revenue 0; 2015-01-01 equity -1.31%',
   'restated', 'entity_reset_check',
   'Review against §6.5.2.4: 2016 发行股份购买银漫矿业 100%（股本 1,193,889,056→1,868,500,557，归母权益 FY2015 2,744m→FY2016 4,864m）; candidate reset_report_date 2016-12-31 (low urgency: code enters universe 2024-04-30). FY2015 originals ' + OPT,
   '追溯调整公告 p2-p3 三张影响表；面板 2015-12-31 NP -28,796,824.16（调整后）',
   '资产注入型同一控制下合并；银漫矿业此后成为主要利润来源', 'no')
ev('000568', '2014-10-22', '1200316491', 'policy_change', '2013-12-31 (opening equity)',
   'equity +0.056% (10,568,084,468.94→10,573,957,268.94; retained earnings +5,872,800); NP of prior periods unaffected',
   'restated', 'no_action', 'none (<1%)',
   '台账文件为独立董事意见（无数字）；数字取同日《关于会计政策变更的公告》1200316492 p2-p3 与 2014 三季报正文 1200316487 p1（2013 年末归母权益调整前/后）；三表 2013-12-31 权益 10,573,957,268.94（调整后）',
   '2014 年新修订七项准则：长期股权投资重分类至可供出售、北方硝化棉转交易性金融资产', 'yes (2009-04-30~2017-04-19)')
ev('000725', '2011-04-26', '59337741', 'policy_change', 'pre-2010 equity (2009-12-31)',
   'parent equity +6,891,026 (≈+0.04% of 2009-12-31 parent equity 18,029.7m)', 'not_checked', 'no_action', 'none (<1%)',
   '董事会说明 p1（解释第4号：子公司少数股东超额亏损改由少数股东承担）；主文件 59337728 为扫描件，内容同独董/监事会说明',
   '000725 自 2020-04-30 才进入宇宙', 'no')
ev('000725', '2019-03-26', '1205937149', 'policy_change', '2017-12-31 / FY2017 (presentation only)',
   'NP 0; equity 0 (reclassification of receivables/payables, 管理费用→研发费用 3,177.8m)', 'n/a (presentation only)', 'no_action',
   'none', '董事会专项说明 p2-p4（"对本公司及母公司2017年度净利润及2017年年初及年末所有者权益无影响"）', '财会[2018]15号报表格式、解释第9-12号', 'no')
ev('000725', '2020-04-28', '1207641673', 'policy_change', '2019-01-01 opening only (comparatives not restated)',
   'parent equity -7,360,469 at 2019-01-01 (-0.01%); 2018 comparatives not restated', 'n/a', 'no_action', 'none',
   '董事会专项说明 p2 新金融工具准则衔接表', '新金融工具准则不重述比较期', 'no')
ev('000725', '2022-03-31', '1212750853', 'policy_change', 'FY2020/FY2021 presentation (cost vs admin expense); 2021-01-01 lease opening',
   'NP 0; equity 0', 'n/a', 'no_action', 'none', '董事会专项说明 p1-p2（新租赁准则不调整可比期；固定资产修理费重分类对净利润无重大影响）', '', 'yes (2020-04-30~)')
ev('000725', '2022-04-28', '1213164915', 'policy_change', '2021-03-31 (income); 2021-12-31 (balance)',
   '2021Q1 NP +1.51% (5,182,037,171→5,260,529,397); revenue +1.25% (49,655,379,519→50,275,246,475); EPS 0.147→0.149; ROE 5.51→5.59; 2021-12-31 retained earnings +160.7m (≈+0.1%)',
   'restated', 'register_originals', 'register 000725 2021-03-31 original (row drafted, superseded_at 2022-04-28)',
   '董事会专项说明 p1-p2（解释第15号试运行销售：营收/成本/费用/少数股东损益调整数）；原值 2021 一季报正文 1209863711 p1-p2；面板 2021-03-31 行=调整后',
   '归母净利变动按表内各项调整数合计（营业利润 +233.47m − 少数股东损益 +154.97m）推算，与原报告 5,182,037,171 与面板 5,260,529,397 之差一致', 'yes (2020-04-30~)')
ev('000725', '2022-08-30', '1214449842', 'policy_change', '2021-06-30 (income); 2021-12-31 (balance)',
   '2021H1 NP +1.22% (12,762,024,968→12,917,163,177); revenue +1.24% (107,285,327,026→108,618,018,710); EPS 0.363→0.367; ROE 13.40→13.54',
   'restated', 'register_originals', 'register 000725 2021-06-30 original (row drafted, superseded_at 2022-08-30)',
   '董事会专项说明 p2；原值 2021 半年报摘要 1210925277 p1-p2（2021-09-02 更新后全文同数）', '', 'yes (2020-04-30~)')
ev('000725', '2022-10-31', '1214965943', 'policy_change', '2021-09-30 (income)',
   '2021Q3 NP ≈+0.72% (Δ +143.9m on 20,159.3m restated); revenue +0.93%', 'restated', 'no_action', 'none (<1%)',
   '董事会专项说明 p2 调整数（营业收入 +1,524,082,301 等）', '', 'yes (2020-04-30~)')
ev('000725', '2023-04-04', '1216320152', 'policy_change', '2021-12-31 / FY2021',
   'FY2021 NP ≈+0.50% (Δ +129.8m); revenue +0.79%; parent equity +278.7m (+0.19%)', 'restated', 'no_action', 'none (<1%)',
   '董事会专项说明 p2 调整表', '', 'yes (2020-04-30~)')
for d, m in [('2023-04-29', '1216690213'), ('2023-08-29', '1217675822'), ('2024-04-02', '1219494110')]:
    ev('000725', d, m, 'policy_change', '2022-12-31 / FY2022',
       'FY2022 NP -0.13% (7,550,877,790→7,541,423,198); retained earnings -9.6m (≈-0.01%)', 'restated', 'no_action', 'none (<1%)',
       '董事会专项说明 p1-p2（解释第16号）', '', 'yes (2020-04-30~)')
ev('000725', '2025-04-22', '1223193320', 'policy_change', 'FY2023 (selling expense → cost)', 'NP 0; equity 0', 'n/a', 'no_action', 'none',
   '董事会专项说明 p1（解释第18号，1,840.6m 重分类）', '', 'yes (2020-04-30~)')
ev('000792', '2009-07-25', '55105174', 'policy_change+error_correction', '2008-06-30 (income), 2008-12-31 (equity)',
   '2008 equity ≈+3.0% (policy +85.19m, correction +2.42m on ~2,996m); 2008H1 operating cost +44.1m', 'restated (vendor notice 2009-07-25 on 2008-06-30 row)', 'no_action',
   'none: look-ahead window ended 2009-07-25, before the earliest backtest start 2009-11-01',
   '会计师专项说明 p1-p2（解释第3号安全费、2008 所得税汇算）', '', 'no (ends before 2009-11-01)')
# ---- 双汇
SH_NOTE = '双汇 2010-2013 两轮同一控制下合并；000895 自 2005-04-30 起在宇宙内且在现行池内'
ev('000895', '2011-04-29', '59362166', 'same_control_merger', '2010-03-31 (income); 2010-12-31 (equity)',
   '2010Q1 NP +9.07% (220,010,016.49→239,969,078.32); revenue -1.38%; EPS 0.3631→0.3960; ROE 7.21→7.55; 2010-12-31 equity +7.30% (3,422,646,302.18→3,672,376,465.51, same day as original annual)',
   'restated (NP/revenue/EPS/ROE/ocfps; bps original)', 'register_originals',
   'register 000895 2010-03-31 original (drafted, superseded_at 2011-04-29); also 2010-06-30 (restated 2011-08-19 in the H1 report, no announcement) drafted',
   '2011 一季报全文 59362163 p1「调整前/调整后」表；董事会/独董说明 p1（原因）；面板 2010-03-31 行=调整后',
   SH_NOTE + '；首轮：2011 年 1 月收购罗特克斯所持 9 家公司股权（6 家成为子公司）', 'yes (2005-04-30~)')
ev('000895', '2011-10-22', '60092574', 'same_control_merger', '2010-09-30 (income)',
   '2010Q3 NP +7.48% (754,383,513.43→810,822,030.40); revenue -1.31%; EPS 1.2449→1.338',
   'restated (NP/revenue/EPS/GM; bps/ROE/ocfps original)', 'register_originals', 'register 000895 2010-09-30 original (drafted, superseded_at 2011-10-22)',
   '董事会专项说明 p1-p2 主要变动数据表（万元）；原值 2010 三季报全文 58593243 p1', SH_NOTE, 'yes (2005-04-30~)')
ev('000895', '2012-03-02', '60612315', 'same_control_merger', '2010-12-31; 2009-12-31 (3-year table)',
   'FY2010 NP +6.42% (1,089,281,494.22→1,159,206,378.09); revenue -1.19%; EPS 1.80→1.91; equity +7.24% (3,422,646,302.18→3,670,449,087.24); FY2009 equity +8.09% (2,940,228,490.83→3,178,140,275.49), ROE 34.96→34.13',
   'restated (FY2010 NP/rev/EPS/bps; FY2009 bps/ROE/ocfps; FY2010 ROE later replaced by the 2013-03-26 version)', 'register_originals',
   'register 000895 2010-12-31 original (sa 2012-03-02) + intermediate 2012-03-02 version (sa 2013-03-26) and 2009-12-31 original (sa 2012-03-02); statement side: delay FY2010 three statements to 2012-03-02',
   '审计师追溯调整专项说明 60612315 p3-p4；2011 年报 60612313 p4-p5 三年表（调整前/调整后）；原值 2010 年报 59362821 p4-p5、2009 年报 57864122 p4-p5',
   SH_NOTE, 'yes (2005-04-30~)')
ev('000895', '2012-10-20', '61679129', 'same_control_merger', '2011-09-30 (income); 2011-12-31 (equity)',
   '2011Q3 NP +160.1% (278,267,544.12→723,811,120.41); revenue -7.40%; EPS 0.4592→0.6578; 2011-12-31 equity +146% (3,681,682,275.43→9,059,284,659.96)',
   'restated (NP/revenue/EPS/GM; bps/ROE/ocfps original)', 'register_originals',
   'register 000895 2011-09-30 original (drafted, superseded_at 2012-10-20). Also entity_reset_check: 2012 重大资产重组（发行股份购买 22 家、吸收合并 2 家，股本 605,994,900→1,100,289,224）— review whether pre-2010 (unrestated) years should be cut from ratio/ten-year windows (candidate reset 2012-12-31)',
   '董事会专项说明 p1-p2 权益与利润表影响表；原值 2011 三季报全文 60092571 p1、p12', SH_NOTE + '；次轮：2012 重大资产重组', 'yes (2005-04-30~)')
ev('000895', '2013-03-26', '62271939', 'same_control_merger', '2011-12-31; 2010-12-31 (3-year table)',
   'FY2011 NP +136.2% (564,893,042.07→1,334,201,313.00); revenue -4.74%; EPS 0.93→1.21; equity +147.5% (3,681,682,275.43→9,111,101,629.79); FY2010 re-restated (NP 3,030,489,055.92, ROE 35.43)',
   'restated (FY2011 all key fields; FY2010 ROE only)', 'register_originals',
   'register 000895 2011-12-31 original (drafted, superseded_at 2013-03-26); statement side: delay FY2011 three statements to 2013-03-26. Vendor defect: current FY2011 bps 15.03 = combined equity ÷ pre-issuance 605,994,900 shares',
   '审计师专项说明 62271939 p7-p8；2012 年报更新后 62472535 p8 三年表；原值 2011 年报 60612313 p4-p5', SH_NOTE, 'yes (2005-04-30~)')
ev('000895', '2013-08-07', '62913391', 'same_control_merger', '2012-06-30 (income)',
   '2012H1 NP +153.1% (404,854,450.41→1,024,605,013.21); revenue -7.22%; EPS 0.6681 (published)→0.4656 (restated on 2,200.6m post-bonus shares)',
   'restated (NP/revenue/EPS/ROE/ocfps/GM; bps/deduct EPS original)', 'register_originals',
   'register 000895 2012-06-30 original (drafted, superseded_at 2013-08-07). Also: the paired 2013-04-24 correction restated 2012-03-31 (NP +172.5%) but its pairing covers only 2012-12-31 → 2012-03-31 drafted too',
   '董事会专项说明 p1-p2；原值 2012 半年报 61490820 p2、p38', SH_NOTE, 'yes (2005-04-30~)')
ev('000933', '2009-04-10', '51153292', 'policy_change+error_correction', '2007-12-31 / 2008-01-01',
   'FY2007 NP +15.96m (policy) + tax correction; 2008-01-01 parent equity +21.9m', 'not_checked', 'no_action',
   'none: look-ahead window (FY2007 row) ended 2009-04-10, before the earliest backtest start 2009-11-01', '公告 p1-p3', '', 'no (ends before 2009-11-01)')
ev('000933', '2010-03-23', '57717123', 'policy_change+error_correction', '2008-12-31 / FY2008',
   '2008-12-31 parent equity +9.88m (+0.34% of 2,938.6m); FY2008 NP +0.13m (+0.01%)',
   'restated (vendor notice of 2008-12-31 row = 2010-03-23)', 'no_action', 'none (<1%)', '会计师说明 57717123 p1-p2', '解释第3号安全费；子公司所得税汇算', 'yes (2004-04-30~2015-03-25)')
ev('000933', '2011-03-22', '59153533', 'error_correction', '2009-12-31 / FY2009',
   'FY2009 revenue -1.44% (-155,298,690.01 intra-group sales not eliminated); NP 0; equity 0',
   'restated (vendor notice of 2009-12-31 row = 2011-03-22)', 'no_action',
   'none: revenue-only (<5%); NP/equity unchanged — revenue only feeds net_margin() in the ROE-trend check',
   '公告 p1', '', 'yes (2004-04-30~2015-03-25)')
ev('000975', '2018-04-27', '1204799713', 'error_correction (not restated)', 'none', 'no retrospective restatement (immaterial: 0.63%/0.96% of NP)', 'n/a', 'no_action', 'none',
   '公告 p2（"按照非重大会计差错处理方法不进行追溯重述法调整"）', '', 'no (universe 2025-04-30~)')
ev('000975', '2019-04-17', '1206041058', 'same_control_merger+policy_change', '2017-12-31 / FY2017',
   'FY2017 NP +3.51% (325,273,623.60→336,703,028.44); revenue +50.2% (1,482,617,517.48→2,227,241,801.59); parent equity +22.7% (4,103,389,561.43→5,035,434,956.48)',
   'restated', 'entity_reset_check',
   'Review against §6.5.2.4: 2018 发行股份购买上海盛蔚 89.38%（作价 40.31 亿，并入黄金矿山）; candidate reset_report_date 2018-12-31 (code enters universe 2025-04-30; its ten-year windows still include FY2015-2016 old-entity years). FY2017 originals ' + OPT,
   '公告 p1-p2（原因）、p3-p5 期初资产负债表与上年同期利润表影响表（调整前/同控调整/政策调整/调整后）；面板与三表 FY2017=调整后', '', 'no (universe 2025-04-30~)')
ev('000999', '2009-03-14', '50177804', 'error_correction', '2007-12-31 / FY2007',
   'FY2007 NP -1.19% (285,285,469.30→281,888,086.28); equity -3.40m (-0.12%)', 'restated (vendor notice of FY2007 row = 2009-03-14)', 'no_action',
   'none: look-ahead window ended before the earliest backtest start 2009-11-01 (and code enters universe 2010-04-30)', '公告 p1 调整表', '', 'no')
ev('002128', '2010-10-26', '58570382', 'same_control_merger', '2009-12-31 (equity); 2009-09-30 (income)',
   '2009-12-31 parent equity +10.8% (3,213,603,166.13→3,560,616,033.24); 2009Q3 NP +1.65m (+0.26%); FY2009 NP -0.01%, revenue -2.66% (2010 annual)',
   'restated (FY2009 row = 2010-annual version, vendor notice 2011-03-10, capped to 2010-04-30)', 'register_originals',
   'register 002128 2009-12-31 original (drafted, superseded_at 2011-03-10); statement side: delay FY2009 three statements to 2011-03-10',
   '公告 p1-p2（调增 2009 年末所有者权益 347,012,867.11）；原值 2009 年报 57667306 p4-p5；调整后 2010 年报 59101413 p4', '收购扎哈淖尔露天矿采矿权及相关资产', 'yes (2009-04-30~)')
ev('002128', '2026-08-26', '1225504327', 'same_control_merger', '2025-06-30, 2025-09-30 (income); 2025-12-31 (balance)',
   '2025H1 NP +27.4% (2,786,570,009→3,548,957,356.30); revenue +37.9%; 2025-12-31 parent equity +23.5% (38,199,816,368.61→47,178,833,949.32)',
   'restated (archived originals exist)', 'no_action',
   'none: panel archives superseded/2025-06-30.csv & 2025-09-30.csv hold the originals (superseded_at 2026-08-31); statements archive balance 2025-12-31 (superseded_at 2026-08-26) + statement_restatements.csv; entity reset already registered (reset 2025-12-31, known_from 2026-08-26)',
   '公告 p1-p6 调整表；data/raw/financials/superseded/*.csv；data/raw/financials_statements/superseded/balance.csv', '白音华煤电', 'yes (2009-04-30~)')
ev('002270', '2021-10-26', '1211371522', 'same_control_merger', '2020-12-31 (balance), 2020-09-30 (income)',
   'NP -0.04% (259,999,053.44→259,902,971.15); EPS 0.3424→0.3423; parent equity +0.08%; revenue 0', 'restated', 'no_action', 'none (<1%)',
   '公告 p4-p6 调整表', '收购凌凯物业（物业公司）', 'no (universe 2022-04-30~)')
ev('002287', '2024-04-19', '1219662657', 'policy_change', '2022-12-31 / FY2022',
   'FY2022 NP +0.03% (+134,199.86); equity -0.1m', 'restated', 'no_action', 'none (<1%)', '董事会专项说明 p1-p2（解释第16号）', '', 'yes (2016-04-30~)')
ev('002371', '2025-04-26', '1223309168', 'same_control_merger', '2024-03-31 (income); 2024-12-31 (balance)',
   '2024Q1 NP +1.09% (1,126,550,627.36→1,138,817,830.60); revenue +1.56%; EPS 2.1245→2.1476; OCF 260.0m→235.5m; 2024-12-31 parent equity +0.17%',
   'restated', 'register_originals', 'register 002371 2024-03-31 original (drafted, superseded_at 2025-04-26; low priority, ~1%)',
   '公告 p2-p6 调整表；原值 2024 一季报 1219908881 p1、p7、p8、p10', '收购七星飞行（1.20 亿）', 'yes (2021-04-30~)')
ev('002371', '2025-08-29', '1224615656', 'same_control_merger', '2024-06-30 (income)',
   '2024H1 NP +0.35% (2,780,604,301.25→2,790,294,946.72); revenue +1.04%; EPS +0.35%', 'restated', 'no_action',
   'none: NP/EPS <1%; revenue +1.04% only feeds net_margin()', '公告 p4 调整表', '', 'yes (2021-04-30~)')
ev('002371', '2025-10-31', '1224774314', 'same_control_merger', '2024-09-30 (income)',
   '2024Q3 NP +0.12% (4,462,521,361.56→4,467,785,189.44); revenue +0.88%', 'restated', 'no_action', 'none (<1%)', '公告 p5 调整表', '', 'yes (2021-04-30~)')
ev('002371', '2026-04-18', '1225122929', 'same_control_merger', '2024-12-31 / FY2024',
   'FY2024 NP +0.01% (5,621,189,109.03→5,621,756,343.64); revenue +0.79%; equity +0.0006%', 'restated', 'no_action', 'none (<1%)', '公告 p5-p6 调整表', '', 'yes (2021-04-30~)')
ev('002466', '2015-04-13', '1200815509', 'same_control_merger', '2013-12-31 / FY2013 (and 2014 quarterly comparatives)',
   'FY2013 NP -44% (-132,361,442.45→-191,049,768.97); revenue +157% (414,975,907.31→1,068,198,171.99); parent equity +257% (865,488,220.10→3,087,900,625.85)',
   'restated', 'entity_reset_check',
   'Review against §6.5.2.4 (strong candidate): 2014 定增收购文菲尔德 51%（泰利森）与天齐矿业 100%; candidate reset_report_date 2014-12-31. Code enters universe 2016-04-30, so bands 2016-2023 use ten-year windows reaching pre-2013 old-entity years. FY2013 originals ' + OPT,
   '公告 p2-p3 权益与 2013 年度利润表影响表（调整前/调整后）；面板与三表 FY2013=调整后', '', 'no (universe 2016-04-30~)')
ev('002568', '2018-03-15', '1204477708', 'error_correction', '2017-06-30, 2017-09-30',
   '2017H1 NP -21.6% (78,174,753.43→61,299,753.43); 2017Q3 NP -12.6% (133,823,813.87→116,948,813.87); equity -1.0%',
   'restated', 'register_originals', OPT, '公告 p1-p2 两张影响表', '政府补助 2,250 万元改列递延收益', 'no (universe 2022-04-30~)')
ev('600066', '2015-03-31', '1200766379', 'policy_change (+prospective estimate change)', '2013-12-31 / FY2013 (presentation)',
   'NP 0; equity 0 (长期股权投资→可供出售 142.4m；递延收益重列 253.4m); estimate change prospective (+19.38m FY2014)', 'n/a', 'no_action', 'none',
   '扫描件，渲染页图 p4-p5（"上述会计政策变更对当期净利润无影响"）；未见前期差错更正', '', 'yes (2012-04-30~)')
for d, m, p, pct in [
        ('2024-04-20', '1219693963', '2023-03-31 (income); 2023-12-31 (balance)', '2023Q1 NP -0.03% (352,412,349.97→352,321,475.54); revenue +0.008%; 2023-12-31 parent equity +0.20% (10,073,880,098.87→10,093,967,223.89)'),
        ('2024-08-08', '1220814762', '2023-06-30 (income)', '2023H1 revenue +0.009%; NP ≈0; EPS 0.78→0.78'),
        ('2024-10-31', '1221573355', '2023-09-30 (income)', '2023Q3 NP +0.31% (911,676,667.40→914,504,782.73); revenue +0.01%'),
        ('2025-04-10', '1223046739', '2023-12-31 / FY2023', 'FY2023 NP +0.20% (1,270,164,997.63→1,272,719,795.37); EPS 1.47→1.48; equity +0.20%')]:
    ev('600298', d, m, 'same_control_merger', p, pct, 'restated', 'no_action', 'none (<1%)',
       '公告调整表（追溯调整前/后）；面板 2023 各期=调整后（例 2023-03-31 NP 352,321,475.54）', '收购安琪生物农业（2,089 万元）', 'yes (2021-04-30~)')
ev('600436', '2019-04-13', '1206014130', 'policy_change', '2017-12-31 / FY2017 (presentation)',
   'NP 0; equity 0 (报表格式重分类；管理费用→研发费用 69.9m)', 'n/a', 'no_action', 'none',
   '文本层乱码，渲染页图 p2-p3："会计估计变更：无""重大会计差错更正：无"', '', 'yes (2011-02-26~)')
ev('600750', '2010-03-09', '57667660', 'error_correction (tax-policy driven)', '2008-12-31 / FY2008',
   'FY2008 NP +15.0% (130,618,543.92→150,182,278.05); 2009-01-01 retained earnings +19.56m (≈+2.1% equity)',
   'restated (vendor notice of FY2008 row = 2010-03-09)', 'register_originals', OPT + ' (window 2009-04-30→2010-03-09 ends before universe entry 2010-04-30)',
   '公告 p1-p2 两张影响表', '', 'no (universe 2010-04-30~)')
ev('600862', '2018-06-16', '1205064513', 'error_correction', '2017-12-31 / FY2017; 2018-03-31',
   'FY2017 NP +0.93% (82,796,585.23→83,567,613.61); 2018Q1 NP +0.86%; equity +0.02%', 'restated', 'no_action', 'none (<1%)',
   '公告 p2-p28 更正前后对照（p8 利润表、p26-28 一季报）', '', 'no (universe 2020-04-30~)')
ev('603156', '2024-09-10', '1221174535', 'error_correction', '2024-03-31 (balance/ROE)',
   'equity -2.49% (11,902,448,295.06→11,606,453,550.57); ROE 7.65→7.75; NP/revenue/EPS 0',
   'restated (bps/ROE)', 'register_originals',
   'register 603156 2024-03-31 original (drafted, superseded_at 2024-09-10). Scanner gap: same-day "2024年第一季度报告（更正版）" not matched by UPDATED regex (更正版 missing) — add 更正版',
   '更正公告 p1-p3；原一季报 1219766062 p2、p7；更正版 1221174537 p2', '', 'yes (2019-04-30~)')
for d, m, p, pct in [
        ('2019-10-31', '1207048944', '2018-09-30 (income), 2018-12-31 (balance)', '2018Q3 revenue +116% (3,113,432,496.93→6,721,920,196.65); NP +0.63%; EPS 0.54→0.29'),
        ('2020-04-10', '1207475041', '2018-12-31 / FY2018', 'FY2018 revenue +145% (3,963,509,424.61→9,701,902,368.56); EPS 0.32→0.29'),
        ('2020-04-24', '1207582838', '2019-03-31 (income)', '2019Q1 revenue +266%; NP -3.2% (51,068,927.42→49,454,973.86)'),
        ('2020-08-21', '1208213612', '2019-06-30 (income)', '2019H1 revenue +268%; NP +199.8% (25,284,421.14→75,801,380.95); EPS 0.06→0.15')]:
    ev('603501', d, m, 'same_control_merger', p, pct, 'restated', 'entity_reset_check',
       'Review against §6.5.2.4 (strong candidate): 2019 发行股份购买北京豪威 85.53% 等（韦尔→豪威，分销商→CIS 设计）; candidate reset_report_date 2019-12-31 (restated FY2018 already combined). Code enters universe 2022-04-30. Originals ' + OPT,
       '公告 p2-p6 调整表（调整前/调整后/影响数）；面板各期=调整后', '', 'no (universe 2022-04-30~)')

# ============================ scope (b): other panel codes ============================
ev('000001', '2011-08-18', '59833409', 'policy_change', '2010-12-31 (+2010H1 comparatives)',
   '2010-12-31 equity -0.94%; FY2010 NP -0.59% (6,283.8m→6,246.5m); (2009 equity -1.29%, NP -0.84% in multi-year tables)',
   'restated', 'no_action', 'none (<1%)', '公告 p2 影响表（千元）', '投资性房地产公允价值模式→成本模式（与平安集团统一）', 'yes (2008-04-30~)')
ev('000661', '2009-03-17', '50225615', 'error_correction', '2007-12-31 / FY2007', 'FY2007 NP +1.02m (+15.6% of restated 7.52m); reclass surplus↔retained', 'not_checked', 'no_action',
   'none: window ended before 2009-11-01 and code enters universe 2016-04-30', '公告 p1', '', 'no')
ev('000661', '2015-03-13', '1200695367', 'policy_change+consolidation scope', '2013-12-31 / FY2013', 'not quantified (reclassification; consolidation of an entity with opening adjustment)', 'not_checked', 'no_action',
   'none: outside universe window (code enters 2016-04-30); magnitude not quantified (low priority)', '董事会说明 p1-p2', '', 'no')
ev('000733', '2011-04-09', '59242386', 'error_correction+policy_change', '2009-12-31 / FY2009', 'not quantified (tax, equity→cost method at subsidiaries)', 'not_checked', 'no_action',
   'none: outside universe window (2022-04-30~2025-04-30); not quantified (low priority)', '公告 p1-p2', '', 'no')
ev('000733', '2015-04-25', '1200910231', 'same_control_merger+policy_change', '2013-12-31 / FY2013', 'not quantified', 'not_checked', 'no_action',
   'none: outside universe window; not quantified (low priority)', '公告 p1-p3', '', 'no')
ev('000778', '2010-03-23', '57717451', 'policy_change', '2008-12-31 / FY2008', 'FY2008 parent NP +6.70m (safety-fund policy)', 'not_checked', 'no_action',
   'none: universe 2004-04-30~2009-04-30 does not overlap the backtest period (≥2009-11-01)', '说明 p1', '', 'no')
ev('000778', '2015-04-21', '1200876819', 'policy_change+same_control_merger', '2013-12-31 / FY2013', 'policy: no NP/equity effect; merger (新兴际华河北资源) not quantified', 'not_checked', 'no_action',
   'none: outside universe window; not quantified (low priority)', '董事会声明 p1-p3', '', 'no')
ev('000778', '2019-04-02', '1205983330', 'same_control_merger', '2017-12-31 / FY2017', 'FY2017 NP -0.27% (109,303→109,012 万元); equity +0.42%; revenue +0.25%', 'restated', 'no_action', 'none (<1%)', '公告 p2-p3（万元）', '收购新兴工程', 'no')
ev('002049', '2025-04-23', '1223222879', 'same_control_merger+policy_change', '2023-12-31 / FY2023', 'revenue +0.14%; EPS 2.9915→2.9936 (+0.07%)', 'restated', 'no_action', 'none (<1%)',
   '公告 p5-p7 调整表', '紫光安芯/紫光芯能 35% 股权', 'yes (2020-04-30~2025-04-30)')
ev('002158', '2018-04-13', '1204620991', 'same_control_merger', '2016-12-31 / FY2016',
   'FY2016 NP +24.4% (166,452,855.41→207,001,861.60); revenue +27.9%; parent equity +7.8% (1,948,497,579.36→2,099,758,415.56)',
   'restated', 'register_originals', OPT + '; reset not indicated (same business, Taiwan sister company)', '公告 p3 调整表', '收购台湾新汉钟', 'no (universe 2024-04-30~)')
ev('002683', '2025-03-28', '1222924520', 'same_control_merger', '2023-12-31 / FY2023', 'revenue +0.57% (11,542,604,057.43→11,607,964,045.71); NP +0.00008%; equity +0.00003%', 'restated', 'no_action',
   'none (<1%); entity reset for the 2025 雪峰科技 consolidation already registered (reset 2025-12-31)', '公告 p3-p5 调整表', '军工集团 40%→55%', 'yes (2024-04-30~2026-09-07)')
ev('300034', '2011-03-17', '59131155', 'error_correction', '2008-12-31, 2009-12-31', 'FY2008 NP +5.5% (31,284,342.24→32,992,432.89); FY2009 NP reduced by the same refund (not quantified here)',
   'original (FY2008 panel NP 31,284,342.24 = pre-correction); FY2009 not checked', 'no_action', 'none: outside universe window (2024-04-30~)', '公告 p1-p2', '', 'no')
SJ = '上海家化；600315 在宇宙内 2013-04-30~2019-03-13'
ev('600315', '2014-03-13', '63669287', 'error_correction', '2012-12-31 / FY2012 (and 2011 in the 3-year table)',
   'FY2012 NP +1.11% (614,632,224.94→621,435,187.18); revenue -11.2% (4,504,122,570.41→3,998,901,455.25); equity -1.98% (2,710,056,138.53→2,656,356,594.86); ROE 27.77→28.82',
   'mixed (NP/revenue/EPS = 2014-03-13 version; bps/ROE = 2015-03-19 CAS restatement 2,240,363,094.86)', 'register_originals',
   'register 600315 2012-12-31 original (sa 2014-03-13) + 2014-03-13 version (sa 2015-03-19) — both drafted; statement side: delay FY2012 three statements to 2015-03-19',
   '更正公告 p1-p3；2013 年报 63669295 p7（调整前/调整后）；原值 2012 年报 62215586 p7、p9', SJ, 'yes (2013-04-30~2019-03-13)')
ev('600315', '2014-04-29', '63941113', 'error_correction', '2013-03-31 (income)',
   '2013Q1 NP +13.75% (124,076,628.94→141,131,049.72); revenue -11.46% (1,325,026,458.93→1,173,213,186.78)',
   'restated (NP/revenue/EPS/ROE; bps original)', 'register_originals', 'register 600315 2013-03-31 original (drafted, superseded_at 2014-04-29)',
   '公告 p4-p5 表 6/表 7；原值 2013 一季报 62428877 p4、p11', SJ, 'yes (2013-04-30~2019-03-13)')
ev('600315', '2014-10-31', '1200356467', 'error_correction', '2013-09-30 (income)',
   '2013Q3 revenue -10.81% (4,012,363,480.39→3,578,791,178.38); NP 0', 'restated (revenue/GM)', 'register_originals',
   'optional (revenue-only ≥5%): register 600315 2013-09-30 original (drafted). Related: paired 2014-08-28 correction restated 2013-06-30 revenue -11.73% but was paired to 2014-06-30 → 2013-06-30 row also drafted',
   '公告 p2 表 2；原值 2013 三季报 63219326 p4、p12', SJ, 'yes (2013-04-30~2019-03-13)')
ev('600315', '2018-03-21', '1204495659', 'same_control_merger', '2016-12-31 / FY2016',
   'FY2016 NP -6.96% (216,016,693.93→200,980,658.86); revenue +12.05%; EPS 0.32→0.30; equity -0.05%',
   'restated', 'register_originals', 'register 600315 2016-12-31 original (drafted, superseded_at 2018-03-21); statement side: delay FY2016 three statements to 2018-03-21. Reset not indicated (cash purchase of Mayborn; equity unchanged)',
   '公告 p2-p3 调整表；原值 2016 年报 1203183101 p8、p22、p59', SJ + '；收购 Cayman A2（Mayborn/汤美星）', 'yes (2013-04-30~2019-03-13)')
ev('600315', '2018-04-27', '1204799994', 'same_control_merger', '2017-03-31 (income)',
   '2017Q1 NP +2.39% (108,279,600.36→110,862,730.52); revenue +25.8%; EPS 0.16→0.17', 'restated (NP/revenue/EPS/ROE/ocfps/GM; bps original)', 'register_originals',
   'register 600315 2017-03-31 original (drafted, superseded_at 2018-04-27)', '公告 p1-p2；原值 2017 一季报 1203402770 p3、p13', SJ, 'yes (2013-04-30~2019-03-13)')
ev('600315', '2018-08-22', '1205312576', 'same_control_merger', '2017-06-30 (income)',
   '2017H1 NP +3.99% (216,242,281.83→224,873,588.27); revenue +26.5%; EPS 0.32→0.34', 'restated', 'register_originals',
   'register 600315 2017-06-30 original (drafted, superseded_at 2018-08-22)', '公告 p1-p2；原值 2017 半年报 1203805659 p5、p32', SJ, 'yes (2013-04-30~2019-03-13)')
ev('600315', '2018-10-30', '1205552406', 'same_control_merger', '2017-09-30 (income)',
   '2017Q3 NP +8.85% (302,156,268.19→328,889,873.24); revenue +27.1%; EPS 0.45→0.49', 'restated', 'register_originals',
   'register 600315 2017-09-30 original (drafted, superseded_at 2018-10-30)', '公告 p1-p2；原值 2017 三季报 1204080984 p3-p4、p14', SJ, 'yes (2013-04-30~2019-03-13)')
ev('600717', '2020-03-25', '1207399102', 'error_correction', '2016-12-31, 2017-12-31, 2018-12-31',
   'FY2016 NP -0.36% (1,263,686,720.41→1,259,086,720.41); FY2017 NP -2.14% (823,876,471.76→806,226,471.76); FY2018 not read', 'restated (FY2016/FY2017)', 'register_originals',
   OPT + ' (universe 2004-04-30~2006-04-30)', '公告 p2-p3 调整表', '焦炭码头财务人员贪污 1.539 亿', 'no')
ev('600763', '2017-04-01', '1203247301', 'error_correction (acquisition re-accounted as same-control)', '2015-12-31 / FY2015',
   'FY2015 NP -35.2% (192,481,831.87→124,713,638.92); parent equity -17.1% (822,084,716.75→681,788,723.35)', 'restated', 'register_originals',
   OPT + ' (universe 2019-04-30~2023-04-30)', '公告 p3 合并资产负债表/利润表影响表（审核报告等为扫描件）', '通策健康 60% 收购改按同一控制', 'no')
ev('600897', '2026-08-27', '1225511709', 'same_control_merger', '2025-06-30 (income); 2025-12-31 (balance)',
   '2025H1 NP +10.8% (252,968,296.53→280,260,135.05); revenue +31.0%; EPS 0.61→0.67', 'restated (archived originals exist)', 'no_action',
   'none: panel archive superseded/2025-06-30.csv holds the original (superseded_at 2026-08-31); statements balance 2025-12-31 archived (superseded_at 2026-08-27); also outside universe window (ended 2023-04-28)',
   '公告 p4-p6 调整表', '收购兆翔科技', 'no')
ev('600988', '2019-04-16', '1206022239', 'error_correction', '2016-12-31, 2017-12-31 (balances)',
   'equity -2.18% (2016: 2,473,404,633.60→2,419,408,833.60), -1.96% (2017: 2,753,344,482.00→2,699,348,682.00); FY2017 NP 0', 'not_checked', 'register_originals',
   OPT + ' (universe 2024-04-30~)', '公告 p2-p3 调整表', '五龙黄金探矿权减值', 'no')
ev('600988', '2020-04-30', '1207694451', 'same_control_merger', '2018-12-31 / FY2018',
   'FY2018 NP -133,047,305.33→-51,231,271.94; revenue +9.8%; parent equity +8.07% (2,519,663,583.49→2,722,960,407.22)', 'restated', 'register_originals',
   OPT + ' (universe 2024-04-30~); reset not indicated', '公告 p3-p5 调整表', '发行股份购买瀚丰矿业', 'no')
ev('601958', '2010-04-27', '57876681', 'policy_change+error_correction', '2008-12-31 / FY2008 (and FY2007)',
   'FY2008 NP -73.4m by policy (≈-2.6%) plus error corrections; FY2007 NP -130.2m; 2008-12-31 equity ≈-154m (≈-1.1%)', 'restated (vendor notice of FY2008 row = 2010-04-27)', 'register_originals',
   OPT + ' (universe 2025-04-30~)', '公告 p1-p2', '安全基金/维简费（解释第3号）', 'no')

rows = [r for r in csv.DictReader(open(R + '/data/interim/restatement_announcements.csv', encoding='utf-8')) if r['paired'] == '0']
missing = set()
out = []
for r in rows:
    k = (r['security_code'], r['announcement_date'])
    e = E.get(k)
    if e is None:
        missing.add(k)
        continue
    docid = r['url'].rsplit('/', 1)[-1].split('.')[0]
    companion = '' if docid == e['main'] else f'companion document (main: {e["main"]}); '
    code = r['security_code']
    scope = 'a' if (code in HOLD or code in POOL) else 'b'
    out.append(dict(code=code, name=r['security_name'], announcement_date=r['announcement_date'], url=r['url'],
                    nature=e['nature'], restated_periods=e['restated_periods'], fields_changed_pct=e['fields_changed_pct'],
                    panel_state=e['panel_state'], classification=e['classification'], proposed_action=e['proposed_action'],
                    evidence=companion + e['evidence'], notes=e['notes'], scope=scope,
                    in_universe_window=e['overlap'], universe_windows=uni(code), title=r['title']))
assert not missing, missing
F = ['code', 'name', 'announcement_date', 'url', 'nature', 'restated_periods', 'fields_changed_pct', 'panel_state', 'classification',
     'proposed_action', 'evidence', 'notes', 'scope', 'in_universe_window', 'universe_windows', 'title']
with open(OUT + '/oi214_review.csv', 'w', newline='', encoding='utf-8') as fh:
    w = csv.DictWriter(fh, fieldnames=F)
    w.writeheader()
    w.writerows(sorted(out, key=lambda x: (x['scope'], x['code'], x['announcement_date'], x['url'])))
from collections import Counter
print(len(out), Counter((x['scope']) for x in out))
print(Counter((x['scope'], x['classification']) for x in out))
evs = {(x['code'], x['announcement_date']): (x['scope'], x['classification']) for x in out}
print('events', len(evs), Counter(evs.values()))
