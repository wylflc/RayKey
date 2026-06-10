# AShareQuant

AShareQuant is a research and data-analysis project for listed companies in mainland China, Hong Kong, and U.S. equity markets.

The project is intended to support a reproducible equity-research workflow: build an investable universe, identify companies worth following based on durable business quality, collect market and fundamental data, and keep the analysis auditable over time.

## Scope

- Build and maintain universes for A-share, Hong Kong, and U.S. listed securities.
- Distinguish listed companies from their tradable securities, share classes, exchanges, and identifiers.
- Screen listed companies for durable business advantages before any valuation decision.
- Track watchlists as research outputs, not as buy recommendations.
- Collect historical market data including daily open, high, low, close, volume, and related trading fields.
- Track corporate actions such as dividends, splits, bonus shares, rights issues, and other events that affect historical comparability.
- Collect financial report data and disclosure timelines, including forecast, pre-announcement, and official announcement dates where available.

## Principles

- Keep raw source records separate from normalized data and derived signals.
- Preserve data provenance: provider, retrieval time, raw identifier, exchange, currency, reporting period, and adjustment policy.
- Treat trading calendars, suspensions, corporate actions, and identifier mapping as first-class data concerns.
- Keep business-quality screening separate from valuation assessment.
- Avoid committing credentials, paid-data access details, cookies, or private account identifiers.

## Project Docs

- `AGENTS.md` contains repository-specific instructions for coding agents.
- `CONTEXT.md` defines the stable domain language used by the project.
- `.agents/skills/equity-research-workflow/SKILL.md` contains reusable workflow guidance for future agent work in this repository.
- `.agents/` and `.codex/` are local agent workspaces and are intentionally ignored by Git.

## Development Workflow

Read the project docs before making changes. After modifying files, run the most targeted useful local check available and commit the completed change batch. Do not push to a remote unless explicitly requested.

## Scripts

Fetch the current mainland China A-share security universe:

```bash
python3 scripts/fetch_a_share_universe.py --output data/raw/a_share_securities.csv
```

The CSV records security code, exchange, board, listed-company name, security name, listing date, industry, region, source provider, retrieval time, and raw provider identifier useful for later screening.

Fetch the current Hong Kong listed equity security universe:

```bash
python3 scripts/fetch_hong_kong_universe.py --output data/raw/hong_kong_securities.csv
```

The Hong Kong CSV is security-level and keeps separate counters, share classes, and trading currencies as separate **Hong Kong Securities**.

Fetch the current U.S. listed security universe:

```bash
python3 scripts/fetch_us_universe.py --output data/raw/us_securities.csv
```

The U.S. CSV combines Nasdaq Trader `nasdaqlisted.txt` and `otherlisted.txt`, excludes provider test issues by default, and keeps ETF/status/exchange fields for later screening.

Run the legacy first-pass moat screening for A-share and Hong Kong securities:

```bash
python3 scripts/run_moat_screening.py
```

This legacy script reads manually curated evidence from `data/interim/moat_screening_evidence.csv` and writes `data/processed/moat_watchlist_candidates.csv`. That candidate file is kept for audit/history, but it is not the canonical current watchlist. Use the full-coverage market-specific outputs below for current A-share, Hong Kong, and U.S. screening.

The screening workflow keeps `data/raw/` immutable. Source-backed research evidence belongs in `data/interim/`; generated screening outputs belong in `data/processed/`.

For the A-share, Hong Kong, and U.S. universes, the target workflow is now a **Two-Layer Company Review**. The first layer keeps full-universe coverage through baseline triage: every listed security receives an explicit screening status, and every eligible listed-company common-equity security receives a preliminary business-quality review unless it meets the narrow **Insufficient Disclosure** definition. The second layer performs a full **Deep Company Review** for companies with `triage_score >= 65`, companies marked `borderline`, and companies explicitly challenged by a reviewer.

The existing `full_coverage_dimensional_v0.4` scoring model is a baseline triage aid, not the final watchlist decision model. It has seven dimensions: business moat, technology/product/process barrier, market position, business quality, operating quality, industry outlook/cyclicality/compounding profile, and governance risk. Deep reviews must use authoritative research sources such as company periodic reports, exchange announcements, regulator disclosures, official investor-relations materials, reputable institution reports, or professional research reports. Aggregator company introductions are discovery hints only, not scoring evidence. See `docs/moat-scoring-rubric.md`, `docs/adr/0002-use-full-coverage-dimensional-moat-scoring.md`, and `docs/adr/0003-adopt-two-layer-company-review.md`.

Build the current two-layer company triage and second-layer deep-review queue:

```bash
python3 scripts/run_two_layer_company_review.py
```

The script reads the market-specific full-coverage score files and optional reviewer challenges from `data/interim/deep_review_challenges.csv`. It writes `data/processed/company_triage_reviews.csv` as the company-level first-layer triage output and `data/interim/deep_review_queue.csv` as the pending second-layer review queue. The queue is not a final watchlist; it is the auditable worklist for full deep reviews using authoritative sources. Reviewer-challenged companies enter the queue even when the baseline triage score is below the normal threshold.

During calibration, run markets separately. A-share is the first calibration market:

```bash
python3 scripts/run_two_layer_company_review.py --markets A_SHARE --triage-output data/processed/a_share_company_triage_reviews.csv --queue-output data/interim/a_share_deep_review_queue.csv
python3 scripts/audit_a_share_review_standard.py
```

The A-share run writes `data/processed/a_share_company_triage_reviews.csv` and `data/interim/a_share_deep_review_queue.csv`. The audit writes `data/processed/a_share_review_standard_audit.csv`, checking A-share-only scope, universe coverage, queue construction, score-band distribution, and reviewer-challenge routing. Passing this audit only validates the workflow structure. Reviewer-challenged companies are not calibration anchors merely because they were named; reusable rules should come from peer-group calibration, where similar companies in one industry are compared side by side before the reviewer decides which deserve continued attention.

The first A-share peer-group calibration output is baijiu:

- `data/processed/a_share_baijiu_peer_group_calibration.csv`
- `data/processed/a_share_baijiu_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-baijiu.md`

The second A-share peer-group calibration output is EV batteries and new-energy platforms:

- `data/processed/a_share_ev_battery_peer_group_calibration.csv`
- `data/processed/a_share_ev_battery_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-ev-battery.md`

The third A-share peer-group calibration output is high-end medical devices and medical-device platforms:

- `data/processed/a_share_medical_device_peer_group_calibration.csv`
- `data/processed/a_share_medical_device_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-medical-device.md`

The fourth A-share peer-group calibration output is listed banks:

- `data/processed/a_share_bank_peer_group_calibration.csv`
- `data/processed/a_share_bank_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-bank.md`

The fifth A-share peer-group calibration output is semiconductor equipment:

- `data/processed/a_share_semiconductor_equipment_peer_group_calibration.csv`
- `data/processed/a_share_semiconductor_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-semiconductor-equipment.md`

The sixth A-share peer-group calibration output is strategic resources and mining:

- `data/processed/a_share_strategic_resources_peer_group_calibration.csv`
- `data/processed/a_share_strategic_resources_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-strategic-resources.md`

The seventh A-share peer-group calibration output is lithium resources and lithium salts:

- `data/processed/a_share_lithium_resource_peer_group_calibration.csv`
- `data/processed/a_share_lithium_resource_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-lithium-resource.md`

This group separates lithium resource ownership and lithium-salt capacity from broader EV batteries, cathode materials, battery recycling, and strategic-resource mining rules.

The eighth A-share peer-group calibration output is battery materials and nickel-cobalt integration:

- `data/processed/a_share_battery_materials_peer_group_calibration.csv`
- `data/processed/a_share_battery_materials_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-battery-materials.md`

This group compares precursor, nickel-cobalt resource integration, electrolyte, separator, anode, coating, and cathode companies. Boundary companies are judged by margin quality, product technical content, whether a larger competitor could easily copy the business, and whether the company has a durable local industrial advantage.

The ninth A-share peer-group calibration output is CXO and pharmaceutical R&D outsourcing:

- `data/processed/a_share_cxo_peer_group_calibration.csv`
- `data/processed/a_share_cxo_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-cxo.md`

This group compares CRDMO, CRO, CDMO, clinical CRO, SMO, molecular-building-block, and pharmaceutical R&D service companies. Boundary companies are judged by margin quality, technical or service complexity, customer trust, regulatory/quality-system history, project continuity, and whether a larger retained platform could easily copy the service.

The tenth A-share peer-group calibration output is infrared thermal imaging and special optoelectronic sensing:

- `data/processed/a_share_infrared_sensing_peer_group_calibration.csv`
- `data/processed/a_share_infrared_sensing_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-infrared-sensing.md`

This group is the first carved-out subgroup from the broad residual electronic-equipment queue. It compares infrared detector, thermal imaging, laser/optical, and special optoelectronic sensing companies. High industry barrier does not imply automatic inclusion; weaker companies are rejected when their role is covered by stronger retained leaders.

The eleventh A-share peer-group review output is residual electronic equipment manufacturing:

- `data/processed/a_share_electronic_equipment_manufacturing_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-electronic-equipment-manufacturing.md`

This group applies company-by-company analyst judgment to the broad residual electronic-equipment group. It retains clear hard-technology platforms and distinct boundary niches, rejects replaceable EMS/component/application vendors, and records defense-electronics questions in `docs/peer-group-calibration/a-share-pending-questions.md` for later dedicated handling.

