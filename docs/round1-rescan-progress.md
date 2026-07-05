# A-Share Round-1 Full Rescan — Progress & Handoff

Round-1 three-class triage (`worth_attention` / `boundary_pending` / `garbage`) over the full A-share universe under the ADR-0006 standard. Model judgment, batched, resumable. This note is a snapshot plus handoff; the **live source of truth is the data files**, not this snapshot.

## Source of truth (live)

- **Standard:** `docs/000_Ashare_workflow.md` §5.4 — 5.4.1 总体原则 / 5.4.2 三类定义 / 5.4.3 garbage 条件 / 5.4.4 输出字段 / 5.4.5 行业校准锚（规则 1-12 + 防过度纳入清单及豁免）/ 5.4.6 执行流程; and `docs/adr/0006-round-1-three-class-triage-standard.md`.
- **Worked calibration examples:** `docs/peer-group-calibration/a-share-baijiu.md` §1.10, `a-share-display-devices.md` §1.5, `a-share-decoration-construction.md` §1.5.
- **Worklist:** `data/interim/a_share_full_rescan_queue.csv` (priority-ordered, full universe).
- **Output (this round):** `data/processed/a_share_attention_triage.csv` (§5.4.4 fields).
- **Audit:** `data/processed/a_share_workflow_decision_log.csv` (`workflow_stage = attention_triage`).

## Snapshot (as of 2026-07-05)

| Class | Done |
| --- | ---: |
| worth_attention | 117 |
| boundary_pending | 311 |
| garbage | 16 (governance_fraud 2 / structural_industry 14) |
| **Total triaged** | **444 / 5653** |

Remaining: `1_worth_attention` (prior worth_attention) **833** · `2_ex_l5_boundary` **421** · `3_unreviewed` **3955**.

Batches done: 3 industry-calibration batches (baijiu 21, panel 8, decoration 15) + 16 priority-1 batches (400). Cadence 25/batch.

### Current worth_attention pool (117)

- **品牌消费:** 贵州茅台·五粮液·山西汾酒·泸州老窖·洋河股份(白酒) · 东阿阿胶·云南白药·华润三九(中药/OTC) · 美的集团·格力电器·苏泊尔(家电/炊具) · 双汇发展(肉制品) · 汤臣倍健(VDS/膳食营养补充剂)
- **垄断/稀缺资源:** 藏格矿业·盐湖股份(盐湖钾锂) · 锡业股份(全球锡) · 赣锋锂业·天齐锂业·中矿资源(全球锂资源/锂盐/小金属) · 天山铝业(电解铝产能红线/低成本一体化)
- **军工高壁垒电子:** 振华科技·航天电器·中航光电(器件/连接器) · 紫光国微(军工FPGA) · 海格通信(军工通信/北斗)
- **AI/半导体/高端电子:** 沃尔核材(高速铜连接) · 顺络电子(高端电感) · 通富微电(先进封装) · 福晶科技(光学晶体) · 光迅科技(光器件/光芯片) · 中际旭创(高速光模块) · 天孚通信(AI光通信无源器件) · 北方华创(半导体设备) · 晶盛机电(晶体生长/半导体设备) · 东山精密(AI PCB/FPC/光模块制造) · 沪电股份·深南电路·鹏鼎控股·胜宏科技(AI高速PCB/封装基板) · 雅克科技(半导体材料/前驱体) · 南大光电(前驱体/电子特气/光刻胶材料) · 鼎龙股份(CMP/半导体材料) · 中瓷电子·三环集团(电子陶瓷/高端封装材料) · 江海股份(高端电容器) · 高德红外(红外/特种光电) · 景嘉微(国产GPU/军工计算) · 利亚德·洲明科技(全球LED显示平台)
- **软件/硬件生态:** 大华股份·海康威视(安防AIoT) · 石基信息(酒店信息系统) · 广联达(造价软件/工程数字化) · 深信服(网络安全/企业云) · 中科创达(嵌入式OS/智能汽车软件) · 奔图科技(国产打印生态)
- **科技/装备龙头:** 中兴通讯·紫光股份(新华三) · 大族激光 · 汇川技术(工业自动化/工控) · 麦克奥迪(高压绝缘/精密仪器) · 炬华科技(能源IoT/智能电表) · 三花智控(全球热管理) · 汉钟精机(压缩机/真空泵) · 华明装备(分接开关) · 水晶光电(精密光学) · 英维克(AIDC液冷/温控) · 奥普光电(军工光电) · 杭氧股份(空分设备/工业气体) · 中泰股份(深冷/LNG装备) · 江苏神通(核电/特种阀门) · 豪迈科技(轮胎模具/大型零部件) · 伊之密(高端成型装备) · 先导智能(锂电装备平台) · 中密控股(高端机械密封) · 美亚光电(色选机品类垄断)
- **资本周期龙头(规则6):** 京东方A·TCL科技(面板) · 中联重科·徐工机械·潍柴动力·中国重汽(机械/重卡)
- **金融/金融科技:** 宁波银行 · 同花顺(金融数据/交易工作流) · 东方财富(互联网券商/财富平台)
- **医药/生物/医疗服务:** 长春高新(金赛) · 华兰生物(浆站) · 上海莱士(血液制品) · 恩华药业(CNS/麻醉精神药) · 科伦药业(输液/ADC创新药) · 东诚药业(核药) · 凯莱英(CDMO) · 泰格医药(临床CRO) · 鱼跃医疗(家用医疗器械) · 爱尔眼科(眼科连锁) · 我武生物(过敏原免疫治疗) · 隆平高科(种业/转基因)
- **农牧服务:** 海大集团(饲料/养殖服务平台)
- **化工寡头/特种材料:** 新和成(维生素) · 蓝晓科技(吸附分离树脂/工艺包)
- **平台网络:** 分众传媒(电梯广告点位网络) · 芒果超媒(长视频内容生态)
- **垂直数据平台:** 上海钢联(大宗商品数据/工作流)
- **物流网络:** 顺丰控股(直营时效物流/综合供应链)
- **精密制造平台:** 立讯精密(消费电子/AI硬件精密制造)
- **新能源/电池链:** 比亚迪(新能源车/磷酸铁锂/垂直整合) · 阳光电源(光伏逆变器/储能电力电子) · 亿纬锂能(二线电池平台/储能圆柱) · 新宙邦(电池特种化学品) · 当升科技(高端正极/固态材料)
- **专业服务:** 华测检测(检测认证) · 电科院(电气检测认证)
- **高可靠连接:** 永贵电器(轨交/新能源高可靠连接器)
- **智能汽车:** 华阳集团(智能座舱/HUD) · 德赛西威(座舱/智驾域控)

