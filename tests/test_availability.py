import unittest

from tests.support import make_raw, make_graph
from src.resilience.availability import Snapshot, week_start
from src.resilience.graph import build_graph

DAY = "2026-09-28"  # 周一


def link_id(graph, supplier_short):
    for lk in graph.links.values():
        if graph.registry.get(lk.supplier_id).short_name == supplier_short:
            return lk.link_id
    raise KeyError(supplier_short)


class AvailabilityBaselineTest(unittest.TestCase):
    def setUp(self):
        self.g = make_graph()
        self.snap = Snapshot(self.g, DAY)

    def state(self, supplier, variant="VF"):
        return self.snap.link_state(self.g.links[link_id(self.g, supplier)],
                                    variant)

    def test_primary_mass_certified_usable(self):
        st = self.state("主城齿轮")
        self.assertTrue(st.certified)
        self.assertTrue(st.usable)
        self.assertEqual(st.available_capacity, 60)
        self.assertEqual(st.price, 100)

    def test_trial_cert_not_usable(self):
        st = self.state("试制乙配")
        self.assertEqual(st.cert_status, "trial")
        self.assertFalse(st.usable)
        self.assertTrue(any("试制" in r for r in st.blocked_reasons))

    def test_unconfirmed_commitment_blocks(self):
        st = self.state("待确认丙配")
        self.assertFalse(st.confirmed)
        self.assertFalse(st.usable)
        self.assertTrue(any("确认" in r for r in st.blocked_reasons))

    def test_supply_stop_zeroes_capacity_baseline_keeps_it(self):
        raw = make_raw()
        raw["events"] = [{
            "event_id": "E1", "kind": "supply_stop",
            "effective_from": DAY, "effective_to": None,
            "target_type": "company", "target_id": "主城齿轮",
        }]
        g = build_graph(raw)
        snap = Snapshot(g, DAY)
        lid = link_id(g, "主城齿轮")
        stopped = snap.link_state(g.links[lid], "VF")
        self.assertFalse(stopped.usable)
        self.assertTrue(any("断供" in r for r in stopped.blocked_reasons))
        baseline = snap.link_state(g.links[lid], "VF",
                                   ignore_supply_stop=True)
        self.assertTrue(baseline.usable)
        self.assertEqual(baseline.available_capacity, 60)

    def test_quality_hold_window(self):
        raw = make_raw()
        raw["events"] = [{
            "event_id": "E2", "kind": "quality_hold",
            "effective_from": "2026-09-21", "effective_to": "2026-10-05",
            "target_type": "link", "target_id": link_id(make_graph(), "本地甲配"),
        }]
        g = build_graph(raw)
        inside = Snapshot(g, "2026-09-28").link_state(
            g.links[link_id(g, "本地甲配")], "VF")
        self.assertFalse(inside.usable)
        after = Snapshot(g, "2026-10-05").link_state(
            g.links[link_id(g, "本地甲配")], "VF")
        # 有效窗口为 [from, to)：10-05 已恢复。
        self.assertTrue(after.usable)

    def test_price_expiry_blocks_business_not_physical(self):
        raw = make_raw()
        raw["events"] = [{
            "event_id": "E3", "kind": "price_expiry",
            "effective_from": "2026-09-15", "effective_to": None,
            "target_type": "commitment", "target_id": "M-A1",
        }]
        g = build_graph(raw)
        st = Snapshot(g, DAY).link_state(
            g.links[link_id(g, "本地甲配")], "VF")
        self.assertGreater(st.physical_capacity, 0)
        self.assertFalse(st.usable)
        self.assertTrue(any("报价" in r for r in st.blocked_reasons))

    def test_ramp_trial_to_mass_with_curve(self):
        raw = make_raw()
        raw["events"] = [{
            "event_id": "E4", "kind": "ramp",
            "effective_from": "2026-09-28", "effective_to": None,
            "target_type": "link",
            "target_id": link_id(make_graph(), "试制乙配"),
            "ramp_curve": {"0": 20, "1": 50, "2": 80},
        }]
        g = build_graph(raw)
        week0 = Snapshot(g, "2026-09-28").link_state(
            g.links[link_id(g, "试制乙配")], "VF")
        self.assertTrue(week0.usable)
        self.assertEqual(week0.available_capacity, 20)
        week1 = Snapshot(g, "2026-10-05").link_state(
            g.links[link_id(g, "试制乙配")], "VF")
        self.assertEqual(week1.available_capacity, 50)
        week2 = Snapshot(g, "2026-10-12").link_state(
            g.links[link_id(g, "试制乙配")], "VF")
        self.assertEqual(week2.available_capacity, 80)

    def test_maintenance_partial_week_reduces_capacity(self):
        raw = make_raw()
        raw["equipment"] = [{
            "equipment_id": "Q1", "name": "热处理炉",
            "shared_by": ["主城齿轮", "本地甲配"],
        }]
        # 给主供链接挂上设备。
        for lk in raw["sourcing_links"]:
            if lk["link_id"] == "L-P":
                lk["equipment_ids"] = ["Q1"]
        raw["events"] = [{
            "event_id": "E5", "kind": "maintenance",
            "effective_from": "2026-09-28", "effective_to": "2026-10-02",
            "target_type": "equipment", "target_id": "Q1",
        }]  # 周一至周四，停机 4 天 → 产能 60 * 3/7 = 25
        g = build_graph(raw)
        st = Snapshot(g, DAY).link_state(g.links["L-P"], "VF")
        self.assertTrue(st.usable)
        self.assertEqual(st.available_capacity, 25)

    def test_certification_expiry(self):
        raw = make_raw()
        for c in raw["certifications"]:
            if c["cert_id"] == "K-A1-VF":
                c["valid_to"] = "2026-09-01"
        g = build_graph(raw)
        st = Snapshot(g, DAY).link_state(
            g.links[link_id(g, "本地甲配")], "VF")
        self.assertEqual(st.cert_status, "expired")
        self.assertFalse(st.usable)


if __name__ == "__main__":
    unittest.main()
