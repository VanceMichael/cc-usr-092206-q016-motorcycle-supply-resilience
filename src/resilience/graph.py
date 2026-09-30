"""可计算的产业链韧性图谱结构。

节点：企业（Registry 归并后的规范主体）、零部件、车型版本、共享设备。
边：
- bom          车型版本 --N:1--> 顶层零部件（含单车用量），零部件之间用 parent 构成层级
- certification 某企业供应某零件的车型级认证（含试制/量产状态与生效期）
- commitment   供应商对某零件的周产能承诺与报价（在线确认前为草案）
- equipment    共享设备及其占用（检修事件在 availability 层解释）
- sourcing     零件 ←→ 供应商 的寻源链接，串起认证、承诺、交期、替代候选
- event        试制转量产 / 质量暂停 / 价格失效 / 设备检修 / 断供
- order        整车订单（车型版本 + 数量 + 交付周）
"""

from dataclasses import dataclass, field

from .registry import Registry, build_registry
from .timeutil import as_date

# 平台大类。
PLATFORMS = ("fuel", "electric", "offroad")

# 事件类型 → 作用对象
EVENT_KINDS = (
    "ramp",          # 试制转量产：certification 状态 trial → mass，可带产能爬坡
    "quality_hold",  # 质量暂停：暂停某寻源链接/认证
    "price_expiry",  # 价格失效：承诺报价到期
    "maintenance",   # 设备检修：共享设备在时间窗内不可用
    "supply_stop",   # 断供：供应商（可对某零件）停产
)

# 寻源链接角色
ROLE_PRIMARY = "primary"
ROLE_ALTERNATE = "alternate"


@dataclass
class Part:
    part_id: str
    name: str
    category: str          # 如 gear / controller / battery_pack
    critical: bool = False
    parent_id: str | None = None
    also_parents: list[str] = field(default_factory=list)  # 多父件（共用原料）


@dataclass
class ModelVariant:
    """车型版本：平台 + 车型 + 版本（年款/配置）。"""

    variant_id: str
    platform: str          # fuel / electric / offroad
    model: str
    version: str
    oem_id: str            # 整车企业主体 id
    bom: dict[str, int] = field(default_factory=dict)  # part_id -> 单车用量


@dataclass
class Certification:
    cert_id: str
    company_id: str
    part_id: str
    variant_id: str
    status: str            # trial / mass / suspended / revoked
    valid_from: str
    valid_to: str | None = None


@dataclass
class Commitment:
    """供应商在线确认的周产能承诺与报价。"""

    commitment_id: str
    company_id: str
    part_id: str
    capacity_per_week: int
    price: float
    currency: str
    lead_time_days: int
    confirmed: bool
    valid_from: str
    valid_to: str | None = None


@dataclass
class Equipment:
    """跨供应商共享的关键设备（如齿轮热处理线）。"""

    equipment_id: str
    name: str
    shared_by: list[str] = field(default_factory=list)  # company_id


@dataclass
class SourcingLink:
    """零件 ← 供应商 的一条合作关系，挂认证、承诺、交期与替代信息。"""

    link_id: str
    part_id: str
    supplier_id: str
    role: str                       # primary / alternate
    cert_ids: list[str] = field(default_factory=list)
    commitment_ids: list[str] = field(default_factory=list)
    equipment_ids: list[str] = field(default_factory=list)
    lead_time_days: int = 0
    candidate_for: list[str] = field(default_factory=list)  # 作为哪些 link 的替代候选
    switch_cost: float = 0.0        # 切换到该备选的一次性成本


@dataclass
class Event:
    """生效时间驱动的状态变更。

    target 类型由 kind 决定：
      ramp/quality_hold → certification 或 sourcing link
      price_expiry      → commitment
      maintenance       → equipment
      supply_stop       → supplier 企业（part_id 可选，限定零件）
    """

    event_id: str
    kind: str
    effective_from: str
    effective_to: str | None        # 暂停/检修类事件的恢复时间；断供可为空（持续）
    target_type: str                # certification / link / commitment / equipment / company
    target_id: str
    part_id: str | None = None
    note: str = ""
    ramp_curve: dict[str, int] | None = None  # 周偏移 -> 当周可达产能（试制爬坡）


