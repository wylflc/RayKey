# 指导性文档审计（2026-07-31）

对照 [The new rules of context engineering for Claude 5 generation models](https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models) 的反模式清单，扫描 `AGENTS.md`、`CLAUDE.md`、`CONTEXT.md`、`docs/` 指导性文档与项目级/用户级 skill。

**总结论**：本 repo 的**架构是对的**——「标准只存在于 `docs/000_Ashare_workflow.md`，skill 只做路由不复述阈值」正是文章推荐的渐进披露。问题出在**执行不彻底**：skill 自己违反了自己写的这条规则，复述了阈值与机制，而这些复述**已经过期**。

按严重度分三类。

---

## 一、过期指令（比过度指导严重——会直接导致错误行为）

文章讨论的是"约束过多"；本 repo 的首要问题是"约束过时"。skill 复述工作流机制后没有随工作流更新，形成了**与现行标准冲突的第二事实源**。

### 1.1 `a-share-holdings-sell-scan/SKILL.md` —— 卖出规则整体过期（最高优先级）

该 skill 的 description 与正文写着 10 处已退役机制：

| skill 写的 | 实际状态 |
| --- | --- |
| 3 个月锁定期（lockup） | §14 v1.12（2026-07-20）**已退役** |
| 盈利后离场规则、浮盈档位累计卖出上限（profit-exit ceilings / profit-ladder） | v1.12 **已退役**，且 §14 明写「盈利本身既不是卖出理由，也不再限制卖出」 |
| 退出优先级矩阵 Tier-1/Tier-2 | v1.12 已被「四类卖出许可」取代 |
| 趋势保护线三档全部日线判定 | v1.19/v1.21 已改**分态口径**（趋势态 MA60/MA120；反转态启动结构/MA20） |
| 上调割肉价「不超上限均线」「toward (≤) MA120」 | v1.11（2026-07-20）**已废止**外部锚上限 |
| `stop_loss_price` is up-only **and capped** | 同上，cap 已废止 |

按此 skill 执行会：在已退役的锁定期内拒绝卖出、按已删除的浮盈梯减仓、用已废止的 MA120 上限约束割肉价。**这是本次审计发现的最严重问题。**

### 1.2 `a-share-valuation-pool/SKILL.md` —— 档位名与路径失效

- 使用估值档「**可接受较高估**」——该名称在现行工作流中命中 **0 次**（现行为 低估/较低估/中性/较高估/高估/无法估值）。
- 入池规则「only 低估/较低估/中性/可接受较高估 enter」——已被 §6.2.1 **分层×估值准入矩阵**取代（还有 watch_only 层）。
- 引用 `docs/personal-investment-system-v1.md` §8 —— **文件不存在**（实际为 `-v1.zh.md`）。

### 1.3 `a-share-peer-calibration/SKILL.md` —— 指向不存在的"唯一事实源"

把 `data/processed/a_share_final_screening_results.csv` 称为 "structured source of truth"、"Rows with `final_decision = watch` **are** the current A-share watchlist" —— **该文件不存在**。现行事实源是 `a_share_attention_triage.csv` + `a_share_watchlist_quality_tiers.csv`。

### 1.4 `a-share-quality-tiering/SKILL.md` —— 引用已被 ADR-0006 撤下的评分模型

称 `docs/moat-scoring-rubric.md` 为 "the baseline triage model"，但该文件自己的 scope 说明（2026-07-08，依 ADR-0006）已把 A 股撤出，现仅服务港美股脚本。

### 1.5 `a-share-daily-scan/SKILL.md` —— 版本与仓位口径漂移

- 「workflow v25」（现行 **v1.26**）。
- 「§13 target-position/build-amount」与「可建目标仓位 1/3」—— 目标仓位百分比制与 build_amount 金额制自 v20/v1.02 **已退役**，现行为**重仓 50 万 / 轻仓 25 万二档、一笔建满、由用户逐票定档**。

### 1.6 `CLAUDE.md` —— 与现行仓位制度直接冲突

> "Core holding candidates must justify **15%-25% position potential**"

工作流 §13（v1.02，2026-07-17 用户设定）明写：单票建仓金额只有重仓/轻仓两档，**「原核心/准核心/动量/观察四袖、只数上限与席位兼容规则全部退役」**。CLAUDE.md 保留的百分比仓位制是已退役制度，且 CLAUDE.md 的指令优先级高于 docs——这是最容易造成实际误导的一条。

