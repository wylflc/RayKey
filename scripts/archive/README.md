# 归档：已退役的脚本

本目录存放**不再属于任何现行流程**的脚本。它们能跑，但没有任何一条现行口径调用它们，
放在 `scripts/` 主目录会被后续分析误当作在用工具。

判定标准（三条同时成立才归档）：①`docs/000_Ashare_workflow.md` 未引用；②无其他脚本 import；
③其产物已被现行产物取代或所属轮次已结束。

需要恢复时直接 `git mv` 回 `scripts/` 即可，无路径依赖。

| 脚本 | 退役理由 | 现行替代 |
| --- | --- | --- |
| `fetch_hong_kong_universe.py`<br>`fetch_hong_kong_research_evidence.py`<br>`run_hong_kong_full_coverage_scoring.py`<br>`fetch_us_universe.py`<br>`fetch_us_research_evidence.py`<br>`run_us_full_coverage_scoring.py` | **港股/美股全覆盖打分管线整体退役**。其口径 `docs/moat-scoring-rubric.md` 自 2026-07-08（ADR-0006）起已被 A 股撤出，此后只服务这六个脚本；而海外覆盖已于 v1.22 改为 §6.8「海外关注清单」——只对**用户点名**的公司按 §5.7 分层、§6.5 定带，不做全市场打分。产物 `data/interim/{hong_kong,us}_*.csv` 停在 2026-05-14 | 工作流 §6.8 + `data/processed/overseas_watchlist_valuation.csv` + `scripts/overseas_quotes.py` |
| `build_a_share_full_rescan_queue.py` | 全市场第一轮三类初筛重扫的工作队列生成器。该轮已于 **2026-07-09 完成**（5,653 家：261 worth_attention / 5,332 boundary_pending / 60 garbage），队列不再需要重建 | 季度审查走 `build_quarterly_quality_review_queue.py`（§5.5）；全量重扫如需重启见 §5.4.6 |
| `fetch_a_share_research_evidence.py` | 早期研报证据抓取，产物 `a_share_research_queue.csv` 停在 2026-05-14，且其字段口径不含建带所需的一致预期覆盖机构数 | `fetch_a_share_valuation_evidence.py`（§6.5.4 取数陷阱二的覆盖机构数由它产出） |
| `apply_evidence_review.py` | 2026-08-01 分层证据复核轮的一次性回写工具，该轮已闭环（261 家全部 evidence-reviewed），复核记录见 `data/interim/evidence_review_log.md` | 无——后续分层变更走 §7.2 质量复核触发，逐票写入 |

同类归档：`docs/archive/`（已完成的过程记录与已实施的方案设计）、
`data/archive/`（已跑完的工作队列与已结束轮次的产物）。