@dataclass
class Measure:
    """园区扶持措施，用于对比扶持前后的交付能力。

    kind:
      capacity_grant      对某寻源链接新增周产能（扩产补贴）
      cert_acceleration   把试制认证提前视作量产可用（认证辅导/加速）
      equipment_backup    为依赖共享设备的链接配置备份产能（不受检修折减）
      price_subsidy       单位补贴，降低备选报价（仅影响成本对比）
    """

    measure_id: str
    kind: str
    target_type: str            # link / certification / equipment
    target_id: str
    value: float                # 新增周产能 / 单位补贴金额
    effective_from: str
    effective_to: str | None = None
    note: str = ""


@dataclass
class Order:
    order_id: str
    variant_id: str
    quantity: int
    due_week: str                   # ISO 周一日期
    customer_segment: str = "domestic"


@dataclass
class Graph:
    registry: Registry
    parts: dict[str, Part]
    variants: dict[str, ModelVariant]
    certifications: dict[str, Certification]
    commitments: dict[str, Commitment]
    equipment: dict[str, Equipment]
    links: dict[str, SourcingLink]
    events: list[Event]
    orders: list[Order]
    measures: list[Measure] = field(default_factory=list)
    _cert_index: dict = field(default_factory=dict, repr=False, compare=False)

    # -- 索引 -------------------------------------------------------------

    def links_for_part(self, part_id: str) -> list[SourcingLink]:
        return [lk for lk in self.links.values() if lk.part_id == part_id]

    def primary_link(self, part_id: str) -> SourcingLink | None:
        for lk in self.links_for_part(part_id):
            if lk.role == ROLE_PRIMARY:
                return lk
        return None

    def links_by_supplier(self, company_id: str) -> list[SourcingLink]:
        return [lk for lk in self.links.values() if lk.supplier_id == company_id]

    def certs_for(self, link: SourcingLink, variant_id: str) -> list[Certification]:
        index = getattr(self, "_cert_index", {})
        return list(index.get((link.link_id, variant_id), []))

    def variants_by_platform(self) -> dict[str, list[ModelVariant]]:
        result = {p: [] for p in PLATFORMS}
        for v in self.variants.values():
            result.setdefault(v.platform, []).append(v)
        return result

    def parts_required(self, variant_id: str) -> dict[str, int]:
        """车型版本的全部零件需求（含子零件展开，用量按层级相乘）。"""
        cache = getattr(self, "_parts_required_cache", None)
        if cache is None:
            cache = self._parts_required_cache = {}
        if variant_id in cache:
            return dict(cache[variant_id])
        variant = self.variants[variant_id]
        result: dict[str, int] = {}

        # 预建父件 -> 子件索引，避免每次展开都全表扫描。
        children: dict[str, list[Part]] = {}
        for child in self.parts.values():
            parents = ([child.parent_id] if child.parent_id else []) \
                + child.also_parents
            for pid in parents:
                children.setdefault(pid, []).append(child)

        def walk(part_id: str, qty: int):
            result[part_id] = result.get(part_id, 0) + qty
            for child in children.get(part_id, ()):
                walk(child.part_id, qty)

        for part_id, qty in variant.bom.items():
            walk(part_id, qty)
        cache[variant_id] = dict(result)
        return result

    def supplier_parts(self, company_id: str) -> set[str]:
        return {lk.part_id for lk in self.links_by_supplier(company_id)}