### 1.7 `stock-analysis/SKILL.md` —— 赔率闸门已退役

要求"State whether `base-case upside / bear-case downside` clears the system's threshold: normally >2; >3 for high-volatility..."。**赔率闸门自 v1.02 / 个人体系 v1.8（2026-07-17）已退役**——工作流 §6.2.1 明写「赔率闸门退役，§10 不再计算赔率」，个人体系 §9.1 第 4 条写「赔率自 v1.8 起不再作为买入闸门项，仅作重仓/轻仓定档参考」。skill 仍把它当作必须"clear"的门槛。

### 1.8 skill 的 `agents/openai.yaml` 同样过期

4 份 `openai.yaml` 的 description 与主 SKILL.md 复制了同一批过期表述（"3-month lockup, profit-exit ceilings"、"L1–L5 tiering"、"final watch/reject decisions"、"L1/L2 companies"）。**修 SKILL.md 时极易漏掉这一份**——本次审计初稿即漏掉，靠残留扫描才发现。

### 1.9 `a-share-peer-calibration/SKILL.md` —— 引用两个不存在的脚本

`scripts/audit_a_share_review_standard.py` 与 `scripts/build_a_share_peer_group_screening_queue.py` **均不存在**。该阶段实际全程是判断，无专属脚本。（此项在修订过程中由路径复验脚本发现——初稿照抄了旧 skill 的脚本块。）

### 1.10 `README.md` 指向 `AGENTS.md` 为指令源

与 2.1 的去重方向冲突，已改为指向 `CLAUDE.md`。

### 1.11 `CONTEXT.md` —— L5 定义与 2026-07-31 用户决定冲突

`Quality Tier` 与 Relationships 段落均写「L5 不是保留档，意味着降出 worth-attention」。用户 2026-07-31 已决定（D-21）：**评级只评级，L5 是保留档，名单进出由独立的 attention 扫描负责**。

---

## 二、重复指令（文章点名的 "redundant examples in multiple places"）

### 2.1 `AGENTS.md` 与 `CLAUDE.md` 逐字节相同

两份 56 行文件内容完全一致。Claude Code 只读 CLAUDE.md、其他 agent 读 AGENTS.md，本身合理，但**逐字节复制两份的唯一后果是漂移风险**——改一份忘另一份即产生冲突指令。

### 2.2 `CLAUDE.md` 复述个人投资体系

"Investment Research Rules" + "Position discipline" 共 16 条，内容与 `docs/personal-investment-system-v1.zh.md`（§1 核心原则 / §5 选股策略分类 / §15 禁止事项 / §16 一票否决）重复——而 CLAUDE.md 自己第一句就写着"以该文件为默认标准"。**既指路又复述**，正是文章说的"把 CLAUDE.md 当成完整知识库"。

### 2.3 skill 的 "Required Local Context" 列举 CONTEXT.md 词条

多个 skill 要求"先读 CONTEXT.md 的 X、Y、Z 词条"。这是强制前置披露；术语在用到时按需查即可。

---

## 三、过度指导（文章点名的 "excessive rule-based constraints"）

### 3.1 `CONTEXT.md` 的 `_Avoid_` 从句

约 60 个术语条目，**每条都附一句 `_Avoid_:`**。多数是机械否定（"Avoid: stock, ticker when referring to the business entity"），在术语已被清晰定义的前提下不增加信息，只增加 token 与"必须逐条遵守"的心理负担。保留有真实歧义风险的少数几条即可。

### 3.2 `CONTEXT.md` 的死术语

约 12 个词条属于**已退役的两层复核体系**：`Two-Layer Company Review`（含"triage score ≥ 65"这一已撤销阈值）、`Triage Review`、`Deep Company Review`、`Dimensional Score`、`Special Dimension`、`Full-Coverage Screening Run`、`Moat Score`、`Cross-Market Calibration`、`Market-Staged Calibration`、`Watch Selection Route`、`Final Screening Result`、`Insufficient Disclosure`。其中 `Moat Score`（0-100 粗评分）会与分层 v2 的 `quality_score` 混淆。

### 3.3 skill 的 "Discipline" 段落

每个 skill 末尾的 Discipline 段重述工作流已有的禁令（"不是买入指令"、"不能只因盈利卖出"、"garbage 不因涨价回归"）。工作流是唯一标准源，skill 重述即制造第二事实源——**1.1 的事故正是这样发生的**。

