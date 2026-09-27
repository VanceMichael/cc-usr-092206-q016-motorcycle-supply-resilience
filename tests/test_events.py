import unittest

from src.graph import available_capacity, buildable_units, edge_state_at
from src.model import load_graph


def edge_by_event(graph, event_id):
    for edge in graph.edges.values():
        if any(ev.id == event_id for ev in edge.events):
            return edge
    raise KeyError(event_id)


class EventTest(unittest.TestCase):
    """五类事件按生效时间改变供应边可用性。"""

    @classmethod
    def setUpClass(cls):
        cls.graph = load_graph("fixtures/graph.json")

    def test_supply_stop(self):
        edge = self.graph.edges["E-F250-GEAR-1"]
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-19"), "mass")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-20"), "stopped")
        self.assertEqual(available_capacity(self.graph, edge, "2026-09-19"), 800)
        self.assertEqual(available_capacity(self.graph, edge, "2026-09-27"), 0)

    def test_trial_to_mass(self):
        edge = self.graph.edges["E-X450-GEAR-2"]
        self.assertEqual(edge_state_at(self.graph, edge, "2026-10-14"), "trial")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-10-15"), "mass")
        self.assertEqual(available_capacity(self.graph, edge, "2026-10-14"), 0)
        self.assertEqual(available_capacity(self.graph, edge, "2026-10-16"), 600)

    def test_quality_hold_window(self):
        edge = self.graph.edges["E-X250-CALIPER-1"]
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-09"), "mass")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-15"), "held")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-25"), "mass")

    def test_quality_hold_later_recovery(self):
        edge = self.graph.edges["E-X250-CALIPER-2"]
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-19"), "mass")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-27"), "held")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-10-05"), "mass")

    def test_equipment_downtime_shared_only(self):
        down = self.graph.edges["E-F150-SPROCKET-1"]   # 用共享热处理炉
        other = self.graph.edges["E-F150-SPROCKET-2"]  # 不用
        self.assertEqual(edge_state_at(self.graph, down, "2026-10-03"), "down")
        self.assertEqual(edge_state_at(self.graph, other, "2026-10-03"), "mass")
        self.assertEqual(edge_state_at(self.graph, down, "2026-10-08"), "mass")
        # 检修窗口内另一家仍可支撑 F150 交付。
        self.assertGreaterEqual(buildable_units(self.graph, "F150", "2026-10-03"), 300)

    def test_price_expiry_by_valid_until(self):
        edge = self.graph.edges["E-E5000-CTRL-1"]
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-25"), "mass")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-26"), "unpriced")
        self.assertEqual(available_capacity(self.graph, edge, "2026-09-26"), 0)

    def test_price_expired_by_event(self):
        edge = edge_by_event(self.graph, "EV-RND-PRICE")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-09"), edge.status)
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-10"), "unpriced")

    def test_random_supply_stop(self):
        edge = edge_by_event(self.graph, "EV-RND-STOP")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-14"), edge.status)
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-15"), "stopped")

    def test_random_trial_to_mass(self):
        edge = edge_by_event(self.graph, "EV-RND-CONV")
        self.assertEqual(edge.status, "trial")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-04"), "trial")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-05"), "mass")

    def test_random_quality_hold_window(self):
        edge = edge_by_event(self.graph, "EV-RND-HOLD")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-15"), "held")
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-30"), edge.status)

    def test_unconfirmed_commitment_not_counted(self):
        edge = self.graph.edges["E-E5000-CTRL-2"]
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-27"), "mass")
        self.assertEqual(available_capacity(self.graph, edge, "2026-09-27"), 0)

    def test_cert_not_yet_effective(self):
        edge = self.graph.edges["E-E5000-INSTR-1"]
        self.assertEqual(edge_state_at(self.graph, edge, "2026-09-27"), "mass")
        self.assertEqual(available_capacity(self.graph, edge, "2026-09-27"), 0)
        self.assertEqual(available_capacity(self.graph, edge, "2026-10-01"), 500)


if __name__ == "__main__":
    unittest.main()