The twelfth A-share peer-group review output is industry application software:

- `data/processed/a_share_industry_application_software_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-industry-application-software.md`

This group separates hard software products and vertical workflow anchors from project-heavy system integrators. It retains EDA, industrial control, energy IT, cybersecurity, AI, financial core systems, construction software, CAD/CAE/PDF, GIS, and selected high-switching-cost vertical software while deferring aerospace and defense-software questions.

The thirteenth A-share peer-group review output is other software services:

- `data/processed/a_share_other_software_services_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-software-services.md`

This group keeps only product, infrastructure, workflow, or hard-domain software platforms. It rejects generic IT services, outsourcing, project delivery, and weaker copies, while deferring aviation, traffic-control, and defense-cyber cases.

The fourteenth A-share peer-group review output is biopharma:

- `data/processed/a_share_biopharma_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-biopharma.md`

This group separates global innovative-drug platforms, scarce biological-resource platforms, IVD, companion diagnostics, life-science tools, bioactive materials, vaccines, and weaker early-pipeline companies. Current profit is not the primary screen; clinical/regulatory validation and hard-to-replicate capability are the core tests.

The fifteenth A-share peer-group review output is electronic components:

- `data/processed/a_share_electronic_components_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-electronic-components.md`

This group separates PCB/material leaders, passive and high-reliability components, optical/RF/MEMS/power niches, and weaker duplicate manufacturers. Process know-how, customer qualification, reliability history, and high-end product mix are the core tests.

The sixteenth A-share peer-group review output is the remaining medical-device group:

- `data/processed/a_share_medical_device_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-medical-device-remaining.md`

This pass applies the earlier medical-device calibration to the rest of the device universe. It keeps selected platform and high-barrier niche companies, while rejecting low-barrier consumables, weaker IVD copies, distribution-led businesses, and capacity-driven manufacturers.

The seventeenth A-share peer-group review output is environmental services:

- `data/processed/a_share_environmental_services_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-environmental-services.md`

This group is treated as utility-like rather than high-growth. It keeps only selected concession/operator platforms and differentiated membrane or hazardous-waste technology cases, while rejecting ordinary engineering, sanitation, restoration, and project-contracting companies.

The eighteenth A-share peer-group review output is integrated circuits:

- `data/processed/a_share_integrated_circuit_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-integrated-circuit.md`

This group separates foundry, OSAT, advanced packaging, analog, RF, image sensors, memory/MCU, SoC, communications chips, GPU, FPGA, semiconductor IP, and weaker fabless copies. Strategic compute and semiconductor-platform capability can qualify even before mature profitability.

The nineteenth A-share peer-group review output is chemical formulations:

- `data/processed/a_share_chemical_formulation_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-chemical-formulation.md`

This group separates innovative-drug platforms, branded OTC and specialty pharma, differentiated niches, generic-drug manufacturers, and weaker formulation companies. Innovation, clinical/channel trust, brand, and integrated capability matter more than current profit alone.

The twentieth A-share peer-group review output is auto parts:

- `data/processed/a_share_auto_parts_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-auto-parts.md`

This group separates intelligent vehicle electronics, safety-critical braking/chassis, drivetrain, powertrain, automotive glass, thermal management, lighting, lightweighting, sensors, and low-barrier component manufacturing. Global OEM validation, safety certification, software/electronics depth, and hard manufacturing process are the core tests.

The twenty-first A-share peer-group review output is traditional Chinese medicine:

- `data/processed/a_share_traditional_chinese_medicine_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-traditional-chinese-medicine.md`

This group separates national/category-defining TCM brands, modern evidence-backed TCM platforms, focused OTC niches, and weaker regional or duplicative companies. Brand, scarce formula, category leadership, pricing power, and channel trust are the core tests.

The twenty-second A-share peer-group review output is API and chemical raw drugs:

- `data/processed/a_share_api_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-api.md`

This group separates API-CDMO platforms, regulated API manufacturers, sterile injectable platforms, radiopharmaceuticals, vitamins, excipients, contrast-agent APIs, and commodity intermediates. Process development, quality systems, regulatory filings, customer validation, cost position, and scarce licenses are the core tests.

The twenty-third A-share peer-group review output is consumer electronics:

- `data/processed/a_share_consumer_electronics_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-consumer-electronics.md`

This group separates global EMS/ODM platforms, terminal brands, cross-border brands, optical-display leaders, AI/5G modules, high-end audio niches, legacy consumer-electronics groups, distributors, accessories, and structural-part suppliers. Global platform scale, leading-customer qualification, semiconductor/system capability, differentiated terminal ecosystems, and distinct niche brands or modules are the core tests.

The twenty-fourth A-share peer-group review output is solar:

- `data/processed/a_share_solar_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-solar.md`

This group separates photovoltaic power electronics, equipment, glass, encapsulation materials, wafers, polysilicon, integrated modules, power-station operators, EPC/system integration, late pivots, and low-barrier component suppliers. Global leadership, cost curve, hard process know-how, bankability, and specialty material or equipment barriers are the core tests; cycle-trough profitability is not the primary screen.

The twenty-fifth A-share peer-group review output is other electronic devices:

- `data/processed/a_share_other_electronic_devices_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-electronic-devices.md`

This mixed group separates distributors, polymer and EMI/thermal materials, PCB/interconnect platforms, PMIC and MEMS chips, RF connectors, acoustic components, vacuum electronics, microwave devices, display technologies, portable energy-storage brands, fuses, and ordinary consumer-electronics components. Proprietary materials, hard-technology niches, customer certification, cross-industry capability, and whether stronger retained peers already cover the thesis are the core tests.

The twenty-sixth A-share peer-group review output is communication transmission equipment:

- `data/processed/a_share_communication_transmission_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-communication-transmission.md`

This group separates telecom equipment, optical modules, optical chips/devices, optical fiber/preform/cable, submarine cable, industrial IoT gateways, cellular modules, RF filters, integrated photonics, special communication, industrial networking, high-reliability connectors, test instruments, ceramic filters, and legacy communication-equipment vendors. Network-infrastructure leadership, AI/data-center optical interconnects, deep-sea optical networks, special communication, and high-speed interconnect barriers are the core tests.

The twenty-seventh A-share peer-group review output is pharmaceutical commerce:

- `data/processed/a_share_pharma_commerce_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-pharma-commerce.md`

This group separates integrated pharmaceutical industrial platforms, ordinary regional distribution, national regulated distribution platforms, leading pharmacy chains, medical-brand commercialization platforms, diagnostics leaders, and companies misclassified into commerce despite stronger drug-discovery or branded-drug capabilities. Distribution scale alone is not enough; regulated qualification, industrial capability, chain consolidation, differentiated commercialization, and real technology platforms are the core tests.

The twenty-eighth A-share peer-group review output is the remaining storage-equipment group:

- `data/processed/a_share_storage_equipment_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-storage-equipment-remaining.md`

This pass completes the companies in `电气设备-电源设备-储能设备` that were not already decided in the EV-battery calibration pass. It separates digital-energy and UPS/data-center power platforms, storage-system and power-electronics platforms, special/aerospace power, BMS/PACK, inverter/storage niches, lithium-equipment niches, consumer-battery brands, ordinary battery manufacturing, lead-acid replacement markets, weak storage integrators, and late pivots.

The twenty-ninth A-share peer-group review output is other special machinery:

- `data/processed/a_share_other_special_machinery_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-special-machinery.md`

This pass reviews all companies in `机械设备-专用设备-其他专用机械`. It separates hard-to-replicate process equipment, semiconductor and advanced-manufacturing tools, photovoltaic/lithium process equipment, precision thermal-control and testing platforms, qualification-heavy safety/nuclear equipment, cross-industry capability stacks, ordinary project-based special machines, lower-barrier traditional equipment, and weaker followers already covered by stronger retained peers.

The thirtieth A-share peer-group review output is communication terminal equipment:

- `data/processed/a_share_communication_terminal_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-communication-terminal.md`

This pass reviews all companies in `信息技术-通信设备-通信终端设备`. It separates global enterprise communication endpoint brands, professional/dedicated-network communications, enterprise networking, Beidou/GNSS and defense communications, grid communication niches, secure-card/eSIM, RF/antenna/materials, optical-module boundary cases, ordinary ODM/JDM terminal manufacturing, CPE/STB vendors, mature smart-card followers, and project-based communication system integrators.

The thirty-first A-share peer-group review output is optical components:

- `data/processed/a_share_optical_components_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-optical-components.md`

This pass reviews all companies in `电子设备-光电子器件-光学元件`. It separates AI optical-communication components, photomasks, OLED materials and evaporation-source equipment, precision optics, optical instruments, optical films and functional materials, infrared/sensor niches, laser and military optics, non-leading display panels, camera-module assemblers, low-barrier display/backlight/touch components, and recent optical pivots without proven capability.

The thirty-second A-share peer-group review output is specialized computer equipment:

- `data/processed/a_share_specialized_computer_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-specialized-computer-equipment.md`

This pass reviews all companies in `信息技术-计算机硬件-专用计算机设备`. It separates compute-infrastructure platforms, global automotive diagnostic terminals, LED display-control systems, payment and barcode-recognition platforms, commercial-cryptography hardware, defense embedded-computing equipment, financial self-service machines, data-storage niches, rail and transport terminals, ordinary peripherals, mature financial equipment, video-surveillance followers, and project-based system integrators.

