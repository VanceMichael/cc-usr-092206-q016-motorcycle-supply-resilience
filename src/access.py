"""商业数据的访问控制视图。

商业数据（价格、承诺产能、是否在线确认）只向实际合作链条开放：
供应边所属的零部件企业与对应的整车企业。园区产业服务部门看到的
是结构与状态（有没有、可不可用），质量认证人员只看到认证信息。
"""

from __future__ import annotations

from dataclasses import dataclass

from .graph import edge_state_at, available_capacity, is_certified
from .model import Graph, OEM, PARTS

ROLE_OEM = OEM
ROLE_PARTS = PARTS
ROLE_PARK = "park"
ROLE_CERTIFIER = "certifier"
ROLES = (ROLE_OEM, ROLE_PARTS, ROLE_PARK, ROLE_CERTIFIER)


@dataclass(frozen=True)
class Actor:
    """查询发起方：角色 + 所属企业（园区与认证人员无企业）。"""

    role: str
    company: str | None = None

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError(f"未知角色：{self.role}")
        if self.role in (ROLE_OEM, ROLE_PARTS) and not self.company:
            raise ValueError("整车与零部件企业角色必须携带所属企业")


def _chain_of(graph: Graph, edge) -> set[str]:
    """供应边的实际合作链条：零部件企业 + 对应车型版本的整车企业。"""
    return {edge.supplier, graph.models[edge.model_code].oem}


def edge_view(graph: Graph, edge_id: str, actor: Actor, at) -> dict:
    """按角色返回供应边视图，越权访问商业数据抛出 PermissionError。"""
    edge = graph.edges[edge_id]
    structural = {
        "edge_id": edge.id,
        "model_code": edge.model_code,
        "part_code": edge.part_code,
        "supplier": edge.supplier,
        "oem": graph.models[edge.model_code].oem,
        "state": edge_state_at(graph, edge, at),
        "certified": is_certified(edge, at),
        "local": graph.companies[edge.supplier].local,
        "shared_equipment": list(edge.shared_equipment),
        "lead_time_days": edge.lead_time_days,
    }
    if actor.role in (ROLE_OEM, ROLE_PARTS):
        if actor.company not in _chain_of(graph, edge):
            raise PermissionError("商业数据只向实际合作链条开放")
        return {
            **structural,
            "certification": edge.certification,
            "cert_valid_from": edge.cert_valid_from.isoformat() if edge.cert_valid_from else None,
            "monthly_capacity": edge.monthly_capacity,
            "available_capacity": available_capacity(graph, edge, at),
            "online_confirmed": graph.is_confirmed(edge),
            "unit_price": edge.unit_price,
            "price_valid_until": edge.price_valid_until.isoformat() if edge.price_valid_until else None,
        }
    if actor.role == ROLE_PARK:
        # 园区只看结构与状态，不看价格与承诺数量。
        return {**structural, "available": available_capacity(graph, edge, at) > 0}
    # 质量认证人员只看认证信息。
    return {
        "edge_id": edge.id,
        "model_code": edge.model_code,
        "part_code": edge.part_code,
        "supplier": edge.supplier,
        "certification": edge.certification,
        "cert_valid_from": edge.cert_valid_from.isoformat() if edge.cert_valid_from else None,
        "certified": is_certified(edge, at),
    }
