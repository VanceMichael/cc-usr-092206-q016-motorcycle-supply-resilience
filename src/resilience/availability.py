"""按生效时间计算寻源链接此刻是否可用、还有多少认证产能。

五类事件在给定评估日（周）的效果：

- ramp 试制转量产：认证 trial → mass；ramp_curve 按周限制爬坡产能，
  越过曲线最后一个锚点后恢复承诺满产。
- quality_hold 质量暂停：作用于认证或整条寻源链接，窗口内产能为 0；
  无恢复日期视为持续暂停。
- price_expiry 价格失效：报价自生效日起失效，物理产能仍在，但不能按旧承诺
  承接订单（available_capacity 记 0，physical_capacity 保留）。
- maintenance 设备检修：作用于共享设备，按评估周内停机天数比例折减产能；
  共享该设备的所有链接同时折减。
- supply_stop 断供：作用于供应商企业（可用 part_id 限定零件），窗口内产能为 0。

顺序无关：阻断类原因（暂停/断供/设备全周检修）优先于爬坡折减。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from .graph import (
    Graph, SourcingLink, Certification, Commitment,
)
from .timeutil import as_date, daterange, within


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_days(monday: date):
    return [monday + timedelta(days=i) for i in range(7)]


@dataclass
class LinkState:
    link_id: str
    part_id: str
    supplier_id: str
    day: str
    certified: bool = False
    cert_status: str = "none"          # mass / trial / suspended / expired / none
    confirmed: bool = False
    price_valid: bool = True
    equipment_ok: bool = True
    blocked_reasons: list[str] = field(default_factory=list)
    note: str = ""
    physical_capacity: int = 0         # 含爬坡/检修折减，忽略商务有效性
    available_capacity: int = 0        # 可用于承接整车订单的周产能
    lead_time_days: int = 0
    price: float | None = None
    currency: str = "CNY"

    @property
    def usable(self) -> bool:
        return self.available_capacity > 0 and not self.blocked_reasons


class Snapshot:
    """某一评估日的图谱时效快照（订单按该日所在周评估）。

    apply_measures=True 时叠加园区已生效的扶持措施，用于"扶持后"情景。
    """

    def __init__(self, graph: Graph, day, apply_measures: bool = False):
        self.graph = graph
        self.day = as_date(day)
        self.monday = week_start(self.day)
        self.apply_measures = apply_measures
        self._events_active = self._index_events()
        self._measures_active = self._index_measures()
        self._state_cache: dict[tuple, "LinkState"] = {}

    # -- 事件/措施索引 ----------------------------------------------------

    def _index_events(self) -> dict[str, list]:
        active: dict[str, list] = {}
        for ev in self.graph.events:
            start = as_date(ev.effective_from)
            end = as_date(ev.effective_to) if ev.effective_to else None
            if within(self.day, start, end):
                active.setdefault(ev.kind, []).append(ev)
        return active

    def _index_measures(self) -> dict[str, list]:
        active: dict[str, list] = {}
        if not self.apply_measures:
            return active
        for ms in self.graph.measures:
            start = as_date(ms.effective_from)
            end = as_date(ms.effective_to) if ms.effective_to else None
            if within(self.day, start, end):
                active.setdefault(ms.kind, []).append(ms)
        return active

    def _measures_on(self, kind: str, target_type: str, target_id: str):
        return [
            ms for ms in self._measures_active.get(kind, [])
            if ms.target_type == target_type and ms.target_id == target_id
        ]

    def _events_on(self, kind: str, target_type: str, target_id: str):
        return [
            ev for ev in self._events_active.get(kind, [])
            if ev.target_type == target_type and ev.target_id == target_id
        ]

    def _stopped_suppliers(self) -> dict[str, set[str | None]]:
        """company_id -> 被断供限定的零件集合（None 表示全零件）。"""
        cached = getattr(self, "_stop_cache", None)
        if cached is not None:
            return cached
        out: dict[str, set] = {}
        for ev in self._events_active.get("supply_stop", []):
            if ev.target_type != "company":
                continue
            company_id = self.graph.registry.resolve(ev.target_id)
            out.setdefault(company_id, set()).add(ev.part_id)
        self._stop_cache = out
        return out

    # -- 认证 -------------------------------------------------------------

    def cert_state(self, cert: Certification) -> str:
        """认证在此刻的实际状态。"""
        start = as_date(cert.valid_from)
        end = as_date(cert.valid_to) if cert.valid_to else None
        if not within(self.day, start, end):
            return "expired"
        status = cert.status
        # 试制转量产事件。
        for ev in self._events_on("ramp", "certification", cert.cert_id):
            status = "mass"
        # 质量暂停可直接挂在认证上。
        if self._events_on("quality_hold", "certification", cert.cert_id):
            status = "suspended"
        if status in ("revoked",):
            return "revoked"
        return status

    def _active_cert(self, link: SourcingLink, variant_id: str) -> Certification | None:
        """该链接对某车型版本最具代表性的认证。

        优先级：有效量产 > 试制 > 暂停 > 过期 > 撤销；都没有才返回 None。
        """
        priority = {"mass": 0, "trial": 1, "suspended": 2,
                    "expired": 3, "revoked": 4}
        ranked = [
            (priority[self.cert_state(cert)], cert)
            for cert in self.graph.certs_for(link, variant_id)
        ]
        if not ranked:
            return None
        ranked.sort(key=lambda x: x[0])
        return ranked[0][1]

    # -- 承诺 -------------------------------------------------------------

    def _active_commitment(self, link: SourcingLink) -> Commitment | None:
        valid = []
        for mid in link.commitment_ids:
            m = self.graph.commitments[mid]
            start = as_date(m.valid_from)
            end = as_date(m.valid_to) if m.valid_to else None
            if within(self.day, start, end):
                valid.append(m)
        if not valid:
            return None
        # 多条并存时取最新确认的一条。
        valid.sort(key=lambda m: (m.confirmed, m.valid_from), reverse=True)
        return valid[0]

    def _commitment_price_valid(self, commitment: Commitment) -> bool:
        for ev in self._events_on("price_expiry", "commitment", commitment.commitment_id):
            return False
        return True

    # -- 设备 -------------------------------------------------------------

    def _equipment_factor(self, link: SourcingLink) -> tuple[float, list[str]]:
        """共享设备检修造成的周产能折减系数与停机设备名。

        多个设备（或多个检修窗口）在同一天停机时只计一天；本周停机天数/7
        即产能折减。无恢复日期的检修视为持续停机。
        """
        sunday = self.monday + timedelta(days=6)
        down_days: set[date] = set()
        down_names = []
        for eid in link.equipment_ids:
            evs = self._events_on("maintenance", "equipment", eid)
            days: set[date] = set()
            for ev in evs:
                start = max(as_date(ev.effective_from), self.monday)
                if ev.effective_to:
                    stop = min(as_date(ev.effective_to) - timedelta(days=1), sunday)
                else:
                    stop = sunday
                if start <= stop:
                    days.update(daterange(start, stop))
            if days:
                down_names.append(self.graph.equipment[eid].name)
                down_days |= days
        if not down_days:
            return 1.0, []
        factor = max(0.0, 1.0 - len(down_days) / 7.0)
        return factor, down_names

    # -- 爬坡 -------------------------------------------------------------

    def _ramp_cap(self, link: SourcingLink, cert: Certification | None) -> int | None:
        """若该链接正处于试制转量产爬坡期，返回本周产能上限。"""
        ramp_events = []
        if cert is not None:
            ramp_events += self._events_on("ramp", "certification", cert.cert_id)
        ramp_events += self._events_on("ramp", "link", link.link_id)
        if not ramp_events:
            return None
        ev = max(ramp_events, key=lambda e: e.effective_from)
        curve = ev.ramp_curve or {}
        offset = (self.monday - week_start(as_date(ev.effective_from))).days // 7
        cap = None
        for key in sorted(curve, key=lambda k: int(k)):
            if int(key) <= offset:
                cap = int(curve[key])
        if cap is None:
            # 曲线尚未给出本周锚点：按首个锚点之前不可交付处理。
            first = min((int(k) for k in curve), default=0)
            cap = curve[str(first)] if curve else 0
            if offset < first:
                cap = 0
        return max(0, cap)

    # -- 链接状态 ---------------------------------------------------------

    def link_state(self, link: SourcingLink, variant_id: str,
                   ignore_supply_stop: bool = False) -> LinkState:
        cache_key = (link.link_id, variant_id, ignore_supply_stop)
        if cache_key in self._state_cache:
            return self._state_cache[cache_key]
        state = self._compute_link_state(link, variant_id, ignore_supply_stop)
        self._state_cache[cache_key] = state
        return state

    def _compute_link_state(self, link: SourcingLink, variant_id: str,
                            ignore_supply_stop: bool) -> LinkState:
        state = LinkState(
            link_id=link.link_id, part_id=link.part_id,
            supplier_id=link.supplier_id, day=self.day.isoformat(),
            lead_time_days=link.lead_time_days,
        )
        cert = self._active_cert(link, variant_id)
        if cert is not None:
            state.cert_status = self.cert_state(cert)
        # 试制转量产事件可挂在链接上：爬坡开始即视同量产可用。
        if state.cert_status == "trial" and self._events_on(
            "ramp", "link", link.link_id
        ):
            state.cert_status = "mass"
        # 认证加速：试制认证在措施生效期内视同量产可用（可挂认证或链接）。
        if state.cert_status == "trial":
            for cid in link.cert_ids:
                if self._measures_on("cert_acceleration", "certification", cid):
                    state.cert_status = "mass"
                    break
            if state.cert_status == "trial" and self._measures_on(
                "cert_acceleration", "link", link.link_id
            ):
                state.cert_status = "mass"
        state.certified = state.cert_status == "mass"

        commitment = self._active_commitment(link)
        if commitment is not None:
            state.confirmed = commitment.confirmed
            state.price = commitment.price
            state.currency = commitment.currency
            # 承诺交期 0 表示现货即发；有承诺即以承诺为准。
            state.lead_time_days = commitment.lead_time_days
            state.price_valid = self._commitment_price_valid(commitment)
            capacity = commitment.capacity_per_week
        else:
            capacity = 0

        cap = self._ramp_cap(link, cert)
        if cap is not None:
            capacity = min(capacity, cap)

        factor, down_names = self._equipment_factor(link)
        backup = 0
        if down_names:
            for eid in link.equipment_ids:
                if self._events_on("maintenance", "equipment", eid):
                    backup += int(sum(
                        ms.value for ms in
                        self._measures_on("equipment_backup", "equipment", eid)
                    ))
        capacity = int(capacity * factor) + backup
        state.equipment_ok = not down_names
        if down_names and backup == 0 and factor == 0:
            state.blocked_reasons.append(f"设备全周检修:{'/'.join(down_names)}")
        elif down_names:
            state.note = (
                f"设备检修:{'/'.join(down_names)}，本周产能折减至 {factor * 100:.0f}%"
                + (f"，备份产能 {backup}/周" if backup else "")
            )

        # 扶持：扩产补贴直接增加周产能。
        capacity += int(sum(
            ms.value for ms in self._measures_on("capacity_grant", "link", link.link_id)
        ))
        # 单位补贴只改变成本对比，不改变物理可用性。
        if state.price is not None:
            subsidy = sum(
                ms.value for ms in self._measures_on("price_subsidy", "link", link.link_id)
            )
            state.price = max(0.0, state.price - subsidy)

        if self._events_on("quality_hold", "link", link.link_id):
            state.blocked_reasons.append("质量暂停")

        stopped = self._stopped_suppliers().get(link.supplier_id)
        if not ignore_supply_stop and stopped is not None and (
            None in stopped or link.part_id in stopped
        ):
            state.blocked_reasons.append("供应商断供")

        if not state.certified:
            label = {"trial": "仅试制认证", "suspended": "认证暂停",
                     "expired": "认证过期", "revoked": "认证撤销",
                     "none": "无该车型认证"}[state.cert_status]
            state.blocked_reasons.append(label)
        if commitment is None:
            state.blocked_reasons.append("无有效产能承诺")
        elif not commitment.confirmed:
            state.blocked_reasons.append("承诺未经在线确认")
        elif not state.price_valid:
            state.blocked_reasons.append("报价已失效")

        state.physical_capacity = capacity
        state.available_capacity = 0 if state.blocked_reasons else capacity
        return state

    def part_supply(self, part_id: str, variant_id: str) -> list[LinkState]:
        return [
            self.link_state(lk, variant_id)
            for lk in self.graph.links_for_part(part_id)
        ]

    def certified_capacity(self, part_id: str, variant_id: str) -> int:
        """该零件对该车型版本当前可承接订单的认证周产能合计。"""
        return sum(s.available_capacity for s in self.part_supply(part_id, variant_id))
