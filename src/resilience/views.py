"""按角色开放数据：商业数据只向实际合作链条开放。

四类视图：
- 整车企业（oem）：自己车型 BOM 上的合作链接（主供或被主供登记的候选替代）
  可见全部商业字段（报价、周产能、承诺、订单影响、替代成本）；非合作链接只
  看到"是否存在认证产能"，报价与产能数字屏蔽。
- 零部件企业（supplier）：本企业链接可见全部字段；其他供应商链接只见认证
  状态，不见报价/产能；能看到自己所供零件在合作车型上的需求。
- 质量认证人员（certifier）：可见全部认证与质量状态，不见任何报价/产能数字。
- 园区产业服务部门（park）：可见结构、认证有无、聚合产能、本地配套率、
  单点依赖、扶持前后对比；不见单笔报价与订单明细，成本字段一律屏蔽。
"""

from dataclasses import dataclass

from .graph import Graph, ROLE_PRIMARY
from .impact import simulate_impact
from .park import find_single_points, local_content_rates, before_after_measures

ROLE_OEM = "oem"
ROLE_SUPPLIER = "supplier"
ROLE_CERTIFIER = "certifier"
ROLE_PARK = "park"

# 商业敏感字段：报价、成本、承诺原始记录、逐笔订单客户分布。
COMMERCIAL_KEYS = ("price", "currency", "switch_cost", "extra_unit_cost")


@dataclass
class Viewer:
    role: str
    company_id: str | None = None      # oem / supplier 时必填


# -- 合作链条判定 -----------------------------------------------------------


def oem_part_ids(graph: Graph, oem_id: str) -> set[str]:
    """该整车企业全部车型版本 BOM 展开后的零件集合。"""
    parts: set[str] = set()
    for variant in graph.variants.values():
        if variant.oem_id == oem_id:
            parts.update(graph.parts_required(variant.variant_id))
    return parts


def cooperation_link_ids(graph: Graph, viewer: Viewer) -> set[str]:
    """该视角实际参与的合作链条（寻源链接 id）。"""
    if viewer.role == ROLE_PARK or viewer.role == ROLE_CERTIFIER:
        return set()
    cid = viewer.company_id
    ids: set[str] = set()
    if viewer.role == ROLE_SUPPLIER:
        for lk in graph.links.values():
            if lk.supplier_id == cid:
                ids.add(lk.link_id)
        return ids
    if viewer.role == ROLE_OEM:
        for part_id in oem_part_ids(graph, cid):
            primary = graph.primary_link(part_id)
            for lk in graph.links_for_part(part_id):
                if lk.role == ROLE_PRIMARY and lk is primary:
                    ids.add(lk.link_id)
                elif primary is not None and primary.link_id in lk.candidate_for:
                    ids.add(lk.link_id)
        return ids
    return ids


def sees_commercial(graph: Graph, viewer: Viewer, link_id: str) -> bool:
    return link_id in cooperation_link_ids(graph, viewer)


# -- 链接状态投影 -----------------------------------------------------------


def project_link_state(graph: Graph, viewer: Viewer, state) -> dict:
    """把时效快照的链接状态按视角投影成可对外展示的字典。"""
    link = graph.links[state.link_id]
    supplier = graph.registry.get(state.supplier_id)
    base = {
        "link_id": state.link_id,
        "part_id": state.part_id,
        "supplier_id": state.supplier_id,
        "supplier_name": supplier.short_name,
        "local": supplier.local,
        "day": state.day,
        "role": link.role,
        "cert_status": state.cert_status,
        "certified": state.certified,
        "usable": state.usable,
        "lead_time_days": state.lead_time_days,
        "blocked_reasons": list(state.blocked_reasons),
    }
    if state.note:
        base["note"] = state.note

    trusted = viewer.role == ROLE_PARK  # 园区可见产能（供给保障属性）
    if sees_commercial(graph, viewer, state.link_id):
        base.update({
            "confirmed": state.confirmed,
            "available_capacity": state.available_capacity,
            "physical_capacity": state.physical_capacity,
            "price": state.price,
            "currency": state.currency,
            "price_valid": state.price_valid,
        })
        return base
    if trusted:
        base.update({
            "available_capacity": state.available_capacity,
            "physical_capacity": state.physical_capacity,
        })
        base["price"] = "***"
        return base
    # 非合作方：只回答"有没有认证产能"，不给数字。
    base["has_certified_capacity"] = state.usable
    base["available_capacity"] = "***"
    base["price"] = "***"
    return base


# -- 角色级报表 -------------------------------------------------------------


