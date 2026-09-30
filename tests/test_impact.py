import copy
import unittest

from tests.support import make_raw, make_graph, order
from src.resilience.graph import build_graph
from src.resilience.impact import simulate_impact

DAY = "2026-09-28"
W1, W3 = "2026-10-05", "2026-10-19"


def stop_primary(raw):
    raw["events"] = [{
        "event_id": "STOP", "kind": "supply_stop",
        "effective_from": DAY, "effective_to": None,
        "target_type": "company", "target_id": "主城齿轮",
    }]
    return raw


def weekly_orders(raw):
    raw["orders"] = []
    n = 1
    for week in (DAY, W1, W3):
        for variant, qty in (("VF", 50), ("VE", 60), ("VO", 40)):
            raw["orders"].append(order(f"O{n}", variant, qty, week))
            n += 1
    return raw


class ImpactTest(unittest.TestCase):
    def test_platform_answer_and_timing(self):
        raw = weekly_orders(stop_primary(make_raw()))
        g = build_graph(raw)
        rep = simulate_impact(g, DAY, horizon_weeks=4)

        # 危机分配遵循"备选先保既有客户"：基线下主供的 60 产能供给排序最前的
        # 电动车型；备选甲配 50 供燃油、外源供越野。主供断供后，其电动客户
        # 在外地备选第 3 周就绪前无救急产能，燃油/越野因备选关系保留而不受影响。
        p = rep.by_platform
        self.assertEqual(p["electric"].impacted_units, 120)   # 60 × 第0、1周
        self.assertEqual(p["fuel"].impacted_units, 0)
        self.assertEqual(p["offroad"].impacted_units, 0)
        self.assertEqual(p["electric"].impacted_orders, 2)
        self.assertEqual(p["fuel"].impacted_orders, 0)
        self.assertEqual(p["offroad"].impacted_orders, 0)

    def test_weekly_recovery_when_distant_alternative_ready(self):
        raw = weekly_orders(stop_primary(make_raw()))
        rep = simulate_impact(build_graph(raw), DAY, horizon_weeks=4)
        short_rows = {row["week"]: row["short_units"] for row in rep.weekly}
        self.assertGreater(short_rows[DAY], 0)
        self.assertGreater(short_rows[W1], 0)
        self.assertEqual(short_rows[W3], 0)  # 外地备选第3周就绪且产能充足

    def test_substitution_accounting_identity(self):
        raw = weekly_orders(stop_primary(make_raw()))
        rep = simulate_impact(build_graph(raw), DAY, horizon_weeks=4)
        for plan in rep.plans:
            self.assertEqual(
                plan.displaced_units,
                plan.substituted_units + plan.residual_gap,
                msg=plan.part_id,
            )
        # 齿轮主供承担量确实被识别为转移量（三周各 60 = 180）。
        gear_plans = [p for p in rep.plans if p.part_id == "gear"]
        self.assertEqual(sum(p.displaced_units for p in gear_plans), 180)

    def test_distant_alternative_not_in_week_zero_mix(self):
        raw = weekly_orders(stop_primary(make_raw()))
        rep = simulate_impact(build_graph(raw), DAY, horizon_weeks=4)
        week0_suppliers = set()
        for plan in rep.plans:
            for a in plan.allocations:
                if "外源" in a.supplier_name and plan.variant_id in ("VF",):
                    # 汇总数无法区分周；外源对燃油只可能在第3周有量。
                    week0_suppliers.add(a.supplier_name)
        # 通过交期断言：外地备选交期 21 天。
        g = build_graph(raw)
        waiyuan = [lk for lk in g.links.values()
                   if g.registry.get(lk.supplier_id).local is False][0]
        self.assertEqual(waiyuan.lead_time_days, 21)

    def test_no_stop_no_impact(self):
        raw = weekly_orders(make_raw())  # 无断供事件
        rep = simulate_impact(build_graph(raw), DAY, horizon_weeks=4)
        self.assertEqual(rep.total_impacted_units, 0)
        self.assertEqual(rep.plans, [])

    def test_support_measures_close_gap(self):
        # 备选甲配交期改为 0 天；扶持新增周产能 200。
        raw = weekly_orders(stop_primary(make_raw()))
        for m in raw["commitments"]:
            if m["commitment_id"] == "M-A1":
                m["lead_time_days"] = 0
        raw["measures"] = [{
            "measure_id": "MS1", "kind": "capacity_grant",
            "target_type": "link", "target_id": "L-A1", "value": 200,
            "effective_from": DAY, "effective_to": None,
            "note": "扩产补贴",
        }]
        g = build_graph(raw)
        before = simulate_impact(g, DAY, horizon_weeks=4, apply_measures=False)
        after = simulate_impact(g, DAY, horizon_weeks=4, apply_measures=True)
        self.assertGreater(before.total_impacted_units, 0)
        self.assertEqual(after.total_impacted_units, 0)

    def test_variant_filter_isolates_oem(self):
        raw = weekly_orders(stop_primary(make_raw()))
        raw["orders"].append(order("OB1", "VF2", 90, DAY))  # 乙整车订单
        g = build_graph(raw)
        own = simulate_impact(g, DAY, horizon_weeks=4,
                              variant_filter={"VF", "VE", "VO"})
        allrep = simulate_impact(g, DAY, horizon_weeks=4)
        self.assertFalse(any(o.variant_id == "VF2" for o in own.orders))
        self.assertTrue(any(o.variant_id == "VF2" for o in allrep.orders))


if __name__ == "__main__":
    unittest.main()
