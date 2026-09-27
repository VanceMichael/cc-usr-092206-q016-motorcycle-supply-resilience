"""企业名称规范化与主体归并。

园区收集到的名录里，同一家企业常以工商全称、简称、旧称等多种写法
出现。这里先把名称规范化为可比较的键，再用并查集把指向同一主体的
记录归并起来。归并依据有两类：

- 显式声明：记录自带 ``same_as`` 指向另一条原始记录；
- 名称等价：规范化后的名称或别名相同。

生产环境中还应结合统一社会信用代码等登记信息复核，本模块只处理名称
层面的等价关系。
"""

from __future__ import annotations

import re

# 组织形式后缀，按从长到短匹配，命中即截断一次。
_SUFFIXES = (
    "有限责任公司",
    "股份有限公司",
    "有限公司",
    "股份公司",
    "集团公司",
    "公司",
    "集团",
    "厂",
)

# 空白、常见标点与连接符，全角半角都去掉。
_NOISE = re.compile(r"[\s·・,，。.、:：;；\-—_()（）\[\]【】{}《》'\"“”]+")

_FULLWIDTH = str.maketrans(
    "（）【】｛｝－：；，。、",
    "()[]{}-:;,、、",
)


def normalize_name(name: str) -> str:
    """返回去掉组织后缀、标点与空白后的可比较名称键。"""
    text = name.strip().translate(_FULLWIDTH)
    text = _NOISE.sub("", text)
    for suffix in _SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text


class _UnionFind:
    def __init__(self, ids):
        self.parent = {i: i for i in ids}

    def find(self, x):
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def resolve_entities(records: list[dict]) -> list[dict]:
    """把原始名录归并为去重后的企业主体列表。

    每条原始记录至少包含 ``id``、``name``，可含 ``aliases``、``kind``、
    ``local``、``same_as``。返回的主体包含归并得到的 ``aliases``（除
    主名称外的全部写法）以及来源记录号 ``source_records``。主记录取记
    录号最小的一条，其 ``kind``/``local`` 作为主体属性。
    """
    if not records:
        raise ValueError("原始名录为空")
    ids = [r["id"] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError("原始名录存在重复记录号")
    by_id = {r["id"]: r for r in records}
    uf = _UnionFind(ids)
    seen_keys: dict[str, str] = {}

    def bind(key: str, record_id: str) -> None:
        if not key:
            return
        other = seen_keys.setdefault(key, record_id)
        if other != record_id:
            uf.union(record_id, other)

    for record in records:
        same_as = record.get("same_as")
        if same_as:
            if same_as not in by_id:
                raise ValueError(f"记录 {record['id']} 的 same_as 指向不存在的记录 {same_as}")
            uf.union(record["id"], same_as)
        bind(normalize_name(record["name"]), record["id"])
        for alias in record.get("aliases", []):
            bind(normalize_name(alias), record["id"])

    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(uf.find(record["id"]), []).append(record)

    entities = []
    for members in groups.values():
        members.sort(key=lambda r: r["id"])
        primary = members[0]
        names = []
        for member in members:
            names.append(member["name"])
            names.extend(member.get("aliases", []))
        # 保持出现顺序去重，主名称放首位。
        aliases = list(dict.fromkeys(n for n in names if n != primary["name"]))
        entities.append(
            {
                "name": primary["name"],
                "aliases": aliases,
                "kind": primary.get("kind", "parts"),
                "local": bool(primary.get("local", False)),
                "source_records": [m["id"] for m in members],
            }
        )
    entities.sort(key=lambda e: e["source_records"][0])
    return entities
