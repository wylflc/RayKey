# A 股回测备用策略清单

**用途**：回测口径（估值、宇宙、资金、读数）再有大变化时，不必重扫 §12.171 那样的 144 臂，先跑这份清单里有本质区别的十几条臂，看历代主要方案在新口径下各自落在哪里。清单只登记「要跑什么」，不预设结论；判定、登记与落地一律走 `docs/000_Ashare_workflow.md` §12.1（先登记轨道再跑数，决策读数与双表门槛以该节为准）。

**三个落点**：

| 内容 | 位置 |
| --- | --- |
| 清单本体（一行一臂，可增删） | `data/experiments/exp_strategy_shortlist/configs/shortlist_arms.tsv` |
| 一条命令跑完（先建需重建的臂，再扫描） | `bash scripts/slurm/submit_strategy_shortlist.sh` |
| 读数 | `data/experiments/exp_strategy_shortlist/report_rules_<日期>.txt`／`report_val_<日期>.txt` |

## 1. 主要参数维度

在册值只认 §9.3.1 与 `scripts/sweep_backtest_configs.py` 的 `BASE`；下表「写作时在册」为 2026-09-02 快照，只为对照备选，过期以那两处为准。「性质」决定用哪把尺子：**估值口径**按机制正确性裁定、回测只作记录（§12.120／OI-128 先例）；**风险约束**是风险偏好裁定、不是收益优化对象（§12.112 对杠杆的判法）；**操作规则**按 §12.1 轨道 B 的决策读数判。

| 维度 | 开关 | 写作时在册 | 主要备选（本清单臂） | 性质 | 备选出处 |
| --- | --- | --- | --- | --- | --- |
| 周期守卫·谷侧 | `--trough-guard` | on | off（`GE_TROUGHOFF`） | 估值口径 | §12.172／§12.174 |
| 周期守卫·探测器 | `--roic-cycle-guard` | peak | efficiency（`GUARDEFF`） | 估值口径 | §12.67／§12.172 |
| 分子锚 | `--roic-nopat-source` | conditional3 | median（`NPMEDIAN`） | 估值口径 | §12.72／§12.171 表 D |
| 增速腿权重 | `--roic-trail-weight` | 0 | 1.0（`TW100`） | 估值口径（上一纪元） | §12.163 |
| 少数股东扣减 | `--minority-basis` | earnings | book（`MINBOOK`） | 估值口径（上一纪元） | §12.167 |
| 银行/保险股利折现利差 | `rebuild_bank_bands.py divspread:` | 0.02 | 0.03（`DIVS03`） | 估值输入 | OI-141 |
| 宇宙 | `--universe-file` | v6b | v6a（`U6A`） | 宇宙 | §12.71／OI-141 |
| 买入线 | `--width` | 1 − 在册线 | 不单独优化；随口径按 §12.30 重解 | — | OI-139 |
| 换仓边际 | `--swap-margin` | 在册值 | 不进清单；换口径后按 0.01 一档重扫 | — | §12.1 第 4 款① |
| 相关性上限 | `--max-corr` | 1.0（只报告不过滤） | 0.70（`C070`，恢复簇约束） | 风险约束 | §12.171 表 G／§12.174 表 S |
| 涨幅减持 | `--gain-sell` `--gain-sell-mode` | 1.10 ungated | 1.25 gated（`G125G`，恢复走势闸门）；0（`NOGAIN`） | 操作规则 | §12.171 表 E／§12.174 表 S |
| 换仓 | `--swap` | 开（减一档、源同日不重复、非涨幅源须弱势） | 关（`NOSWAP`） | 操作规则 | §12.171 表 A |
| 止损 | `--stop-ma` `--stop-line` `--trail-ratio` | 60／min_entry_current／无 | 上移锚 0.667（`TRAIL067`） | 操作规则 | §12.93／§12.171 表 H |
| 两侧估值 | `--hold-states` | 持仓侧读 `max(BASE,B2)` | 单侧（`NOSPA`） | 操作规则 | §12.137／§12.171 表 A |
| 授信比例 | `--credit-ratio` | 0.666 | 0（`CR000`） | 风险约束 | §12.112／§12.163 |
| 单票上限 | `--position-cap` | 0.60 | 0.40（`CAP40`） | 风险约束 | §12.123／§12.163 |

不进清单但纪元变化时须一并核对的：一档比例 `--x`（3~7% 全在噪声内，§12.171 表 B）、`--max-positions`／`--scan-depth`／`--corr-window`／`--trend-ma`（OI-141 C14）。

## 2. 清单臂

读数列是 14 起点两遍配对差（Δ复利 全样本／去赢家，pp）：「上一纪元」为 §12.171~§12.174 在 OI-128／131／132 纪元的读数，「2026-09-05」为本清单首次整跑（回测日志 §12.196，`report_rules_20260905.txt`／`report_val_20260905.txt`）；**只作方向参考，不跨纪元迁移**，口径一变即作废。

