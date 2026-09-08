# 1. A-Share Bank Peer-Group Calibration

> 历史行业校准记录：仅供追溯研究线索。当前名单、质量档及筛选规则读取工作流程与结构化真值；引用本页事实前须核对原始证据。

## 1.1 Purpose

This note starts A-share **Peer-Group Calibration** for listed banks.

Banks require a narrower standard than industrial companies. A bank can be stable, cheap, systemically important, or high dividend without being a strong fit for this project's current **business-quality watchlist**. This calibration therefore asks whether a bank has a hard-to-replace franchise in deposits, customers, risk culture, wealth management, small-business service, or a differentiated network, rather than whether it is currently undervalued.

## 1.2 Evidence Boundary

This first pass uses company annual reports or annual-report mirrors, official company announcements, regulator or banking-association industry data, designated financial media, and reputable research summaries.

Rows using media summaries or research-summary mirrors are acceptable for calibration discussion, but direct exchange or company annual-report PDFs should replace them before freezing a final rule. Aggregator company introductions are not used as moat evidence.

## 1.3 Industry Context

Chinese banks operate in a regulated, leveraged, macro-credit-sensitive industry. Net interest margin pressure, property-cycle exposure, local-government credit exposure, and policy guidance can limit long-term compounding even for well-managed banks.

That does not make all banks unwatchable. The right moat test is whether a funded entrant or another incumbent can easily take the same customers, deposits, risk data, operating culture, or specialized service capability. In banking, the strongest moats are often slow-built rather than technology-like: trusted retail customer relationships, low-cost core deposits, private-bank and wealth-management ecosystems, conservative risk culture, granular small-business credit data, and local relationship networks.

The calibration therefore separates three ideas:

1. **Quality watchlist**: banks with differentiated, hard-to-replace business franchises.
2. **Value or dividend list**: large stable banks that may be attractive at the right price but do not need to consume quality-watchlist attention.
3. **Regional beta**: banks whose growth mainly reflects a strong local economy or credit expansion, unless they prove a distinct customer or risk-control capability.

## 1.4 Preliminary Attention Calls

| Tier | Companies | Preliminary Call |
| --- | --- | --- |
| Quality anchor | 招商银行 | Core watch |
| Differentiated city-bank sample | 宁波银行 | Watch |
| Boundary differentiated networks | 邮储银行, 常熟银行 | Watch if the network or microloan moat is accepted |
| Stable but reclassified | 工商银行, 建设银行 | Reclassify into future value/dividend work, not current quality watch |
| Reject for now | 中信银行, 平安银行, 兴业银行, 江苏银行, 杭州银行, 成都银行 | Do not include in the current quality watchlist unless reviewer supplies a stronger differentiated thesis |

The structured calibration table is `data/processed/a_share_bank_peer_group_calibration.csv`. The structured reviewer decision table is `data/processed/a_share_bank_peer_group_decisions.csv`.

## 1.5 Reviewer Decision

Reviewer feedback explicitly retained:

- 招商银行
- 宁波银行
- 邮储银行
- 常熟银行

Reviewer feedback explicitly rejected all other companies in this group:

- 工商银行
- 建设银行
- 中信银行
- 平安银行
- 兴业银行
- 江苏银行
- 杭州银行
- 成都银行

I accept this decision. It preserves a useful distinction between quality-bank watchlist candidates and large stable banks that may still matter in a later low-valuation or dividend workflow.

## 1.6 Accepted Rules

