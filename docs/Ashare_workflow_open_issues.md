# A 股工作流待处理缺陷登记

本文件登记**已确认但尚未修订**的工作流缺陷，以及**用户指令登记的待办工作项**，供下一次集中修订（§15）统一处理。
规则：确认即登记，不在此文件下结论；修订完成后正文移入 `Ashare_workflow_changelog.md`（对应版本行）与 `Ashare_backtest_log.md`，编号与一行处置移入 `Ashare_workflow_open_issues_closed.md` 顶部，本文件不留结案项。

**两类登记项要分清**（2026-08-07 起本文件同时承载两类）：`缺陷` = 现行机制与成文标准不符或成文未落地，**已经在产生错误结论**；`待办` = 用户要求新增的能力或分析，**当前不存在也不算错**。编号连续，各项开头标明类别。

登记项按发现日倒序；**每个待处理项一个三级标题**，在 outline 里即可数清余量（用户 2026-08-19 指令）。

## 待处理（3 项）

### OI-158｜缺陷：剔除集对称性运行的 A／B／U 标签跨实验复用，台账归并时旧行被同名新行顶掉

**来源（2026-09-06，§12.200 归并时发现）**：`ex_winner_symmetry.py` 给三组剔除集的 `BASE` 行统一打 `ABASE`／`BBASE`／`UBASE` 标签，扫描标签（`summary_tag`）只由标签与起点决定；`clean_derived_artifacts.py backtest --apply` 按扫描标签去重归并，本次并入 §12.200 的 U 复核后把 `data/archive/scan_summaries_m1.csv` 里旧口径的同名 42 行（A／B／U × 14 起点）删掉。本次已用 `git checkout` 复原归档文件；现行台账与按臂索引里 `ABASE`／`BBASE`／`UBASE` 三臂的读数只对应最近一次运行，不能用来数臂。修法候选：对称性脚本的集合标签带挑战臂名（如 `A@SC`），或归并时以（扫描标签，计量版本，实验目录）为键。无前置项。

### OI-157｜待考察：涨幅减持只按 T+1 收盘判（`--t1-judge gain`）

**来源（2026-09-06，§12.200）**：全样本 Δ主／Δ复利 −1.80／−1.95pp，第 2 款不采纳；剔除集 A 与 U（两集相同：T1_GAIN 锚定起点前五与 BASE 前五一致）下标准指标集各项配对差均 ≥ −0.15pp，按 §12.1 第 4 款登记。同族卖侧 T+1 形态（§12.136／§12.138 的 C1／SC，§12.200 的 T1_SWAP／T1_SELL）同为全样本负、去赢家正，SC 在 U 下两项劣未登记。采纳前须补齐第 4 款三项：①该臂上换仓边际按 0.01 一档重扫；②剔除赢家只数 1／3／5／10 剂量曲线（`scripts/experimental/ex_winner_dose.py`）；③第 10~12 款读数（`selection_edge_audit.py`、`panel_tier_forward.py`、`delta_attribution.py`）。三项齐备后报用户裁定；证据 `data/experiments/exp_t1_info/`。无前置项。

### OI-150｜待办：海外市场估值信号的预登记前向检验（第三批次，可选）

**来源（2026-09-05，[指标审核与最终方案](reports/backtest_metric_review_plan.zh.md)第三批次）**：先预登记固定 `P/V` 分档对未来收益的检验，再考虑完整组合回测。前提：历史时点股票池、退市与公司行动、原始财报可得时间、本地税费与执行规则齐备；当前海外关注清单与当前估值不构成无偏历史样本。港美股与 A 股共享宏观风险，不当作独立抽样；据结果改规则后该市场同样转为研究样本。无前置项。**当前处置（2026-09-06）**：用户裁定暂时搁置。已完成：预登记书与数据前提审计 [overseas_pv_forward_prereg.zh.md](reports/overseas_pv_forward_prereg.zh.md)（美股为正式样本，港股无历史池不作正式样本）；管线 `scripts/experimental/overseas_pv_forward.py` 五步写完并冒烟通过；股票池 653 家与 companyfacts 已缓存，价格取到 141 只（原始缓存 2.1 GB 在 `data/experiments/exp_oi150_overseas_forward/raw/`，不入库）。首跑在取价步因腾讯接口限流（约 250 次请求／33 分钟）未完成，取价器已改为失败退避重试、按已有文件续取（翻页取数与旧结果逐根一致）。重启即提交 `scripts/slurm/oi150_overseas_forward.sbatch`，各步自动续跑。
