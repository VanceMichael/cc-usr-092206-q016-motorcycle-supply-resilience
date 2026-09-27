import unittest

from src.access import Actor
from src.graph import confirm_supply, simulate
from src.model import load_graph

OEM_FUEL = "苍岚重机有限公司"
OEM_EV = "澄湖电驱有限公司"
R2 = "恒力电子有限公司"


class ConfirmationTest(unittest.TestCase):
    def test_only_supplier_confirms(self):
        graph = load_graph("fixtures/graph.json")
        with self.assertRaises(PermissionError):
            confirm_supply(graph, Actor(role="parts", company=R2), "E-F250-GEAR-1")
        with self.assertRaises(PermissionError):
            confirm_supply(graph, Actor(role="oem", company=OEM_FUEL), "E-E5000-CTRL-2")

    def test_confirmation_unlocks_capacity(self):
        graph = load_graph("fixtures/graph.json")
        edge = graph.edges["E-E5000-CTRL-2"]
        self.assertFalse(graph.is_confirmed(edge))
        confirm_supply(graph, Actor(role="parts", company=R2), "E-E5000-CTRL-2")
        self.assertTrue(graph.is_confirmed(edge))


class SimulationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = load_graph("fixtures/graph.json")
        cls.oem = Actor(role="oem", company=OEM_FUEL)
        cls.at = "2026-09-27"

    def test_baseline_shortfall_from_stop(self):
        report = simulate(self.graph, self.oem, self.at)
        f250 = report["versions"]["F250"]
        # 齿轮停产，F250 全部 700 单受阻。
        self.assertEqual(f250["buildable"], 0)
        self.assertEqual(f250["shortfall"], 700)
        self.assertIn("P01", f250["limiting_parts"])

    def test_activate_candidate_partially_recovers(self):
        report = simulate(
            self.graph, self.oem, self.at,
            use_candidates={"E-F250-GEAR-1": ["E-F250-GEAR-2"]},
        )
        f250 = report["versions"]["F250"]
        # 候选齿轮月产能 500，恢复 500 台，仍缺 200。
        self.assertEqual(f250["buildable"], 500)
        self.assertEqual(f250["shortfall"], 200)
        self.assertEqual(f250["limiting_parts"], ["P01"])
        self.assertEqual(report["notes"], [])

    def test_order_override_with_candidate(self):
        report = simulate(
            self.graph, self.oem, self.at,
            order_overrides={"F250": 400},
            use_candidates={"E-F250-GEAR-1": ["E-F250-GEAR-2"]},
        )
        f250 = report["versions"]["F250"]
        self.assertEqual(f250["open_orders"], 400)
        self.assertEqual(f250["shortfall"], 0)
        self.assertEqual(f250["limiting_parts"], [])

    def test_only_oem_simulates(self):
        with self.assertRaises(PermissionError):
            simulate(self.graph, Actor(role="park"), self.at)

    def test_cannot_touch_other_oem_versions(self):
        actor = Actor(role="oem", company=OEM_FUEL)
        with self.assertRaises(PermissionError):
            simulate(self.graph, actor, self.at, order_overrides={"E3000": 100})
        with self.assertRaises(PermissionError):
            simulate(
                self.graph, actor, self.at,
                use_candidates={"E-F250-GEAR-1": ["E-X450-GEAR-2"]},
            )

    def test_unregistered_candidate_rejected(self):
        with self.assertRaises(ValueError):
            # F150 与 F250 同属苍岚重机，但该边不是齿轮边的登记替代。
            simulate(
                self.graph, self.oem, self.at,
                use_candidates={"E-F250-GEAR-1": ["E-F150-SPROCKET-1"]},
            )


if __name__ == "__main__":
    unittest.main()