1. **Bank Core Watch** requires a differentiated liability base, customer ecosystem, risk culture, and business model that are hard for another funded player to replicate.
2. `招商银行` is the accepted A-share bank quality anchor.
3. `宁波银行` is retained as a differentiated city-bank sample because its SME and private-business customer service model is not merely a weaker copy of 招商银行.
4. `邮储银行` is retained because the postal network and down-market deposit franchise are accepted as a separate moat, even though broad profitability quality is weaker than 招商银行.
5. `常熟银行` is retained because the microloan and small-business model is accepted as a specialized niche worth observing.
6. **Retain Multiple Banks Only When Differentiated**: keep more than one bank only if each has a separate hard-to-replace advantage, such as retail wealth management, regional SME service, postal-network deposits, or granular microloan underwriting.
7. **Reclassify Large Stable Banks**: system importance, state backing, and dividend stability are valid investment attributes, but they should be handled in a value/dividend workflow unless paired with a differentiated quality moat.
8. **Reject Regional Beta**: a regional bank should not be retained only because its local economy is strong or loan growth is high. It needs evidence of customer stickiness, superior risk selection, liability advantage, or a model that remains strong across credit cycles.
9. **Reject Weak Copies**: a bank that mostly imitates a retained leader's retail, wealth-management, or regional-bank strategy should be rejected unless it has a distinct and durable niche.

## 1.7 Analyst Dissent Policy

1. No dissent on retaining `招商银行`, `宁波银行`, `邮储银行`, and `常熟银行`.
2. No dissent on rejecting `中信银行`, `平安银行`, `兴业银行`, `江苏银行`, `杭州银行`, and `成都银行` under the current evidence.
3. No dissent on excluding `工商银行` and `建设银行` from the quality watchlist, provided they remain available for a separate value/dividend or balance-sheet-stability review.

## 1.8 Remaining Work

1. Apply these accepted bank rules when later calibrating Hong Kong and U.S. banks.
2. Consider a separate value/dividend bank workflow later for large state banks and other stable financial institutions.

## 1.9 Sources

- 招商银行 2025 annual-report summary and result coverage: `https://paper.cnstock.com/html/2026-03/28/content_2193399.htm`, `https://4g.stockstar.com/detail/IG2026032800000033`
- Banking-industry margin and profitability context from China Banking Association / regulator data: `https://china-cba.net/Index/show/catid/34/id/46216.html`
- 宁波银行 2025 annual report and result coverage: `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12194756&stockid=002142`, `https://finance.sina.com.cn/stock/bxjj/2026-04-24/doc-inhvrnzs7737295.shtml`, `https://cn.investing.com/news/stock-market-news/article-3330285`
- 邮储银行 2025 result coverage: `https://finance.sina.com.cn/roll/2026-03-30/doc-inhsuvau2583372.shtml`
- 工商银行 2025 annual report: `https://v.icbc.com.cn/userfiles/resources/icbcltd/download/2026/2025AnnualReportA.pdf`
- 建设银行 2025 result materials: `https://www.ccb.com/chn/attachDir/2026/03/2026032016453497945.pdf`
- 中信银行 2025 result coverage: `https://www.citicbank.com/about/companynews/banknew/message/202603/t20260320_3596386.html`, `https://www.stcn.com/article/detail/3688989.html`
- 平安银行 2025 result coverage and company report mirror: `https://stock.stockstar.com/RB2026032200001712.shtml`, `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12009205&stockid=000001`
- 兴业银行 2025 result coverage: `https://finance.sina.com.cn/stock/hkstock/ggscyd/2026-03-27/doc-inhsiyyf9934458.shtml`
- 江苏银行 2025 annual report and research summary: `https://stockmc.xueqiu.com/202604/600919_20260429_X7YV.pdf`, `https://www.fxbaogao.com/detail/5402167`
- 杭州银行 2025 annual report and research summary: `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12154354&stockid=600926`, `https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/830278015172/index.phtml`
- 成都银行 2025 result coverage and research summary: `https://finance.sina.com.cn/jjxw/2026-04-22/doc-inhvkupw9240070.shtml`, `https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/830260383521/index.phtml`
- 常熟银行 2025 annual report and research summary: `http://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-24/601128_20260424_5AUA.pdf`, `https://www.nxny.com/report/view_6273702.html`
