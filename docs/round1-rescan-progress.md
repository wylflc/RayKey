# A-Share Round-1 Full Rescan — Progress & Handoff

Round-1 three-class triage (`worth_attention` / `boundary_pending` / `garbage`) over the full A-share universe under the ADR-0006 standard. Model judgment, batched, resumable. This note is a snapshot plus handoff; the **live source of truth is the data files**, not this snapshot.

## Source of truth (live)

- **Standard:** `docs/000_Ashare_workflow.md` §5.4 — 5.4.1 总体原则 / 5.4.2 三类定义 / 5.4.3 garbage 条件 / 5.4.4 输出字段 / 5.4.5 行业校准锚（规则 1-12 + 防过度纳入清单及豁免）/ 5.4.6 执行流程; and `docs/adr/0006-round-1-three-class-triage-standard.md`.
- **Worked calibration examples:** `docs/peer-group-calibration/a-share-baijiu.md` §1.10, `a-share-display-devices.md` §1.5, `a-share-decoration-construction.md` §1.5.
- **Worklist:** `data/interim/a_share_full_rescan_queue.csv` (priority-ordered, full universe).
- **Output (this round):** `data/processed/a_share_attention_triage.csv` (§5.4.4 fields).
- **Audit:** `data/processed/a_share_workflow_decision_log.csv` (`workflow_stage = attention_triage`).

## Snapshot (as of 2026-07-07)

| Class | Done |
| --- | ---: |
| worth_attention | 180 |
| boundary_pending | 748 |
| garbage | 16 (governance_fraud 2 / structural_industry 14) |
| **Total triaged** | **944 / 5653** |

Remaining: `1_worth_attention` (prior worth_attention) **333** · `2_ex_l5_boundary` **421** · `3_unreviewed` **3955**.

Batches done: 3 industry-calibration batches (baijiu 21, panel 8, decoration 15) + 36 priority-1 batches (900). Cadence 25/batch.

### Current worth_attention pool (180)

