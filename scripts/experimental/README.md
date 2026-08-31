# 实验脚本（不属于生产流水线）

本目录放两类代码，都**不被生产流水线（§6.7 / §8 / §9）调用**：

1. **已做完并已在 `docs/Ashare_backtest_log.md` 记录结论的实验代码**，供后续复现或改进；
2. **`docs/000_Ashare_workflow.md` §12.1 验证纪律点名要跑的常设核验工具**——
   `align_buy_line.py`（第 12.1 节三线对齐）、`selection_edge_audit.py`（第 9 款）、
   `panel_tier_forward.py`（第 9 款）、`swap_regime_control.py`（第 9 款，换仓方向性的对照）、
   `delta_attribution.py`（第 10 款）。
   第 2 类改动前先确认 §12.1 的引用是否同步。

## §12.1 常设核验工具（信号层与归因）

回测的路径读数由少数复利段主导，臂间差异常常只反映「谁更妥善地碰到了那几个赢家」。
以下两个脚本把评价从「这条路径赚了多少」挪到「选择动作本身是否含信息」和
「这个 Δ 由多少只票撑起来」，样本量与稳健性都与赢家身份无关。

| 文件 | 作用 | §12.1 |
| --- | --- | --- |
| `selection_edge_audit.py` | 三表：①**边际选择检验**——同日合格集里买到的对没买到的前向总回报（排序＋相关性过滤＋资金分配合起来的边际信息量）；②**排序信息量**——合格集名次对前向回报的单调性；③**换仓方向性**——同日换入目标对换出源的前向回报配对 | 第 9 款 |
| `delta_attribution.py` | 按代码拆开 A/B 的配对差，报前 1/3/5 只的**净额占比**与**总动量占比**；净额占比 >100% 表示扣掉后 Δ 反号 | 第 10 款 |
| `swap_regime_control.py` | `selection_edge_audit.py` 表 3 的对照组，四表：A**面板层 `P/V` 信息量**（逐年 Spearman 与三分位价差）、B**合成换仓**（只用面板 `P/V` 档构造的换仓价差，不引用任何持仓）、C**`P/V` 匹配对照**（逐笔换仓与同日同 `P/V` 的在册面板名字比，拆买腿／卖腿超额）、D**样本独立性**（不同 `(源, 标的)` 配对数）| 表 3 的对照 |

```bash
# 先跑一次带两份日志的回测（BASE 全参数见 sweep_backtest_configs.py 的 BASE）
python3 scripts/backtest_valuation_strategy.py <BASE 全参数> --since 2011-11-01 \
    --candidate-log /path/cand.csv --trade-log /path/trades.csv --out-dir /path/bt
python3 scripts/experimental/selection_edge_audit.py \
    --candidate-log /path/cand.csv --trade-log /path/trades.csv --horizon 250
python3 scripts/experimental/delta_attribution.py \
    --base /path/bt_base/BASE_trades.csv --arm /path/bt_arm/ARM_trades.csv
# 表 3 的对照组（两份逐日状态各扫一遍，本机约 1~2 分钟）
python3 scripts/experimental/swap_regime_control.py \
    --candidate-log /path/cand.csv --trade-log /path/trades.csv \
    --states data/processed/a_share_daily_states_adopted.csv \
    --hold-states data/processed/a_share_daily_states_hold.csv \
    --panel data/processed/pit_attention/panel_moat_bank_v6b.csv --split 2017
```

统计口径：同日多个候选强相关，故**先在日内取中位、再跨日汇总**，报逐日配对差中位与为正日数；
跨日前向窗口仍重叠，故结论以**逐年同号年数**为准，单一年份撑起来的差值不作证据。
表 3 还要额外扣一层：换仓的动作就是沿 `P/V` 向下移仓，其符号同时受面板层信号纪元支配，
故报表 3 时同报 `swap_regime_control.py` 的对照读数；`换仓·减一档` 每天只卖一档，
同一 `(源, 标的)` 会连周重复，配对数才是「日数」的有效上界（依据见回测日志 §12.144）。

## 估值神经网络（结论：全部不采纳，见回测日志 §12.28.4 与 §12.29.3/§12.29.4）

