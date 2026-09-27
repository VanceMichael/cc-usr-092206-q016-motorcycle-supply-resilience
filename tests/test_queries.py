import unittest

from src.graph import (
    certified_local_ratio,
    compare_capability,
    delivery_capability,
    impact_of_supply_stop,
    measure_effect,
    single_point_parts,
)
from src.model import load_graph

GEAR = "岚山精密齿轮有限公司"


class ImpactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = load_graph("fixtures/graph.json")
        cls.at = "2026-09-27"

    def test_affected_orders_by_kind(self):
        report = impact_of_supply_stop(self.graph, GEAR, self.at)
        # 关键齿轮企业供 F250 与 X450，不供电动车。
        self.assertEqual(report["by_kind"]["fuel"]["affected_orders"], 700)
        self.assertEqual(report["by_kind"]["offroad"]["affected_orders"], 500)
        self.assertEqual(report["by_kind"]["ev"]["affected_orders"], 0)
        self.assertEqual(report["total_affected"], 1200)

    def test_blocking_parts_and_candidates(self):
        report = impact_of_supply_stop(self.graph, GEAR, self.at)
        f250 = report["by_kind"]["fuel"]["versions"]["F250"]
        parts = {p["part"]: p for p in f250["blocking_parts"]}
        self.assertEqual(set(parts), {"P01"})
        cand = parts["P01"]["candidates"][0]
        self.assertEqual(cand["edge_id"], "E-F250-GEAR-2")
        self.assertEqual(cand["available_capacity"], 500)
        self.assertEqual(cand["switch_days"], 10)
        # X450 的候选齿轮此刻还是试制状态。
        x450 = report["by_kind"]["offroad"]["versions"]["X450"]
        self.assertEqual(x450["blocking_parts"][0]["part"], "P01")

    def test_irrelevant_supplier_no_impact(self):
        # 一家只出现在其他版本上的随机供应商，对 F250/X450 的停产影响为零。
        supplier = next(
            e.supplier for e in self.graph.edges.values()
            if e.model_code == "E3000"
        )
        report = impact_of_supply_stop(self.graph, supplier, self.at)
        self.assertEqual(report["by_kind"]["fuel"]["affected_orders"], 0)
        self.assertEqual(report["by_kind"]["offroad"]["affected_orders"], 0)

    def test_unknown_supplier(self):
        with self.assertRaises(ValueError):
            impact_of_supply_stop(self.graph, "不存在的企业", self.at)


class SinglePointTest(unittest.TestCase):
    def test_gear_is_single_point(self):
        graph = load_graph("fixtures/graph.json")
        points = single_point_parts(graph, "2026-09-01")
        hits = {(f["model"], f["part"]): f for f in points}
        self.assertEqual(hits[("F250", "P01")]["supplier"], GEAR)
        self.assertEqual(hits[("X450", "P01")]["supplier"], GEAR)
        # 9-20 断供后不再是「唯一可用」，因为已经没有可用供应商。
        points_after = single_point_parts(graph, "2026-09-27")
        self.assertNotIn(("F250", "P01"), {(f["model"], f["part"]) for f in points_after})


class LocalRatioTest(unittest.TestCase):
    def test_real_ratio_differs_from_published_and_moves_with_time(self):
        graph = load_graph("fixtures/graph.json")
        before = certified_local_ratio(graph, "F250", "2026-09-01")
        after = certified_local_ratio(graph, "F250", "2026-09-27")
        self.assertAlmostEqual(before["published_ratio"], 0.62)
        # 公布值不能回答某零件此刻是否有认证产能：断供后真实比例下降。
        self.assertLess(after["ratio"], before["ratio"])
        self.assertFalse(after["detail"]["P01"])

    def test_certification_later_effective_raises_part_coverage(self):
        graph = load_graph("fixtures/graph.json")
        ev = certified_local_ratio(graph, "E5000", "2026-09-27")
        self.assertFalse(ev["detail"]["P27"])
        ev2 = certified_local_ratio(graph, "E5000", "2026-10-02")
        self.assertTrue(ev2["detail"]["P27"])


class CapabilityTest(unittest.TestCase):
    def test_measure_before_after(self):
        graph = load_graph("fixtures/graph.json")
        effect = measure_effect(graph, "M1", "2026-10-16")
        offroad = effect["by_kind"]["offroad"]
        # 10-15 本地齿轮试制转量产：越野缺口恰由 600 台月产能补上。
        self.assertEqual(offroad["buildable_delta"], 600)
        self.assertGreaterEqual(offroad["after"]["buildable"], 600)

    def test_compare_requires_order(self):
        graph = load_graph("fixtures/graph.json")
        with self.assertRaises(ValueError):
            compare_capability(graph, "2026-10-16", "2026-10-01")

    def test_capability_keys(self):
        graph = load_graph("fixtures/graph.json")
        cap = delivery_capability(graph, "2026-09-01")
        self.assertEqual(set(cap), {"fuel", "ev", "offroad"})
        self.assertTrue(all(0 <= k["coverage"] <= 1 for k in cap.values()))


if __name__ == "__main__":
    unittest.main()
