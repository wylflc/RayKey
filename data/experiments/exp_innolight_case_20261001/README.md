# 中际旭创 2025 年 4 月估值（OI-249 个案）

用户 2026-10-01 问：2025 年 4 月的中际旭创按 PE、PEG 看明显低估，是否属实；如属实，对比现行模型，如何兼容成长股估值。研究参考，不改口径。

- `value.py`：读仓库财务摘要与年报三表、行情，按 2025-04-18 收盘后可得的信息做四情景股权折现、反推与盈亏平衡；用生产 `intrinsic_value` 拆解模型带，并用生产参数重建四只股票的带（`bands_prod.csv`；`bands_nopeak.csv` 为 `--roic-peak-k 99` 关峰守卫的对照）。输出 `value.json`、`value.md`。
- 结论与兼容成长股的候选见 [`docs/reports/innolight_2025-04_valuation_2026-10-01.zh.md`](../../../docs/reports/innolight_2025-04_valuation_2026-10-01.zh.md)。

    python3 value.py