| 文件 | 作用 |
| --- | --- |
| `nn_dataset.py` | 装配训练样本：全市场季度财报 × 20 季 × 16 个无身份比率特征 → **两个标签**：未来 3 年年化后复权总回报、未来三个完整财年的年度 ROE 均值 |
| `nn_train.py` | 训练 1D-CNN（1,057 参数）并跑三项防记忆诊断（公司留出／打乱标签／岭回归对照） |
| `nn_apply.py` | 滚动重训（每 2 年，只用标签已兑现的样本）+ 逐日推断 → 回测可读的逐日估值文件 |
| `nn_diagnose.py` | 「训练集 × 标签」四组合对照（全市场／仅时点面板 × 回报／ROE） |
| `nn_diagnose_corrected.py` | 上一项的更正版：D2 打乱标签改为**不按真实验证 IC 挑 epoch**（原做法是假阴性），并加「同样本量」对照；末尾直接比较现行 `roe0` 与网络对未来 ROE 的 IC |
| `nn_panel_apply.py` | 用户口径：**只用时点关注面板内的样本**训练并滚动推断（§12.29.3，回测 −10.05pp） |
| `nn_roe.py` | 只预测 ROE，输出 `security_code,available_at,roe0`，交给 `build_historical_valuation_bands.py --roe-external` 喂回现行 DCF（§12.29.4，回测 −2.69pp） |

**依赖 `torch` 与 `numpy`，本仓库其余部分都不需要。** 不要为了跑它们改动仓库的依赖声明；
在临时虚拟环境里装即可：

```bash
python3 -m venv /tmp/nnvenv && /tmp/nnvenv/bin/pip install numpy torch
/tmp/nnvenv/bin/python scripts/experimental/nn_dataset.py            # 产出 nn_data.pkl（约 500MB）
/tmp/nnvenv/bin/python scripts/experimental/nn_diagnose_corrected.py # 诊断（含现行口径对照）
/tmp/nnvenv/bin/python scripts/experimental/nn_apply.py              # 回报模型 → 逐日估值文件
/tmp/nnvenv/bin/python scripts/experimental/nn_panel_apply.py        # 仅面板训练版
/tmp/nnvenv/bin/python scripts/experimental/nn_roe.py nn_data.pkl nn_roe_pred.csv pit116_codes.txt
```

脚本都从自身所在目录读写中间产物（`nn_data.pkl` / `nn_model.pt`），
`nn_apply.py` 与 `nn_roe.py` 还需要同目录下的 `pit116_codes.txt`（时点面板的代码清单）。
中间产物与产出的逐日估值文件**都不入库**。

## 银行估值口径重算（2026-08-13，见回测日志 §12.30.4）

`rebuild_bank_bands.py` 自 v4.00 起是生产脚本（§6.7 第 3 步，模式 `divspread:0.02`）；`fixed:COE`／`peer`／`pbhist`／`ri:`／`ddm:` 各模式保留为研究口径（§12.104~§12.105 不采纳）。

## 成长/PEG 并联通道（2026-08-13，结论：不采纳，见回测日志 §12.31.4）

| 文件 | 作用 |
| --- | --- |
| `add_growth_path.py` | 给现行估值带并联一条 PEG 通道（`V = EPS_ttm × g×100 × PEG目标`），取 `min(P/V_DCF, P/V_PEG)`，只放宽不收紧。支持 `--min-g/--max-g/--min-roe/--max-pe/--accel/--only-nonbank` 各类护栏 |

```bash
python3 scripts/experimental/add_growth_path.py 1.0 data/processed/vd_pit116_pegG.csv --max-g 1.50 --max-pe 80
```

不需要 `torch`/`numpy`。**结论为负**：合格面守恒使并联通道变成「换人」而非「加法」，
新放进来的观测其后一年 +4.3%、被挤掉的 +5.7%。护栏加不出正收益，`--accel` 还会反向恶化。

## 逐筛选年时点重判（2026-08-13，结论：机械化失败，见回测日志 §12.33）

| 文件 | 作用 |
| --- | --- |
| `pit_moat_screen.py` | 阈值版：五条并联护城河签名（M1 品牌定价权／M2 高于同业／M3 扩张不降毛利／M4 周期抗压／M5 规模龙头），各对应 §5.4 一条判据 |
| `pit_moat_rank.py` | 综合分版：八个分项逐年在全市场分位归一后**等权**相加，取前 N。权重不拟合已知名单，141 家只作事后验收 |

