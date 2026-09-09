# 输入来源与复现

- 指数：乐咕乐股[沪深300估值](https://legulegu.com/stockdata/hs300-ttm-lyr)，公开接口`index-basic-pe`，取`addTtmPe`整体滚动PE，不能替换为`ttmPe`等权滚动PE。字段对应参照[AKShare官方实现](https://github.com/akfamily/akshare/blob/master/akshare/stock_feature/stock_a_pe_and_pb.py)。已保存258条观测，2005-04-29至2026-09-09，历史为月末，最后一条为取数日。
- 利率：仓库既有`fetch_cost_of_equity_inputs.fetch_treasury_yields`，东财`RPTA_WEB_TREASURYYIELD`的`EMM00166466`中国10年国债收益率，原百分数除100；抓取时使用中国/美国长短端利差恒等式验证字段。已保存6167条观测，2002-01-04至2026-09-09。[中债国债收益率曲线](https://yield.chinabond.com.cn/cbweb-cbrc-web/cbrc/showCbrc)可作口径参考，本轮实际输入来自东财，未声称逐条与中债重新核对。
- 股债信号：在每个指数估值观测日，向后查找最近的已知债息；不从未来插值。`data/reference/equity_bond_csi300.csv`保存原始估值、原始债息及两者日期、来源。利差和历史分位在加载时计算，CSV不保存可被误用的全样本分位。
- 可得性边界：当前下载的历史序列缺少逐期发布档案，不能独立证明供应商从未重述历史或改变计算方式。月度来源也不等于逐日估值择时。本轮严格遵循观测日延迟执行，但只作探索性历史诊断。

```bash
# 仅从已保存原始观测重建，不联网
python3 scripts/fetch_equity_bond_inputs.py
# 需要更新研究输入时才重新抓取；会改变源哈希
python3 scripts/fetch_equity_bond_inputs.py --refresh
# 两阶段分别读取对应预登记；完整基准与子集等价由prepare核查
sbatch --account=tes21035 scripts/slurm/equity_bond_scan_20260909.sbatch
sbatch --account=tes21035 scripts/slurm/equity_bond_high_base_20260909.sbatch
python3 data/experiments/exp_equity_bond_20260909/report.py
python3 data/experiments/exp_equity_bond_20260909/report_high_base.py
```

个股价格、公司行动、时点名单、估值、费税、融资利息与原BASE一致。保留OI-167的单股整手上限行为和OI-169的已有收益记账口径；总仓位守卫用成交日收盘净资产独立核验。补充实验的高性价比状态完整恢复BASE，`daily cap`为空表示该日不施加覆盖，信号有效性仍由观测和历史样本数验证。
