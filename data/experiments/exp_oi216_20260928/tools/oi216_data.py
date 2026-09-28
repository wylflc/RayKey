"""OI-216 primary-source amounts (read from filings in ../filings). Units noted per block."""

HKEX = "https://www1.hkexnews.hk"

# ---------------------------------------------------------------- 00316 OOIL (US$'000)
# Interest income inside "Other operating income" (inside Operating profit); annual: note 7 "Other operating income";
# interim: note 7 "Operating profit" (credited items).
OOIL_SRC = {
    "AR2025": (HKEX + "/listedco/listconews/sehk/2026/0422/2026042200995.pdf", "PDF p.142 note 7; P&L PDF p.110"),
    "AR2024": (HKEX + "/listedco/listconews/sehk/2025/0416/2025041601677.pdf", "PDF p.138 note 7"),
    "AR2023": (HKEX + "/listedco/listconews/sehk/2024/0424/2024042400748.pdf", "PDF p.140 note 7"),
    "AR2022": (HKEX + "/listedco/listconews/sehk/2023/0425/2023042501320.pdf", "PDF p.142 note 7"),
    "AR2021": (HKEX + "/listedco/listconews/sehk/2022/0427/2022042701223.pdf", "PDF p.145 note 7"),
    "AR2020": (HKEX + "/listedco/listconews/sehk/2021/0428/2021042800579.pdf", "PDF p.145 note 7"),
    "IR2026": (HKEX + "/listedco/listconews/sehk/2026/0923/2026092300558.pdf", "PDF p.31 note 7; P&L PDF p.18"),
    "IA2026": (HKEX + "/listedco/listconews/sehk/2026/0827/2026082701643.pdf", "2026 Interim Results announcement PDF p.15 note 7 (1H26 and 1H25 columns; same figures in Interim Report 2026 PDF p.31)"),
    "IR2025": (HKEX + "/listedco/listconews/sehk/2025/0917/2025091700508.pdf", "PDF p.31 note 7"),
}
# period: (src, revenue, other_operating_income_total, operating_profit, int_banks, int_fellow_sub, int_amortised_cost,
#          int_fvtpl_portfolio, portfolio_distribution, portfolio_dividend, fvoci_dividend)
OOIL = {
    "2019-12-31": ("AR2020", 6878740, 83679, 361281, 51064, 0, 9683, 11487, 1084, 661, 7903),
    "2020-12-31": ("AR2020", 8191304, 78853, 992187, 44384, 91, 7775, 4100, 482, 315, 7971),
    "2021-12-31": ("AR2021", 16832185, 50977, 7380271, 31497, 354, 5031, 2227, 602, 224, 6812),
    "2022-12-31": ("AR2022", 19820188, 252044, 10079101, 240251, 1546, 4347, 1175, 348, 221, 133),
    "2023-12-31": ("AR2023", 8343857, 499962, 1405676, 491491, 1817, 2935, 0, 280, 752, 55),
    "2024-12-31": ("AR2024", 10701943, 397221, 2624844, 387453, 2250, 2686, 0, 18, 1058, 59),
    "2025-12-31": ("AR2025", 9722494, 322277, 1535466, 315603, 2305, 2606, 0, 11, 244, 2),
    "2025-06-30": ("IA2026", 4876265, 179250, 977994, 175712, 1144, 1343, 0, 5, 90, None),
    "2026-06-30": ("IA2026", 5173277, 124709, 720261, 120262, 1077, 1053, 0, 12, 66, None),
}

# ---------------------------------------------------------------- 06862 Haidilao (RMB'000)
# "Other income" note (annual note 6, interim note 4); interest income split by source.
HDL_SRC = {
    "AR2025": (HKEX + "/listedco/listconews/sehk/2026/0424/2026042401134.pdf", "PDF p.205 note 6; P&L PDF p.152"),
    "AR2024": (HKEX + "/listedco/listconews/sehk/2025/0424/2025042400828.pdf", "PDF p.193 note 6"),
    "AR2023": (HKEX + "/listedco/listconews/sehk/2024/0425/2024042501638.pdf", "PDF p.329 note 6"),
    "AR2022": (HKEX + "/listedco/listconews/sehk/2023/0426/2023042602019.pdf", "PDF p.306 note 6 (2022 column; 2021 column restated for continuing ops = F10 basis)"),
    "AR2021": (HKEX + "/listedco/listconews/sehk/2022/0426/2022042601195.pdf", "PDF p.286 note 6"),
    "AR2020": (HKEX + "/listedco/listconews/sehk/2021/0426/2021042601335.pdf", "PDF p.272 note 6"),
    "IR2026": (HKEX + "/listedco/listconews/sehk/2026/0922/2026092200356.pdf", "PDF p.63 note 4"),
    "IA2026": (HKEX + "/listedco/listconews/sehk/2026/0825/2026082501119.pdf", "Interim results announcement PDF p.22 note 4 (1H26 and 1H25 columns; same in Interim Report 2026 PDF p.63)"),
    "IR2025": (HKEX + "/listedco/listconews/sehk/2025/0922/2025092200398.pdf", "PDF p.62 note 4"),
}
# period: (src, other_income_total, int_bank_deposits(+deposits placed in financial institution), int_other_fin_assets,
#          int_fvtoci_fvtpl, int_rental_deposits)
HDL = {
    "2019-12-31": ("AR2020", 262701, 81341 + 55960, 1, 0, 6074),
    "2020-12-31": ("AR2020", 360867, 12590 + 18528, 66, 0, 10105),
    "2021-12-31": ("AR2022", 357794, 12630, 0, 2106, 13047),
    "2022-12-31": ("AR2022", 496040, 99873, 620, 42, 15146),
    "2023-12-31": ("AR2023", 940781, 264794, 52411, 439, 9245),
    "2024-12-31": ("AR2024", 635651, 275632, 98275, 0, 9019),
    "2025-12-31": ("AR2025", 580505, 151272, 108698, 0, 10713),
    "2025-06-30": ("IA2026", 290252, 79800, 55716, 0, 4865),
    "2026-06-30": ("IA2026", 259794, 49183, 51687, 0, 4302),
}

