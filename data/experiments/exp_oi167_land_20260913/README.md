# OI-167 落地核验（2026-09-13，轨道 A）

回测引擎的高价股一手兜底改为受单票上限余量约束（余量不足一手跳过、不触发卖出），与 §9.3.1／§9.3.1.1 成文及生产扫描器同判；策略名标记 `_cap0.6s`。预登记见 `preregister.md`，规则变化见 changelog v4.182，读数见回测日志 §12.233。

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | 输入哈希；护栏输入（在册状态子集＋按在册哈希从 git 取回的三张参考表 `raw/frozen_ref/`）与登记输入（当前生产状态的面板子集 `states/`、参考表冻结副本 `raw/frozen_current/`）；子集与生产逐行 digest 相同、与在册子集相同 |
| `sweep_guardrail.txt`、`report_guardrail.txt` | 新引擎（OI167）对在册 BASE（`exp_c030r35_land_20260910`）同输入配对：五项配对差中位全 0.00pp，闸门／否决未触发 |
| `sweep_base.txt`、`report_sweep_base.txt`、`in_register.json` | 新 BASE 28 条正式扫描与在册读数 |
| `path_deltas.csv`、`guardrail.json` | 逐路径差异（14/28 逐字段相同）、守卫触发次数（31）、赢家不变、登记跑与护栏跑 14/14 相同 |
| `summary_rows.csv`、`verification.json`、`registration.json`、`tests.txt` | 摘要、核验、台账登记（新增 28 键、旧 `cap0.6` 行保留）、435 项测试 |

`cache/`、`nav/`、`stats/`、`daily/`、`errors/`、`states/`、`raw/` 为可重建大产物，不入库。作业 26654813（16 核、2 分 54 秒、峰值 19.2 GiB）；在项目空间配额受限期间于 scratch 克隆上运行（`RAYKEY_ROOT`）。