### 3.4 `CLAUDE.md` 的通用工程原则

"Research And Data Principles" 与 "Validation" 共 10 条（先原始记录后归一化、保留 provenance、跑最小可用检查……）属于模型默认就会做的良好实践，属文章所说"为早期模型准备的防御性脚手架"。

---

## 四、修订原则

1. **过期即删或即改**，不保留"历史参考"——过期指令的危害大于信息价值；历史留在 `Ashare_workflow_changelog.md` 与本审计。
2. **skill 严格回归路由**：只保留「这是哪一阶段」「权威章节在哪」「跑哪个脚本」「哪部分是模型判断」。**不复述任何阈值、档位名、机制名**——这条规则 skill 自己已经写了，本次是让它真正生效。
3. **CLAUDE.md 只保留三类内容**：路由、docs 无法表达的硬约束（密钥、提交规范、`docs/xzy/` 边界）、以及**与默认行为相反**的项目特例。凡 docs 已写的一律删。
4. **CONTEXT.md 回归术语表本职**：定义术语、说明关系；删死术语、删机械 `_Avoid_`。
5. **AGENTS.md 改为指针**，消除双份漂移。

修订执行见下一节提交记录。

---

## 五、本次修订清单

| 文件 | 动作 |
| --- | --- |
| `a-share-holdings-sell-scan/SKILL.md` | 重写——删除全部 10 处已退役机制，改为纯路由 |
| `a-share-valuation-pool/SKILL.md` | 修正档位名、入池规则改指 §6.2.1 矩阵、修复失效路径 |
| `a-share-peer-calibration/SKILL.md` | 删除对不存在 CSV 的"唯一事实源"表述 |
| `a-share-quality-tiering/SKILL.md` | 删除对已撤下评分模型的引用；L5 表述改为指向工作流 |
| `a-share-daily-scan/SKILL.md` | 删除版本号与已退役仓位口径 |
| `equity-research-workflow/SKILL.md` | 改为纯路由表；保留 4 条非显然的数据建模约定 |
| `stock-analysis/SKILL.md` | 修正赔率口径（闸门→定档参考）、精简教条、保留输出模板 |
| 4 份 `agents/openai.yaml` | 同步修正过期 description |
| `CLAUDE.md` | 删 15%-25% 冲突项、删复述个人体系的 16 条、删通用工程原则 |
| `AGENTS.md` | 改为指向 CLAUDE.md 的指针 |
| `CONTEXT.md` | 删/降格死术语为一节「Retired Vocabulary」、删机械 `_Avoid_`、修正 Quality Tier 定义 |
| `README.md` | 指令源指向由 AGENTS.md 改为 CLAUDE.md，并补上两份主 spec |

**未改动**：`docs/000_Ashare_workflow.md`（唯一标准源，本次不动其内容）、`docs/personal-investment-system-v1.zh.md`、`docs/peer-group-calibration/`（审计上下文）、用户级 skill（`diagnose`/`tdd`/`write-a-skill` 等为通用工具，与本 repo 领域无关，未见过度指导）。

### 体量变化

| | 修订前 | 修订后 |
| --- | ---: | ---: |
| `AGENTS.md` + `CLAUDE.md` | 112（逐字节重复两份） | 31 |
| `CONTEXT.md` | 240 | 95 |
| 7 份 SKILL.md | 446 | 339 |
| **合计** | **798** | **465（−42%）** |

减少的部分几乎全部是**复述与过期内容**；领域模型、脚本调用、判断/脚本分工、输出模板均保留。

---

## 六、防复发

本次 10 处过期指令有一个共同成因：**skill 复述了工作流的机制名与阈值**。工作流每次修订（近三周从 v20 走到 v1.26）都会让这些复述失效，而没有任何机制提醒去同步。

三条建议：

1. **skill 只写章节号，不写机制名。** 写「见 §14 卖出许可」而非「3 个月锁定期 / 浮盈档位上限」——章节号在重构时才失效，机制名在每次修订时都会失效。本次已按此重写全部 7 份。
2. **`openai.yaml` 与 `SKILL.md` 的 description 一同修改**（本次差点漏掉）。
3. **工作流修订（§15）时顺手扫一遍 skill**：`grep -rn "<被退役的机制名>" .agents/skills/` 即可。
