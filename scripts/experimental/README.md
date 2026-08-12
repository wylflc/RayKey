# 实验脚本（不属于生产流水线）

本目录只放**已做完并已在 `docs/Ashare_backtest_log.md` 记录结论的实验代码**，
供后续复现或改进用。**不被任何生产流程调用**，`docs/000_Ashare_workflow.md` 也不引用它们。

## 估值神经网络（2026-08-12，结论：不采纳，见回测日志 §12.28.4）

| 文件 | 作用 |
| --- | --- |
| `nn_dataset.py` | 装配训练样本：全市场 12,108 家 × 20 季 × 16 个无身份比率特征 → 未来 3 年年化总回报 |
| `nn_train.py` | 训练 1D-CNN（1,057 参数）并跑三项防记忆诊断（公司留出／打乱标签／岭回归对照） |
| `nn_apply.py` | 滚动重训（每 2 年，只用标签已兑现的样本）+ 逐日推断 → 写成回测可读的逐日估值文件 |

**依赖 `torch` 与 `numpy`，本仓库其余部分都不需要。** 不要为了跑它们改动仓库的依赖声明；
在临时虚拟环境里装即可：

```bash
python3 -m venv /tmp/nnvenv && /tmp/nnvenv/bin/pip install numpy torch
/tmp/nnvenv/bin/python scripts/experimental/nn_dataset.py   # 产出 nn_data.pkl（约 475MB）
/tmp/nnvenv/bin/python scripts/experimental/nn_train.py     # 诊断 + nn_model.pt
/tmp/nnvenv/bin/python scripts/experimental/nn_apply.py     # 逐日估值文件
```

三个脚本都从自身所在目录读写中间产物（`nn_data.pkl` / `nn_model.pt`），
且 `nn_apply.py` 需要同目录下的 `pit116_codes.txt`（时点面板的代码清单）。