The thirty-third A-share peer-group review output is other power-transmission equipment:

- `data/processed/a_share_power_transmission_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-power-transmission-equipment.md`

This pass reviews all companies in `电气设备-输变电设备-其他输变电设备`. It separates UHV/high-voltage core equipment, full transmission platforms, transformer and tap-changer leadership, inverter and module-level power electronics, low-voltage electrical brands, high-voltage insulation and grid-protection components, smart-distribution niches, ordinary distribution equipment, transmission-tower fabrication, low-barrier relays and components, and ST or diversified cases without scarce grid technology.

The thirty-fourth A-share peer-group review output is semiconductor materials:

- `data/processed/a_share_semiconductor_materials_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-semiconductor-materials.md`

This pass reviews all companies in `电子设备-半导体-半导体材料`. It separates silicon wafers, SiC substrates, CMP materials, electronic specialty gases, precursors, sputtering targets, photomasks, wet electronic chemicals, ceramic/quartz parts, independent testing, foundry/package-adjacent capability, semiconductor laser chips, consumer-electronics materials, IC-card/package commodity parts, diluted non-semiconductor businesses, and weaker silicon-wafer followers.

The thirty-fifth A-share peer-group review output is gas utilities:

- `data/processed/a_share_gas_utilities_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-gas-utilities.md`

This pass reviews all companies in `公用事业-燃气-燃气`. It separates national gas and clean-energy platforms, dense city-gas franchises, LNG supply-chain platforms, provincial pipeline franchises, gas-equipment technology, ordinary small local gas utilities, mixed public-utility portfolios, commodity-exposed gas traders, ST cases, and regional concessions without scale or sourcing advantage.

The thirty-sixth A-share peer-group review output is other internet services:

- `data/processed/a_share_other_internet_services_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-internet-services.md`

This pass reviews all companies in `互联网-互联网服务-其他互联网服务`. It separates cybersecurity platforms, visual-content copyright databases, financial IT, public cloud, industrial internet communication, network visibility, public-safety software, vertical data/content platforms, low-barrier advertising and MCN/live-commerce operators, generic IT outsourcing, game/content hit businesses, platform-dependent traffic services, and system integrators without product or data lock-in.

The thirty-seventh A-share peer-group review output is display devices:

- `data/processed/a_share_display_devices_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-display-devices.md`

This pass reviews all companies in `电子设备-电子器件-显示器件`. It separates global display panel platforms, small/automotive/professional display specialists, substrate glass and polarizer materials, AMOLED/microdisplay, display automation equipment, optical/touch/coating materials, ordinary display modules/backlights, LED display projects, consumer electronics assemblers, ST cases, and mixed businesses without display-platform control.

The thirty-eighth A-share peer-group review output is thermal power:

- `data/processed/a_share_thermal_power_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-thermal-power.md`

This pass reviews all companies in `公用事业-电力-火电`. It separates national generation platforms, high-load regional integrated-energy platforms, coal-power/resource integration, clean-energy transition platforms, ordinary local thermal generators, small heat/cogeneration utilities, weaker duplicate SOE platforms, and broad energy stories without clear platform control.

The thirty-ninth A-share peer-group review output is instruments:

- `data/processed/a_share_instruments_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-instruments.md`

This pass reviews all companies in `机械设备-通用设备-仪器仪表`. It separates high-end electronic measurement, industrial process-control instruments, motion-control platforms, machine-vision/metrology, analytical and mass-spectrometry instruments, differentiated sensors, utility-meter installed-base platforms, lower-barrier metering followers, project-heavy environmental monitoring, generic automation hardware, and small instrument niches without category control.

The fortieth A-share peer-group review output is communication support services:

- `data/processed/a_share_communication_support_services_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-communication-support-services.md`

This pass reviews all companies in `信息技术-通信设备-通信配套服务`. It separates cellular IoT module leadership, quantum communication, special communication and BeiDou/satellite systems, telecom/power surge-protection components, communication construction and O&M services, SMS/value-added telecom channels, generic system integration, ST cases, and mixed IDC/energy/repair service businesses.

The forty-first A-share peer-group review output is remaining battery materials:

- `data/processed/a_share_battery_materials_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-battery-materials.md`

This pass completes the still-unreviewed companies in `有色金属-金属非金属新材料-电池材料` using the already documented battery-material calibration rules. It separates additional high-end cathode, carbon-nanotube conductive additive, electronic silver paste, manganese-material, copper-foil, anode-coating, fuel-cell, and multi-material niches from weaker duplicate cathode, anode, electrolyte, precursor, lithium-salt, battery-structure, and mixed material companies.

The forty-second A-share peer-group review output is other general machinery:

- `data/processed/a_share_other_general_machinery_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-general-machinery.md`

This pass reviews all companies in `机械设备-通用设备-其他通用机械`. It separates global thermal-management parts, lithium-battery equipment, high-end mechanical seals, turbomachinery, filter presses, harmonic reducers, vacuum equipment, cryogenic/LNG equipment, liquid cooling, pumps, compressor systems, special bearings, tank containers, superhard tools, magnetic-levitation turbomachinery, logistics automation, ordinary pump/valve/bearing/gear/tool companies, project automation, ST cases, and mixed general machinery businesses.

The forty-third A-share peer-group review output is food comprehensive:

- `data/processed/a_share_food_comprehensive_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-food-comprehensive.md`

This pass reviews all companies in `食品饮料-食品-食品综合`. It separates category-defining consumer brands, national frozen-food platforms, yeast/fermentation and nutrition-ingredient platforms, pet-food brands, vertically integrated protein supply chains, lower-barrier snack retailers, regional bakery/prepared-food brands, commodity agricultural processors, ST cases, and weak packaged-food brands without pricing power.

The forty-fourth A-share peer-group review output is water utilities:

- `data/processed/a_share_water_utilities_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-water-utilities.md`

This pass reviews all companies in `公用事业-水务-水务`. It separates large-city water and wastewater platforms, national/regional environmental infrastructure platforms, integrated water/waste/gas/solid-waste assets, water-saving irrigation and industrial-water niches, ordinary local water concessions, project-heavy environmental engineering firms, mixed utility portfolios, and ST cases.

The forty-fifth A-share peer-group review output is LED:

- `data/processed/a_share_led_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-led.md`

This pass reviews all companies in `电子设备-光电子器件-LED`. It separates LED chip and compound-semiconductor platforms, global LED display platforms, Mini/MicroLED and packaging technology, LED driver/power component niches, ordinary lighting, city-lighting projects, weak display contractors, commodity chip/packaging followers, mixed lighting businesses, and ST cases.

The forty-sixth A-share peer-group review output is remaining medical services:

- `data/processed/a_share_medical_services_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-medical-services.md`

This pass completes the still-unreviewed companies in `医药生物-医疗服务-医疗服务`. It separates specialist medical chains, third-party medical laboratories, genomics platforms, clinical CRO/data-management niches, dental and neurosurgery specialists, weak duplicate eye hospitals, hospital asset operators, medical cleanroom/engineering providers, small CROs, and ST cases.

The forty-seventh A-share peer-group review output is expressways:

- `data/processed/a_share_expressway_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-expressways.md`

This pass reviews all companies in `交通运输-公路铁路-高速公路`. It separates national toll-road platforms, high-quality coastal and economic-corridor assets, strong provincial expressway platforms, lower-quality regional concessions, mixed real-estate/tourism/investment portfolios, small bridge/road assets, and ordinary local toll concessions.

The forty-eighth A-share peer-group review output is wire and cable:

- `data/processed/a_share_wire_cable_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-wire-cable.md`

This pass reviews all companies in `电气设备-输变电设备-电线电缆`. It separates submarine-cable leaders, high-voltage cable-accessory specialists, UHV transformer material suppliers, aerospace/nuclear/industrial special-cable companies, broad regional cable manufacturers, ordinary construction and power-cable producers, electronic-wire suppliers, and mixed portfolios where cable is no longer the main moat.

The forty-ninth A-share peer-group review output is renewable power:

- `data/processed/a_share_renewable_power_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-renewable-power.md`

This pass reviews all companies in `公用事业-电力-新能源发电`. It separates nuclear power, wind and solar flagship platforms, large central-SOE renewable platforms, provincial renewable operators, private project developers, integrated-energy service companies, EPC and solution providers, and companies whose renewable-power tag is incidental to a different business.

The fiftieth A-share peer-group review output is discrete semiconductors:

- `data/processed/a_share_discrete_semiconductors_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-discrete-semiconductors.md`

This pass reviews all companies in `电子设备-半导体-半导体分立器件`. It separates power-semiconductor IDMs and designers, IGBT and SiC module platforms, HVDC thyristor suppliers, diode and rectifier manufacturers, probe-card and probe-station companies, semiconductor test-equipment suppliers, photonics companies, memory-chip designers, auxiliary semiconductor-equipment subsystems, and mixed transition stories.

The fifty-first A-share peer-group review output is hydropower:

- `data/processed/a_share_hydropower_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-hydropower.md`

This pass reviews all companies in `公用事业-电力-水电`. It separates world-class river-cascade platforms, basin-level hydropower operators, integrated power companies with scarce hydropower exposure, pumped-storage platforms, regional hydropower operators, local power and water utilities, and diversified local utility companies.

The fifty-second A-share peer-group review output is metal products:

- `data/processed/a_share_metal_products_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-metal-products.md`

