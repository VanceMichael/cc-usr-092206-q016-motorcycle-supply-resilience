"""园区产业服务部门的分析视图。

- 单点依赖：某零件对某车型版本只有一条当前可用的认证供应链接（含共享设备
  造成的隐性单点）。
- 真实本地配套率：公布的"本地配套率"按企业注册地统计，回答不了某个零件此刻
  是否有认证产能。这里按"当前可用的认证周产能中本地供应商占比"逐零件、
  逐车型计算，并按实际需求加权汇总。
- 扶持前后交付能力：对同一断供情景分别在不启用/启用扶持措施下模拟，比较
  受影响台数、缺口与替代成本。
"""

from dataclasses import dataclass, field

from .availability import Snapshot
from .graph import Graph, PLATFORMS
from .impact import simulate_impact


@dataclass
class SinglePoint:
    part_id: str
    part_name: str
    variant_id: str
    platform: str
    link_id: str
    supplier_id: str
    supplier_name: str
    reason: str
    shared_equipment: list[str] = field(default_factory=list)


@dataclass
class LocalRate:
    scope: str                    # part / variant / overall
    target_id: str
    demand_units: int
    local_capacity: int
    total_capacity: int

    @property
    def rate(self) -> float:
        if self.total_capacity == 0:
            return 0.0
        return self.local_capacity / self.total_capacity

    @property
    def certified_at_all(self) -> bool:
        return self.total_capacity > 0


def find_single_points(graph: Graph, day) -> list[SinglePoint]:
    """找出当前每个车型版本零件需求中的单点依赖。"""
    snap = Snapshot(graph, day)
    points = []
    for variant in graph.variants.values():
        for part_id in graph.parts_required(variant.variant_id):
            usable = [
                st for st in snap.part_supply(part_id, variant.variant_id)
                if st.usable
            ]
            if len(usable) == 1:
                st = usable[0]
                link = graph.links[st.link_id]
                company = graph.registry.get(st.supplier_id)
                shared = [
                    graph.equipment[eid].name for eid in link.equipment_ids
                    if len(graph.equipment[eid].shared_by) > 1
                ]
                reason = "唯一可用认证供应"
                if shared:
                    reason += "；且依赖共享设备：" + "、".join(shared)
                points.append(SinglePoint(
                    part_id=part_id, part_name=graph.parts[part_id].name,
                    variant_id=variant.variant_id, platform=variant.platform,
                    link_id=st.link_id, supplier_id=st.supplier_id,
                    supplier_name=company.short_name, reason=reason,
                    shared_equipment=shared,
                ))
    return points


def local_content_rates(graph: Graph, day, *, horizon_weeks: int = 8
                        ) -> dict:
    """按车型版本与整体计算"有认证产能支撑"的真实本地配套率。

    口径：窗口内每周每零件需求（台数×单车用量）为权重，分子是本地供应商
    当前可用的认证周产能（封顶到需求，避免冗余产能虚高），分母同口径的
    全部可用产能。无任何认证产能的零件单独标红。
    """
    snap = Snapshot(graph, day)
    by_variant: dict[str, dict] = {}

    for order in graph.orders:
        from .availability import week_start
        from .timeutil import as_date

        offset = (week_start(as_date(order.due_week)) - snap.monday).days // 7
        if offset < 0 or offset >= horizon_weeks:
            continue
        bucket = by_variant.setdefault(order.variant_id, {
            "demand": 0, "local": 0, "total": 0, "uncovered_parts": set(),
        })
        variant = graph.variants[order.variant_id]
        bucket["demand"] += order.quantity
        for part_id, usage in graph.parts_required(variant.variant_id).items():
            need = order.quantity * usage
            states = [
                st for st in snap.part_supply(part_id, variant.variant_id)
                if st.usable
            ]
            total = sum(min(st.available_capacity, need) for st in states)
            local = 0
            remaining = need
            # 先本地后外地封顶，使分子口径与总量一致。
            for st in sorted(states, key=lambda s: not graph.registry.get(
                s.supplier_id
            ).local):
                take = min(st.available_capacity, max(0, remaining))
                remaining -= take
                if graph.registry.get(st.supplier_id).local:
                    local += take
            bucket["local"] += local
            bucket["total"] += min(total, need)
            if total == 0:
                bucket["uncovered_parts"].add(part_id)

    variants = []
    overall = {"demand": 0, "local": 0, "total": 0}
    for variant_id, b in sorted(by_variant.items()):
        rate = LocalRate(
            scope="variant", target_id=variant_id, demand_units=b["demand"],
            local_capacity=b["local"], total_capacity=b["total"],
        )
        variants.append({
            "variant_id": variant_id,
            "platform": graph.variants[variant_id].platform,
            "model": graph.variants[variant_id].model,
            "demand_units": b["demand"],
            "real_local_rate": round(rate.rate, 4),
            "has_certified_capacity": rate.certified_at_all,
            "uncovered_parts": sorted(b["uncovered_parts"]),
        })
        for key in overall:
            overall[key] += b[key]
    overall_rate = LocalRate(
        scope="overall", target_id="ALL",
        demand_units=overall["demand"],
        local_capacity=overall["local"], total_capacity=overall["total"],
    )
    return {
        "day": snap.day.isoformat(),
        "overall_real_local_rate": round(overall_rate.rate, 4),
        "overall_demand_units": overall["demand"],
        "variants": variants,
    }


def before_after_measures(graph: Graph, day, *, horizon_weeks: int = 8
                          ) -> dict:
    """同一断供通知下，扶持措施前后的交付能力对比。"""
    before = simulate_impact(graph, day, horizon_weeks=horizon_weeks,
                             apply_measures=False)
    after = simulate_impact(graph, day, horizon_weeks=horizon_weeks,
                            apply_measures=True)

    def pack(report):
        return {
            "impacted_units": report.total_impacted_units,
            "by_platform": {
                key: {
                    "orders": report.by_platform[key].orders,
                    "impacted_orders": report.by_platform[key].impacted_orders,
                    "impacted_units": report.by_platform[key].impacted_units,
                }
                for key in PLATFORMS
            },
            "residual_gap": sum(p.residual_gap for p in report.plans),
            "substitution_feasible_parts": sum(
                1 for p in report.plans if p.feasible
            ),
            "substitution_plans": sum(1 for p in report.plans),
            "weekly_short": [
                {"week": row["week"], "short_units": row["short_units"]}
                for row in report.weekly if row["short_units"]
            ],
        }

    b, a = pack(before), pack(after)
    return {
        "day": before.day,
        "before": b,
        "after": a,
        "improved_units": b["impacted_units"] - a["impacted_units"],
        "gap_closed": b["residual_gap"] - a["residual_gap"],
        "measures_in_force": [
            {
                "measure_id": ms.measure_id, "kind": ms.kind,
                "target": f"{ms.target_type}:{ms.target_id}",
                "value": ms.value, "note": ms.note,
            }
            for ms in graph.measures
        ],
    }
