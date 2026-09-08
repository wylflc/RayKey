# AShareQuant

A 股上市公司研究、估值、每日执行与持仓跟踪，附港股、美股和韩股观察清单及独立回测研究。

## 执行入口

- [工作流程](docs/000_Ashare_workflow.md)：按任务路由表执行；名单、评分、估值、交易和回测规范的主入口。
- [个人投资体系](docs/000_personal-investment-system-v1.zh.md)：账户约束、策略标签与研究纪律。
- [核心池阅读版](docs/000_a_share_core_valuation_pool.md)：当前估值、池外档案与海外观察清单。
- [每日扫描日志](docs/000_daily_scan_log.md)：执行清单、持仓与成交记录。
- [待处理事项](docs/000_Ashare_workflow_open_issues.md)：执行前检查相关缺陷。

代理工作规则见 [CLAUDE.md](CLAUDE.md)，[AGENTS.md](AGENTS.md) 为指针。

## 文档与证据

| 位置 | 用途 |
| --- | --- |
| [质量评分细则](docs/Ashare_quality_rubric.md) | 四维打分方法与证据字段；层级与交易规则读取工作流程 |
| [版本记录](docs/Ashare_workflow_changelog.md)、[回测日志](docs/Ashare_backtest_log.md) | 当前纪元的变更与实验证据索引，按需检索 |
| [结案索引](docs/Ashare_workflow_open_issues_closed.md) | 已处理缺陷与待办的处置 |
| `docs/reports/` | 各次实验与审计报告；报告日期对应当时状态 |
| [行业校准记录](docs/peer-group-calibration/README.md) | 历史行业研究线索；使用前核对当前名单与原始证据 |
| [文档归档](docs/archive/README.md) | 已完成的研究过程与旧纪元记录；旧正文从 Git 历史读取 |

## 数据与代码

| 位置 | 用途 |
| --- | --- |
| `data/raw/` | 原始数据与不可变证券名单快照；抓取缓存由 `fetch_*` 脚本重建 |
| `data/reference/` | 模型参考输入与人工核验事件 |
| `data/interim/` | 更新队列、取证与校验中间件 |
| `data/processed/` | 当前结构化真值与生产产物；具体落点读取工作流程 |
| `data/companies/` | 逐票阅读档案和研究台账；自动估值更新不代表人工研究已复核 |
| `data/experiments/`、`data/backtest/` | 实验配置、摘要与扫描台账 |
| [数据归档](data/archive/README.md) | 已完成轮次的证据与历史记录 |
| `scripts/` | 生产脚本、数据工具与本地检查 |
| `scripts/slurm/` | 长时作业入口；资源规范见代理工作规则 |
| [实验脚本](scripts/experimental/README.md) | 常设回测核验工具及实验复现代码 |
| [脚本归档](scripts/archive/README.md) | 退役工具与保留期限 |
| `notebooks/` | 估值与成交诊断可视化 |

## 维护

生产命令链只维护在工作流程中。文档一致性检查运行 `python3 scripts/audit_repository_docs.py`；生产与回测参数同步检查运行 `python3 scripts/test_strategy_parameter_sync.py`。

可重建的大型派生产物不入库。`python3 scripts/clean_derived_artifacts.py closed` 预览已结案实验的清理清单；确认无相关运行作业后加 `--apply`。保留原始证据、配置、摘要与生产输入。
