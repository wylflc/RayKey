# 1. A-Share Semiconductor Equipment Peer-Group Calibration

> 历史行业校准记录：仅供追溯研究线索。当前名单、质量档及筛选规则读取工作流程与结构化真值；引用本页事实前须核对原始证据。

## 1.1 Purpose

This note starts A-share **Peer-Group Calibration** for semiconductor equipment companies.

The group is intentionally narrower than "semiconductors". It excludes chip designers, foundries, OSAT companies, and most materials companies. Semiconductor equipment should be judged by process know-how, customer validation, installed base, service capability, supply-chain control, and product-roadmap execution.

The key test is whether a well-funded new entrant can quickly defeat the company. For semiconductor equipment, capital helps, but usually cannot buy years of process tuning, reliability data, customer qualification, and tool-service feedback loops.

## 1.2 Evidence Boundary

This first pass uses company annual reports or annual-report mirrors, official exchange or CNINFO PDFs, designated financial media reporting from annual reports, SEMI industry context, and reputable research-summary sources.

Rows using annual-report mirrors or media summaries are acceptable for calibration discussion, but direct exchange or company annual-report PDFs should replace them before final rule freezing. Aggregator company introductions are not used as moat evidence.

## 1.3 Industry Context

Semiconductor equipment has a stronger structural outlook than many cyclical manufacturing groups because AI, advanced packaging, memory, power devices, and domestic semiconductor self-sufficiency keep driving investment. SEMI reported in April 2026 that worldwide 300mm fab equipment spending is expected to grow in 2026 and 2027, with China investment still supported by domestic capacity expansion and policy initiatives.

The same context argues for selectivity. Equipment is cyclical, capital-expenditure dependent, and often customer-concentrated. A high-growth year may reflect order timing rather than durable moat. The watchlist standard should therefore emphasize hard-to-replace process positions rather than broad "国产替代" narratives.

## 1.4 Preliminary Attention Calls

| Tier | Companies | Preliminary Call |
| --- | --- | --- |
| Platform or core process leaders | 北方华创, 中微公司 | Core watch |
| Distinct front-end process leaders | 华海清科, 拓荆科技, 盛美上海 | Watch |
| Testing and metrology boundary cases | 华峰测控, 长川科技, 中科飞测, 精测电子 | Watch if differentiated advantage is accepted |
| Lithography-track boundary case | 芯源微 | Watch if 涂胶显影 and customer validation are accepted as independent moat |
| Reject or reclassify | 京仪装备, 金海通, 至纯科技 | Reject for now or move to narrower future groups |

The structured calibration table is `data/processed/a_share_semiconductor_equipment_peer_group_calibration.csv`. The structured reviewer decision table is `data/processed/a_share_semiconductor_equipment_peer_group_decisions.csv`.

## 1.5 Reviewer Decision

Reviewer feedback explicitly retained:

- 北方华创
- 中微公司
- 华海清科

For the remaining companies, the reviewer asked the analyst to decide based on business-moat strength and the reasonable profitability of the specific equipment step. Short-term profit-margin volatility should not dominate the decision when the business has a high-barrier step and a reasonable stable gross-margin profile.

Additional analyst-retained companies:

- 拓荆科技: retained because thin-film deposition is a distinct front-end process step and 2025 margins remain consistent with high-value equipment economics.
- 盛美上海: retained because cleaning, wet-process, plating, and advanced-packaging wet tools have strong process barriers and strong gross-margin quality.
- 华峰测控: retained because ATE has platform-like software and hardware economics, a long installed base, and very high reasonable margins.
- 长川科技: retained because testing, handlers, and probe-station coverage provide a different testing-equipment angle from 华峰测控.
- 中科飞测: retained because inspection and metrology are scarce high-barrier steps; weak current net margin is acceptable given high gross margin and heavy R&D.
- 精测电子: retained with monitoring because front-end metrology contracts for advanced storage and HBM are meaningful, although semiconductor-business purity must be tracked.
- 芯源微: retained with lower conviction because 涂胶显影, front-end cleaning, and temporary bonding/debonding are scarce process steps; short-term net-margin weakness should not be treated as a direct rejection reason.

Rejected or reclassified:

- 京仪装备: rejected from this group because it is more like auxiliary semiconductor subsystems than core process equipment.
- 金海通: rejected for now because high margins in a narrow test-handler niche are not enough when the broader testing-equipment platforms already cover the attention slot.
- 至纯科技: rejected because mixed system integration, weak margin structure, and overlapping wet-process exposure do not justify core equipment watchlist attention.

## 1.6 Accepted Rules

