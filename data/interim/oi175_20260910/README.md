# OI-175定向重算证据

截止2026-09-10，工作流程v4.179。结论与原始公告见[核验报告](../../../docs/reports/oi175_minority_claims_2026-09-10.md)。

- `roic_bands.csv`、`roic_bands_b2.csv`：两家公司按统一参数重算的129期结果；紫光当前拒绝出带，不能从其较早的 `ok` 行取当前合理价。
- `landing_validation.json`：首次应用到两份全市场带及五份逐日缓存的范围、删除数量及保留流SHA-256。每份状态删除464行；其他行保持原样。复跑时不要用“第二次删除0行”覆盖首次落地证据。
- `presentation_validation.json`：结构化档案、阅读版、三类名单与生产池成员核对。
- `checks.json`：本项定向测试与文档审计结果。

输入三表保留在 `../company_review_20260910/statements/`，点名研究的旧模型值保留在该目录，已经显式标为历史快照。完整回放命令与参数由 `scripts/experimental/resolve_oi175_minority_claims.py` 维护；缺省只重算定向证据，不更改当前结构化档案。派生逐日回放写到 `/tmp/oi175_roic_daily*.csv`，行情截至2026-08-07。
