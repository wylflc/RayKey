# 比亚迪独立估值（OI-245 水平守卫个案复核）

用户 2026-09-30 要求客观分析比亚迪按现价多少 `P/V` 合适（水平守卫 LG1.3 把它从 0.81 拉到 2.54）。研究参考，不改口径。

- `value.py`：读仓库年报三表与本目录的东财 F10 中报三表（`byd_*.json`，09-30 取数），算财务要点、三个情景（股权两段式折现，10%／9%）、P/B–ROE 核对、现价隐含增长，并对照模型带与 LG1.3。输出 `value.json`、`value.md`。
- 结论与特宝生物、下限变体示意见 [`docs/reports/byd_independent_valuation_2026-09-30.zh.md`](../../../docs/reports/byd_independent_valuation_2026-09-30.zh.md)。

    python3 value.py
