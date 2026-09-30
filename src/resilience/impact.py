"""断供冲击评估与替代组合模拟。

模型
----
- 订单按交付周、车型版本汇总。
- 每个零件的供应商周产能是一个池子（承诺以"零件 × 供应商"为粒度），
  在同周各车型间共享，不重复计数。供应商对车型只有在该车型有当前可用的
  量产认证时，产能才能服务该车型。
- 候选备选受交期约束：通知周起经过 ceil(交期/7) 周后才就绪。
- 分配顺序：主供优先，备选按单位报价升序补位；每周围绕"零件 × 供应商"
  池子，在有认证的车型需求间按订单先后分配。
- 基线情景临时移除断供阻断，断供情景保留——两者之差即被替代/缺口量。
"""

from dataclasses import dataclass, field
from datetime import timedelta

from .availability import Snapshot, week_start
from .graph import Graph, ROLE_PRIMARY
from .timeutil import as_date


def _weeks_to_ready(lead_time_days: int) -> int:
    """承诺交期折算为自通知周起的就绪周数。

    到货日落在第 n 个自然周（周一起算）即计入第 n 周：lead 7 天为次周一，
    就绪周为 1；lead 10 天落在次周内，就绪周也是 1。
    """
    if lead_time_days <= 0:
        return 0
    return max(1, lead_time_days // 7)


@dataclass
class Allocation:
    link_id: str
    supplier_id: str
    supplier_name: str
    qty: int
    weekly_capacity: int
    lead_time_days: int
    price: float
    is_alternate: bool


@dataclass
class SubstitutionPlan:
    part_id: str
    part_name: str
    variant_id: str
    displaced_units: int = 0               # 断供主供原本承担、需转移的量
    substituted_units: int = 0             # 已被备选接住的量
    residual_gap: int = 0                  # 无认证备选可覆盖的量
    allocations: list[Allocation] = field(default_factory=list)
    one_time_switch_cost: float = 0.0
    extra_unit_cost: float = 0.0           # 替代部分相对主供报价的差价合计
    primary_price: float | None = None

    @property
    def feasible(self) -> bool:
        return self.residual_gap == 0


@dataclass
class OrderImpact:
    order_id: str
    variant_id: str
    platform: str
    model: str
    due_week: str
    quantity: int
    short_qty: int
    bottlenecks: list[str] = field(default_factory=list)

    @property
    def impacted(self) -> bool:
        return self.short_qty > 0


@dataclass
class PlatformImpact:
    platform: str
    orders: int = 0
    units: int = 0
    impacted_orders: int = 0
    impacted_units: int = 0


@dataclass
class ImpactReport:
    day: str
    horizon_weeks: int
    by_platform: dict[str, PlatformImpact]
    orders: list[OrderImpact]
    plans: list[SubstitutionPlan]
    weekly: list[dict]

    @property
    def total_impacted_units(self) -> int:
        return sum(p.impacted_units for p in self.by_platform.values())

    def answer_lines(self) -> list[str]:
        names = {"fuel": "燃油", "electric": "智能电动", "offroad": "越野"}
        return [
            f"{names[key]}：{self.by_platform[key].impacted_orders} 笔订单 / "
            f"{self.by_platform[key].impacted_units} 台车受影响"
            f"（窗口内共 {self.by_platform[key].orders} 笔、"
            f"{self.by_platform[key].units} 台）"
            for key in ("fuel", "electric", "offroad")
        ]


# -- 周度分配 ---------------------------------------------------------------


@dataclass
class _Pool:
    """一个零件的供应商周产能池及其在各车型上的认证可用性。"""

    link_id: str
    supplier_id: str
    capacity: int
    price: float
    is_primary: bool
    ready_week: int          # 备选自通知周起的切换就绪周；在途主供为 0
    serves_variants: set[str]


def _build_pools(snapshot: Snapshot, part_id: str, baseline: bool,
                 notify_monday, week_offset: int) -> list[_Pool]:
    graph = snapshot.graph
    pools = []
    # 紧急切换交期仅在该零件主供被中断（断供/质量暂停）时才对备选生效；
    # 主供正常时，认证备选是常规多源，随时可供。
    primary_link = graph.primary_link(part_id)
    part_disrupted = False
    if not baseline and primary_link is not None:
        stopped = snapshot._stopped_suppliers().get(primary_link.supplier_id)
        if stopped is not None and (None in stopped or part_id in stopped):
            part_disrupted = True
        if snapshot._events_on("quality_hold", "link", primary_link.link_id):
            part_disrupted = True
    for link in graph.links_for_part(part_id):
        # 该供应商在此零件上对哪些车型当前有可用量产认证。
        serves = set()
        capacities: list[int] = []
        price = None
        lead = link.lead_time_days
        for variant in graph.variants.values():
            st = snapshot.link_state(
                link, variant.variant_id, ignore_supply_stop=baseline
            )
            if st.usable:
                serves.add(variant.variant_id)
                capacities.append(st.available_capacity)
                price = st.price
                lead = st.lead_time_days
        if not serves:
            continue
        # 零件×供应商周产能是共享池：取各车型认证可见产能（同一条承诺）。
        capacity = max(capacities)
        is_primary = link.role == ROLE_PRIMARY and not link.candidate_for
        # 断供/主供暂停情景下，备选受紧急切换交期约束；其余情形备选即常规多源。
        ready = _weeks_to_ready(lead) if (
            not baseline and not is_primary and part_disrupted
        ) else 0
        # 当周已有试制转量产或认证加速生效：该备选按爬坡计划当周即可交付。
        if ready > week_offset and not baseline:
            activated = bool(snapshot._events_on("ramp", "link", link.link_id))
            if not activated:
                for cid in link.cert_ids:
                    if snapshot._events_on("ramp", "certification", cid):
                        activated = True
                        break
            if not activated and snapshot.apply_measures:
                if snapshot._measures_on("cert_acceleration", "link",
                                         link.link_id):
                    activated = True
                else:
                    for cid in link.cert_ids:
                        if snapshot._measures_on(
                            "cert_acceleration", "certification", cid
                        ):
                            activated = True
                            break
            if activated:
                ready = week_offset
        pools.append(_Pool(
            link_id=link.link_id, supplier_id=link.supplier_id,
            capacity=capacity,
            price=price if price is not None else float("inf"),
            is_primary=is_primary,
            ready_week=ready,
            serves_variants=serves,
        ))
    # 主供优先，其后备选按报价、再按就绪周。
    pools.sort(key=lambda p: (not p.is_primary, p.price, p.ready_week,
                              p.link_id))
    return pools


def _greedy(pools, needs, week_offset, variant_order,
            *, reserved=None):
    """按主供→报价次序把需求分给已就绪池。

    reserved: {link_id: {variant_id: 已预占件数}}（危机时保留备选的常规供货）。
    返回 (各车型缺口, {link_id: {variant_id: 总分配件数}})。
    """
    allocations: dict[str, dict[str, int]] = {}
    used_cap: dict[str, int] = {}
    remaining = dict(needs)
    for lid, per in (reserved or {}).items():
        allocations[lid] = dict(per)
        used_cap[lid] = sum(per.values())
        for vid, qty in per.items():
            remaining[vid] = remaining.get(vid, 0) - qty

    for pool in pools:
        if pool.ready_week > week_offset or pool.capacity <= 0:
            continue
        free_cap = pool.capacity - used_cap.get(pool.link_id, 0)
        for variant_id in variant_order:
            if free_cap <= 0 or remaining.get(variant_id, 0) <= 0:
                continue
            if variant_id not in pool.serves_variants:
                continue
            take = min(free_cap, remaining[variant_id])
            free_cap -= take
            remaining[variant_id] -= take
            row = allocations.setdefault(pool.link_id, {})
            row[variant_id] = row.get(variant_id, 0) + take
            used_cap[pool.link_id] = used_cap.get(pool.link_id, 0) + take

    gaps = {vid: max(0, qty) for vid, qty in remaining.items()}
    return gaps, allocations


def _allocate_part_week(snapshot: Snapshot, part_id: str, week_offset: int,
                        needs: dict[str, int], baseline: bool,
                        notify_monday) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """把某零件一周内各车型需求分给供应商池。

    needs: variant_id -> 该零件需求件数。
    断供情景遵循"先保备选已有的常规供货，再用剩余产能救急"：按基线分配
    预占未中断链接的既有量，剩余需求再用各池空闲产能按报价补位。
    """
    variant_order = sorted(needs)
    base_pools = _build_pools(snapshot, part_id, True,
                              notify_monday, week_offset)
    if baseline:
        return _greedy(base_pools, needs, week_offset, variant_order)

    stop_pools = _build_pools(snapshot, part_id, False,
                              notify_monday, week_offset)
    _, base_alloc = _greedy(base_pools, needs, week_offset, variant_order)
    surviving_links = {p.link_id for p in stop_pools}

    # 预占：幸存链接（在供主供与已在用备选）保留其基线供货，危机不把缺口
    # 在车型间转嫁；空闲产能才用于接住断供主供原来的量。
    reserved: dict[str, dict[str, int]] = {}
    for lid, per_variant in base_alloc.items():
        if lid in surviving_links:
            reserved[lid] = dict(per_variant)
    return _greedy(stop_pools, needs, week_offset, variant_order,
                   reserved=reserved)


# -- 主流程 -----------------------------------------------------------------


def simulate_impact(graph: Graph, day, *, horizon_weeks: int = 8,
                    apply_measures: bool = False,
                    variant_filter: set[str] | None = None) -> ImpactReport:
    """评估断供通知日之后 horizon_weeks 周内的订单冲击与替代组合。"""
    snapshot = Snapshot(graph, day, apply_measures=apply_measures)
    notify_monday = snapshot.monday

    # 订单按周、车型汇总；记录每笔订单所属周。
    week_units: dict[tuple[int, str], int] = {}
    order_meta: list[tuple] = []
    for order in graph.orders:
        if variant_filter is not None and order.variant_id not in variant_filter:
            continue
        due = week_start(as_date(order.due_week))
        offset = (due - notify_monday).days // 7
        if offset < 0 or offset >= horizon_weeks:
            continue
        week_units[(offset, order.variant_id)] = week_units.get(
            (offset, order.variant_id), 0
        ) + order.quantity
        order_meta.append((order, offset))

    part_ids = sorted(graph.parts)
    # 结果容器：gap[(week, part)] -> {variant: 缺口件数}
    # alloc[scenario][week][part] = {link: {variant: qty}}
    gaps: dict[str, dict] = {"stop": {}, "base": {}}
    alloc: dict[str, dict[int, dict[str, dict]]] = {"stop": {}, "base": {}}

    weekly_rows: dict[int, dict] = {}
    for (offset, variant_id), units in sorted(week_units.items()):
        row = weekly_rows.setdefault(offset, {
            "week": (notify_monday + timedelta(weeks=offset)).isoformat(),
            "demand_units": 0, "short_units": 0,
        })
        row["demand_units"] += units

    # 逐周构建时效快照：爬坡、检修、质量暂停、承诺与措施窗口都按各周一生效状态计算。
    def week_snapshot(offset: int) -> Snapshot:
        return Snapshot(
            graph, notify_monday + timedelta(weeks=offset),
            apply_measures=apply_measures,
        )

    def stopped_link_ids(snap: Snapshot, part_id: str) -> set[str]:
        """该周该零件处于断供状态的寻源链接。"""
        stopped = snap._stopped_suppliers()
        ids = set()
        for lk in graph.links_for_part(part_id):
            parts = stopped.get(lk.supplier_id)
            if parts is not None and (None in parts or part_id in parts):
                ids.add(lk.link_id)
        return ids

    # 逐周逐零件：把该周全部车型需求一起送入共享产能池。
    weeks = sorted({w for (w, _) in week_units})
    stopped_by_week: dict[int, set[str]] = {}
    for offset in weeks:
        snap_w = week_snapshot(offset)
        stopped_by_week[offset] = set()
        variants_this_week = {
            vid: units for (w, vid), units in week_units.items() if w == offset
        }
        for part_id in part_ids:
            needs = {}
            for vid, units in variants_this_week.items():
                req = graph.parts_required(vid)
                if part_id in req:
                    needs[vid] = units * req[part_id]
            if not needs:
                continue
            stopped_by_week[offset] |= stopped_link_ids(snap_w, part_id)
            for scenario, baseline in (("stop", False), ("base", True)):
                part_gaps, part_alloc = _allocate_part_week(
                    snap_w, part_id, offset, needs, baseline,
                    notify_monday,
                )
                gaps[scenario][(offset, part_id)] = part_gaps
                alloc[scenario].setdefault(offset, {})[part_id] = part_alloc

    # 车型×周因断供新增的短缺台数 = min over parts of (断供增量缺口 / 单车用量)。
    short_variant_week: dict[tuple[int, str], int] = {}
    bottleneck_names: dict[tuple[int, str], list[str]] = {}
    for (offset, variant_id), units in week_units.items():
        req = graph.parts_required(variant_id)
        caps = []
        names = []
        for part_id, usage in req.items():
            stop_gap = gaps["stop"].get((offset, part_id), {}).get(variant_id, 0)
            base_gap = gaps["base"].get((offset, part_id), {}).get(variant_id, 0)
            delta_gap = stop_gap - base_gap
            if delta_gap > 0:
                caps.append(delta_gap // usage)
                names.append(f"{graph.parts[part_id].name}缺{delta_gap}件")
        if caps:
            short_variant_week[(offset, variant_id)] = min(units, min(caps))
            bottleneck_names[(offset, variant_id)] = names
            weekly_rows[offset]["short_units"] += short_variant_week[
                (offset, variant_id)
            ]

    # 订单级：同车型同周按订单先后承接短缺。
    order_impacts: list[OrderImpact] = []
    remaining_short = dict(short_variant_week)
    for order, offset in sorted(order_meta, key=lambda x: (x[1], x[0].order_id)):
        variant = graph.variants[order.variant_id]
        short = min(order.quantity,
                    remaining_short.get((offset, order.variant_id), 0))
        remaining_short[(offset, order.variant_id)] = (
            remaining_short.get((offset, order.variant_id), 0) - short
        )
        order_impacts.append(OrderImpact(
            order_id=order.order_id, variant_id=order.variant_id,
            platform=variant.platform, model=variant.model,
            due_week=order.due_week, quantity=order.quantity, short_qty=short,
            bottlenecks=bottleneck_names.get((offset, order.variant_id), []),
        ))

    by_platform = {p: PlatformImpact(platform=p)
                   for p in ("fuel", "electric", "offroad")}
    for oi in order_impacts:
        agg = by_platform[oi.platform]
        agg.orders += 1
        agg.units += oi.quantity
        if oi.impacted:
            agg.impacted_orders += 1
            agg.impacted_units += oi.short_qty

    plans = _build_plans(graph, week_snapshot, week_units, gaps, alloc,
                         stopped_by_week)
    return ImpactReport(
        day=snapshot.day.isoformat(), horizon_weeks=horizon_weeks,
        by_platform=by_platform, orders=order_impacts, plans=plans,
        weekly=[weekly_rows[k] for k in sorted(weekly_rows)],
    )


def _build_plans(graph, week_snapshot, week_units, gaps, alloc,
                 stopped_by_week) -> list[SubstitutionPlan]:
    """对比基线/断供两套分配，逐零件车型汇总跨周替代组合。

    会计恒等式（每个 周×零件×车型）：
      转移量（断供链接基线承担量）= 备选新增分配 + 增量缺口
    """
    plans: dict[tuple[str, str], SubstitutionPlan] = {}
    books: dict[tuple[str, str], dict[str, dict]] = {}

    for (offset, variant_id), units in sorted(week_units.items()):
        snap_w = week_snapshot(offset)
        stopped_links = stopped_by_week.get(offset, set())
        req = graph.parts_required(variant_id)
        for part_id, usage in req.items():
            stop_gap = gaps["stop"].get((offset, part_id), {}).get(variant_id, 0)
            base_gap = gaps["base"].get((offset, part_id), {}).get(variant_id, 0)
            stop_by_link = alloc["stop"].get(offset, {}).get(part_id, {})
            base_by_link = alloc["base"].get(offset, {}).get(part_id, {})

            displaced = sum(
                base_by_link.get(lid, {}).get(variant_id, 0)
                for lid in stopped_links
            )
            residual_delta = max(0, stop_gap - base_gap)
            if displaced <= 0 and residual_delta <= 0:
                continue

            key = (part_id, variant_id)
            plan = plans.get(key)
            if plan is None:
                primary = graph.primary_link(part_id)
                plan = SubstitutionPlan(
                    part_id=part_id, part_name=graph.parts[part_id].name,
                    variant_id=variant_id,
                    primary_price=(
                        snap_w.link_state(primary, variant_id,
                                          ignore_supply_stop=True).price
                        if primary else None
                    ),
                )
                plans[key] = plan
                books[key] = {}
            plan.displaced_units += displaced
            plan.residual_gap += residual_delta
            _merge_week(graph, snap_w, plan, books[key], variant_id,
                        stop_by_link, base_by_link, stopped_links)

    for key, plan in plans.items():
        _finalize_plan(graph, plan, books[key])
    return list(plans.values())


def _link_price_cap(graph, snapshot: Snapshot, link_id: str,
                    variant_id: str) -> tuple[float, int]:
    """该链接当前对该车型的有效报价与周产能（不可用时回退到承诺记录）。"""
    link = graph.links[link_id]
    st = snapshot.link_state(link, variant_id, ignore_supply_stop=True)
    if st.price is not None:
        return st.price, max(st.available_capacity, st.physical_capacity)
    for mid in link.commitment_ids:
        m = graph.commitments[mid]
        return m.price, m.capacity_per_week
    return 0.0, 0


def _merge_week(graph, snapshot: Snapshot, plan: SubstitutionPlan,
                book: dict[str, dict], variant_id: str,
                stop_by_link: dict[str, dict[str, int]],
                base_by_link: dict[str, dict[str, int]],
                stopped_links: set[str]):
    """按周累计备选净增量（备选之间可能因报价次序相互替代，需取净值）。"""
    for link_id in set(stop_by_link) | set(base_by_link):
        if link_id in stopped_links:
            continue
        stop_qty = stop_by_link.get(link_id, {}).get(variant_id, 0)
        base_qty = base_by_link.get(link_id, {}).get(variant_id, 0)
        if stop_qty == 0 and base_qty == 0:
            continue
        price, cap = _link_price_cap(graph, snapshot, link_id, variant_id)
        row = book.setdefault(link_id, {"stop": 0, "base": 0,
                                        "price": price, "cap": 0})
        row["stop"] += stop_qty
        row["base"] += base_qty
        row["cap"] = max(row["cap"], cap)
        delta = stop_qty - base_qty
        if delta:
            plan.extra_unit_cost += delta * (price - (plan.primary_price or 0))


def _finalize_plan(graph, plan: SubstitutionPlan, book: dict[str, dict]):
    """把跨周记账转成对外的替代组合行，并计入一次性切换成本。"""
    for link_id, row in sorted(book.items(),
                               key=lambda kv: (kv[1]["price"], -kv[1]["stop"])):
        if row["stop"] <= 0:
            continue
        link = graph.links[link_id]
        company = graph.registry.get(link.supplier_id)
        plan.allocations.append(Allocation(
            link_id=link_id, supplier_id=link.supplier_id,
            supplier_name=company.short_name, qty=row["stop"],
            weekly_capacity=row["cap"], lead_time_days=link.lead_time_days,
            price=row["price"],
            is_alternate=(
                link.role != ROLE_PRIMARY or bool(link.candidate_for)
            ),
        ))
        if row["base"] == 0:
            plan.one_time_switch_cost += link.switch_cost
    plan.substituted_units = max(0, plan.displaced_units - plan.residual_gap)