This pass reviews all companies in `机械设备-金属制品-金属制品`. It separates powder metallurgy, MIM and soft-magnetic materials, global hand tools, battery structural parts, aerospace superalloys, high-end cutting tools, special-alloy materials, high-end pressure vessels, prestressed rail materials, welding materials, magnet wire, wind-power metal parts, semiconductor-equipment precision parts, consumer hardware, metal packaging, wire rope, coated steel sheet, ordinary casting, and generic precision machining.

The fifty-third A-share peer-group review output is ports:

- `data/processed/a_share_ports_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-ports.md`

This pass reviews all companies in `交通运输-港口航运-港口`. It separates national and global port platforms, world-scale deepwater gateways, international container hubs, regional comprehensive ports, bulk ports, emerging strategic gateway ports, single-port container assets, inland ports, and mixed local logistics or utility profiles.

The fifty-fourth A-share peer-group review output is shipping:

- `data/processed/a_share_shipping_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-shipping.md`

This pass reviews all companies in `交通运输-港口航运-航运`. It separates global liner platforms, diversified shipping platforms, energy-shipping leaders, special-cargo shipping, product tanker operators, regional container lines, domestic container logistics, port-backed feeder operators, route-scarcity ferry operators, chemical and dangerous-goods shipping companies, shipping finance/leasing profiles, dry-bulk fleets, forwarding services, and unclear transformed shipping classifications.

The fifty-fifth A-share peer-group review output is electrical automation:

- `data/processed/a_share_electrical_automation_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-electrical-automation.md`

This pass reviews all companies in `电气设备-输变电设备-电气自控设备`. It separates grid automation, relay protection, dispatch and distribution automation, UHV/DC and high-voltage equipment, global relays, industrial control, renewable power conversion, domain-specific automation, distribution switchgear, charging piles, project-heavy power IT, narrow control niches, and weak legacy electrical-equipment companies.

The fifty-sixth A-share peer-group review output is railway equipment:

- `data/processed/a_share_railway_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-railway-equipment.md`

This pass reviews all companies in `交运设备-铁路设备-铁路专用设备及器材`. It separates railway engineering and maintenance equipment, high-speed rail fasteners and track materials, high-reliability connectors, rail signal and safety systems, rail monitoring and inspection equipment, rail vehicle components, maintenance-platform stories, mature rail axle manufacturers, and ST rail-equipment cases.

The fifty-seventh A-share peer-group review output is other power equipment:

- `data/processed/a_share_other_power_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-power-equipment.md`

This pass reviews all companies in `电气设备-电源设备-其他电源设备`. It separates energy-storage systems, high-reliability military and aerospace power supplies, power-electronics testing equipment, clean-energy thermal equipment, power-management ICs, photovoltaic transformers and magnetic components, defense power-electronics cases, charging power modules, generator sets, explosion-proof electrical equipment, communication power supplies, ST cases, and companies already retained under battery materials.

The fifty-eighth A-share peer-group review output is PC, server, and hardware:

- `data/processed/a_share_pc_server_hardware_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-pc-server-hardware.md`

This pass reviews all companies in `信息技术-计算机硬件-PC、服务器及硬件`. It separates global security and video-IoT platforms, AI-server and data-center hardware, strategic domestic CPU architecture, domestic computing and trusted-hardware ecosystem exposure, printer and office-hardware ecosystems, commercial-vehicle video niches, consumer PC brands, legacy flash-storage IP stories, EMS manufacturing services, ST cases, and mixed technology holdings.

The fifty-ninth A-share peer-group review output is game entertainment:

- `data/processed/a_share_game_entertainment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-game-entertainment.md`

This pass reviews all companies in `互联网-互联网服务-游戏娱乐`. It separates self-developed boutique studios, scaled mobile-game publishers, legacy IP operators, MMORPG/RPG developers, social-entertainment and internet-cafe service platforms, acquired game studios, mixed cultural-media groups, and ST turnaround cases. It retains only companies where content, IP, R&D, publishing, long-life operation, or cross-business capability is harder to copy than simply funding a new studio or buying traffic.

The sixtieth A-share peer-group review output is other electrical equipment:

- `data/processed/a_share_other_electrical_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-electrical-equipment.md`

This pass reviews all companies in `电气设备-其他电气设备-其他电气设备`. It separates high-voltage insulation materials, smart-grid diagnostics, intelligent controllers, industrial power electronics, PV trackers, PV modules, wind turbines, storage systems, consumer electrical brands, rail-signal systems, electrical contact materials, battery interconnects, appliance components, PV junction boxes, electrical cabinets, distributors, and ST transition cases. Misclassified company-level platforms are judged by their real business capability rather than by the residual peer-group label.

The sixty-first A-share peer-group review output is other power generation:

- `data/processed/a_share_other_power_generation_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-power-generation.md`

This pass reviews all companies in `公用事业-电力-其他发电`. It separates nuclear power, grid technology services, regional coal-power platforms, provincial energy platforms, local heating utilities, provincial renewable operators, landfill-gas power, energy-finance holding companies, and ST transition cases. It retains scarce regulated assets, grid technology capability, and only selected regional utility platforms with load-center or franchise-like advantages.

The sixty-second A-share peer-group review output is wind power equipment:

- `data/processed/a_share_wind_power_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-wind-power-equipment.md`

This pass reviews all companies in `电气设备-电源设备-风能`. It separates wind-turbine OEMs, wind towers, offshore foundations, wind main shafts, castings, composite wind parts, and companies whose wind label is incidental to renewable-power operation. It retains turbine platforms and selected globally validated or process-critical component suppliers while rejecting ordinary capacity exposure.

The sixty-third A-share peer-group review output is airlines:

- `data/processed/a_share_airlines_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-airlines.md`

This pass reviews all companies in `交通运输-航空机场-航空`. It separates national passenger airlines, low-cost airlines, private full-service airlines, air cargo and logistics platforms, regional airlines, and general-aviation helicopter services. It treats route and hub scarcity as real but discounts the sector's fuel, FX, recession, disease-shock, and capital-intensity risks.

The sixty-fourth A-share peer-group review output is B2B e-commerce:

- `data/processed/a_share_b2b_ecommerce_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-b2b-ecommerce.md`

This pass reviews all companies in `互联网-互联网商务-电子商务B2B`. It separates industrial B2B platforms, commodity data and pricing platforms, cross-border B2B marketplaces, electronic-component supply-chain platforms, cross-border brand operators, e-commerce service providers, brand-licensing models, cashback and marketing platforms, and legacy e-commerce companies. It retains data, workflow, and transaction-network moats while rejecting traffic, service, authorization, and trading models without durable lock-in.

The sixty-fifth A-share peer-group review output is cogeneration and heat power:

- `data/processed/a_share_cogeneration_heat_power_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-cogeneration-heat-power.md`

This pass reviews all companies in `公用事业-电力-热电`. It separates local cogeneration utilities, industrial-park steam suppliers, municipal heating companies, heat-service and energy-saving operators, and mixed local-development or materials companies with incidental heat-power assets. It treats heat power as local utility infrastructure and keeps only selected boundary cases with pipe-network, park-customer, or energy-saving operating advantages.

The sixty-sixth A-share peer-group review output is telecom operators:

- `data/processed/a_share_telecom_operators_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-telecom-operators.md`

This pass reviews all companies in `信息技术-通信运营-通信运营`. It separates national telecom operators, satellite operators, data-center and computing-infrastructure platforms, State Grid information-communication platforms, cloud communication providers, video-conferencing and AI interaction vendors, and telecom-adjacent smart-home service companies. It retains scarce infrastructure control while rejecting ordinary communication-service vendors.

The sixty-seventh A-share peer-group review output is condiments:

- `data/processed/a_share_condiments_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-condiments.md`

This pass reviews all companies in `食品饮料-食品-调味品`. It separates national condiment brands, zero-additive premium brands, hotpot and compound-seasoning brands, vinegar brands, mushroom-sauce and spice niches, B2B restaurant seasoning-solution companies, functional sugar and sugar-alcohol ingredient companies, MSG brands, flavor/additive suppliers, sugar processors, and misclassified transformation stories. It retains category-defining brand/channel moats and selected differentiated ingredient or food-solution niches.

The sixty-eighth A-share peer-group review output is integrated internet services:

- `data/processed/a_share_integrated_internet_services_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-integrated-internet-services.md`

This pass reviews all companies in `互联网-互联网服务-综合互联网服务`. It separates central-SOE digitalization companies, 5G wireless technology companies, AI training-data vendors, smart-campus platforms, environmental IoT and carbon-data platforms, internet marketing services, small IDC/cloud providers, digital-content companies, and provincial digital-media companies. It retains only selected boundary cases with domain workflow, data, customer-access, standards, or regulated-platform evidence.

The sixty-ninth A-share peer-group review output is remaining rare small metals:

- `data/processed/a_share_rare_small_metals_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-rare-small-metals-remaining.md`

This pass completes the remaining undecided companies in `有色金属-稀有金属-其他稀有小金属`. It separates uranium, vanadium-titanium, precious-metal materials and recycling, tantalum-niobium, titanium, molybdenum, silver, nano-metal powder, zirconium, weak lithium/cobalt followers, and transformation-material stories. It corrects low baseline scores where resource scarcity, national-security relevance, aerospace/nuclear qualification, or hard material process technology matters more than current commodity-cycle profit.