1. **Core Equipment Watch** requires evidence of customer-qualified tools in high-value semiconductor manufacturing steps, repeat orders, process coverage, and roadmap expansion.
2. `北方华创`, `中微公司`, and `华海清科` are accepted semiconductor-equipment watchlist companies.
3. **Retain Multiple Equipment Companies When Process Steps Differ**: 刻蚀、薄膜沉积、CMP、清洗湿法、测试、量检测、涂胶显影 are not interchangeable. A company should not be rejected only because a retained leader is larger in another process step.
4. **Use Reasonable Step-Level Profitability**: evaluate margins by the economics of the equipment step. ATE, metrology, and high-value front-end tools can have very high gross margins; auxiliary systems and system integration normally deserve lower margin expectations.
5. **Do Not Over-Penalize Early Profitability**: for metrology, inspection, lithography-track, and other scarce high-barrier equipment, early losses or weak net margin should not automatically reject the company if gross margin and customer validation indicate high-value equipment economics.
6. **Reject Pure Theme Exposure**: revenue growth from domestic substitution is not enough unless the company proves tool performance, customer qualification, and repeated commercial deployment.
7. **Reject Weak Copies Within The Same Step**: within the same process step, keep only companies with a clear independent advantage or a niche not covered by stronger retained peers.
8. **High Margin Alone Is Not Enough**: a high-margin narrow niche can still be rejected if broader retained platforms cover the same attention slot and the moat is not clearly irreplaceable. `金海通` is the accepted example.
9. **Reclassify Auxiliary Systems**: facility systems, high-purity gas/chemical delivery, temperature control, or components may be important, but they should not be mixed with core process-equipment watchlist rules unless their moat is equally hard to replicate.

## 1.7 Analyst Dissent Policy

1. No dissent on retaining `北方华创`, `中微公司`, `华海清科`, `拓荆科技`, `盛美上海`, `华峰测控`, `长川科技`, `中科飞测`, `精测电子`, and `芯源微`.
2. I would dissent if `中科飞测`, `精测电子`, or `芯源微` are rejected solely because current net margins are low. Their gross margins and process scarcity matter more at this stage.
3. I would not dissent if `京仪装备`, `金海通`, or `至纯科技` remain excluded under the current evidence.

## 1.8 Remaining Work

1. Apply these process-step and profitability rules when later calibrating Hong Kong and U.S. semiconductor-equipment companies.
2. Calibrate semiconductor materials, foundries, OSAT, and chip-design companies in separate peer groups rather than mixing them with equipment.
3. Track retained early-stage companies for customer validation, recurring orders, and whether gross margins translate into stable operating profit as scale improves.

## 1.9 Sources

- SEMI 300mm fab equipment spending outlook: `https://www.semi.org/en/semi-press-release/semi-projects-double-digit-growth-in-global-300mm-fab-equipment-spending-for-2026-and-2027`
- 北方华创 2025 annual report and result coverage: `https://static.cninfo.com.cn/finalpage/2026-04-18/1225122918.PDF`, `https://finance.sina.cn/tech/2026-04-20/detail-inhvcrna0557365.d.html?vt=4`
- 中微公司 2025 annual report mirror and result coverage: `https://stockmc.xueqiu.com/202603/688012_20260331_3UTD.pdf`, `https://finance.sina.com.cn/stock/relnews/cn/2026-04-02/doc-inhsztwe2300695.shtml`, `https://finance.sina.com.cn/stock/relnews/cn/2026-03-31/doc-inhswavw3349354.shtml`
- 华海清科 2025 annual report and result coverage: `https://static.cninfo.com.cn/finalpage/2026-04-23/1225156951.PDF`, `https://finance.sina.com.cn/stock/zqgd/2026-04-23/doc-inhvmvzq3871681.shtml`
- 拓荆科技 2025 result coverage: `https://finance.sina.com.cn/tech/roll/2026-04-28/doc-inhvzfsq7349196.shtml`, `https://www.yicai.com/news/103155699.html`
- 盛美上海 2025 annual report and result coverage: `https://static.cninfo.com.cn/finalpage/2026-02-27/1224986438.PDF`, `https://finance.sina.com.cn/roll/2026-03-02/doc-inhppxwy5496993.shtml`
- 华峰测控 2025 annual report mirror and ESG report: `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12258268&stockid=688200`, `https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12258242&stockid=688200`, `https://finance.sina.com.cn/stock/aiassist/yjbg/2026-04-28/doc-inhwaicx1582204.shtml?froms=ggmp`
- 长川科技 2025 annual report mirror and result coverage: `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12197571&stockid=300604`, `https://finance.sina.com.cn/stock/bxjj/2026-04-24/doc-inhvrnzw3072510.shtml`
- 中科飞测 2025 annual report mirror and result coverage: `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12185819&stockid=688361`, `https://www.stcn.com/article/detail/3805929.html`
- 精测电子 2025 annual report mirror and result coverage: `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12216269&stockid=300567`, `https://finance.sina.com.cn/stock/zqgd/2026-04-27/doc-inhvyeex2215082.shtml`
- 芯源微 2025 result coverage: `https://finance.sina.com.cn/tech/roll/2026-04-20/doc-inhvcrmy3780131.shtml`, `https://finance.sina.com.cn/stock/zqgd/2026-04-17/doc-inhuvkww6340123.shtml`
- 京仪装备 2025 result coverage: `https://finance.sina.com.cn/stock/zqgd/2026-03-30/doc-inhsuquw2663271.shtml`, `https://finance.sina.com.cn/stock/aiassist/yjbg/2026-03-30/doc-inhsuqus9558362.shtml`
- 金海通 2025 annual report mirror and result coverage: `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=11989815&stockid=603061`, `https://finance.sina.com.cn/stock/relnews/cn/2026-03-10/doc-inhqphnh6168492.shtml`
- 至纯科技 2025 annual report mirror and result coverage: `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12289849&stockid=603690`, `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12289847&stockid=603690`, `https://finance.sina.com.cn/stock/aigc/stockfs/2026-04-30/doc-inhwfpqm0455254.shtml?froms=ggmp`
