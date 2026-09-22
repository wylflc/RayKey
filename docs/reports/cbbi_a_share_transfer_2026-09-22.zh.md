# CBBI 计算核查与 A 股迁移研究（2026-09-22）

可以借鉴 CBBI 的多指标标准化、合成和展示方式，研究 A 股的市场温度；不宜原样移植九个指标，更不能把分数当作见顶概率。对本项目最有价值的问题是：价格偏离、交易拥挤和杠杆信息，能否在现有股债约束之上改善风险识别。这一判断是方法研究结论，尚无本轮 A 股回测支持。

核查对象为[用户指定网站](https://colintalkscrypto.com/cbbi/)、[官方 FAQ](https://colintalkscrypto.com/cbbi/faq.html)、官方仓库的九个指标模块、公共函数、取数及汇总程序，并以原作者和数据提供方资料核对基础指标定义。浏览到的[提交历史](https://github.com/Zaczero/CBBI/commits/main/)顶部为 2026-05-08 的 [efd6dcf08b9b8619c63b8669dee0990b4f076aac](https://github.com/Zaczero/CBBI/commit/efd6dcf08b9b8619c63b8669dee0990b4f076aac)。本文计算细节据本次读取的 `main` 文件；未验证服务器部署版本与该提交逐字一致。

**先区分基础指标与 CBBI 对它的再加工。** 网站列出的 NUPL、MVRV 等是原始指标，旁边的百分数已经过 CBBI 变换，不能直接当作原始 NUPL 或 MVRV 数值。其主要链路为：原始指标 → 必要的对数、平滑或时移 → 高低边界映射 → 每项截断至 0～1 → 等权平均。它没有在这些模块中训练一个“未来某段时间见顶”的概率分类器。

设第 i 项处理后的原始量为 z_i(t)，其上、下边界为 U_i(t)、L_i(t)，多数指标的未截断分数为：

\[
q_i(t)=\frac{z_i(t)-L_i(t)}{U_i(t)-L_i(t)}.
\]

上下边界通常是在挑选的历史价格高点、低点所对应的指标值上，分别对时间做线性回归；不是全历史百分位，也不是所有指标统一除以一个固定阈值。Pi Cycle 的实现另有距离和分段处理，见下文。

当前公开汇总代码实际先逐项截断，再计算有效项均值：

\[
s_i(t)=\min(1,\max(0,q_i(t))),\qquad
CBBI(t)=100\frac{\sum_{i\in A_t}s_i(t)}{|A_t|}.
\]

A_t 是当天有非空有效分数的指标集合；九项齐备时各占 1/9。`main.py` 将 NaN 转成 null 后调用 `mean_horizontal`。因此 80 分代表多项指标总体处在各自较热的位置，不代表未来下跌概率为 80%。例如原始量 1.5、下界 0.5、上界 2.5，对应单项分数 50。依据：[汇总程序](https://raw.githubusercontent.com/Zaczero/CBBI/main/main.py)、[回归函数](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/_common.py)。

FAQ 对总分超界后截断的描述不能替代当前实现：源码明确逐项 `clip(0, 1)` 在前，平均在后。例如两项未截断分数为 1.4、0.2，逐项截断后平均为 0.6，而先平均是 0.8。本文以源码顺序为准。

**九项指标的基础含义与实际评分。** 以下 P 为 BTC 美元价格，MC 为市场市值，RC 为已实现市值。RC 以各 UTXO 最后移动时的价格计值，是链上成本代理；内部转账等也能引起移动，因此不能视为每个投资者的真实买入成本。

| 指标 | 基础计算及经济含义 | 当前 CBBI 的处理 |
| --- | --- | --- |
| Pi Cycle Top | 比较 MA111 与 2×MA350，衡量上涨加速和均线接近/交叉 | z = ln(MA111/(2×MA350))；按它自身的历史高低点建立目标线及分段冷端，加入交叉后距离下限，转成接近热端的分数 |
| RUPL / NUPL | (MC−RC)/MC，衡量链上净浮盈占市值的比例 | 对原值分别拟合高、低边界；低点样本去掉第一个；按上下界线性映射 |
| RHODL Ratio | 1 周币龄与 1～2 年币龄的已实现价值比，再乘市场年龄调整，描述短期资金相对长期持币者的活跃程度 | 取 ln(RHODL) 后拟合上下界；低点去掉第一个；高点集合额外加入 2024-12-18 |
| Puell Multiple | 当日新发行 BTC 的美元价值 / 其 365 日均值，衡量发行收入相对历史的高低；不是矿工扣成本后的利润率 | 取对数后做 3 日均值；高界拟合价格高点处的指标，低界固定 −1 |
| 2 Year Moving Average | 价格相对 730 日均线的偏离 | 对 ln(P/MA730) 的高点、低点拟合两条偏离边界，映射分数；并非直接套用常见的“2 年均线×5”热区 |
| Trolololo Trend Line | 用市场年龄构造长期对数增长通道，比较价格与通道的位置 | 固定时间函数外，再对价格高低点的超调/欠调拟合回归修正；第一个顶部残差乘 0.6 |
| MVRV Z-Score | (MC−RC)/σ(MC)，用市值标准差缩放市值与链上成本的偏离；区别于 MVRV 比值 MC/RC | 在减半距今天数小于上次价格低点距今天数的日期，取滞后 6 行的指标；再 ln(1+Z)；下界回归结果加 0.26 |
| Reserve Risk | P/HODL Bank，比较当前卖出诱因与长期不卖形成的累计机会成本 | 原指标滞后 1 行、前向填充、取对数；低点去掉第一个；上界回归结果减 0.15 |
| Woobull Top Cap vs CVDD | 价格位于长期顶部带与链上底部带之间的位置 | 先算 z = (lnP−lnCVDD)/(lnTop−lnCVDD)，再拟合 z 的高低界二次映射；低点去掉第一个，上界减 0.025 |

上表实现逐项来源：[Pi Cycle](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/pi_cycle.py)、[NUPL](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/rupl.py)、[RHODL](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/rhodl_ratio.py)、[Puell](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/puell_multiple.py)、[2YMA](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/two_year_moving_average.py)、[Trolololo](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/trolololo.py)、[MVRV](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/mvrv_z_score.py)、[Reserve Risk](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/reserve_risk.py)、[Woobull](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/woobull_topcap_cvdd.py)。

基础定义另核对 [Glassnode NUPL](https://docs.glassnode.com/further-information/metric-guides/unrealized-profit-loss/nupl-net-unrealized-profit-loss)、[Glassnode MVRV Z-Score](https://docs.glassnode.com/further-information/metric-guides/mvrv/mvrv-z-score) 与 [RHODL/Reserve Risk 接口定义](https://docs.glassnode.com/basic-api/endpoints/indicators)。这些说明用于确认指标含义，不代表 CBBI 使用 Glassnode API；当前源码的 NUPL、RHODL、MVRV、Reserve Risk 实际通过 [CoinAnk 接口](https://raw.githubusercontent.com/Zaczero/CBBI/main/api/coinsoto_api.py)取得，未独立重建其底层 UTXO 数据。

**几个容易被名称掩盖的计算细节。** Pi Cycle 当前版本的核心可写为：

\[
z_t=\ln\frac{MA_{111,t}}{2MA_{350,t}},\qquad
q_t=1-\frac{\max(U_t-z_t,0,D_t)}{|U_t-C_t|}.
\]

U_t 是 z 高点的回归值与 0 的较小者；少于三个高点时设为 0。C_t 是从首个有效点及各低点开始、分段保持的冷端值。D_t 在一次正向交叉区间的最大偏离之后维持距离下限，达到后续解除条件时清零。因此，不能把网站的 Pi Cycle 百分数解释为“两根均线交叉就给 100”的简单开关；这些分段极值也需要专门检查时点可得性。[Pi Cycle 源码](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/pi_cycle.py)

Trolololo 令 d 为距 2012-01-01 的自然日数，基础上下界在自然对数价格空间为：

\[
U_0=\ln(10)[2.900\ln(d+1400)-19.463],
\]
\[
L_0=\ln(10)[2.788\ln(d+1200)-19.463].
\]

随后分别对 lnP−U_0 的顶部残差、lnP−L_0 的底部残差做回归修正，得到最终上下界。这是针对 BTC 时间路径的经验拟合，不是可直接适用于任意股票指数的估值公式。[Trolololo 源码](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/trolololo.py)

Woobull 中 Top 的价格口径为 `35×历史累计平均市值/当期币供应量`；CVDD 为 `Σ(币天销毁量×当时价格)/(市场年龄天数×6,000,000)`。币天销毁量指被转移币数量乘其休眠天数。35 和 6,000,000 都是模型校准常数。CBBI 读取作者提供的两条序列，再进行上述二次标准化。[Top 定义](https://woocharts.com/bitcoin-price-models/)、[CVDD 原文](https://woobull.com/experiments-on-cumulative-destruction/)

Reserve Risk 的 HODL Bank 也不是简单的长期持币数量。Glassnode 展示的一种组件口径为：VOCDD = P×供给调整后的币天销毁量；取其 30 日移动中位数 MVOCDD；累计 P−MVOCDD 得到 HODL Bank，再以 P 除之。该组件解释不构成对 CoinAnk 具体数据口径的一致性验证。[组件定义](https://studio.glassnode.com/charts/btc-reserve-risk-components?a=BTC&mScl=log&pScl=log)

BTC 价格及发行值来自 Coin Metrics。Puell 用发行美元值计算，不包含交易费收入；730 日均线允许不足 730 个有效样本时提前形成值。价格表计算部分指标后，保留 2011-06-27 及以后的行，Pi Cycle 的 111/350 日均线在这个截取后的表上计算。自然日窗口不能原样等同于 A 股交易日窗口。[取数及预处理](https://raw.githubusercontent.com/Zaczero/CBBI/main/fetch_bitcoin_data.py)

**历史曲线的可回测性是最大限制。** `mark_highs_lows` 会从当前位置向后最多约 730 行搜索高低点；价格标记忽略最后 180 行，Pi Cycle 标记忽略最后 365 行。拟合时将所取得的高低点一次性用于整个时间序列，而不是对每个历史日期只拟合当时已经知道的数据。由此可推断：在新极值被纳入、参数调整或上游历史数据变化后，重算得到的旧日期分数可能变化。最后若干行不标记，并不能让整条回溯曲线成为逐日样本外结果。[极值函数](https://raw.githubusercontent.com/Zaczero/CBBI/main/utils.py)、[NUPL 的整段回归](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/rupl.py)

代码还包含明确的人为选择：将 2021-11-08 的价格顶部标记移到 2021-04-14；RHODL 增加 2024-12-18 高点；Trolololo 首次顶部残差打折；以及上表几项固定偏移。这些操作不等于模型无用，但构成自由度，历史拟合效果不能当作独立验证。[日期调整](https://raw.githubusercontent.com/Zaczero/CBBI/main/fetch_bitcoin_data.py)、[RHODL 修正](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/rhodl_ratio.py)

当前公共函数还把 2025-10-07 及之后的高低点标记全部清除，代码注释说明用于稳定算法直到下次重大更新。因此 FAQ 所说的每轮周期动态校准，在当前代码中还受到这道固定日期限制。[稳定化掩码](https://raw.githubusercontent.com/Zaczero/CBBI/main/utils.py)

判断实时有效性需要历史当天保存的分数、当时版本和数据发布时间，或按每个历史时点截断数据重新运行，并把当时尚不可知的极值及人工调整排除。本文未获得这一整套历史版本证据，也未量化历史改写幅度，故不报告 CBBI 的胜率、提前量或收益率。当前分数有研究价值与回溯图不能直接用于回测可以同时成立。

另一个限制是指标相关性。NUPL 和 MVRV 共用 MC 与 RC；均线、时间趋势、Top 带也大量使用同一条价格序列。九项等权并不等于九份独立证据，也不能仅凭项数声称统计置信度更高。数据故障时，[基类](https://raw.githubusercontent.com/Zaczero/CBBI/main/metrics/base_metric.py)会回退到网站已有分数并前向填充；若迁移，必须显示各项观测日、陈旧程度与有效项数，不能把沿用旧值显示成新增确认。

**迁移到 A 股，保留经济问题，重新选择可观测变量。** 下表是本次研究提出的类比，并非指标之间存在严格等价关系。

| BTC 指标所问的问题 | A 股可研究的替代量 | 迁移判断 |
| --- | --- | --- |
| 价格远离长期锚了吗？Pi/2YMA/Trolololo | 宽基指数 ln(P/MA250)、ln(P/MA500)，或同口径趋势偏离 | 最容易实现；重设窗口、检验结构变化，不套用 BTC 的倍数与年龄函数 |
| 市价相对成本/价值偏高了吗？NUPL/MVRV | 股债利差、指数 PB/PE 历史位置；现有股票池 P/V 另作组合诊断 | 保留估值偏离思路；PB 的账面权益、P/V 的模型价值都不等于 RC |
| 新资金和短线交易是否占主导？RHODL | 全市场换手率、融资买入占比，后续可研究新开户或基金发行 | 属于交易热度代理，不能测出真实“一周投资者/两年投资者”的持仓比例 |
| 长期持有人是否开始分配筹码？Reserve Risk | 换手、机构持仓披露、股东增减持等 | 披露有时滞且样本不完整，不足以复刻每日 HODL Bank |
| 生产者获得了异常高收益吗？Puell | 对特定资源行业可另研究利润率、商品价格相对成本 | 不存在合理的全 A 股矿工收入对应量；不强行凑入全市场指数 |
| 长期成本底和顶部带在哪里？Top/CVDD | 多种估值及历史交易成本代理 | A 股缺少覆盖全体证券持仓转移的公开链上账本，无法原样算 CVDD |

成交量加权均价 VWAP 可以作为近期成交成本的代理，但无法识别同一股份重复换手及当前仍持有者是谁；不能据此声称已经复制 MVRV/NUPL。企业盈利、分红、增发和指数成分变化也使 A 股的长期锚不同于 BTC。大盘蓝筹、中小盘和行业之间可能同时冷热不一，应分别显示其温度，不能只用沪深 300 代表所有持仓。

**建议的第一版研究规格是四类温度，另列趋势/宽度。** 以下为候选定义，不是已采纳的交易参数。

| 类别 | 第一版原始量 x | 数值升高的含义 | 首要数据问题 |
| --- | --- | --- | --- |
| V：相对估值 | −(1/PE_TTM−10 年国债收益率) | 股债性价比变差、估值温度升高 | PE 用指数整体盈利口径，债息用小数；按当时已公布观测对齐 |
| D：价格偏离 | ln(P/MA250) | 价格偏离长期均线更多 | 需要真实交易日日线；收益评价使用全收益口径并固定定义 |
| T：交易拥挤 | 同一市场范围内的 20 日平均换手率 | 交易更活跃 | 分子成交股数与流通股本口径一致，不能仅用成交额绝对水平 |
| L：融资拥挤 | 股票融资余额/匹配证券范围的流通市值 | 杠杆持仓占比升高 | 沪深数据合并、证券范围变化、基金是否纳入及公布时点 |

上交所公开披露融资余额、融资买入额等，并说明汇总数据含被调出标的的余额余量，明细只包括当前标的。因此两融数据可以提供研究输入，但分子分母必须统一覆盖范围。[上交所汇总数据说明](https://www.sse.com.cn/market/othersdata/margin/sum/)

各类先转成仅使用过去信息的经验分位，再等权合成。作为可复核的初始规格，可在每月信号日收集最新已公布观测，以前 60 个有效月末观测为比较分布，至少 36 个，当前值不进入参考样本。令 H_t 为该历史集合：

\[
S_i(t)=100\frac{\sum_{s\in H_t}[\mathbf{1}(x_i(s)<x_i(t))+0.5\mathbf{1}(x_i(s)=x_i(t))]}{|H_t|},
\qquad Heat_t=\frac{S_V+S_D+S_T+S_L}{4}.
\]

这些方向均已统一为“高分更热”。60/36 是待检验的起始规格，需要相邻窗口敏感性与滚动样本外验证；并非 CBBI 参数，也不覆盖工作流程已有的股债分位定义。不同频率的数据不能靠重复前向填充值虚增历史样本量。四项不齐时报告缺失；若需要短版，只能另行标记为 V+D 原型，不能把两项指数混称为四项指数。

如果再加入 PE、PB，应先在估值类别内合成；MA250、MA500 同样先在价格类别内合成，然后类别等权，以免堆叠相关因子提高隐含权重。分位在长期低迷市场也可能给出很高温度，故同时保留绝对股债利差和绝对价格偏离，不能仅靠相对排名判断贵贱。

市场宽度如“站上 MA60 的股票比例”另列为趋势状态，第一版不直接放进反向温度：宽度扩大既可能是牛市初期修复，也可能是后期普涨。需要历史证券范围、足够价格历史及覆盖率，不能用当前关注池冒充全市场。在温度之外保留趋势状态，有助于分开研究“高温且趋势向上”“高温且趋势转弱”，但是否应减仓仍须检验。

**与当前仓库衔接的证据。** 已读取 [工作流程](../000_Ashare_workflow.md) §9.3.1、§12.1、[个人投资体系](../000_personal-investment-system-v1.zh.md)和当前[待处理事项](../000_Ashare_workflow_open_issues.md)。生产已包含股债总仓位上限，研究比较必须以当前 `BASE` 为基准，不能用不带该约束的旧策略代替。市场温度首先可作为研究信息；进入执行体系的实验与采纳条件读取工作流程。

当前本地 `data/raw/macro/csi300_pe_ttm.csv` 与 `data/reference/equity_bond_csi300.csv` 各有 258 条观测，日期 2005-04-29 至 2026-09-21。前者含 `index_close`，后者包含 PE、债息及各自日期。它们约为月度历史密度，不能把 258 行当作 258 个交易日日线来算 MA250。已有 [取数脚本](../../scripts/fetch_equity_bond_inputs.py)可服务估值类，但当前供应商回溯历史不自动构成逐期发布版本证据。

[市场背景取数](../../scripts/fetch_daily_market_evidence.py)已有主要指数及成交额的当日快照，并明确全市场涨跌家数需另行取证。这不能证明已经具备完整历史宽度、换手率和融资面板；本轮未做全量数据覆盖审计。

已有[大回撤诊断](drawdown_review_2026-09-11.zh.md)和回测日志 §12.230 提示，某些持仓回撤与沪深 300 同期表现明显不同，宽度信号也曾较晚确认。这只作为选题线索，不能外推为所有宽度指标无效。它意味着新指数除检验指数风险外，还要检验对实际股票池、行业暴露和融资组合的作用，不能指望宏观温度覆盖个股经营风险。

**需要怎样的验证，才值得接入。** 建议先检验信息，再检验交易规则，避免根据历史图反复挑阈值。

1. 冻结原始变量、方向、窗口、数据公布规则与缺失处理。以 T 日信号截止时间已知数据计算，最早按既定 T+1 执行约定成交。融资与财报若在截止时间后公布，应延后使用；不能仅凭数据标签日期当作已经可用。
2. 按时间滚动训练/校准并测试，不随机打散日期；每次校准仅使用当时已有历史。今天下载的旧数据需审计重述和口径变动；宽度用当时证券名单，收益评价考虑分红。
3. 在预定温度区间下看后续 3、6、12 个月收益，以及信号后 6 个月路径最大回撤；高温若没有更差的前向收益分布或更大的尾部风险，就不进入仓位实验。报告每段连续高温事件，避免把相邻交易日当成独立样本。
4. 做拆分比较：估值 V、V+D、V+D+T+L，分别检查新增信息。随后以当前 `BASE` 做仓位实验，并设置平均风险暴露接近的固定仓位对照，区分信号价值与单纯降低仓位的效果。
5. 检查不同完整周期、不同宽基/股票池、相邻窗口及逐项剔除；记录错过的上涨、过早减仓、极端行情漏报、融资成本及费税滑点。正式 A/B、全/A/U、交易守卫和采纳判定沿用工作流程 §12.1。

本轮完成的是源码核查、指标释义、迁移方案与现有输入的小范围检查。没有运行 CBBI 全量取数与历史实时重建，没有运行新的 A 股回测，也没有据此产生当前市场温度或交易信号。公开网页和源码通过浏览工具读取；终端网络解析不可用，固定 SHA 的 raw 地址抓取未成功，因此保留已读 `main` 链接与提交历史定位，不声称完成了本地源码快照或部署一致性验证。