The seventieth A-share peer-group review output is remaining other chemical products:

- `data/processed/a_share_other_chemical_products_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-chemical-products-remaining.md`

This pass completes the remaining undecided companies in `基础化工-化学制品-其他化学制品`. It separates platform material capabilities such as organic silicone, titanium/zirconium chemistry, electronic gases, membranes, adsorption resins, OLED and liquid-crystal materials, food ingredients, synthetic biology, chromatography media, fluorochemicals, and molecular sieves from ordinary commodity capacity, coatings, adhesives, water-treatment chemicals, fertilizers, fragrances, and ST transition cases.

The seventy-first A-share peer-group review output is other professional services:

- `data/processed/a_share_other_professional_services_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-professional-services.md`

This pass reviews the remaining companies in `休闲、生活及专业服务-专业服务-其他专业服务`. It separates comprehensive TIC platforms, national electrical and automotive testing institutes, irradiation sterilization, semiconductor production services, construction-science institutes, metallurgy and food-security engineering platforms, and selected scale operating networks from ordinary project consulting, design, HR, municipal outsourcing, exhibition, procurement, and low-barrier service businesses.

The seventy-second A-share peer-group review output is cloud, IDC, and CDN:

- `data/processed/a_share_cloud_idc_cdn_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-cloud-idc-cdn.md`

This pass reviews all companies in `互联网-互联网技术-云服务(含IDC、CDN)`. It separates enterprise-cloud software and CDN/edge-network platforms from capital-intensive data-center operators, smaller cloud-network providers, game-to-cloud transition cases, and ST cloud/AI stories; IDC companies are retained only when customer relationships, core-city assets, energy efficiency, operating reliability, or cloud-network resources make the business harder to replicate than ordinary server capacity.

The seventy-third A-share peer-group review output is mining and metallurgy machinery:

- `data/processed/a_share_mining_metallurgy_machinery_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-mining-metallurgy-machinery.md`

This pass reviews all companies in `机械设备-专用设备-矿山冶金机械`. It separates mining-intelligence, coal-mining equipment, heavy metallurgical equipment, oilfield tools, wear-resistant consumables, crushing/screening systems, nuclear/heavy-forging equipment, and ordinary cyclical equipment makers. It retains companies with installed-base service lock-in, process-critical qualification, scarce heavy-manufacturing capability, resource-industry customer validation, or consumable replacement economics.

The seventy-fourth A-share peer-group review output is security brokerages:

- `data/processed/a_share_security_brokerages_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-security-brokerages.md`

This pass reviews all companies in `金融-非银行金融-证券`. It separates top-tier integrated securities platforms, investment-banking leaders, wealth-management and institutional-service platforms, regional brokerages, internet-brokerage stories, and smaller capital-market intermediaries. It retains scale, capital strength, institutional franchise, investment-banking capability, product platform, and cross-cycle risk-control advantages rather than brokerage-license scarcity alone.

The seventy-fifth A-share peer-group review output is mechanical basic components:

- `data/processed/a_share_mechanical_basic_components_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-mechanical-basic-components.md`

This pass reviews all companies in `机械设备-通用设备-基础件`. It separates hydraulic components, industrial valves, precision bearings, nuclear/aerospace/special valves, seals, fasteners, tools, transmission components, catalog-style MRO platforms, and ordinary mechanical parts. It retains process-critical components with qualification, reliability, installed-base, high-end material/process, or customer-switching-cost evidence.

The seventy-sixth A-share peer-group review output is cable TV:

- `data/processed/a_share_cable_tv_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-cable-tv.md`

This pass reviews all companies in `文化传媒-广播电视-有线电视`. It separates provincial cable-network operators, integrated media and digital-content platforms, smart-city or data-network transitions, and smaller regional cable operators. It retains only companies with scarce local network access, content/platform integration, or credible digital-service extension rather than mature cable access alone.

The seventy-seventh A-share peer-group review output is electrical instruments:

- `data/processed/a_share_electrical_instruments_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-electrical-instruments.md`

This pass reviews all companies in `电气设备-输变电设备-电气仪表`. It separates smart-meter leaders, energy-management and distribution-monitoring platforms, State Grid/utility qualification niches, electricity information-collection systems, and ordinary meter/module suppliers. It retains companies with utility procurement qualification, installed-base data/service extension, product reliability, and power-IoT platform evidence.

The seventy-eighth A-share peer-group review output is railway transport:

- `data/processed/a_share_railway_transport_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-railway-transport.md`

This pass reviews all companies in `交通运输-公路铁路-铁路运输`. It separates high-speed rail corridor assets, heavy-haul coal railways, national railway-adjacent logistics, special-cargo platforms, regional passenger railways, and mixed logistics portfolios. It retains scarce route/franchise assets, corridor economics, cargo specialization, or infrastructure-control advantages while discounting cyclicality and tariff constraints.

The seventy-ninth A-share peer-group review output is dairy products:

- `data/processed/a_share_dairy_products_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-dairy-products.md`

This pass reviews all companies in `食品饮料-食品-乳制品`. It separates national dairy brands, regional fresh-milk brands, cheese categories, infant-formula and premium dairy exposure, and small regional dairy producers. It retains category leadership, brand trust, cold-chain/channel control, product mix, and scale advantages while rejecting weak regional players without durable differentiation.

The eightieth A-share peer-group review output is beer:

- `data/processed/a_share_beer_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-beer.md`

This pass reviews all companies in `食品饮料-饮料-啤酒`. It separates national beer brands, regional strongholds, premiumization leaders, malt-supply platforms, and weaker local brewers. It retains brand, channel, regional density, premium mix, and cost/supply-chain advantages while rejecting subscale or weakly differentiated beer assets.

The eighty-first A-share peer-group review output is furniture manufacturing:

- `data/processed/a_share_furniture_manufacturing_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-furniture-manufacturing.md`

This pass reviews all companies in `轻工制造-家具-家具制造`. It separates custom-home furnishing platforms, upholstered furniture brands, office/seating exporters, smart beds and ergonomic products, hardware/home-improvement niches, and ordinary furniture manufacturers. It retains brand/channel/installation networks, category leadership, overseas customer validation, manufacturing efficiency, or product-function differentiation rather than capacity alone.

The eighty-second A-share peer-group review output is other nonbank finance:

- `data/processed/a_share_other_nonbank_finance_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-nonbank-finance.md`

This pass reviews all companies in `金融-非银行金融-其他非银行金融`. It separates financial holdings, leasing platforms, distressed-asset management, futures platforms, local financial-service companies, and payment or credit-service stories. It retains regulated licenses only when combined with scale, customer access, risk-control history, asset-origination capability, or scarce platform position.

The eighty-third A-share peer-group review output is remaining defense electronics and defense computing:

- `data/processed/a_share_defense_electronics_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-defense-electronics-remaining.md`

This pass resolves the previously deferred companies in `电子设备-电子设备制造-电子设备制造`. It separates national radar platforms, domestic defense-computing/GPU capability, millimeter-wave phased-array microsystems, air-defense radar, military control electronics, military network bus and display niches, optoelectronic guidance systems, underwater acoustic systems, and weaker opaque defense-electronics stories.

The eighty-fourth A-share peer-group review output is construction machinery:

- `data/processed/a_share_construction_machinery_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-construction-machinery.md`

This pass reviews all companies in `机械设备-专用设备-工程机械`. It separates global construction-machinery leaders, forklift and industrial-vehicle platforms, logistics automation, micro-drive systems, hydraulic seals and attachments, tunnel/asphalt/port machinery, and ordinary cyclical equipment makers. Low baseline scores are overridden when global scale, product breadth, overseas channels, or hard component qualification clearly matter more than current-cycle profit.

The eighty-fifth A-share peer-group review output is environmental equipment:

- `data/processed/a_share_environmental_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-environmental-equipment.md`

This pass reviews all companies in `机械设备-专用设备-环保设备`. It separates special-environment control, semiconductor cleanroom purification, thermal cracking, atmospheric governance, heavy-metal treatment, environmental monitoring, membrane/water-treatment platforms, ordinary flue-gas equipment, generic sanitation vehicles, low-barrier VOC/odor projects, and ST environmental-equipment cases.

The eighty-sixth A-share peer-group review output is healthcare nutrition products:

- `data/processed/a_share_healthcare_nutrition_products_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-healthcare-nutrition-products.md`

This pass reviews all companies in `医药生物-保健护理-保健护理产品`. It separates global nutrition ingredient and bio-manufacturing platforms, nutrition product CDMO, health-food dosage-form manufacturers, disposable care products, and legacy health-food brands. It retains hard process, formulation, global manufacturing, and regulated product capability rather than OEM capacity alone.

The eighty-seventh A-share peer-group review output is network media:

- `data/processed/a_share_network_media_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-network-media.md`

This pass reviews all companies in `互联网-互联网服务-网络媒体`. It separates long-video content platforms, elevator media networks, high-speed rail scene media, central official news portals, and digital culture/metaverse projects. It retains scarce traffic, content production, location-network, official media authority, and differentiated media access.

The eighty-eighth A-share peer-group review output is soft drinks:

- `data/processed/a_share_soft_drinks_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-soft-drinks.md`

This pass reviews all companies in `食品饮料-饮料-软饮料`. It separates national energy-drink brands, plant-protein drink category leaders, scarce water-resource brands, concentrated juice suppliers, regional packaged beverage brands, and fad-like drink categories. It retains brand/channel/category leadership and resource scarcity while rejecting commodity processing and weak regional brands.