# ---------------------------------------------------------------- 09618 JD (RMB million)
JD_SRC = {
    "AR2025": (HKEX + "/listedco/listconews/sehk/2026/0416/2026041601496.pdf",
               "P&L PDF p.265; BS PDF p.263; note 6 PDF p.313; note 18 Others,net PDF p.327"),
    "AR2024": (HKEX + "/listedco/listconews/sehk/2025/0417/2025041701385.pdf", "5-yr summary; BS PDF p.266; note 18 PDF p.334; note 6"),
    "AR2023": (HKEX + "/listedco/listconews/sehk/2024/0418/2024041801564.pdf", "BS PDF p.264; Others,net PDF p.336; note 8"),
    "AR2022": (HKEX + "/listedco/listconews/sehk/2023/0420/2023042001939.pdf", "BS PDF p.280; Others,net PDF p.353; note 8"),
    "AR2021": (HKEX + "/listedco/listconews/sehk/2022/0428/2022042803935.pdf", "5-yr summary (2017-2021 equity-method share); BS; Others,net PDF p.336; note 8 equity method 2021"),
    "AR2020": (HKEX + "/listedco/listconews/sehk/2021/0418/2021041800019.pdf", "5-yr summary (2016-2020 equity-method share); P&L; BS; note 8 equity method 2019/2020"),
    "IA2026": (HKEX + "/listedco/listconews/sehk/2026/0813/2026081300917.pdf", "segment/P&L table PDF p.9; BS; IFRS recon"),
    "IA2025": (HKEX + "/listedco/listconews/sehk/2025/0814/2025081400830.pdf", "P&L table"),
}
# period: (src, share_of_results_of_equity_investees, interest_income_in_others_net, others_net_total)
JD_EM = {
    "2016-12-31": ("AR2020", -2782, None, None),
    "2017-12-31": ("AR2021", -1927, None, None),
    "2018-12-31": ("AR2021", -1113, None, None),
    "2019-12-31": ("AR2021", -1738, 1786, 7161),
    "2020-12-31": ("AR2020", 4291, 2753, 35310),
    "2021-12-31": ("AR2021", -4918, 4213, -590),
    "2022-12-31": ("AR2022", -2195, 5742, -1555),
    "2023-12-31": ("AR2023", 1010, 9576, 7496),
    "2024-12-31": ("AR2024", 2327, 9353, 13371),
    "2025-12-31": ("AR2025", 8025, 9056, 17327),
    "2025-06-30": ("IA2026", 3402, None, 8208),
    "2026-06-30": ("IA2026", 4187, None, 6602),
}
# Balance sheet: (src, investments_in_equity_investees_total, of_which_equity_method,
#                 marketable_securities_and_other_investments (2019-2021: 'Investment securities'))
JD_BS = {
    "2019-12-31": ("AR2020", 35576, 15479, 21417),
    "2020-12-31": ("AR2020", 58501, 30165, 39085),
    "2021-12-31": ("AR2021", 63222, 36254, 19088),
    "2022-12-31": ("AR2023", 57641, 28952, 14360),   # AR2022 original presentation: 'Investment securities' 11,611
    "2023-12-31": ("AR2023", 56746, 30460, 80840),
    "2024-12-31": ("AR2024", 56850, 34294, 59370),
    "2025-12-31": ("AR2025", 51978, 31680, 51840),
    "2026-06-30": ("IA2026", 58040, None, 38395),    # equity-method split not disclosed in the interim announcement
}
# JD 2023 fields missing in HK F10 (AR2024 comparative column)
JD_2023_FILL = dict(cash=71892, restricted=7506, st_invest=118254, parent_equity=231858, nci=63908, total_equity=295766,
                    mezzanine=614, st_debt=5034, unsecured_notes=10411, lt_borrowings=31555, op_lease_c=7755, op_lease_nc=13676)