def oem_dashboard(graph: Graph, viewer: Viewer, day, *,
                  horizon_weeks: int = 8) -> dict:
    """整车企业视角：断供冲击 + 替代组合（含商业字段），仅限本企业车型。"""
    if viewer.role != ROLE_OEM:
        raise PermissionError("该接口仅向整车企业开放")
    own_variants = {
        vid for vid, v in graph.variants.items() if v.oem_id == viewer.company_id
    }
    report = simulate_impact(graph, day, horizon_weeks=horizon_weeks,
                             variant_filter=own_variants)
    names = {"fuel": "燃油", "electric": "智能电动", "offroad": "越野"}
    platforms = {}
    for key, agg in report.by_platform.items():
        platforms[key] = {
            "label": names[key],
            "orders_in_window": agg.orders,
            "units_in_window": agg.units,
            "impacted_orders": agg.impacted_orders,
            "impacted_units": agg.impacted_units,
        }
    return {
        "viewer": graph.registry.get(viewer.company_id).short_name,
        "day": report.day,
        "answer": report.answer_lines(),
        "by_platform": platforms,
        "orders": [
            {
                "order_id": o.order_id, "model": o.model,
                "due_week": o.due_week, "quantity": o.quantity,
                "short_qty": o.short_qty, "bottlenecks": o.bottlenecks,
            }
            for o in report.orders if o.variant_id in own_variants
        ],
        "substitution_plans": [
            {
                "part": p.part_name, "variant_id": p.variant_id,
                "displaced_units": p.displaced_units,
                "substituted_units": p.substituted_units,
                "residual_gap": p.residual_gap,
                "feasible": p.feasible,
                "primary_price": p.primary_price,
                "one_time_switch_cost": p.one_time_switch_cost,
                "extra_unit_cost": round(p.extra_unit_cost, 2),
                "allocations": [
                    {
                        "supplier": a.supplier_name, "qty": a.qty,
                        "weekly_capacity": a.weekly_capacity,
                        "lead_time_days": a.lead_time_days,
                        "unit_price": a.price,
                        "alternate": a.is_alternate,
                    }
                    for a in p.allocations
                ],
            }
            for p in report.plans if p.variant_id in own_variants
        ],
        "weekly": report.weekly,
    }


def supplier_dashboard(graph: Graph, viewer: Viewer, day) -> dict:
    """零部件企业视角：本企业链接的实时状态与所供零件的需求。"""
    if viewer.role != ROLE_SUPPLIER:
        raise PermissionError("该接口仅向零部件企业开放")
    from .availability import Snapshot

    snap = Snapshot(graph, day)
    own_links = graph.links_by_supplier(viewer.company_id)
    links_view, parts_seen = [], set()
    demand_rows = []
    for lk in own_links:
        parts_seen.add(lk.part_id)
        for variant in graph.variants.values():
            if lk.part_id not in graph.parts_required(variant.variant_id):
                continue
            st = snap.link_state(lk, variant.variant_id)
            links_view.append(project_link_state(graph, viewer, st))
            due_units = sum(
                o.quantity for o in graph.orders
                if o.variant_id == variant.variant_id
            )
            demand_rows.append({
                "part_id": lk.part_id,
                "variant_id": variant.variant_id,
                "model": variant.model,
                "weekly_need_per_unit": graph.parts_required(
                    variant.variant_id
                )[lk.part_id],
                "units_on_order": due_units,
            })
    company = graph.registry.get(viewer.company_id)
    return {
        "viewer": company.short_name,
        "day": snap.day.isoformat(),
        "my_links": links_view,
        "demand_on_my_parts": demand_rows,
    }


def certifier_dashboard(graph: Graph, viewer: Viewer, day) -> dict:
    """质量认证人员：全部认证的实时状态与暂停事件。"""
    if viewer.role != ROLE_CERTIFIER:
        raise PermissionError("该接口仅向质量认证人员开放")
    from .availability import Snapshot

    snap = Snapshot(graph, day)
    rows = []
    for cert in graph.certifications.values():
        rows.append({
            "cert_id": cert.cert_id,
            "company": graph.registry.get(cert.company_id).short_name,
            "part_id": cert.part_id,
            "variant_id": cert.variant_id,
            "recorded_status": cert.status,
            "effective_status": snap.cert_state(cert),
            "valid_from": cert.valid_from,
            "valid_to": cert.valid_to,
        })
    holds = [
        {
            "event_id": ev.event_id, "target": f"{ev.target_type}:{ev.target_id}",
            "from": ev.effective_from, "to": ev.effective_to, "note": ev.note,
        }
        for ev in snap._events_active.get("quality_hold", [])
    ]
    return {"day": snap.day.isoformat(), "certifications": rows, "active_holds": holds}


def park_dashboard(graph: Graph, viewer: Viewer, day, *,
                   horizon_weeks: int = 8) -> dict:
    """园区视角：单点依赖、真实本地配套率、扶持前后交付能力（成本屏蔽）。"""
    if viewer.role != ROLE_PARK:
        raise PermissionError("该接口仅向园区产业服务部门开放")
    points = find_single_points(graph, day)
    rates = local_content_rates(graph, day, horizon_weeks=horizon_weeks)
    comparison = before_after_measures(graph, day, horizon_weeks=horizon_weeks)

    return {
        "day": rates["day"],
        "single_point_dependencies": [
            {
                "part": p.part_name, "variant_id": p.variant_id,
                "platform": p.platform, "supplier": p.supplier_name,
                "local": graph.registry.get(p.supplier_id).local,
                "reason": p.reason,
            }
            for p in points
        ],
        "real_local_content_rate": rates,
        "delivery_before_after_support": comparison,
    }