The eighty-ninth A-share peer-group review output is railway and urban rail construction:

- `data/processed/a_share_railway_urban_rail_construction_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-railway-urban-rail-construction.md`

This pass reviews all companies in `建筑-基础建设-铁路城轨建设`. It separates global railway infrastructure contractors, urban-rail design institutes, railway electrification equipment, and smaller regional contractors. It retains qualification, execution scale, line-use history, and scarce design/equipment capability while rejecting ordinary project exposure.

The ninetieth A-share peer-group review output is machine tools:

- `data/processed/a_share_machine_tools_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-machine-tools.md`

This pass reviews all companies in `机械设备-通用设备-机床设备`. It separates industrial mother-machine and CNC-control platforms, five-axis systems, high-speed spindles, high-end grinders, CNC machine-tool platforms, battery rolling equipment, and ordinary machine-tool assemblers. Strategic domestic-substitution capability can override low baseline scores when the company controls core CNC systems, five-axis integration, or precision functional components.

The ninety-first A-share peer-group review output is lighting equipment:

- `data/processed/a_share_lighting_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-lighting-equipment.md`

This pass reviews all companies in `家电-照明设备-照明设备`. It separates professional industrial/special lighting, consumer and commercial lighting brands, stage and cultural-tourism lighting, commercial LED exporters, IoT lighting ODMs, mobile lighting, and lighting components. It retains only professional, brand/channel, or application-specific niches because ordinary LED manufacturing is low-barrier.

The ninety-second A-share peer-group review output is feed and animal nutrition:

- `data/processed/a_share_feed_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-feed.md`

This pass reviews all companies in `农林牧渔-畜牧业-饲料`. It separates global animal nutrition and amino-acid platforms, feed leaders, pet food, biological feed additives, aquatic feed, seed/ag-biotech cross-industry cases, commodity feed, pig-cycle integrated operators, and regional feed companies. It retains scale, R&D, cost curve, fermentation/process capability, channel density, and differentiated animal-nutrition technology rather than low-margin feed capacity alone.

The ninety-third A-share peer-group review output is marketing services:

- `data/processed/a_share_marketing_services_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-marketing-services.md`

This pass reviews all companies in `文化传媒-营销服务-营销服务`. It treats ordinary advertising agency, media buying, livestream commerce, e-commerce operation, public-relations, and event execution as low-barrier service businesses, retaining only selected boundary marketing-technology or global advertising platforms with differentiated data, tooling, overseas media access, or scaled client workflows.

The ninety-fourth A-share peer-group review output is electric motors:

- `data/processed/a_share_electric_motors_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-electric-motors.md`

This pass reviews all companies in `电气设备-电机-电机`. It separates national special-motor platforms, global industrial motor and drive systems, major strategic electrical-equipment companies, e-bike drive systems, motion-control motors, micro motors, wind-turbine companies, appliance motor components, EV-drive suppliers, and motor-core manufacturers. Misclassified strategic equipment companies are judged by company-level capability rather than the narrow electric-motor label.

The ninety-fifth A-share peer-group review output is lead and zinc resources:

- `data/processed/a_share_lead_zinc_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-lead-zinc.md`

This pass reviews all companies in `有色金属-基本金属-铅锌`. It separates mine-owning lead-zinc and multi-metal resource platforms, overseas resource companies, silver-tin scarcity cases, germanium and by-product optionality, zinc/lead smelters, nonferrous engineering contractors, and zinc-powder manufacturers. Resource ownership, reserve quality, by-product scarcity, and cost position matter more than current commodity-cycle profit.

The ninety-sixth A-share peer-group review output is refrigeration and air-conditioning equipment:

- `data/processed/a_share_refrigeration_ac_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-refrigeration-ac-equipment.md`

This pass reviews all companies in `机械设备-通用设备-制冷空调设备`. It separates screw compressors, HVAC valves and heat exchangers, petrochemical/power/nuclear air-cooling systems, industrial refrigeration, hydrogen and thermal-power equipment, data-center liquid cooling, high-reliability ventilation, scroll compressors, commercial cold-chain cabinets, HVAC parts, and air-filter components.

The ninety-seventh A-share peer-group review output is satellite applications:

- `data/processed/a_share_satellite_applications_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-satellite-applications.md`

This pass reviews all companies in `信息技术-卫星应用-卫星应用`. It separates high-precision BeiDou/GNSS leaders, satellite navigation modules and correction networks, older satellite-navigation platforms, aerospace chips, micro/nano satellites, remote-sensing software, and ST satellite-application cases. Core algorithms, chips/modules, augmentation networks, and strategic aerospace electronics are the central tests.

The ninety-eighth A-share peer-group review output is airports:

- `data/processed/a_share_airports_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-airports.md`

This pass reviews all companies in `交通运输-航空机场-机场`. It separates major international hub airports, regional gateway airports, and mixed airport/property/commercial platforms. It retains scarce gateway location, route network, passenger/cargo flow, and commercial concession economics while discounting tariff regulation, hub overlap, and diluted non-airport assets.

The ninety-ninth A-share peer-group review output is industrial robots:

- `data/processed/a_share_industrial_robots_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-industrial-robots.md`

This pass reviews all companies in `机械设备-机器人-工业机器人`. It separates industrial automation control platforms, domestic robot bodies and motion-control systems, national robot platforms, embodied-intelligence equipment, power-grid robots, nuclear and defense robots, welding robots, automotive system integrators, and smaller automation-line suppliers. Current profit weakness is not enough to reject a company with core control, servo, robot-body, or strategic special-robot capability.

The one hundredth A-share peer-group review output is commercial vehicles:

- `data/processed/a_share_commercial_vehicles_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-commercial-vehicles.md`

This pass reviews all companies in `交运设备-汽车-商用车`. It separates bus leaders, heavy-truck platforms, light-commercial vehicles, semi-trailer platforms, new-energy commercial vehicles, and weaker local commercial-vehicle manufacturers. It retains segment leadership, export/channel strength, electrification capability, powertrain depth, and scale advantages while rejecting weaker duplicate bus and truck exposure.

The one hundred first A-share peer-group review output is public bus and local passenger transport:

- `data/processed/a_share_public_bus_transport_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-public-bus-transport.md`

This pass reviews all companies in `交通运输-公路铁路-公交`. It treats road passenger transport, taxi fleets, and local bus operators as structurally low-growth and labor/capital intensive, retaining only a scarce urban rail operating asset as a boundary case.

The one hundred second A-share peer-group review output is paper and paper-based materials:

- `data/processed/a_share_paper_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-paper.md`

This pass reviews all companies in `轻工制造-造纸印刷-造纸`. It separates integrated pulp-paper leaders, specialty paper and paper-based functional material platforms, decorative base paper, aramid paper, tobacco paper, tissue brands, packaging board, recycled paper mills, bamboo pulp, and ST paper-cycle cases. Scale, cost curve, product breadth, process technology, and customer qualification are required; commodity paper capacity alone is rejected.

The one hundred third A-share peer-group review output is other metal new materials:

- `data/processed/a_share_other_metal_new_materials_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-metal-new-materials.md`

This pass reviews the remaining companies in `有色金属-金属非金属新材料-其他金属新材料`. It separates metal fiber, powder metallurgy, magnesium/lightweighting, superconducting, titanium, superalloy, copper-alloy, master-alloy, and metal-composite cases from ordinary aluminum processing and mixed glass/material businesses. Strategic-material qualification, process know-how, institute origin, and high-validation customers can override low baseline scores.

The one hundred fourth A-share peer-group review output is integrated power equipment:

- `data/processed/a_share_integrated_power_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-integrated-power-equipment.md`

This pass reviews all companies in `电气设备-电源设备-综合电力设备商`. It retains power-electronics, generation-equipment, and broad power/industrial-equipment platforms while rejecting power EPC or service-operation models without scarce product capability.

The one hundred fifth A-share peer-group review output is passenger vehicles:

- `data/processed/a_share_passenger_vehicles_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-passenger-vehicles.md`

This pass reviews the remaining companies in `交运设备-汽车-乘用车`. It retains independent or strategically relevant vehicle platforms with brand, engineering, electrification, export, ecosystem, or complete-vehicle qualification advantages while rejecting weak legacy manufacturers, turnaround stories, and misclassified bus companies.

The one hundred sixth A-share peer-group review output is basic software:

- `data/processed/a_share_basic_software_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-basic-software.md`

This pass reviews all companies in `信息技术-计算机软件-基础软件`. It separates office-software ecosystems, domestic foundational software, databases, data/AI infrastructure, font/IP software, and project-heavy management software. Product reuse, ecosystem lock-in, standard/interface control, data model depth, and IP assets are required.

The one hundred seventh A-share peer-group review output is remaining defense and aerospace software:

- `data/processed/a_share_defense_aerospace_software_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-defense-aerospace-software-remaining.md`

This pass resolves the previously deferred aerospace, military simulation, defense equipment digitalization, and electromagnetic/antenna software companies in `信息技术-计算机软件-行业应用软件`. These companies are judged by mission-critical product role, domain validation, and program relevance rather than ordinary civilian SaaS metrics.

The one hundred eighth A-share peer-group review output is internet finance:

- `data/processed/a_share_internet_finance_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-internet-finance.md`

