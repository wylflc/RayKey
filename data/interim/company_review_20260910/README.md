# 紫光股份与中伟新材点名复核

> 2026-09-10后续更正：本页及CSV保留初次研究快照。紫光11.21—13.70元估值带因少数股权请求权重叠与历史份额失真已撤销，当前为无法估值；中伟结果不变。统一修复与新模型见[OI-175报告](../../../docs/reports/oi175_minority_claims_2026-09-10.md)，不得将下文紫光历史值当作当前合理价。

研究截止：2026-09-10，北京时间。执行规范：工作流程 v4.178。两家公司均维持 `boundary_pending`；本批为池外研究与建档，不产生交易信号。

本批补取两家公司历史三大报表，纠正原来因缺表而使用权益退路的档案估值。`statements/` 保留本批下载输入，`roic_bands.csv` 保留两家公司逐期模型结果；全量缓存中仅合入本批两家公司的新增报表和模型行，未重建回测状态。`annual_metrics.csv` 的 ROIC 由仓库 `roic_inputs.roic_of` 计算，并非公司披露指标。

公开来源：

- 紫光[2026H1报告](https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12565854&stockid=000938)，2026-08-29披露；[2025审计报告](https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12088791&stockid=000938)，2026-04-15披露。
- 中伟[2026H1报告](https://disc.static.szse.cn/disc/disk03/finalpage/2026-08-25/53856f2b-83a4-477b-913d-79194ee16cf7.PDF)，2026-08-25披露；[2025年报](https://static.cninfo.com.cn/finalpage/2026-03-31/1225054811.PDF)，2026-03-31披露；[8月26日交流记录](https://static.cninfo.com.cn/finalpage/2026-08-26/1225514526.PDF)。
- 同业与客户：[锐捷2026H1报告](https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12494616&stockid=301165)、[华友2026H1报告](https://static.cninfo.com.cn/finalpage/2026-08-19/1225480594.PDF)、[当升2026H1报告](https://disc.static.szse.cn/disc/disk03/finalpage/2026-08-26/b6a449ac-cada-48d5-b554-3485ce86a956.PDF)。

取数首次因沙箱 DNS 限制失败，放行公开数据只读联网后成功：balance 39行、income 39行、cashflow 36行，均覆盖2025财年、每家公司三表不少于3个财年。原始下载时间见各行 `retrieved_at_utc`。取数接口仅作结构化输入；2025利润、经营现金流、资本开支及期末资产负债与上述原始公告核对。

复现命令（仓库根目录执行；`--signal-date 2026-09-09` 对应脚本证据截止2026-09-10，并非本批发出9月9日交易信号）：

```bash
python3 scripts/fetch_a_share_financial_statements.py --codes 000938 300919 --signal-date 2026-09-09 --out-dir /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey/data/interim/company_review_20260910/statements --timeout 15 --pause 0
python3 scripts/build_historical_valuation_bands.py --codes 000938,300919 --value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2002-01-01 --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 --roic-trail-weight 0 --minority-basis earnings --wc-aggregation operating --statements-dir /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey/data/interim/company_review_20260910/statements --out-bands /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey/data/interim/company_review_20260910/roic_bands.csv --out-daily /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey/data/interim/company_review_20260910/roic_daily.csv
```

`--uniform-tier L2` 仅为工作流程统一模型参数，不能据此给这两家公司标注L2。两家公司均未评分、无P/V、不进候选或持仓生产带。此次未运行全市场六份输入刷新、B2、回测状态或每日执行链，不能将本次局部补档描述为完成全市场估值重建。日线缓存截至8月7日，本批派生逐日状态只作重现副产物，不能用于9月交易判断。

估值范围与误差：两只最新带均为2026H1的 `growth` 路径。紫光IV 12.4505元，中伟IV 27.9871元。紫光历史少数股东盈利占比42.33%与当前新华三少数股权12.02%差异很大，且二者分母不同；不可直接用12.02%替换合并利润占比。中伟的融资、A/H股及永续工具影响每股权益口径。敏感度范围见逐票研究卡；模型带为机械情景，非价格承诺。

本批另按 `codes.txt` 刷新两家公司的除权事件，并在刷新后重算；两个最新中值不变。财务面板定向检查8期发现2条可疑、0条严重，均为紫光2024Q3/FY的“净利/期末权益”高于加权ROE。2025年报第8页核对2024期末归母权益133.32亿元、2023年末339.46亿元，以及2024加权ROE5.80%；期末权益与年度加权分母因权益交易显著不同，不能按脚本建议BPS强行改数。2024Q3原始季报未在本批独立核验，保留该历史行提示；它不作为本批直接盈利锚，当前H1指标已核验。原始提示见 `panel_anomalies.csv`。本批没有消除模型中历史少数股东比例的滞后，研究卡显式保留该限制。

落地核验：两家公司模型、档案区间、名单、无分层/无候选与持仓带、阅读版登记均通过定向核对，文档审计0错误；其他公司的三类记录、档案与除权行语义不变。全档案 `--check` 另报181份未修改的旧阅读页有渲染漂移，不含本批两家，不能声称全库无漂移。详见 `validation.json`。紫光档案上下沿先保留两位小数后，阅读版均值显示12.46元；未舍入模型IV为12.4505元，该分位差不代表第二套模型。
