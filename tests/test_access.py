import unittest

from src.access import Actor, edge_view
from src.model import load_graph

OEM_FUEL = "苍岚重机有限公司"
OEM_EV = "澄湖电驱有限公司"
GEAR = "岚山精密齿轮有限公司"


class AccessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = load_graph("fixtures/graph.json")
        cls.at = "2026-09-27"

    def test_oem_sees_commercial_fields_of_own_chain(self):
        actor = Actor(role="oem", company=OEM_FUEL)
        view = edge_view(self.graph, "E-F250-GEAR-1", actor, self.at)
        self.assertIn("unit_price", view)
        self.assertIn("monthly_capacity", view)
        self.assertIn("online_confirmed", view)

    def test_oem_denied_other_chain(self):
        # 电动整车厂看不到燃油车型供应边的商业数据。
        actor = Actor(role="oem", company=OEM_EV)
        with self.assertRaises(PermissionError):
            edge_view(self.graph, "E-F250-GEAR-1", actor, self.at)

    def test_supplier_sees_own_edge(self):
        actor = Actor(role="parts", company=GEAR)
        view = edge_view(self.graph, "E-F250-GEAR-1", actor, self.at)
        self.assertEqual(view["unit_price"], 35.0)

    def test_supplier_denied_other_company(self):
        actor = Actor(role="parts", company="潼溪齿轮有限公司")
        with self.assertRaises(PermissionError):
            edge_view(self.graph, "E-F250-GEAR-1", actor, self.at)

    def test_park_sees_state_but_not_price(self):
        actor = Actor(role="park")
        view = edge_view(self.graph, "E-F250-GEAR-1", actor, self.at)
        self.assertEqual(view["state"], "stopped")
        self.assertFalse(view["available"])
        self.assertNotIn("unit_price", view)
        self.assertNotIn("monthly_capacity", view)

    def test_certifier_sees_cert_only(self):
        actor = Actor(role="certifier")
        view = edge_view(self.graph, "E-F250-GEAR-1", actor, self.at)
        self.assertIn("certification", view)
        self.assertNotIn("unit_price", view)
        self.assertNotIn("state", view)

    def test_actor_validation(self):
        with self.assertRaises(ValueError):
            Actor(role="oem")
        with self.assertRaises(ValueError):
            Actor(role="unknown")


if __name__ == "__main__":
    unittest.main()