## How to resume (for Codex)

Follow `docs/000_Ashare_workflow.md` §5.4.6. Per batch: take the next 25 un-triaged companies from the queue by priority order, judge each **independently** under §5.4 + the §5.4.5 anchors and anti-over-inclusion checklist plus rule-12 exceptions (light triage — business model + durable hard-to-replicate moat + obvious negatives; if the reason is mainly research value, theme exposure, cyclical recovery, scale without pricing power, or self-hedged language such as "需跟踪/可研究", classify as `boundary_pending` unless it meets the品类垄断 or capped-capacity 低成本龙头 exception), append to the triage CSV, append one batch row to the decision log, and commit with a one-sentence message.

Recompute live progress / get the next batch:

```python
import csv, collections
tri=list(csv.DictReader(open("data/processed/a_share_attention_triage.csv",encoding="utf-8-sig")))
done={r["security_code"].zfill(6) for r in tri}
print(collections.Counter(r["attention_class"] for r in tri), "done", len(done))
q=list(csv.DictReader(open("data/interim/a_share_full_rescan_queue.csv",encoding="utf-8-sig")))
nxt=[r for r in q if r["security_code"].zfill(6) not in done][:25]  # priority-ordered
```

## Handoff notes

1. `worth_attention` is **model judgment, not a threshold script** (ADR-0004/0006).
2. Priority order: re-judge prior worth_attention first, then the 421 ex-L5 (temporarily reclassified to boundary), then the unreviewed.
3. `garbage` rows that carry `需核验` in `evidence_basis` rest on documented fraud/governance history — confirm against filings before freezing.
4. After the whole universe is triaged, run **L1–L5 tiering (§5.7/§5.8) on the worth_attention set only** (stage 1, step 2).
5. Established calibration anchors (§5.4.5): brand-moat must be proven through a downcycle (baijiu); capex-cyclical with irreversible structural consolidation → worth_attention (panel, rule 6); structural_industry garbage applies even to the relative leader (decoration, rule 8); infrastructure monopoly with regulated returns → boundary (rule 9); extreme licence but regulated returns e.g. nuclear → boundary (rule 10); only best-run franchise banks → worth_attention (rule 11);品类垄断 and capped-capacity 低成本龙头 can remain worth_attention when excess returns are already verified (rule 12).
6. **worth_attention is strict — run the 防过度纳入清单 (§5.4.5) every batch.** A 2026-06-30 audit found drift toward over-inclusion; 7 names were reclassified to boundary (中国广核·安宁股份·科华数据·科士达·伊戈尔·华亚智能·兆威机电). A 2026-07-01 follow-up audit reclassified 12 names, then restored 3 over-corrections (美亚光电·广联达·天山铝业). Net 9 additional names remain downgraded (科大讯飞·双环传动·光启技术·博实股份·埃斯顿·康弘药业·恩捷股份·科达利·雷赛智能). Disqualifiers: "research value" is not the bar; a moat note that hedges (规模弱/需跟踪/景气受益/可研究) → boundary; strong position ≠ excess-return moat; resources need scarcity + low cost + scale unless rule 12 applies; a smaller peer cannot be worth_attention when a larger one is already boundary.
