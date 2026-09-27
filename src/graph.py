"""韧性图谱的可用性计算与查询。

核心问题：某零件在某车型版本上「此刻是否有认证产能」。答案由四步推出：

1. 供应边的基础状态（试制 / 量产）叠加按生效时间排序的事件，得到
   该边在时刻 t 的状态（见 ``edge_state_at``）；
2. 状态为量产的边还要求认证已生效、产能承诺已在线确认，才计入
   可用产能（见 ``available_capacity``）；
3. 车型版本的可交付量取 BOM 各零件可用产能的最小值（瓶颈零件决定
   整车交付，见 ``buildable_units``）；
4. 在此之上回答停产影响、单点依赖、真实本地配套率、扶持措施前后
   对比，以及整车企业的订单变化与替代组合模拟。
"""

from __future__ import annotations

from datetime import date, timedelta

from .model import (
    ACTIVE_STATES,
    EVENT_TYPES,
    Graph,
    Edge,
    ModelVersion,
    as_date,
)

# 状态严重度：数值大者覆盖小者。试制转量产是唯一的「升级」。
_SEVERITY = {"trial": 0, "mass": 0, "unpriced": 1, "down": 2, "held": 3, "stopped": 4}


def _merge(state: str, candidate: str) -> str:
    if candidate == "mass":
        return "mass" if state == "trial" else state
    return candidate if _SEVERITY[candidate] > _SEVERITY[state] else state


def _event_active(event, t: date) -> bool:
    if t < event.effective_from:
        return False
    return event.effective_to is None or t < event.effective_to


def edge_state_at(graph: Graph, edge: Edge, t, *, suppress_stop_for: str | None = None) -> str:
    """供应边在时刻 t 的状态：基础状态叠加事件与共享设备检修。

    ``suppress_stop_for`` 用于停产影响的 what-if 分析：评估某企业时
    暂时忽略其断供事件，还原「按承诺应交付」的基线。
    """
    t = as_date(t)
    state = edge.status
    # 价格自然到期与「价格失效」事件一样，使该边不可用于排产。
    if state == "mass" and edge.price_valid_until is not None and t > edge.price_valid_until:
        state = "unpriced"
    for event in edge.events:
        if event.type == "supply_stop" and edge.supplier == suppress_stop_for:
            continue
        if _event_active(event, t):
            state = _merge(state, event.state)
    for group in edge.shared_equipment:
        for event in graph.equipment_events.get(group, ()):
            if _event_active(event, t):
                state = _merge(state, "down")
    return state


def is_certified(edge: Edge, t) -> bool:
    """认证已签发且到时刻 t 已生效。"""
    t = as_date(t)
    return edge.certification is not None and edge.cert_valid_from <= t


def available_capacity(graph: Graph, edge: Edge, t, *, suppress_stop_for: str | None = None) -> int:
    """时刻 t 该边可计入的月产能：量产状态 + 认证生效 + 在线确认。"""
    if edge_state_at(graph, edge, t, suppress_stop_for=suppress_stop_for) not in ACTIVE_STATES:
        return 0
    if not is_certified(edge, t):
        return 0
    if not graph.is_confirmed(edge):
        return 0
    return edge.monthly_capacity


def part_supply(graph: Graph, model_code: str, part_code: str, t, *,
                exclude_supplier: str | None = None,
                extra_edges: tuple[str, ...] = (),
                suppress_stop_for: str | None = None) -> int:
    """某零件在某车型版本上的基线可用产能合计（候选替代不计入）。"""
    total = 0
    for edge in graph.baseline_edges_for(model_code, part_code):
        if exclude_supplier is not None and edge.supplier == exclude_supplier:
            continue
        total += available_capacity(graph, edge, t, suppress_stop_for=suppress_stop_for)
    for edge_id in extra_edges:
        edge = graph.edges[edge_id]
        if edge.model_code == model_code and edge.part_code == part_code:
            total += available_capacity(graph, edge, t)
    return total


