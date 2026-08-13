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

## 生产脚本上唯一为这些实验开的口子

`scripts/build_historical_valuation_bands.py --roe-external CSV`：用外部预测的 ROE 覆盖 `roe0`，
其余输入（折现率、终值 ROE、增长、护栏）一律沿用现行模型，故回测差异只能归因到 ROE 这一个输入。
**不给该参数时行为逐位不变**，既往产出可复现。