```bash
python3 scripts/experimental/pit_moat_rank.py --top-n 200 --calib          # 只验收
python3 scripts/experimental/pit_moat_rank.py --top-n 200 --out panel.csv  # 出面板
```

**结论为负**：最好 −0.84pp，滚动三年回撤 36%（现行面板 20%），入选股自入选日起中位年化 **−2.4%**
（后视护城河名单为 +7.3%）。原因是八个分项全是「已实现的基本面强度」，在基本面顶点同时最大化，
而基本面顶点与价格顶点重合。局部进步：宁德时代与牧原股份都比人工判定早两年入选。

## `deviation_gate_diagnostics.py`：偏离度闸门的三项诊断（§12.40）

```bash
python3 scripts/experimental/deviation_gate_diagnostics.py <逐日估值状态.csv> <面板.csv> [买入线] [起点]
```

**结论为负**，且这三张表是否决用户点名的「偏离 60 日线超阈值即停投」的全部依据：
①闸门作用面（合格集 `收/MA60` 中位 1.068，走势闸门本已蕴含站上 MA60）；
②偏离度的**中位**单调预测变差、**均值**却没有梯度（左右尾同时变肥，P90 由 16.9% 升到 24.7%）；
③**过一遍建仓日 MA20 止损后各档均值被拉平成 +0.06%~+1.24%、偏离度不再含信息**——
即止损已经把「买贵了」的后果吃掉，事前再加入场过滤是冗余。

**顺带记一条通用标尺**：同批回测里，只挡掉合格集的 **0.2%** 就能让 Δ年化中位动 −0.91pp，
而空跑对照逐位等于基准。**故 |Δ| ≲ 1pp 且符号数在 8/23~15/23 之间者一律读作无效应。**

## 中轴按什么定：`decompose_pv_bias.py` / `calibrate_band_by_group.py` / `calibrate_band_ma60.py` / `calibrate_band_zscore_partial.py` / `align_buy_line.py`（§12.45~§12.49）

```bash
python3 scripts/experimental/decompose_pv_bias.py            # 偏置能被什么解释（R² 分解）
python3 scripts/experimental/calibrate_band_by_group.py <输入逐日> <输出逐日> <ind1|ind2|tier|ind1xtier>
python3 scripts/experimental/calibrate_band_ma60.py ...          # 居中判据改 MA60（§12.49，全负）
python3 scripts/experimental/calibrate_band_zscore_partial.py ... # 方差归一 / 部分校准 α（§12.48，全负）
python3 scripts/experimental/align_buy_line.py <基准逐日> <基准线> <待对齐逐日>...
```

**结论为负，但诊断有效**：偏置由**行业**决定（一级行业 R²=**0.540**）而非护城河（质量分层 R²=**0.014**）；
按行业做时点扩窗校准确实把纠偏原则修好了（合格率 14%→33%、log 离散度 0.482→0.378），
**但回测 −6.34pp（0/23）**，且行业×分层更差（−13.50pp）。
机理：校准把合格面从化石能源挪向医药生物（+11pp），正是把钱从真正赚钱的那批挪走。

**`calibrate_band_by_group.py` 是时点扩窗的**：第 Y 年的因子只用 Y 年之前的观测，样本不足退回 1.0，预热 5 年。
**`align_buy_line.py` 必须对三条线都用**——买入线、减持线、换仓阈值凡定义在 `P/V` 上的都要重标度，
只对齐买入线会让卖出机制睡着（§12.45.4 踩过，方向没变但幅度差 4pp）。

## 生产脚本上唯一为这些实验开的口子

`scripts/build_historical_valuation_bands.py --roe-external CSV`：用外部预测的 ROE 覆盖 `roe0`，
其余输入（折现率、终值 ROE、增长、护栏）一律沿用现行模型，故回测差异只能归因到 ROE 这一个输入。
**不给该参数时行为逐位不变**，既往产出可复现。

## 护城河终值补偿实验台（2026-08-20，见回测日志 §12.94；结论：终值超额杠杆干净但修不到买入区，分档/打分不含增量信息）