# ---------------------------------------------------------------- TSM (NT$ thousand)
TSM_SRC = {
    "FS2025": ("https://www.sec.gov/Archives/edgar/data/1046179/000104617926000024/a2025q4consolidatedreport-.htm",
               "6-K filed 2026-02-26, FY2025 audited consolidated balance sheet"),
    "20F2025": ("https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/R3.htm",
                "20-F FY2025 filed 2026-04-16, R3 statement of financial position / R4 P&L"),
    "FS2Q26": ("https://www.sec.gov/Archives/edgar/data/1046179/000104617926000541/a2026q2consolidatedreport-.htm",
               "6-K filed 2026-08-14, 2Q26 reviewed consolidated balance sheet p.3 / P&L p.4"),
}
TSM_NCFA = {  # FVTPL nc, FVTOCI nc, amortized cost nc, equity-method investments (stay in IC)
    "2024-12-31": ("20F2025", 15199800, 7822900, 88596500, 37247800),
    "2025-06-30": ("FS2Q26", 13831497, 7605736, 81827491, 34162043),
    "2025-12-31": ("FS2Q26", 15032128, 8797170, 110507804, 38033271),
    "2026-06-30": ("FS2Q26", 15780286, 88151593, 105877457, 18126371),
}
TSM_EM = {"2025-12-31": ("20F2025", 5488500), "2025-06-30": ("FS2Q26", 2589255), "2026-06-30": ("FS2Q26", 3123375)}

# ---------------------------------------------------------------- SEC filers (US$ million)
SEC_SRC = {
    "NVDA_10K_FY26": "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/R5.htm",
    "NVDA_10Q_Q2FY27": "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/R4.htm",
    "NVDA_10Q_Q2FY27_R43": "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/R43.htm",
    "NVDA_10K_FY25_R57": "https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/R57.htm",
    "UBER_10K_FY25_R52": "https://www.sec.gov/Archives/edgar/data/1543151/000154315126000015/R52.htm",
    "UBER_10K_FY24_R51": "https://www.sec.gov/Archives/edgar/data/1543151/000154315125000008/R51.htm",
    "UBER_10K_FY23_R50": "https://www.sec.gov/Archives/edgar/data/1543151/000154315124000012/R50.htm",
    "UBER_10K_FY21_R55": "https://www.sec.gov/Archives/edgar/data/1543151/000154315122000008/R55.htm",
    "UBER_10Q_Q2_26_R2": "https://www.sec.gov/Archives/edgar/data/1543151/000154315126000032/R2.htm",
    "UBER_10Q_Q2_26_R39": "https://www.sec.gov/Archives/edgar/data/1543151/000154315126000032/R39.htm",
    "META_10K_FY25_R54": "https://www.sec.gov/Archives/edgar/data/1326801/000162828026003942/R54.htm",
    "META_10K_FY25_R50": "https://www.sec.gov/Archives/edgar/data/1326801/000162828026003942/R50.htm",
    "META_10Q_Q2_26_R41": "https://www.sec.gov/Archives/edgar/data/1326801/000162828026050705/R41.htm",
    "META_10Q_Q2_26_R8": "https://www.sec.gov/Archives/edgar/data/1326801/000162828026050705/R8.htm",
}
# NVDA current marketable equity securities (us-gaap:EquitySecuritiesFvNi, presented inside current 'Marketable securities')
NVDA_EQ_CURRENT = {"2026-01-25": 12886, "2026-07-26": 42783}
NVDA_EQUITY_METHOD_IN_NONMKT = {"2026-07-26": 3259}   # 51,157 face - 47,898 measurement alternative (R43: ~$3.3bn equity method)
# UBER face 'Investments' (uber:MarketableAndNonMarketableInvestments, non-current, excludes equity-method line)
UBER_INV = {  # total, didi, grab, aurora, other_mkt_equity, other_nonmkt_equity, note_receivable_rp, grab_nonmkt_debt
    "2020-12-31": (9052, 6299, 0, 0, 0, 329, 83, 2341),
    "2021-12-31": (11806, 2838, 3821, 3388, 1312, 315, 132, 0),
    "2022-12-31": (4401, 1802, 1726, 364, 87, 312, 110, 0),
    "2023-12-31": (6101, 2245, 1806, 1425, 170, 329, 126, 0),
    "2024-12-31": (8460, 2602, 2529, 2054, 523, 608, 144, 0),
    "2025-12-31": (9178, 3011, 2674, 1252, 667, 1455, 119, 0),
    "2026-06-30": (8759, 1900, 2020, 1763, 813, 2263, 0, 0),
}
UBER_EQUITY_METHOD = {"2020-12-31": 1079, "2021-12-31": 800, "2022-12-31": 870, "2023-12-31": 353, "2024-12-31": 302,
                      "2025-12-31": 287, "2026-06-30": 3773}
META_NONMKT = {"2024-12-31": (6070, 6018, 52), "2025-12-31": (27524, 20076, 7448), "2026-06-30": (30157, 20751, 9406)}
META_RESTRICTED = {"2025-12-31": 3227, "2026-06-30": 13809}
