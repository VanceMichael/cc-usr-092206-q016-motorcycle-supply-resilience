import json
import unittest

from tests.support import make_raw, make_graph, order
from src.resilience.graph import build_graph
from src.resilience.park import (
    find_single_points, local_content_rates, before_after_measures,
)
from src.resilience.views import (
    Viewer, oem_dashboard, supplier_dashboard, certifier_dashboard,
    park_dashboard, cooperation_link_ids, sees_commercial,
)

DAY = "2026-09-28"


def disrupted_raw():
    raw = make_raw()
    raw["events"] = [{
        "event_id": "STOP", "kind": "supply_stop",
        "effective_from": DAY, "effective_to": None,
        "target_type": "company", "target_id": "主城齿轮",
    }]
    raw["orders"] = [
        order("O1", "VF", 50, DAY), order("O2", "VE", 60, DAY),
        order("O3", "VO", 40, DAY),
    ]
    return raw


class ParkAnalyticsTest(unittest.TestCase):
    def test_single_point_detection(self):
        g = make_graph()
        # 电控仅一家本地独源，是稳定单点（齿轮有 4 家认证备选，不是）。
        points = find_single_points(g, DAY)
        keys = {(p.part_id, p.variant_id) for p in points}
        self.assertIn(("controller", "VE"), keys)
        gear_points = [p for p in points if p.part_id == "gear"]
        self.assertEqual(gear_points, [])

    def test_real_local_rate_counts_only_certified_capacity(self):
        raw = disrupted_raw()
        g = build_graph(raw)
        rates = local_content_rates(g, DAY)
        # 断供周齿轮的本地主供为 0；外地备选交期未到，齿轮需求几乎无覆盖，
        # 真实本地配套率显著低于"按注册地统计"的账面比例。
        ev = next(v for v in rates["variants"] if v["variant_id"] == "VE")
        self.assertLess(ev["real_local_rate"], 0.99)

    def test_before_after_measures_improvement(self):
        raw = disrupted_raw()
        # 甲配现货 + 扩产补贴。
        for m in raw["commitments"]:
            if m["commitment_id"] == "M-A1":
                m["lead_time_days"] = 0
        raw["measures"] = [{
            "measure_id": "MS1", "kind": "capacity_grant",
            "target_type": "link", "target_id": "L-A1", "value": 200,
            "effective_from": DAY, "effective_to": None,
        }]
        g = build_graph(raw)
        ba = before_after_measures(g, DAY)
        self.assertGreater(ba["before"]["impacted_units"],
                           ba["after"]["impacted_units"])
        self.assertGreater(ba["improved_units"], 0)
        self.assertEqual(ba["after"]["impacted_units"], 0)


class AccessControlTest(unittest.TestCase):
    def setUp(self):
        self.g = build_graph(disrupted_raw())
        self.oem = self.g.registry.resolve("甲整车")
        self.oem2 = self.g.registry.resolve("乙整车")
        self.primary = self.g.registry.resolve("主城齿轮")
        self.alt = self.g.registry.resolve("本地甲配")

    def test_oem_sees_commercial_only_on_cooperation_chain(self):
        viewer = Viewer("oem", self.oem)
        chain = cooperation_link_ids(self.g, viewer)
        # 主供 + 候选替代都在合作链条内。
        self.assertIn("L-P", chain)
        self.assertIn("L-A1", chain)
        self.assertTrue(sees_commercial(self.g, viewer, "L-P"))
        dash = oem_dashboard(self.g, viewer, DAY)
        blob = json.dumps(dash, ensure_ascii=False)
        self.assertIn("primary_price", blob)
        # 只能看到本企业订单。
        self.assertTrue(all(o["order_id"] != "OB" for o in dash["orders"]))

    def test_competing_oem_sees_no_orders_no_prices(self):
        viewer = Viewer("oem", self.oem2)
        dash = oem_dashboard(self.g, viewer, DAY)
        self.assertEqual(dash["orders"], [])
        self.assertEqual(
            sum(v["impacted_units"] for v in dash["by_platform"].values()), 0
        )

    def test_supplier_sees_own_links_but_not_others_prices(self):
        viewer = Viewer("supplier", self.alt)
        dash = supplier_dashboard(self.g, viewer, DAY)
        suppliers = {row["supplier_id"] for row in dash["my_links"]}
        self.assertEqual(suppliers, {self.alt})
        for row in dash["my_links"]:
            self.assertIn("price", row)  # 自己的报价可见
        # 合作链集合只含本企业链接。
        chain = cooperation_link_ids(self.g, viewer)
        self.assertNotIn("L-P", chain)

    def test_certifier_sees_certs_but_no_prices(self):
        viewer = Viewer("certifier", self.g.registry.resolve("认证机构"))
        dash = certifier_dashboard(self.g, viewer, DAY)
        blob = json.dumps(dash, ensure_ascii=False)
        self.assertNotIn("price", blob)
        self.assertNotIn("110", blob)  # 报价数字不外泄
        self.assertTrue(any(
            row["recorded_status"] == "mass"
            for row in dash["certifications"]
        ))

    def test_park_sees_rates_and_points_but_no_prices_or_orders(self):
        viewer = Viewer("park")
        dash = park_dashboard(self.g, viewer, DAY)
        blob = json.dumps(dash, ensure_ascii=False)
        for secret in ("primary_price", "unit_price", "switch_cost",
                       "extra_unit_cost", "ORD-"):
            self.assertNotIn(secret, blob)
        self.assertIn("real_local_content_rate", blob)
        self.assertIn("single_point_dependencies", blob)
        self.assertIn("delivery_before_after_support", blob)

    def test_role_guard_raises(self):
        with self.assertRaises(PermissionError):
            oem_dashboard(self.g, Viewer("park"), DAY)
        with self.assertRaises(PermissionError):
            supplier_dashboard(self.g, Viewer("oem", self.oem), DAY)


class GraphValidationTest(unittest.TestCase):
    def test_unknown_part_rejected(self):
        raw = make_raw()
        raw["variants"][0]["bom"]["ghost"] = 1
        with self.assertRaises(ValueError):
            build_graph(raw)

    def test_unknown_supplier_reference_rejected(self):
        raw = make_raw()
        raw["sourcing_links"][0]["supplier"] = "幽灵企业"
        with self.assertRaises(KeyError):
            build_graph(raw)

    def test_bad_platform_rejected(self):
        raw = make_raw()
        raw["variants"][0]["platform"] = "flying"
        with self.assertRaises(ValueError):
            build_graph(raw)

    def test_bad_event_kind_rejected(self):
        raw = make_raw()
        raw["events"] = [{
            "event_id": "X", "kind": "earthquake",
            "effective_from": DAY, "target_type": "company",
            "target_id": "主城齿轮",
        }]
        with self.assertRaises(ValueError):
            build_graph(raw)


if __name__ == "__main__":
    unittest.main()