| 文件 | 作用 |
| --- | --- |
| `moat_param_lab.py` | 单票：把同一只股票在不同终值参数下（`build_historical_valuation_bands.py --out-daily` 的多份逐日状态）的 `P/V` 并排——关键时点读数、逐年可买/减持区天数、月末 `P/V` 对其后 3/5 年**含分红再投**年化的校准（Spearman、各桶中位、对数线性拟合上前向恰等于要求回报的「公允 P/V」） |
| `panel_tier_forward.py` | 全池：面板在册月末 `P/V` → 前向 3/5 年总回报，按 2026 年人工分档（含后视）分组报校准，并可落盘逐票统计（`--per-code-out`）供与 Q2/参考分做相关 |

```bash
python3 scripts/build_historical_valuation_bands.py --codes 600519 <§6.7 第 2 步全部参数> \
    --terminal-excess 0.06 --out-daily /tmp/x/E6_daily.csv          # 或 --moat-params overrides.csv
python3 scripts/experimental/moat_param_lab.py --code 600519 --states BASE=... E6=... \
    --key-dates 2013-12-30 2018-10-30 2021-02-10 2024-09-18
python3 scripts/experimental/panel_tier_forward.py --states data/processed/a_share_daily_states_adopted.csv \
    --panel data/processed/pit_attention/panel_moat_bank_v6b.csv --exclude-banks --per-code-out /tmp/x/per_code.csv
```

生产脚本上为此开的两个口子（缺省关、既往产出逐位可复现）：`--terminal-excess X`（`ROE_T/ROIC_T = r/WACC + X`）、
`--moat-params CSV`（逐票覆盖 `fade_years` / `terminal_excess` / `n1`，空列沿用全局）。

决策层一侧（回测日志 §12.95，结论：凡进排序者全负、只放宽 L1 买入线弱正不过独立期，OI-070 据此关闭）：
`backtest_valuation_strategy.py --tier-buy-scale L1=1.5[,L3=0.875]`／`--tier-sell-scale L1=1.5`（按 2026 分档给买入线／减持线乘倍数，
缺省空＝逐位等于 BASE）；全决策折扣臂用「L1 的 `P/V` ÷m、V×m」的状态文件等价实现（与 §12.94 的带乘数同义，未另入库）。

## 回撤路径剖析（2026-08-20，见回测日志 §12.92）

| 文件 | 作用 |
| --- | --- |
| `reconstruct_holding_weights.py` | 从逐笔流水重建逐日持仓的时间加权平均权重（「重仓股是哪些」，§12.43.6／§12.76 集中度核对的输入） |
| `drawdown_path.py` | 读一次**带产物**的回测（`*_equity.csv`、`*_trades.csv`、`--trade-log` 流水），列出全部回撤段，并对最深的几段给出峰/谷日账户结构、沪深300 与上证对照、峰→谷成交流水，以及用流水重建逐日股数（含送转）后的**老仓层／新钱层两层盈亏归因**与峰值日老仓明细（距生效止损线、离场日与原因） |

```bash
python3 scripts/backtest_valuation_strategy.py <BASE 全参数> --since 2009-11-01 \
    --out-dir /tmp/bt_base --trade-log /tmp/bt_base/tradelog_base.csv      # 不要带 --no-artifacts
python3 scripts/experimental/drawdown_path.py /tmp/bt_base --top 3
```

## 实验 A/B：无选股与纯量价（结论见 `docs/Ashare_quant_exp1_index_universe.md`、`docs/Ashare_quant_exp2_volume_price.md`）

| 文件 | 作用 |
| --- | --- |
| `build_cap_rank_universe.py` | 时点总市值排名的指数类股票库（沪深 300／中证 500／中证 1000／全市场代理）＋按代码持久的哈希抽样子集，格式同 `panel_moat_bank_v6b.csv` |
| `subset_daily_states.py` | 把全市场逐日估值状态按若干面板的代码并集切成子集文件（只为回测提速，逐位等价） |
| `vp_signal_lab.py` | 量价信号实验室：事件研究（事件等权 / 按日等权、同日市场基准、MFE）＋ 随机抽样持有组合模拟（含费、挂单止盈、安慰剂）。**依赖 numpy，本机用 `python3.11`（miniconda）运行** |