This pass reviews all companies in `互联网-互联网金融-其他互联网金融`. It retains platforms with investor traffic, data, account relationships, transaction loops, or trading-workflow lock-in while rejecting generic fintech solution vendors and weaker financial terminals.

The one hundred ninth A-share peer-group review output is meat products:

- `data/processed/a_share_meat_products_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-meat-products.md`

This pass reviews all companies in `食品饮料-食品-肉制品`. It separates national processed-meat brands, traditional category brands, casual braised-food chains, poultry/pork processors, and regional meat platforms. Brand trust, channel density, food-safety credibility, and repeat consumption matter more than simple protein-processing capacity.

The one hundred tenth A-share peer-group review output is rail transit equipment:

- `data/processed/a_share_rail_transit_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-rail-transit-equipment.md`

This pass reviews all companies in `交运设备-轨道交通设备-轨道交通设备`. It retains rail-control systems, traction/electrical systems, tunnel-boring and railway-construction equipment, rail doors, rail materials, inspection/monitoring, and selected rail-signal niches while rejecting supply-chain, interior, and ordinary component cases.

The one hundred eleventh A-share peer-group review output is building equipment:

- `data/processed/a_share_building_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-building-equipment.md`

This pass reviews all companies in `机械设备-专用设备-楼宇设备`. It distinguishes national elevator platforms, elevator service/installed-base cases, safety components, fire-safety IoT systems, generic elevator manufacturing, and ST mixed-equipment cases.

The one hundred twelfth A-share peer-group review output is apparel:

- `data/processed/a_share_apparel_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-apparel.md`

This pass reviews all companies in `纺织服装-服装家纺-服装`. Because ordinary apparel is structurally low-barrier, it retains only selected companies with unusually strong brand/category control, channel density, intimate-apparel trust, B2B workflow, C2M systems, cross-industry optionality, or global manufacturing qualification.

The one hundred thirteenth A-share peer-group review output is logistics:

- `data/processed/a_share_logistics_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-logistics.md`

This pass reviews all companies in `交通运输-物流-物流`. It separates premium express and integrated supply-chain networks, global freight-forwarding platforms, chemical and dangerous-goods logistics, petrochemical storage infrastructure, manufacturing-embedded logistics, commodity supply-chain trading, regional transport, weak express followers, and ST logistics cases.

The one hundred fourteenth A-share peer-group review output is insurance:

- `data/processed/a_share_insurance_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-insurance.md`

This pass reviews all companies in `金融-非银行金融-保险`. It retains insurance franchises with brand, capital, distribution, asset-management, customer ecosystem, and segment leadership while rejecting weaker insurance peers whose franchise is not clearly differentiated from retained leaders.

The one hundred fifteenth A-share peer-group review output is planting agriculture:

- `data/processed/a_share_planting_agriculture_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-planting-agriculture.md`

This pass reviews all companies in `农林牧渔-农业-种植业`. It separates scarce farmland, modern large-scale farming systems, seed and agricultural-service integration, strategic natural-rubber assets, and weaker regional crop companies.

The one hundred sixteenth A-share peer-group review output is other textiles:

- `data/processed/a_share_other_textiles_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-textiles.md`

This pass reviews all companies in `纺织服装-纺织-其他纺织`. It retains only selected technical material, automotive interior textile, high-grade down, protective textile, and luggage workflow cases because ordinary textile production, dyeing, fabric, home textile, and OEM capacity is structurally low-barrier.

The one hundred seventeenth A-share peer-group review output is audio-visual equipment:

- `data/processed/a_share_audio_visual_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-audio-visual-equipment.md`

This pass reviews all companies in `家电-视听器材-视听器材`. It separates global display brands, TV/LED/ODM platforms, laser-display and optical technology, and ST digital-TV equipment cases.

The one hundred eighteenth A-share peer-group review output is textile and apparel machinery:

- `data/processed/a_share_textile_apparel_machinery_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-textile-apparel-machinery.md`

This pass reviews all companies in `机械设备-专用设备-纺织服装机械`. It separates intelligent sewing equipment, global sewing and material-joining brands, spinning machinery, computerized knitting machinery, generic textile equipment, and ST textile-machinery cases.

The one hundred nineteenth A-share peer-group review output is other chemical raw materials:

- `data/processed/a_share_other_chemical_raw_materials_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-chemical-raw-materials.md`

This pass reviews all companies in `基础化工-化学原料-其他化学原料`. It separates coal-to-new-materials platforms, electronic specialty gases, wet electronic chemicals and photoresist, chromatography microspheres, non-power nuclear materials, semiconductor gases, conductive carbon black, piperazine derivatives, light-hydrocarbon integration, molecular sieves, thermal-storage salts, green catalysis, electronic silane, and ordinary commodity chemicals.

The one hundred twentieth A-share peer-group review output is online shopping:

- `data/processed/a_share_online_shopping_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-online-shopping.md`

This pass reviews all companies in `互联网-互联网商务-网上购物`. It retains only owned consumer-decision content, data, and workflow moats while rejecting platform-dependent brand-operation and cross-border e-commerce service models.

The one hundred twenty-first A-share peer-group review output is gold:

- `data/processed/a_share_gold_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-gold.md`

This pass completes the still-undecided companies in `有色金属-贵金属-黄金`. It does not duplicate companies already decided in the strategic-resource calibration. Gold companies are retained only when they have strategic by-product metals, precious-metal recovery, silver/polymetallic resource exposure, or other company-specific advantages beyond gold-price beta.

The one hundred twenty-second A-share peer-group review output is chemical new materials:

- `data/processed/a_share_chemical_new_materials_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-chemical-new-materials.md`

This pass reviews all companies in `基础化工-化学新材料-化学新材料`. It separates platform-level insulation, optical-film, biomass, high-end ceramic, special polymer, electromagnetic, thermal/EMI, synthetic-biology, functional-film, semiconductor-packaging, and fine-chemical monomer capabilities from commodity PET, nylon, oil-ink, LPG-processing, wood-plastic, ST, and mixed chemical cases.

The one hundred twenty-third A-share peer-group review output is tungsten remaining:

- `data/processed/a_share_tungsten_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-tungsten-remaining.md`

This pass completes the still-undecided tungsten companies and retains only differentiated integrated tungsten resource/carbide capability beyond previously retained tungsten leaders.

The one hundred twenty-fourth A-share peer-group review output is other transport equipment:

- `data/processed/a_share_other_transport_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-transport-equipment.md`

This pass separates global equipment platforms, rail signaling, personal mobility and powersports niches from ordinary bicycles, two-wheelers, components and narrow electric vehicle cases.

The one hundred twenty-fifth A-share peer-group review output is huangjiu:

- `data/processed/a_share_huangjiu_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-huangjiu.md`

This pass keeps only a huangjiu category representative because the category has heritage but limited young-consumer growth and regional demand breadth.

The one hundred twenty-sixth A-share peer-group review output is auto sales:

- `data/processed/a_share_auto_sales_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-auto-sales.md`

This pass rejects the whole auto-sales group because dealership, trading and distribution economics lack durable company-level control points.

The one hundred twenty-seventh A-share peer-group review output is packaging printing:

- `data/processed/a_share_packaging_printing_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-packaging-printing.md`

This pass separates premium customer-workflow packaging, flexible packaging and aseptic packaging from ordinary paper, metal, bottle, cap, label and printing capacity.

The one hundred twenty-eighth A-share peer-group review output is copper remaining:

- `data/processed/a_share_copper_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-copper-remaining.md`

This pass completes remaining copper-group companies and retains only multi-metal resource exposure or high-performance copper-material capability beyond commodity copper scale.

The one hundred twenty-ninth A-share peer-group review output is other light industry:

- `data/processed/a_share_other_light_industry_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-light-industry.md`

This pass separates global artificial-turf and optical-lens niches from ordinary hygiene, disposable, sanitary, household, decorative and housing-linked products.

The one hundred thirtieth A-share peer-group review output is agricultural processing:

- `data/processed/a_share_agricultural_processing_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-agricultural-processing.md`

This pass separates plant-extraction and konjac specialty-ingredient capability from commodity grain, oil, sugar, mushroom and agricultural-processing businesses.

The one hundred thirty-first A-share peer-group review output is wine:

- `data/processed/a_share_wine_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-wine.md`

This pass keeps only the domestic wine category representative and rejects weak regional, ST, or follower wine names.

The one hundred thirty-second A-share peer-group review output is small appliances:

- `data/processed/a_share_small_appliances_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-small-appliances.md`

This pass separates durable kitchen/cleaning appliance brands and motor engineering from trend products, ordinary ODM and weak small-appliance followers.

The one hundred thirty-third A-share peer-group review output is ordinary steel:

- `data/processed/a_share_ordinary_steel_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-ordinary-steel.md`

This pass retains only Baosteel as a boundary high-end steel platform and rejects ordinary steel capacity as commodity-cycle exposure.

The one hundred thirty-fourth A-share peer-group review output is aviation defense cyber software remaining:

- `data/processed/a_share_aviation_defense_cyber_software_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-aviation-defense-cyber-software-remaining.md`

This pass resolves aviation traffic-control and defense-cyber software pending cases under mission-critical qualification rules.

The one hundred thirty-fifth A-share peer-group review output is aviation equipment:

- `data/processed/a_share_aviation_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-aviation-equipment.md`

This pass separates aircraft/OEM platforms, avionics, engine controls, aviation composites and qualified subsystems from generic aircraft parts, MRO, commercial drones and weak ST cases.

