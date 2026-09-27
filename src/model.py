"""韧性图谱的数据模型与校验加载器。

图谱按「整车企业 → 车型版本 → 零件 → 供应边」组织：

- 企业（company）：归并后的主体，分整车厂（oem）和零部件企业（parts）；
- 车型版本（model_version）：燃油 / 电动 / 越野三类，挂未交付订单；
- 零件（part）：车型版本 BOM 中需要采购的最小件；
- 供应边（edge）：某零部件企业对某零件在某车型版本上的供应关系，
  携带认证、产能承诺、共享设备、交期、价格与候选替代；
- 事件（event）：试制转量产、质量暂停、价格失效、设备检修、断供，
  按生效时间改变供应边的可用状态（见 ``graph.edge_state_at``）；
- 扶持措施（measure）：园区对企业的扶持，用于对比措施前后交付能力。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import json

from .names import resolve_entities

OEM = "oem"
PARTS = "parts"

MODEL_FUEL = "fuel"
MODEL_EV = "ev"
MODEL_OFFROAD = "offroad"
MODEL_KINDS = (MODEL_FUEL, MODEL_EV, MODEL_OFFROAD)

# 供应边的基础状态（未叠加事件时的生命周期阶段）。
BASE_STATES = ("trial", "mass")

# 事件类型 → 事件生效期间供应边被推向的状态。
EVENT_TYPES = {
    "trial_to_mass": "mass",       # 试制转量产：转为可用
    "quality_hold": "held",        # 质量暂停：不可用
    "price_expired": "unpriced",   # 价格失效：不可用于新的排产模拟
    "equipment_downtime": "down",  # 设备检修：窗口期内产能不可用
    "supply_stop": "stopped",      # 断供：不可用（企业停产通知）
}
# 可用（计入产能）的状态。
ACTIVE_STATES = ("mass",)
# 允许携带恢复时间（effective_to）的事件类型。
WINDOWED_EVENTS = ("quality_hold", "equipment_downtime")


def as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


@dataclass(frozen=True)
class Company:
    name: str
    aliases: tuple[str, ...]
    kind: str
    local: bool
    source_records: tuple[str, ...]


@dataclass(frozen=True)
class ModelVersion:
    code: str
    name: str
    kind: str
    oem: str
    open_orders: int


@dataclass(frozen=True)
class Part:
    code: str
    name: str
    units_per_unit: int = 1


@dataclass(frozen=True)
class Event:
    id: str
    type: str
    effective_from: date
    effective_to: date | None = None  # 质量暂停解除、设备检修结束

    @property
    def state(self) -> str:
        return EVENT_TYPES[self.type]


@dataclass(frozen=True)
class Edge:
    id: str
    model_code: str
    part_code: str
    supplier: str
    status: str  # trial / mass
    certification: str | None  # 认证编号；None 表示尚无认证
    cert_valid_from: date | None
    monthly_capacity: int
    shared_equipment: tuple[str, ...]  # 共享设备组：同组检修相互影响
    lead_time_days: int
    unit_price: float | None
    price_valid_until: date | None
    online_confirmed: bool  # 零部件企业是否已在线确认产能承诺
    events: tuple[Event, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Candidate:
    """候选替代：同零件同车型版本的另一条供应边及切换周期。"""

    edge_id: str
    switch_days: int


@dataclass(frozen=True)
class Measure:
    id: str
    company: str
    name: str
    effective_from: date


@dataclass
class Graph:
    companies: dict[str, Company]
    models: dict[str, ModelVersion]
    parts: dict[str, Part]
    edges: dict[str, Edge]
    candidates: dict[str, tuple[Candidate, ...]]
    candidate_edge_ids: frozenset[str]
    equipment_events: dict[str, tuple[Event, ...]]
    measures: tuple[Measure, ...]
    published_local_ratio: float
    # 运行期在线确认（零部件企业确认后计入，见 confirm_supply）。
    confirmed_online: set[str] = field(default_factory=set)

    def edges_for(self, model_code: str, part_code: str) -> list[Edge]:
        return [
            e
            for e in self.edges.values()
            if e.model_code == model_code and e.part_code == part_code
        ]

    def baseline_edges_for(self, model_code: str, part_code: str) -> list[Edge]:
        """计入基线产能的供应边：不含只作为候选替代登记的边。"""
        return [
            e
            for e in self.edges_for(model_code, part_code)
            if e.id not in self.candidate_edge_ids
        ]

    def parts_for_model(self, model_code: str) -> list[str]:
        return sorted({e.part_code for e in self.edges.values() if e.model_code == model_code})

    def is_confirmed(self, edge: Edge) -> bool:
        return edge.online_confirmed or edge.id in self.confirmed_online


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_graph(path: str | Path) -> Graph:
    """读取图谱 JSON，完成主体归并与全部引用完整性校验。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entities = resolve_entities(data["raw_directory"])
    _check(len(entities) >= 350, "主体归并后企业数量应达到三百五十家以上")

    companies: dict[str, Company] = {}
    for entity in entities:
        if entity["name"] in companies:
            raise ValueError(f"企业名称重复：{entity['name']}")
        companies[entity["name"]] = Company(
            name=entity["name"],
            aliases=tuple(entity["aliases"]),
            kind=entity["kind"],
            local=entity["local"],
            source_records=tuple(entity["source_records"]),
        )

    models: dict[str, ModelVersion] = {}
    kinds_present = set()
    for item in data["model_versions"]:
        _check(item["kind"] in MODEL_KINDS, f"未知车型类别：{item['kind']}")
        _check(item["oem"] in companies, f"车型版本引用未知整车企业：{item['oem']}")
        _check(companies[item["oem"]].kind == OEM, f"{item['oem']} 不是整车企业")
        models[item["code"]] = ModelVersion(
            code=item["code"],
            name=item["name"],
            kind=item["kind"],
            oem=item["oem"],
            open_orders=int(item["open_orders"]),
        )
        kinds_present.add(item["kind"])
    _check(kinds_present == set(MODEL_KINDS), "燃油、电动、越野三类车型必须齐全")

    parts: dict[str, Part] = {}
    for item in data["parts"]:
        parts[item["code"]] = Part(
            code=item["code"],
            name=item["name"],
            units_per_unit=int(item.get("units_per_unit", 1)),
        )

    measures = tuple(
        Measure(
            id=item["id"],
            company=item["company"],
            name=item["name"],
            effective_from=as_date(item["effective_from"]),
        )
        for item in data.get("measures", [])
    )
    for measure in measures:
        _check(measure.company in companies, f"扶持措施引用未知企业：{measure.company}")

    edge_events: dict[str, list[Event]] = {}
    equipment_events: dict[str, list[Event]] = {}
    for item in data.get("events", []):
        _check(item["type"] in EVENT_TYPES, f"未知事件类型：{item['type']}")
        event = Event(
            id=item["id"],
            type=item["type"],
            effective_from=as_date(item["effective_from"]),
            effective_to=as_date(item["effective_to"]) if item.get("effective_to") else None,
        )
        if event.effective_to is not None:
            _check(
                event.type in WINDOWED_EVENTS and event.effective_to > event.effective_from,
                f"事件 {event.id} 的恢复时间无效",
            )
        if event.type == "equipment_downtime":
            _check("equipment" in item, f"设备检修事件 {event.id} 缺少设备组")
            equipment_events.setdefault(item["equipment"], []).append(event)
        else:
            _check("edge_id" in item, f"事件 {event.id} 缺少供应边引用")
            edge_events.setdefault(item["edge_id"], []).append(event)

    edges: dict[str, Edge] = {}
    for item in data["edges"]:
        edge_id = item["id"]
        _check(item["supplier"] in companies, f"供应边 {edge_id} 引用未知供应商")
        _check(companies[item["supplier"]].kind == PARTS, f"供应边 {edge_id} 的供应商不是零部件企业")
        _check(item["model_code"] in models, f"供应边 {edge_id} 引用未知车型版本")
        _check(item["part_code"] in parts, f"供应边 {edge_id} 引用未知零件")
        _check(item["status"] in BASE_STATES, f"供应边 {edge_id} 状态非法")
        cert = item.get("certification")
        cert_from = as_date(item["cert_valid_from"]) if item.get("cert_valid_from") else None
        _check((cert is None) == (cert_from is None), f"供应边 {edge_id} 认证与生效时间不成对")
        price = item.get("unit_price")
        price_until = as_date(item["price_valid_until"]) if item.get("price_valid_until") else None
        _check((price is None) == (price_until is None), f"供应边 {edge_id} 价格与有效期不成对")
        events = tuple(sorted(edge_events.get(edge_id, []), key=lambda e: e.effective_from))
        edges[edge_id] = Edge(
            id=edge_id,
            model_code=item["model_code"],
            part_code=item["part_code"],
            supplier=item["supplier"],
            status=item["status"],
            certification=cert,
            cert_valid_from=cert_from,
            monthly_capacity=int(item["monthly_capacity"]),
            shared_equipment=tuple(item.get("shared_equipment", [])),
            lead_time_days=int(item["lead_time_days"]),
            unit_price=float(price) if price is not None else None,
            price_valid_until=price_until,
            online_confirmed=bool(item.get("online_confirmed", False)),
            events=events,
        )

    candidates: dict[str, tuple[Candidate, ...]] = {}
    for item in data.get("candidates", []):
        _check(item["edge_id"] in edges, f"候选替代引用未知供应边：{item['edge_id']}")
        group = []
        for alt in item["alternatives"]:
            _check(alt["edge_id"] in edges, f"候选替代指向未知供应边：{alt['edge_id']}")
            group.append(Candidate(edge_id=alt["edge_id"], switch_days=int(alt["switch_days"])))
        candidates[item["edge_id"]] = tuple(group)

    # 候选替代只能在同零件、同车型版本之间切换。
    for edge_id, group in candidates.items():
        origin = edges[edge_id]
        for cand in group:
            alt = edges[cand.edge_id]
            _check(
                alt.part_code == origin.part_code and alt.model_code == origin.model_code,
                f"替代边 {cand.edge_id} 与 {edge_id} 不属于同一零件/车型版本",
            )

    candidate_edge_ids = frozenset(
        cand.edge_id for group in candidates.values() for cand in group
    )

    return Graph(
        companies=companies,
        models=models,
        parts=parts,
        edges=edges,
        candidates=candidates,
        candidate_edge_ids=candidate_edge_ids,
        equipment_events={k: tuple(v) for k, v in equipment_events.items()},
        measures=measures,
        published_local_ratio=float(data["published_local_ratio"]),
    )