- **品牌消费:** 贵州茅台·五粮液·山西汾酒·泸州老窖·洋河股份(白酒) · 重庆啤酒(嘉士伯品牌矩阵/区域垄断) · 青岛啤酒(啤酒寡头/百年品牌基地市场) · 东阿阿胶·云南白药·华润三九(中药/OTC) · 同仁堂·片仔癀(传承品牌中药) · 羚锐制药(骨科贴膏品类垄断) · 华润江中(健胃消食片品类垄断) · 马应龙(痔疮药品类垄断) · 美的集团·格力电器·苏泊尔(家电/炊具) · 海尔智家(白电全球品牌/冰洗第一) · 双汇发展(肉制品) · 伊利股份(乳业双寡头) · 海天味业(调味品龙头) · 养元饮品(核桃乳品类垄断) · 公牛集团(转换器墙开品类垄断/百万终端渠道) · 安孚科技(南孚碱电品类垄断) · 汤臣倍健(VDS/膳食营养补充剂) · 乖宝宠物(宠物食品品牌) · 安克创新(消费电子品牌出海) · 春风动力(全球动力运动品牌出海)
- **垄断/稀缺资源:** 藏格矿业·盐湖股份(盐湖钾锂) · 锡业股份(全球锡) · 赣锋锂业·天齐锂业·中矿资源(全球锂资源/锂盐/小金属) · 天山铝业(电解铝产能红线/低成本一体化) · 北方稀土(轻稀土配额/最低成本) · 紫金矿业(铜金全球储量/并购整合) · 中国神华(煤炭产能指标/自有铁路一体化) · 中国海油(海上油气专营/桶油低成本) · 宝丰能源(煤制烯烃指标约束/成本曲线最低) · 金石资源(萤石采矿证稀缺/储量第一) · 长江电力(长江梯级水电物理独占/联调超额回报)
- **军工高壁垒电子:** 振华科技·航天电器·中航光电(器件/连接器) · 紫光国微(军工FPGA) · 海格通信(军工通信/北斗) · 宏达电子(军用钽电容)
- **AI/半导体/高端电子:** 沃尔核材(高速铜连接) · 顺络电子(高端电感) · 通富微电(先进封装) · 福晶科技(光学晶体) · 光迅科技(光器件/光芯片) · 中际旭创·新易盛(高速光模块) · 天孚通信(AI光通信无源器件) · 北方华创(半导体设备) · 晶盛机电(晶体生长/半导体设备) · 长川科技(半导体测试设备/ATE) · 圣邦股份(模拟IC平台) · 江丰电子(超高纯靶材) · 东山精密(AI PCB/FPC/光模块制造) · 沪电股份·深南电路·鹏鼎控股·胜宏科技(AI高速PCB/封装基板) · 生益科技(覆铜板全球双寡头) · 雅克科技(半导体材料/前驱体) · 南大光电(前驱体/电子特气/光刻胶材料) · 鼎龙股份(CMP/半导体材料) · 中瓷电子·三环集团(电子陶瓷/高端封装材料) · 江海股份(高端电容器) · 扬杰科技(功率分立器件IDM) · 高德红外(红外/特种光电) · 景嘉微(国产GPU/军工计算) · 华大九天(国产EDA平台) · 利亚德·洲明科技(全球LED显示平台) · 诺瓦星云(LED显示控制系统垄断) · 长电科技(封测全球前三/先进封装) · 豪威集团(CIS全球三寡头/车载第一) · 中科曙光(海光CPU/DCU吸并整合中) · 法拉电子(薄膜电容全球龙头) · 宏发股份(继电器全球第一)
- **软件/硬件生态:** 大华股份·海康威视(安防AIoT) · 石基信息(酒店信息系统) · 广联达(造价软件/工程数字化) · 深信服(网络安全/企业云) · 中科创达(嵌入式OS/智能汽车软件) · 奔图科技(国产打印生态)
- **科技/装备龙头:** 中兴通讯·紫光股份(新华三) · 大族激光 · 汇川技术(工业自动化/工控) · 麦克奥迪(高压绝缘/精密仪器) · 炬华科技(能源IoT/智能电表) · 三花智控(全球热管理) · 汉钟精机(压缩机/真空泵) · 华明装备(分接开关) · 水晶光电(精密光学) · 英维克(AIDC液冷/温控) · 奥普光电(军工光电) · 杭氧股份(空分设备/工业气体) · 中泰股份(深冷/LNG装备) · 江苏神通(核电/特种阀门) · 豪迈科技(轮胎模具/大型零部件) · 伊之密(高端成型装备) · 先导智能(锂电装备平台) · 中密控股(高端机械密封) · 美亚光电(色选机品类垄断) · 华测导航(高精度GNSS定位) · 亿联网络(SIP话机全球垄断) · 帝尔激光(光伏激光设备垄断) · 国电南瑞(电网二次设备事实标准) · 福耀玻璃(汽车玻璃全球垄断) · 恒立液压(高压液压件/穿越周期验证) · 景津装备(压滤机全球垄断) · 海兴电力(海外AMI渠道/本地化制造)
- **资本周期龙头(规则6):** 京东方A·TCL科技(面板) · 中联重科·徐工机械·三一重工·潍柴动力·中国重汽(机械/重卡) · 宇通客车(全球客车龙头) · 中国船舶(造船总装不可逆整合)
- **金融/金融科技:** 宁波银行·招商银行(优质franchise银行) · 同花顺(金融数据/交易工作流) · 东方财富(互联网券商/财富平台) · 恒生电子(证券资管核心系统事实标准)
- **医药/生物/医疗服务:** 长春高新(金赛) · 华兰生物(浆站) · 上海莱士(血液制品) · 天坛生物(浆站资源第一) · 恒瑞医药(创新药平台) · 恩华药业(CNS/麻醉精神药) · 科伦药业(输液/ADC创新药) · 东诚药业(核药) · 凯莱英(CDMO) · 康龙化成(全流程CXO) · 泰格医药(临床CRO) · 药明康德(CXO全球平台/CRDMO) · 迈瑞医疗(器械平台龙头) · 鱼跃医疗(家用医疗器械) · 爱尔眼科(眼科连锁) · 我武生物(过敏原免疫治疗) · 兴齐眼药(独家眼科品种) · 健帆生物(血液灌流品类垄断) · 艾德生物(伴随诊断第一) · 爱美客(注射类医美/三类证壁垒) · 隆平高科(种业/转基因)
- **农牧服务:** 海大集团(饲料/养殖服务平台)
- **化工寡头/特种材料:** 新和成(维生素) · 蓝晓科技(吸附分离树脂/工艺包) · 安琪酵母(酵母全球寡头) · 瑞丰新材(润滑油添加剂全球第四极) · 钢研高纳(航空高温合金) · 中航高科(航空复材预浸料近垄断)
- **平台网络:** 分众传媒(电梯广告点位网络) · 芒果超媒(长视频内容生态)
- **垂直数据平台:** 上海钢联(大宗商品数据/工作流)
- **物流网络:** 顺丰控股(直营时效物流/综合供应链)
- **精密制造平台:** 立讯精密(消费电子/AI硬件精密制造)
- **新能源/电池链:** 宁德时代(全球动力电池绝对龙头) · 比亚迪(新能源车/磷酸铁锂/垂直整合) · 阳光电源(光伏逆变器/储能电力电子) · 亿纬锂能(二线电池平台/储能圆柱) · 新宙邦(电池特种化学品) · 当升科技(高端正极/固态材料)
- **专业服务:** 华测检测(检测认证) · 电科院(电气检测认证) · 中国汽研(汽车强制检测认证牌照)
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
