# 实验脚本（不属于生产流水线）

本目录只放**已做完并已在 `docs/Ashare_backtest_log.md` 记录结论的实验代码**，
供后续复现或改进用。**不被任何生产流程调用**，`docs/000_Ashare_workflow.md` 也不引用它们。

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

## 银行估值口径重算（2026-08-13，结论：合格面确实被摊平但年化不动，见回测日志 §12.30.4）

| 文件 | 作用 |
| --- | --- |
| `rebuild_bank_bands.py` | 按 §6.5.7.1 的 J-金融资本型口径只重算银行的估值带，非银行行逐位不动。三种模式：`fixed:COE`（给定折现率）／`peer`（滚动三年同业隐含 COE 中位）／`pbhist`（滚动三年自身 PB 中位） |

```bash
python3 scripts/experimental/rebuild_bank_bands.py fixed:0.17 data/processed/vd_pit116_bkcoe17.csv
python3 scripts/experimental/rebuild_bank_bands.py peer      data/processed/vd_pit116_bkpeer.csv
```

不需要 `torch`/`numpy`，只用标准库。产出的逐日估值文件**不入库**。

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

## `daily_scan_adopted.py` —— 已退役（2026-08-14，结 OI-051）

**其全部功能已并入生产入口 `scripts/screen_daily_volume_price_signals.py`**，本目录不再保留副本。

并入的是 §9.7 机械执行层：模型带 `P/V`、银行股利折现、`收>MA20>MA60` 闸门、
按 `P/V` 升序 + 252 日相关性 ≤0.85 去相关（下扫至多 40 名）、一档 = 净资产 × 1%、
整手向下取整与 §9.7.3 比例冷却。生产入口新增 `--model-bands / --nav / --rf / --plan-out` 四个参数。

**等价性已验证**：同一交易日、同一模型带下，两套实现给出的 17 只买入清单在
**代码、名称、现价、`P/V`、股数上逐只逐字段一致**——且这是跨数据源的一致
（生产走东财 `fqt=1`，退役版走腾讯 `qfq`）。详见 `docs/Ashare_backtest_log.md` §12.42。

## 中轴按什么定：`decompose_pv_bias.py` / `calibrate_band_by_group.py` / `align_buy_line.py`（§12.45）

```bash
python3 scripts/experimental/decompose_pv_bias.py            # 偏置能被什么解释（R² 分解）
python3 scripts/experimental/calibrate_band_by_group.py <输入逐日> <输出逐日> <ind1|ind2|tier|ind1xtier>
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