The one hundred thirty-sixth A-share peer-group review output is jewelry:

- `data/processed/a_share_jewelry_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-jewelry.md`

This pass keeps only the strongest heritage jewelry brand and rejects ordinary gold, diamond, fashion jewelry and watch retail models.

The one hundred thirty-seventh A-share peer-group review output is white appliances:

- `data/processed/a_share_white_appliances_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-white-appliances.md`

This pass retains global appliance platforms with brand, service, R&D, manufacturing and component ecosystems while rejecting weaker white-appliance followers.

The one hundred thirty-eighth A-share peer-group review output is livestock breeding:

- `data/processed/a_share_livestock_breeding_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-livestock-breeding.md`

This pass separates livestock operators with durable genetics, biosecurity, cost and farmer-network systems from ordinary cyclical farms and mixed agriculture cases.

The one hundred thirty-ninth A-share peer-group review output is nonmetal new materials:

- `data/processed/a_share_nonmetal_new_materials_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-nonmetal-new-materials.md`

This pass separates strategic high-purity, defense, electronic and battery nonmetal materials from commodity glass fiber, graphite, silicon and synthetic-diamond cycles.

The one hundred fortieth A-share peer-group review output is print media:

- `data/processed/a_share_print_media_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-print-media.md`

This pass keeps only selected education, content and science-publishing platforms while rejecting ordinary regional publishers and weak media names.

The one hundred forty-first A-share peer-group review output is network tv:

- `data/processed/a_share_network_tv_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-network-tv.md`

This pass retains only boundary IPTV/internet-TV platforms where license, operator workflow and local user scale create defensible economics.

The one hundred forty-second A-share peer-group review output is real estate services:

- `data/processed/a_share_real_estate_services_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-real-estate-services.md`

This pass rejects the whole real-estate-service group because property management, brokerage and related services lack durable pricing power.

The one hundred forty-third A-share peer-group review output is real estate development:

- `data/processed/a_share_real_estate_development_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-real-estate-development.md`

This pass rejects ordinary real-estate developers but retains the misclassified semiconductor equipment/materials platform as a boundary technology case.

The one hundred forty-fourth A-share peer-group review output is water conservancy construction:

- `data/processed/a_share_water_conservancy_construction_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-water-conservancy-construction.md`

This pass retains only the global hydropower, pumped-storage and renewable infrastructure engineering platform while rejecting regional/distressed water contractors.

The one hundred forty-fifth A-share peer-group review output is tin remaining:

- `data/processed/a_share_tin_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-tin-remaining.md`

This pass completes the tin group and retains the remaining tin/polymetallic resource company as a boundary strategic-resource case.

The one hundred forty-sixth A-share peer-group review output is rare earth remaining:

- `data/processed/a_share_rare_earth_remaining_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-rare-earth-remaining.md`

This pass completes remaining rare-earth names, separating quota/resource/platform roles from pure rare-earth price beta.

The one hundred forty-seventh A-share peer-group review output is other rubber products:

- `data/processed/a_share_other_rubber_products_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-rubber-products.md`

This pass separates high-pressure hoses, rubber additives, ePTFE membranes and seismic isolation from ordinary rubber-product capacity.

The one hundred forty-eighth A-share peer-group review output is special steel:

- `data/processed/a_share_special_steel_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-special-steel.md`

This pass separates broad special-steel and high-end alloy/tube capabilities from commodity pipe, stainless strip and steel-cycle exposure.

The one hundred forty-ninth A-share peer-group review output is ground equipment:

- `data/processed/a_share_ground_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-ground-equipment.md`

This pass separates armored vehicle platforms and mission-critical defense electronics, radar, navigation and communications from weaker mixed equipment cases.

The one hundred fiftieth A-share peer-group review output is road bridge construction:

- `data/processed/a_share_road_bridge_construction_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-road-bridge-construction.md`

This pass retains only global transport infrastructure engineering and tunnel specialization while rejecting local road/bridge contractors.

The one hundred fifty-first A-share peer-group review output is railway vehicles:

- `data/processed/a_share_railway_vehicles_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-railway-vehicles.md`

This pass retains the national railway rolling-stock platform based on certification, installed base and system integration barriers.

The one hundred fifty-second A-share peer-group review output is other railway equipment:

- `data/processed/a_share_other_railway_equipment_peer_group_decisions.csv`
- `docs/peer-group-calibration/a-share-other-railway-equipment.md`

This pass retains boundary rail-component and rail-signal/control companies when certification and installed-base barriers are visible.

Fetch A-share screening evidence into resumable interim CSV files:

```bash
python3 scripts/fetch_a_share_research_evidence.py
```

The fetcher writes `data/interim/a_share_research_queue.csv`, `data/interim/a_share_company_profiles.csv`, and `data/interim/a_share_financial_indicators.csv`.

Generate dimensional A-share scores from fetched evidence:

```bash
python3 scripts/run_a_share_full_coverage_scoring.py
```

The scorer writes `data/processed/a_share_full_coverage_scores.csv` and `data/processed/a_share_full_coverage_watchlist.csv`. The full scores file keeps the complete audit fields, including `cyclicality_profile`, `compounding_profile`, `industry_outlook_*`, reasons, sources, and timestamps. The generated watchlist is a compact algorithmic reading view with security code, security name, labeled score fields, peer group, peer-relative position, and scoring model version. It is not the peer-group-calibrated final watchlist. Use `--require-complete` when the fetch queue is complete and the run should fail if any eligible A-share company remains unscored.

Build the current A-share peer-group-calibrated watchlist from accepted reviewer decisions:

```bash
python3 scripts/build_a_share_peer_group_calibrated_watchlist.py
```

The script reads `data/processed/a_share_*_peer_group_decisions.csv` and writes `data/processed/a_share_peer_group_calibrated_watchlist.csv`. Decision files and the watchlist preserve `watch_selection_route`, distinguishing direct reviewer-accepted watch companies from boundary companies retained after analyst judgment under calibrated rules. Cross-industry rejection checks are tracked in `data/processed/a_share_cross_industry_review_audit.csv`; `藏格矿业` is the first corrected false-negative case, because its company-level resource thesis includes potash, lithium, Julong Copper equity economics, and Zijin control rather than only a weaker salt-lake lithium comparison.

Build the A-share remaining peer-group screening queue:

```bash
python3 scripts/build_a_share_peer_group_screening_queue.py
```

The queue reads `data/processed/a_share_company_triage_reviews.csv` and existing peer-group decision tables, then writes `data/interim/a_share_peer_group_screening_queue.csv`. It marks peer groups as not started, partially screened, or complete, proposes review modes, and explicitly allows low-barrier whole-group rejection when an industry lacks durable barriers. Unclear or mixed peer groups can be routed back to reviewer discussion before decisions are finalized.

Peer-group completion must not be done by a threshold-only automated screening script. A final `*_peer_group_decisions.csv` file should represent analyst judgment applied company by company within a comparable peer group, using source-backed evidence and the calibrated rules from prior groups. Scripts may build queues, merge accepted decisions into the watchlist, or validate coverage, but they should not create final watch/reject decisions from numeric thresholds alone. See `docs/adr/0004-require-analyst-peer-group-decisions.md`.

Fetch Hong Kong screening evidence into resumable interim CSV files:

```bash
python3 scripts/fetch_hong_kong_research_evidence.py
```

The fetcher writes `data/interim/hong_kong_research_queue.csv`, `data/interim/hong_kong_company_profiles.csv`, and `data/interim/hong_kong_financial_indicators.csv`. It uses Eastmoney HKF10 first and falls back to ETNet company information for newly listed securities that are not yet covered by Eastmoney.

Generate dimensional Hong Kong scores from fetched evidence:

```bash
python3 scripts/run_hong_kong_full_coverage_scoring.py
```

The scorer writes `data/processed/hong_kong_full_coverage_scores.csv` and `data/processed/hong_kong_full_coverage_watchlist.csv`. The full scores file keeps market identity and complete audit fields. The watchlist is a compact reading view with security code, security name, labeled score fields, peer group, peer-relative position, and scoring model version. When Hong Kong has duplicate currency counters for the same listed company, the full scores keep each security but the watchlist keeps one representative row.

Fetch U.S. screening evidence into resumable interim CSV files:

```bash
python3 scripts/fetch_us_research_evidence.py
```

The fetcher writes `data/interim/us_research_queue.csv`, `data/interim/us_company_profiles.csv`, and `data/interim/us_financial_indicators.csv`. It uses Nasdaq Trader for the raw security universe and SEC EDGAR `company_tickers`, `submissions`, and `companyfacts` for company profile and financial evidence. ETF, ETN, unit, warrant, right, preferred, closed-end fund, and other non-common-equity instruments are kept in the output with an explicit not-applicable status rather than being scored as listed companies. Use `--symbols UNH,MSFT` to refresh a targeted subset without rewriting unrelated evidence rows.

Generate dimensional U.S. scores from fetched evidence:

```bash
python3 scripts/run_us_full_coverage_scoring.py
```

The scorer writes `data/processed/us_full_coverage_scores.csv` and `data/processed/us_full_coverage_watchlist.csv`. The full scores file keeps market identity and complete audit fields. The watchlist is a compact reading view with security code, security name, labeled score fields, peer group, peer-relative position, and scoring model version. When the U.S. universe has multiple common-share classes for the same SEC CIK, the full scores keep each security but the watchlist keeps one representative row.