| 臂 | 组 | 相对 `BASE` 改了什么 | 本质区别 | 上一纪元 Δ复利 | 2026-09-05 Δ复利（v4.137，m2） | 判定 |
| --- | --- | --- | --- | ---: | ---: | --- |
| `BASE` | 对照 | — | 现行 | — | — | — |
| `GE_TROUGHOFF` | 估值口径 | 建带 `--trough-guard off`；买入线重解 | 谷年不再把锚抬到十年中位（非对称守卫） | +8.09／+1.32 | +4.22／−0.01 | 不采纳（闸门 +6.7pp） |
| `GUARDEFF` | 估值口径 | 建带 `--roic-cycle-guard efficiency`；买入线重解 | 周期探测器换走势单调度（锚点关卡未过，只作对照） | +13.14／+4.25 | +1.62／+6.79 | 第 2 款过；锚点关卡未过，只作对照 |
| `NPMEDIAN` | 估值口径 | 建带 `--roic-nopat-source median`；买入线重解 | 分子锚纯中位、无增长态信任 | +5.45／+0.60 | −0.26／+3.62 | 不采纳（两表反向；闸门 +9.0pp） |
| `TW100` | 上一纪元对照 | 建带 `--roic-trail-weight 1.0`；买入线重解 | v4.119 前的增速腿 | +2.05／−6.65 | −3.76／−3.37 | 不采纳 |
| `MINBOOK` | 上一纪元对照 | 建带 `--minority-basis book`；买入线重解 | OI-128 前的少数股东扣减 | 参 §12.167（反向 −16.85） | −2.90／−3.28 | 不采纳 |
| `DIVS03` | 估值输入 | 只重跑 §6.7 第 3 步 `divspread:0.03`；买入线重解 | 银行/保险 V 整体下移 | 未测 | −2.53／+2.72 | 不采纳 |
| `U6A` | 宇宙 | `--universe-file …v6a.csv`；买入线对同一合格面重解 | 银行只含招行／宁波 | 未测 | −7.55／−5.24 | 不采纳（闸门 +5.4pp） |
| `C070` | 风险约束 | `--max-corr 0.70` | 恢复簇约束（v4.131 前在册；反向臂 `C100` 上一纪元 +6.40／+0.27） | 未测 | +1.01／−5.14 | 不采纳（主读数 −3.59） |
| `G125G` | 操作规则 | `--gain-sell 1.25 --gain-sell-mode gated` | 恢复走势闸门与 125% 阈值（v4.131 前在册；反向臂 `G110U` 上一纪元 +9.15／+3.68） | 未测 | −2.96／+2.32 | 不采纳（主读数 −2.21） |
| `NOGAIN` | 操作规则 | `--gain-sell 0` | 无涨幅减持 | −3.16／+1.80 | −7.73／+1.22 | 不采纳 |
| `NOSWAP` | 操作规则 | `--no-swap` | 买入持有＋止损＋减持，无换仓 | +3.59／−2.01 | −6.81／−8.01 | 不采纳 |
| `TRAIL067` | 操作规则 | `--trail-ratio 0.667` | 上移锚止损（0.70 起悬崖） | +6.97／+3.87 | +0.64／−5.07 | 不采纳 |
| `NOSPA` | 操作规则 | `--hold-states …adopted.csv` | 两侧同读候选侧 V | −0.74／−0.81 | −2.56／−0.48 | 不采纳 |
| `CR000` | 风险约束 | `--credit-ratio 0.0` | 不融资 | −8.06／−14.79 | −20.47／−16.96 | 不采纳 |
| `CAP40` | 风险约束 | `--position-cap 0.40` | 单票上限收紧 | +7.18／−2.13 | +0.50／−5.20 | 不采纳 |

增删臂只改 `shortlist_arms.tsv`：`states_from` 写 `self` 的臂由 `build_extra`／`divspread` 重建两侧状态，写别的臂名即复用其状态与买入线，写 `-` 只动扫描器参数；`universe` 给面板路径即只重解买入线。

## 3. 跑法

```bash
# 0. 生产链已按新口径重建（§6.7 第 2~3 步与第 7 步），BASE 与在册两线已更新
# 1. 在 docs/Ashare_backtest_log.md 按 §12.1 第 1 款登记本轮轨道（清单臂缺省轨道 B）
# 2. 一条命令：为需重建的臂各提交建带作业（-n 16，各约 15 分钟，并行），再以 afterok 提交扫描（-n 64，约 20 分钟）
bash scripts/slurm/submit_strategy_shortlist.sh
# 3. 读表
cat data/experiments/exp_strategy_shortlist/report_rules_<日期>.txt
cat data/experiments/exp_strategy_shortlist/report_val_<日期>.txt
```

建带作业的公共开关从 §6.7 第 2 步命令现读、divspread 从第 3 步现读、在册买入线与换仓边际从 `sweep_backtest_configs.BASE` 现读，不在脚本里抄写；已建过的臂（`val/<臂>/align_buy_line.txt` 存在）自动跳过，要重建就删该文件。§12.171 已建的臂可软链复用：`ln -s ../../exp_reaudit_minority/val/GE_TROUGHOFF data/experiments/exp_strategy_shortlist/val/GE_TROUGHOFF`（口径未变时才可复用）。

跑完后：通过双门槛的臂按 §12.1 第 4 款补剔除集 U、边际重扫、剔除只数剂量曲线与第 10~12 款，再报用户裁定；多条同时通过时先出组合臂（OI-140 的教训：三条候选 Δ 归因高度重叠）。