def build_graph(raw: dict, strict: bool = True) -> Graph:
    """从共享资料 JSON 构建图谱，做结构与引用完整性校验。"""
    registry = build_registry(raw["companies"], strict=strict)

    parts = {
        p["part_id"]: Part(
            part_id=p["part_id"],
            name=p["name"],
            category=p["category"],
            critical=bool(p.get("critical", False)),
            parent_id=p.get("parent_id"),
            also_parents=list(p.get("also_parent_of", [])),
        )
        for p in raw.get("parts", [])
    }
    # 子零件只能挂在已存在的父件上。
    for part in parts.values():
        parents = ([part.parent_id] if part.parent_id else []) + part.also_parents
        for pid in parents:
            if pid not in parts:
                raise ValueError(f"零件 {part.part_id} 引用了不存在的父零件 {pid}")
    variants = {}
    for v in raw.get("variants", []):
        if v["platform"] not in PLATFORMS:
            raise ValueError(f"未知平台 {v['platform']}（{v['variant_id']}）")
        for part_id in v["bom"]:
            if part_id not in parts:
                raise ValueError(f"车型 {v['variant_id']} 引用了不存在的零件 {part_id}")
        variants[v["variant_id"]] = ModelVariant(
            variant_id=v["variant_id"],
            platform=v["platform"],
            model=v["model"],
            version=v["version"],
            oem_id=registry.resolve(v["oem"]),
            bom=dict(v["bom"]),
        )

    certifications = {}
    for c in raw.get("certifications", []):
        company_id = registry.resolve(c["company"])
        if c["part_id"] not in parts:
            raise ValueError(f"认证 {c['cert_id']} 引用未知零件 {c['part_id']}")
        if c["variant_id"] not in variants:
            raise ValueError(f"认证 {c['cert_id']} 引用未知车型 {c['variant_id']}")
        if c["status"] not in ("trial", "mass", "suspended", "revoked"):
            raise ValueError(f"认证 {c['cert_id']} 状态非法: {c['status']}")
        if c.get("valid_to") and as_date(c["valid_to"]) < as_date(c["valid_from"]):
            raise ValueError(f"认证 {c['cert_id']} 有效期倒置")
        certifications[c["cert_id"]] = Certification(
            cert_id=c["cert_id"], company_id=company_id, part_id=c["part_id"],
            variant_id=c["variant_id"], status=c["status"],
            valid_from=c["valid_from"], valid_to=c.get("valid_to"),
        )

    commitments = {}
    for m in raw.get("commitments", []):
        company_id = registry.resolve(m["company"])
        if m["part_id"] not in parts:
            raise ValueError(f"承诺 {m['commitment_id']} 引用未知零件 {m['part_id']}")
        if m["capacity_per_week"] < 0 or m["price"] < 0:
            raise ValueError(f"承诺 {m['commitment_id']} 数值非法")
        commitments[m["commitment_id"]] = Commitment(
            commitment_id=m["commitment_id"], company_id=company_id,
            part_id=m["part_id"], capacity_per_week=int(m["capacity_per_week"]),
            price=float(m["price"]), currency=m.get("currency", "CNY"),
            lead_time_days=int(m.get("lead_time_days", 0)),
            confirmed=bool(m.get("confirmed", False)),
            valid_from=m["valid_from"], valid_to=m.get("valid_to"),
        )

    equipment = {}
    for e in raw.get("equipment", []):
        ids = [registry.resolve(c) for c in e.get("shared_by", [])]
        equipment[e["equipment_id"]] = Equipment(
            equipment_id=e["equipment_id"], name=e["name"], shared_by=ids,
        )

    links = {}
    for lk in raw.get("sourcing_links", []):
        supplier_id = registry.resolve(lk["supplier"])
        if lk["part_id"] not in parts:
            raise ValueError(f"链接 {lk['link_id']} 引用未知零件 {lk['part_id']}")
        if lk["role"] not in (ROLE_PRIMARY, ROLE_ALTERNATE):
            raise ValueError(f"链接 {lk['link_id']} 角色非法")
        for cid in lk.get("cert_ids", []):
            if cid not in certifications:
                raise ValueError(f"链接 {lk['link_id']} 引用未知认证 {cid}")
        for mid in lk.get("commitment_ids", []):
            if mid not in commitments:
                raise ValueError(f"链接 {lk['link_id']} 引用未知承诺 {mid}")
        for eid in lk.get("equipment_ids", []):
            if eid not in equipment:
                raise ValueError(f"链接 {lk['link_id']} 引用未知设备 {eid}")
        links[lk["link_id"]] = SourcingLink(
            link_id=lk["link_id"], part_id=lk["part_id"], supplier_id=supplier_id,
            role=lk["role"], cert_ids=list(lk.get("cert_ids", [])),
            commitment_ids=list(lk.get("commitment_ids", [])),
            equipment_ids=list(lk.get("equipment_ids", [])),
            lead_time_days=int(lk.get("lead_time_days", 0)),
            candidate_for=list(lk.get("candidate_for", [])),
            switch_cost=float(lk.get("switch_cost", 0.0)),
        )
    # 替代候选引用的链接必须存在且零件一致。
    for lk in links.values():
        for target_id in lk.candidate_for:
            if target_id not in links:
                raise ValueError(f"链接 {lk.link_id} 指向未知替代目标 {target_id}")
            if links[target_id].part_id != lk.part_id:
                raise ValueError(f"替代候选 {lk.link_id} 与 {target_id} 零件不一致")

    events = []
    for ev in raw.get("events", []):
        if ev["kind"] not in EVENT_KINDS:
            raise ValueError(f"事件类型非法: {ev['kind']}")
        if ev.get("effective_to") and as_date(ev["effective_to"]) <= as_date(ev["effective_from"]):
            raise ValueError(f"事件 {ev['event_id']} 时间窗倒置")
        events.append(Event(
            event_id=ev["event_id"], kind=ev["kind"],
            effective_from=ev["effective_from"], effective_to=ev.get("effective_to"),
            target_type=ev["target_type"], target_id=ev["target_id"],
            part_id=ev.get("part_id"), note=ev.get("note", ""),
            ramp_curve=ev.get("ramp_curve"),
        ))

    measures = []
    for ms in raw.get("measures", []):
        if ms["kind"] not in (
            "capacity_grant", "cert_acceleration",
            "equipment_backup", "price_subsidy",
        ):
            raise ValueError(f"扶持措施类型非法: {ms['kind']}")
        if ms["target_type"] not in ("link", "certification", "equipment"):
            raise ValueError(f"扶持措施目标类型非法: {ms['target_type']}")
        if ms.get("effective_to") and as_date(ms["effective_to"]) <= as_date(
            ms["effective_from"]
        ):
            raise ValueError(f"扶持措施 {ms['measure_id']} 时间窗倒置")
        measures.append(Measure(
            measure_id=ms["measure_id"], kind=ms["kind"],
            target_type=ms["target_type"], target_id=ms["target_id"],
            value=float(ms["value"]), effective_from=ms["effective_from"],
            effective_to=ms.get("effective_to"), note=ms.get("note", ""),
        ))

    orders = []
    for o in raw.get("orders", []):
        if o["variant_id"] not in variants:
            raise ValueError(f"订单 {o['order_id']} 引用未知车型 {o['variant_id']}")
        if o["quantity"] <= 0:
            raise ValueError(f"订单 {o['order_id']} 数量非法")
        orders.append(Order(
            order_id=o["order_id"], variant_id=o["variant_id"],
            quantity=int(o["quantity"]), due_week=o["due_week"],
            customer_segment=o.get("customer_segment", "domestic"),
        ))
    orders.sort(key=lambda o: o.due_week)

    graph = Graph(
        registry=registry, parts=parts, variants=variants,
        certifications=certifications, commitments=commitments,
        equipment=equipment, links=links, events=events, orders=orders,
        measures=measures,
    )
    # 认证反向索引：(link_id, variant_id) -> [Certification]。
    for lk in links.values():
        for cid in lk.cert_ids:
            cert = certifications[cid]
            graph._cert_index.setdefault(
                (lk.link_id, cert.variant_id), []
            ).append(cert)
    return graph
