"""确定性地生成示例图谱资料（合成数据，不含真实企业信息）。

运行：python fixtures/build_graph.py
输出：fixtures/graph.json

数据分两层：
- 剧本层：关键齿轮企业停产、共享设备检修、质量暂停、价格失效、
  未确认承诺、认证未生效等场景，企业与供应边 ID 固定，供测试锚定；
- 随机层：按固定种子生成的三百余家零部件企业与供应关系，让图谱
  规模贴近真实园区。
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.names import normalize_name  # noqa: E402

RNG = random.Random(20260927)

# ---------------------------------------------------------------- 企业

OEMS = ["苍岚重机有限公司", "澄湖电驱有限公司", "朔风越野有限公司"]
OEM_FUEL, OEM_EV, OEM_OFFROAD = OEMS

# 剧本层零部件企业（名称固定，测试直接引用）。
G1 = "岚山精密齿轮有限公司"      # 关键齿轮企业：停产通知主角
G2 = "潼溪齿轮有限公司"          # 候选 + 试制转量产齿轮
H1 = "鹤鸣链轮厂"                # 使用共享热处理炉
H2 = "岷江链轮有限公司"
Q1 = "澄湖制动科技有限公司"      # 质量暂停，9-25 解除
Q2 = "朔风制动系统有限公司"      # 质量暂停，10-05 解除，外地
R1 = "锐进控制器有限公司"        # 价格 9-25 失效
R2 = "恒力电子有限公司"          # 产能承诺未在线确认
S1 = "鑫源仪表有限公司"          # 认证 10-01 才生效

SCRIPTED = [
    {"name": G1, "local": True},
    {"name": G2, "local": True},
    {"name": H1, "local": True},
    {"name": H2, "local": True},
    {"name": Q1, "local": True},
    {"name": Q2, "local": False},
    {"name": R1, "local": True},
    {"name": R2, "local": True},
    {"name": S1, "local": True},
]

RANDOM_PARTS_COMPANIES = 343  # 3 整车 + 9 剧本 + 343 随机 = 355 家主体

_PREFIX_A = "岚潼璧鹤澄朔苍岷云磐岭川洲晟锐骏恒泰隆鑫瑞嶂汀梧矶漾岫砥砺淬烽岱沅沣浒洄湛璟昱"
_PREFIX_B = "山溪河鸣湖风江嶂石东泽渚阳锋驰力和盛源霖岳北兰凤头波云平川"
_CORES = [
    "齿轮", "链轮", "链条", "曲轴", "活塞", "连杆", "凸轮", "化油器", "电喷",
    "离合", "变速", "电机", "电控", "电池", "充电", "线束", "仪表", "灯具",
    "传感", "车架", "平叉", "减震", "制动", "轮毂", "轮胎", "轴承", "油封",
    "坐垫", "塑件", "油箱", "消声", "镜片", "脚踏", "货架", "点火", "整流",
    "线缆", "密封", "弹簧", "紧固", "涂装", "电镀", "热处理", "锻压", "铸造",
    "机加", "精密", "五金", "橡塑",
]
_SUFFIXES = ["有限公司"] * 8 + ["厂", "股份有限公司"]

_used_keys: set[str] = set()


def _key(name: str) -> str:
    return normalize_name(name)


def _fresh_name() -> str:
    while True:
        name = RNG.choice(_PREFIX_A) + RNG.choice(_PREFIX_B) + RNG.choice(_CORES) + RNG.choice(_SUFFIXES)
        if _key(name) not in _used_keys:
            _used_keys.add(_key(name))
            return name


def _short_form(name: str) -> str:
    for suffix in ("股份有限公司", "有限责任公司", "有限公司", "厂"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _alias_of(name: str) -> str:
    """生成一个规范化后不等价的旧称（换地名前缀）。"""
    core = _short_form(name)[2:]
    while True:
        alias = RNG.choice(_PREFIX_A) + RNG.choice(_PREFIX_B) + core + RNG.choice(_SUFFIXES)
        if _key(alias) not in _used_keys:
            _used_keys.add(_key(alias))
            return alias


for _n in OEMS + [s["name"] for s in SCRIPTED]:
    _used_keys.add(_key(_n))

random_companies = [
    {"name": _fresh_name(), "local": RNG.random() < 0.65}
    for _ in range(RANDOM_PARTS_COMPANIES)
]

# ---------------------------------------------------------------- 原始名录

raw_directory: list[dict] = []
_seq = 0


def _add_record(name: str, kind: str, local: bool, aliases=None, same_as=None) -> str:
    global _seq
    _seq += 1
    record = {"id": f"R{_seq:04d}", "name": name, "kind": kind, "local": local}
    if aliases:
        record["aliases"] = aliases
    if same_as:
        record["same_as"] = same_as
    raw_directory.append(record)
    return record["id"]


company_record: dict[str, str] = {}
for name in OEMS:
    company_record[name] = _add_record(name, "oem", True)
for item in SCRIPTED:
    company_record[item["name"]] = _add_record(item["name"], "parts", item["local"])
for item in random_companies:
    company_record[item["name"]] = _add_record(item["name"], "parts", item["local"])

all_parts_companies = [s["name"] for s in SCRIPTED] + [c["name"] for c in random_companies]

# 别名：主记录上声明简称（规范化后必与本体一致，不会误并他家）。
shuffled = all_parts_companies[:]
RNG.shuffle(shuffled)
for name in shuffled[:140]:
    short = _short_form(name)
    if short != name:
        for record in raw_directory:
            if record["name"] == name and "same_as" not in record:
                record.setdefault("aliases", []).append(short)
                break
# 旧称：换地名前缀，规范化后不同，需显式归并。
for name in shuffled[:60]:
    alias = _alias_of(name)
    for record in raw_directory:
        if record["name"] == name and "same_as" not in record:
            record.setdefault("aliases", []).append(alias)
            break

# 额外名录条目：一半靠名称规范化归并（简称），一半靠 same_as 归并（旧称）。
merge_targets = shuffled[140:188]
for name in merge_targets[:24]:
    short = _short_form(name)
    if short != name:
        _add_record(short, "parts", True)  # 名称等价，无需 same_as
for name in merge_targets[24:]:
    _add_record(_alias_of(name), "parts", True, same_as=company_record[name])

# 剧本锚点：停产通知写的是关键齿轮企业的简称与旧称。
_add_record("岚山齿轮厂", "parts", True, same_as=company_record[G1])
_used_keys.add(_key("岚山齿轮厂"))
for record in raw_directory:
    if record["name"] == G1:
        record.setdefault("aliases", []).append("岚山精密齿轮")

# ---------------------------------------------------------------- 零件与车型

PARTS = [
    ("P01", "变速齿轮", 1), ("P02", "主轴齿轮", 1), ("P03", "驱动链条", 1),
    ("P04", "从动链轮", 1), ("P05", "离合器总成", 1), ("P06", "传动皮带", 1),
    ("P07", "曲轴", 1), ("P08", "活塞组件", 1), ("P09", "连杆", 1),
    ("P10", "凸轮轴", 1), ("P11", "化油器", 1), ("P12", "电喷节气门", 1),
    ("P13", "驱动电机", 1), ("P14", "电机控制器", 1), ("P15", "动力电池包", 1),
    ("P16", "车载充电器", 1), ("P17", "车架总成", 1), ("P18", "后平叉", 1),
    ("P19", "方向柱", 1), ("P20", "前减震器", 1), ("P21", "后减震器", 1),
    ("P22", "制动盘", 1), ("P23", "制动卡钳", 1), ("P24", "制动油管", 1),
    ("P25", "ABS模块", 1), ("P26", "全车线束", 1), ("P27", "组合仪表", 1),
    ("P28", "前大灯", 1), ("P29", "尾灯", 1), ("P30", "速度传感器", 1),
    ("P31", "点火线圈", 1), ("P32", "整流器", 1), ("P33", "前轮毂", 1),
    ("P34", "后轮毂", 1), ("P35", "轮胎", 2), ("P36", "轴承套件", 2),
    ("P37", "覆盖塑件", 1), ("P38", "坐垫", 1), ("P39", "燃油箱", 1),
    ("P40", "消声器", 1), ("P41", "后视镜", 1), ("P42", "脚踏组件", 1),
    ("P43", "货架", 1),
]
PART_UNITS = dict((code, units) for code, _, units in PARTS)

FUEL_POOL = [
    "P01", "P02", "P03", "P04", "P05", "P07", "P08", "P09", "P10", "P11",
    "P12", "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P26",
    "P27", "P28", "P29", "P31", "P32", "P33", "P34", "P35", "P36", "P37",
    "P38", "P39", "P40", "P41", "P42",
]
EV_POOL = [
    "P04", "P06", "P13", "P14", "P15", "P16", "P17", "P18", "P19", "P20",
    "P21", "P22", "P23", "P24", "P25", "P26", "P27", "P28", "P29", "P30",
    "P33", "P34", "P35", "P36", "P37", "P38", "P41", "P42",
]
OFFROAD_POOL = FUEL_POOL + ["P25", "P43"]

VERSIONS = [
    {"code": "F150", "name": "苍岚F150风冷版", "kind": "fuel", "oem": OEM_FUEL, "open_orders": 300},
    {"code": "F250", "name": "苍岚F250水冷版", "kind": "fuel", "oem": OEM_FUEL, "open_orders": 700},
    {"code": "E3000", "name": "澄湖E3000城市版", "kind": "ev", "oem": OEM_EV, "open_orders": 600},
    {"code": "E5000", "name": "澄湖E5000性能版", "kind": "ev", "oem": OEM_EV, "open_orders": 450},
    {"code": "X250", "name": "朔风X250林道版", "kind": "offroad", "oem": OEM_OFFROAD, "open_orders": 400},
    {"code": "X450", "name": "朔风X450拉力版", "kind": "offroad", "oem": OEM_OFFROAD, "open_orders": 500},
]
ORDERS = {v["code"]: v["open_orders"] for v in VERSIONS}

# 每个版本必须包含的剧本零件。
SCRIPTED_PART_OF = {"F250": ["P01"], "X450": ["P01"], "F150": ["P04"], "X250": ["P23"], "E5000": ["P14", "P27"]}
BOM_SIZE = {"F150": 22, "F250": 22, "E3000": 20, "E5000": 20, "X250": 24, "X450": 24}
POOL_OF = {"fuel": FUEL_POOL, "ev": EV_POOL, "offroad": OFFROAD_POOL}

BOMS: dict[str, list[str]] = {}
for version in VERSIONS:
    code = version["code"]
    must = SCRIPTED_PART_OF.get(code, [])
    pool = [p for p in POOL_OF[version["kind"]] if p not in must]
    BOMS[code] = sorted(must + RNG.sample(pool, BOM_SIZE[code] - len(must)))

# ---------------------------------------------------------------- 供应边

edges: list[dict] = []
candidates: list[dict] = []
events: list[dict] = []
EQ_HEAT, EQ_PLATE = "EQ-HEAT共享热处理炉", "EQ-PLATE共享电镀线"


def _edge(edge_id, supplier, part, model, *, status="mass", cert_from="2026-01-01",
          capacity, equipment=(), lead=None, price=None, price_until="2026-12-31",
          confirmed=True):
    cert = f"CERT-{edge_id}" if cert_from else None
    edges.append({
        "id": edge_id,
        "model_code": model,
        "part_code": part,
        "supplier": supplier,
        "status": status,
        "certification": cert,
        "cert_valid_from": cert_from,
        "monthly_capacity": capacity,
        "shared_equipment": list(equipment),
        "lead_time_days": lead if lead is not None else RNG.randint(7, 45),
        "unit_price": price if price is not None else round(RNG.uniform(5, 300), 2),
        "price_valid_until": price_until,
        "online_confirmed": confirmed,
    })


# —— 剧本层 ——
_edge("E-F250-GEAR-1", G1, "P01", "F250", capacity=800, equipment=[EQ_HEAT], lead=21, price=35.0)
_edge("E-X450-GEAR-1", G1, "P01", "X450", capacity=600, equipment=[EQ_HEAT], lead=24, price=38.0)
_edge("E-F250-GEAR-2", G2, "P01", "F250", capacity=500, lead=18, price=36.5)
_edge("E-X450-GEAR-2", G2, "P01", "X450", status="trial", capacity=600, lead=20, price=37.0)
_edge("E-F150-SPROCKET-1", H1, "P04", "F150", capacity=400, equipment=[EQ_HEAT], lead=14)
_edge("E-F150-SPROCKET-2", H2, "P04", "F150", capacity=400, lead=16)
_edge("E-X250-CALIPER-1", Q1, "P23", "X250", capacity=500, lead=12)
_edge("E-X250-CALIPER-2", Q2, "P23", "X250", capacity=300, lead=30)
_edge("E-E5000-CTRL-1", R1, "P14", "E5000", capacity=500, lead=25, price=120.0, price_until="2026-09-25")
_edge("E-E5000-CTRL-2", R2, "P14", "E5000", capacity=300, lead=22, price=118.0, confirmed=False)
_edge("E-E5000-INSTR-1", S1, "P27", "E5000", cert_from="2026-10-01", capacity=500, lead=15)

candidates.append({
    "edge_id": "E-F250-GEAR-1",
    "alternatives": [{"edge_id": "E-F250-GEAR-2", "switch_days": 10}],
})

events += [
    {"id": "EV-STOP-F250", "type": "supply_stop", "edge_id": "E-F250-GEAR-1", "effective_from": "2026-09-20"},
    {"id": "EV-STOP-X450", "type": "supply_stop", "edge_id": "E-X450-GEAR-1", "effective_from": "2026-09-20"},
    {"id": "EV-CONV-X450", "type": "trial_to_mass", "edge_id": "E-X450-GEAR-2", "effective_from": "2026-10-15"},
    {"id": "EV-HOLD-X250-1", "type": "quality_hold", "edge_id": "E-X250-CALIPER-1",
     "effective_from": "2026-09-10", "effective_to": "2026-09-25"},
    {"id": "EV-HOLD-X250-2", "type": "quality_hold", "edge_id": "E-X250-CALIPER-2",
     "effective_from": "2026-09-20", "effective_to": "2026-10-05"},
    {"id": "EV-DOWN-HEAT", "type": "equipment_downtime", "equipment": EQ_HEAT,
     "effective_from": "2026-10-01", "effective_to": "2026-10-08"},
]

# —— 随机层 ——
supplier_pool = [c["name"] for c in random_companies]
RNG.shuffle(supplier_pool)
_pool_iter = iter(supplier_pool)


def _next_supplier(local=None) -> str:
    global _pool_iter
    while True:
        try:
            name = next(_pool_iter)
        except StopIteration:
            RNG.shuffle(supplier_pool)
            _pool_iter = iter(supplier_pool)
            name = next(_pool_iter)
        if local is None or _local_of(name) == local:
            return name


_locality = {c["name"]: c["local"] for c in random_companies}
_locality.update({s["name"]: s["local"] for s in SCRIPTED})


def _local_of(name: str) -> bool:
    return _locality[name]


_edge_seq = 1000


def _random_edge(part: str, model: str, *, safe: bool) -> str:
    global _edge_seq
    _edge_seq += 1
    edge_id = f"E{_edge_seq}"
    orders = ORDERS[model] * PART_UNITS[part]
    if safe:
        _edge(edge_id, _next_supplier(), part, model,
              capacity=int(orders * 1.3) + RNG.randint(0, 100))
    else:
        cert_roll = RNG.random()
        cert_from = "2026-01-01" if cert_roll < 0.85 else (
            f"2026-1{RNG.randint(0, 2)}-01" if cert_roll < 0.95 else None)
        priced = RNG.random() < 0.9
        edges.append({
            "id": edge_id,
            "model_code": model,
            "part_code": part,
            "supplier": _next_supplier(),
            "status": "mass" if RNG.random() < 0.85 else "trial",
            "certification": f"CERT-{edge_id}" if cert_from else None,
            "cert_valid_from": cert_from,
            "monthly_capacity": RNG.randint(100, 1500),
            "shared_equipment": [EQ_PLATE] if RNG.random() < 0.2 else [],
            "lead_time_days": RNG.randint(7, 60),
            "unit_price": round(RNG.uniform(5, 300), 2) if priced else None,
            "price_valid_until": "2026-12-31" if priced else None,
            "online_confirmed": RNG.random() < 0.75,
        })
    return edge_id


SCRIPTED_PAIRS = {
    ("F250", "P01"), ("X450", "P01"), ("F150", "P04"), ("X250", "P23"),
    ("E5000", "P14"), ("E5000", "P27"),
}

# E5000 仪表的第二家（外地）供应商，保证该零件可交付。
_edge("E-E5000-INSTR-2", _next_supplier(local=False), "P27", "E5000", capacity=500, lead=28)

for version in VERSIONS:
    code = version["code"]
    for part in BOMS[code]:
        if (code, part) in SCRIPTED_PAIRS:
            continue
        if code == "E3000":
            for _ in range(RNG.choice((1, 1, 2, 2, 3))):
                _random_edge(part, code, safe=False)
        else:
            for _ in range(1 + (RNG.random() < 0.2)):
                _random_edge(part, code, safe=True)

# E3000 的随机事件与候选替代（事件 ID 固定，测试据此定位供应边）。
e3000_edges = [e["id"] for e in edges if e["model_code"] == "E3000"]
RNG.shuffle(e3000_edges)
ev_hold, ev_stop, ev_conv, ev_price = e3000_edges[:4]
# 确保试制转量产事件落在一条试制边上。
trial_edges = [e["id"] for e in edges if e["model_code"] == "E3000" and e["status"] == "trial"]
if trial_edges:
    ev_conv = trial_edges[0]
events += [
    {"id": "EV-RND-HOLD", "type": "quality_hold", "edge_id": ev_hold,
     "effective_from": "2026-09-01", "effective_to": "2026-09-30"},
    {"id": "EV-RND-STOP", "type": "supply_stop", "edge_id": ev_stop, "effective_from": "2026-09-15"},
    {"id": "EV-RND-CONV", "type": "trial_to_mass", "edge_id": ev_conv, "effective_from": "2026-09-05"},
    {"id": "EV-RND-PRICE", "type": "price_expired", "edge_id": ev_price, "effective_from": "2026-09-10"},
    {"id": "EV-DOWN-PLATE", "type": "equipment_downtime", "equipment": EQ_PLATE,
     "effective_from": "2026-11-01", "effective_to": "2026-11-05"},
]
for origin in e3000_edges[4:7]:
    origin_part = next(e["part_code"] for e in edges if e["id"] == origin)
    alt_id = _random_edge(origin_part, "E3000", safe=True)
    candidates.append({
        "edge_id": origin,
        "alternatives": [{"edge_id": alt_id, "switch_days": RNG.randint(7, 21)}],
    })

# ---------------------------------------------------------------- 扶持措施

measures = [
    {"id": "M1", "company": G2, "name": "本地齿轮量产扶持", "effective_from": "2026-10-15"},
]

# ---------------------------------------------------------------- 输出

graph = {
    "domain": "motorcycle-supply-resilience",
    "version": 1,
    "sample_id": "graph-001",
    "note": "合成示例数据，不含真实企业信息",
    "published_local_ratio": 0.62,
    "raw_directory": raw_directory,
    "model_versions": VERSIONS,
    "parts": [{"code": c, "name": n, "units_per_unit": u} for c, n, u in PARTS],
    "edges": edges,
    "candidates": candidates,
    "events": events,
    "measures": measures,
}

out = ROOT / "fixtures" / "graph.json"
out.write_text(json.dumps(graph, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"写入 {out}：{len(raw_directory)} 条名录、{len(edges)} 条供应边、{len(events)} 个事件")