def buildable_units(graph: Graph, model_code: str, t, *,
                    exclude_supplier: str | None = None,
                    extra_edges: tuple[str, ...] = (),
                    suppress_stop_for: str | None = None) -> int:
    """瓶颈零件决定的可交付整车数（不封顶于订单数）。"""
    limits = []
    for part_code in graph.parts_for_model(model_code):
        part = graph.parts[part_code]
        supply = part_supply(
            graph, model_code, part_code, t,
            exclude_supplier=exclude_supplier, extra_edges=extra_edges,
            suppress_stop_for=suppress_stop_for,
        )
        limits.append(supply // part.units_per_unit)
    return min(limits) if limits else 0


def _version_report(graph, model: ModelVersion, t, **kwargs) -> dict:
    orders = kwargs.pop("orders", None)
    orders = model.open_orders if orders is None else orders
    buildable = buildable_units(graph, model.code, t, **kwargs)
    return {
        "open_orders": orders,
        "buildable": buildable,
        "shortfall": max(0, orders - buildable),
    }


def impact_of_supply_stop(graph: Graph, supplier: str, t) -> dict:
    """某零部件企业停产后，燃油 / 电动 / 越野各有多少订单受影响。

    对每个车型版本，比较包含与剔除该企业供应边时的可交付量，差值
    才是这次停产新造成的订单缺口；缺口按零件定位，并给出每条受阻
    零件已登记的候选替代及其当前可用产能。
    """
    t = as_date(t)
    if supplier not in graph.companies:
        raise ValueError(f"未知企业：{supplier}")
    by_kind: dict[str, dict] = {}
    for model in graph.models.values():
        buildable_with = buildable_units(graph, model.code, t, suppress_stop_for=supplier)
        buildable_without = buildable_units(graph, model.code, t, exclude_supplier=supplier)
        affected = max(0, min(model.open_orders, buildable_with) - buildable_without)
        blocking = []
        for part_code in graph.parts_for_model(model.code):
            part = graph.parts[part_code]
            own_edges = [
                e for e in graph.edges_for(model.code, part_code) if e.supplier == supplier
            ]
            if not own_edges:
                continue
            required = model.open_orders * part.units_per_unit
            with_supply = part_supply(graph, model.code, part_code, t, suppress_stop_for=supplier)
            remaining = part_supply(graph, model.code, part_code, t, exclude_supplier=supplier)
            if remaining >= required or with_supply <= remaining:
                continue
            candidates = []
            for edge in own_edges:
                for cand in graph.candidates.get(edge.id, ()):
                    alt = graph.edges[cand.edge_id]
                    candidates.append({
                        "edge_id": alt.id,
                        "supplier": alt.supplier,
                        "switch_days": cand.switch_days,
                        "available_capacity": available_capacity(graph, alt, t),
                        "state": edge_state_at(graph, alt, t),
                    })
            blocking.append({
                "part": part_code,
                "required": required,
                "available_without_supplier": remaining,
                "candidates": candidates,
            })
        bucket = by_kind.setdefault(model.kind, {"affected_orders": 0, "versions": {}})
        bucket["affected_orders"] += affected
        bucket["versions"][model.code] = {
            "open_orders": model.open_orders,
            "buildable_with_supplier": buildable_with,
            "buildable_without_supplier": buildable_without,
            "affected_orders": affected,
            "blocking_parts": blocking,
        }
    return {
        "supplier": supplier,
        "at": t.isoformat(),
        "by_kind": by_kind,
        "total_affected": sum(b["affected_orders"] for b in by_kind.values()),
    }


def single_point_parts(graph: Graph, t) -> list[dict]:
    """只剩一家可用供应商的（车型版本, 零件），即单点依赖。"""
    t = as_date(t)
    findings = []
    for model in graph.models.values():
        for part_code in graph.parts_for_model(model.code):
            edges = graph.baseline_edges_for(model.code, part_code)
            alive = [e for e in edges if available_capacity(graph, e, t) > 0]
            suppliers = {e.supplier for e in alive}
            if len(suppliers) != 1:
                continue
            supplier = next(iter(suppliers))
            findings.append({
                "model": model.code,
                "kind": model.kind,
                "part": part_code,
                "supplier": supplier,
                "local": graph.companies[supplier].local,
                "has_candidates": any(e.id in graph.candidates for e in edges),
            })
    findings.sort(key=lambda f: (f["kind"], f["model"], f["part"]))
    return findings


def certified_local_ratio(graph: Graph, model_code: str, t) -> dict:
    """真实本地配套率：BOM 中此刻有本地认证产能的零件占比。

    与园区公布的 ``published_local_ratio`` 对照——公布值回答不了
    某个零件此刻是否有认证产能。
    """
    t = as_date(t)
    detail = {}
    for part_code in graph.parts_for_model(model_code):
        ok = any(
            available_capacity(graph, e, t) > 0 and graph.companies[e.supplier].local
            for e in graph.baseline_edges_for(model_code, part_code)
        )
        detail[part_code] = ok
    total = len(detail)
    covered = sum(1 for ok in detail.values() if ok)
    return {
        "model": model_code,
        "parts_total": total,
        "parts_with_local_certified_capacity": covered,
        "ratio": covered / total if total else 0.0,
        "published_ratio": graph.published_local_ratio,
        "detail": detail,
    }


def delivery_capability(graph: Graph, t) -> dict:
    """按车型类别汇总：在手订单、可交付量、交付覆盖率。"""
    t = as_date(t)
    capability: dict[str, dict] = {}
    for model in graph.models.values():
        bucket = capability.setdefault(model.kind, {"open_orders": 0, "buildable": 0})
        bucket["open_orders"] += model.open_orders
        bucket["buildable"] += buildable_units(graph, model.code, t)
    for bucket in capability.values():
        orders = bucket["open_orders"]
        bucket["coverage"] = min(bucket["buildable"], orders) / orders if orders else 1.0
    return capability


def compare_capability(graph: Graph, before, after) -> dict:
    """两个时点交付能力的差值，用于观察扶持措施前后是否改善。"""
    before, after = as_date(before), as_date(after)
    if after <= before:
        raise ValueError("after 必须晚于 before")
    a, b = delivery_capability(graph, before), delivery_capability(graph, after)
    kinds = sorted(set(a) | set(b))
    return {
        "before": before.isoformat(),
        "after": after.isoformat(),
        "by_kind": {
            kind: {
                "before": a.get(kind, {"open_orders": 0, "buildable": 0, "coverage": 1.0}),
                "after": b.get(kind, {"open_orders": 0, "buildable": 0, "coverage": 1.0}),
                "buildable_delta": b.get(kind, {}).get("buildable", 0)
                - a.get(kind, {}).get("buildable", 0),
            }
            for kind in kinds
        },
    }


def measure_effect(graph: Graph, measure_id: str, after) -> dict:
    """扶持措施生效前一天与指定时点的交付能力对比。"""
    measure = next((m for m in graph.measures if m.id == measure_id), None)
    if measure is None:
        raise ValueError(f"未知扶持措施：{measure_id}")
    result = compare_capability(graph, measure.effective_from - timedelta(days=1), after)
    result["measure"] = {"id": measure.id, "company": measure.company, "name": measure.name}
    return result


def confirm_supply(graph: Graph, actor, edge_id: str) -> None:
    """零部件企业在线确认产能承诺；确认后才计入可用产能。"""
    edge = graph.edges[edge_id]
    if getattr(actor, "role", None) != "parts" or actor.company != edge.supplier:
        raise PermissionError("只有该供应边所属的零部件企业才能在线确认承诺")
    graph.confirmed_online.add(edge_id)


def simulate(graph: Graph, actor, t, *,
             order_overrides: dict[str, int] | None = None,
             use_candidates: dict[str, list[str]] | None = None) -> dict:
    """整车企业模拟订单变化与替代组合。

    - ``order_overrides``：车型版本 → 新的订单量；
    - ``use_candidates``：原供应边 → 启用的候选替代边列表。

    替代边必须已登记、属于该整车企业的车型版本，且自身在时刻 t 可用
    （状态、认证、确认任一不满足都会在报告中注明原因）。
    """
    t = as_date(t)
    if getattr(actor, "role", None) != "oem":
        raise PermissionError("只有整车企业可以模拟订单与替代组合")
    own_models = {m.code: m for m in graph.models.values() if m.oem == actor.company}
    order_overrides = order_overrides or {}
    use_candidates = use_candidates or {}
    for code in order_overrides:
        if code not in own_models:
            raise PermissionError(f"车型版本 {code} 不属于该整车企业")
    extra_by_model: dict[str, list[str]] = {}
    notes = []
    for origin_id, alt_ids in use_candidates.items():
        if origin_id not in graph.edges:
            raise ValueError(f"未知供应边：{origin_id}")
        origin = graph.edges[origin_id]
        if origin.model_code not in own_models:
            raise PermissionError(f"供应边 {origin_id} 不属于该整车企业")
        registered = {c.edge_id: c for c in graph.candidates.get(origin_id, ())}
        for alt_id in alt_ids:
            if alt_id not in graph.edges:
                raise ValueError(f"未知供应边：{alt_id}")
            alt = graph.edges[alt_id]
            if alt.model_code not in own_models:
                raise PermissionError(f"替代边 {alt_id} 不属于该整车企业")
            if alt_id not in registered:
                raise ValueError(f"{alt_id} 不是 {origin_id} 已登记的候选替代")
            state = edge_state_at(graph, alt, t)
            if state not in ACTIVE_STATES:
                notes.append(f"替代边 {alt_id} 当前状态为 {state}，暂不可用")
            elif not is_certified(alt, t):
                notes.append(f"替代边 {alt_id} 认证尚未生效")
            elif not graph.is_confirmed(alt):
                notes.append(f"替代边 {alt_id} 产能承诺未在线确认")
            extra_by_model.setdefault(alt.model_code, []).append(alt_id)
    versions = {}
    for code, model in sorted(own_models.items()):
        orders = int(order_overrides.get(code, model.open_orders))
        extra = tuple(extra_by_model.get(code, ()))
        report = _version_report(graph, model, t, orders=orders, extra_edges=extra)
        limiting = [
            part_code
            for part_code in graph.parts_for_model(code)
            if part_supply(graph, code, part_code, t, extra_edges=extra)
            // graph.parts[part_code].units_per_unit
            < orders
        ]
        report["limiting_parts"] = limiting
        versions[code] = report
    return {
        "oem": actor.company,
        "at": t.isoformat(),
        "versions": versions,
        "total_shortfall": sum(v["shortfall"] for v in versions.values()),
        "notes": notes,
    }
