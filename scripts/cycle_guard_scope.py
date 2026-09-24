"""§6.5.1 峰谷守卫的适用范围（OI-205）：守卫只对策略标签 H（成本曲线周期型）与 F（资源 NAV 型）生效。

标签取 `data/interim/strategy_tag_map.csv`（个人体系 §5）；该表之外的代码（回测宇宙中已退市或已移出名单、池外档案）
取 `data/reference/cycle_guard_supplement.csv` 按业务性质补判的类别，两表同一代码不得重复。两表都没有的代码不设守卫。
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CYCLICAL_TAGS = frozenset({"H", "F"})
TAG_MAP = ROOT / "data/interim/strategy_tag_map.csv"
SUPPLEMENT = ROOT / "data/reference/cycle_guard_supplement.csv"


def load_tags(tag_map: Path = TAG_MAP, supplement: Path = SUPPLEMENT) -> dict[str, str]:
    """{代码: 标签字母}：策略标签表优先，补判表只收标签表之外的代码。"""
    with tag_map.open(encoding="utf-8-sig", newline="") as fh:
        tags = {r["security_code"].strip(): (r.get("strategy_tag_letter") or "").strip().upper() for r in csv.DictReader(fh)}
    if supplement.exists():
        with supplement.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                code = r["security_code"].strip()
                if code in tags:
                    raise ValueError(f"{supplement.name}：{code} 已有策略标签，补判表只收标签表之外的代码")
                tags[code] = (r.get("guard_class") or "").strip().upper()
    return tags


def cyclical_codes(tag_map: Path = TAG_MAP, supplement: Path = SUPPLEMENT) -> set[str]:
    return {code for code, tag in load_tags(tag_map, supplement).items() if tag in CYCLICAL_TAGS}
