import unittest

from tests.support import make_raw, order
from src.resilience.graph import build_graph
from src.resilience.impact import simulate_impact
from src.resilience.actions import confirm_commitment, ConfirmationError

DAY = "2026-09-28"


def build_disrupted():
    raw = make_raw()
    raw["events"] = [{
        "event_id": "STOP", "kind": "supply_stop",
        "effective_from": DAY, "effective_to": None,
        "target_type": "company", "target_id": "主城齿轮",
    }]
    raw["orders"] = [
        order("O1", "VF", 50, DAY),
        order("O2", "VE", 60, DAY),
        order("O3", "VO", 40, DAY),
    ]
    return build_graph(raw)


class ConfirmationTest(unittest.TestCase):
    def test_unconfirmed_alternative_excluded_from_simulation(self):
        g = build_disrupted()
        # 待确认丙配交期改为现货，但其承诺未经在线确认，不能救急。
        for m_id in g.commitments:
            m = g.commitments[m_id]
        rep_before = simulate_impact(g, DAY, horizon_weeks=1)
        # 主供 60 台产能消失，第 0 周存在缺口。
        self.assertGreater(rep_before.total_impacted_units, 0)

        # 把丙配承诺交期改为现货后再次评估：仍因未确认而不能补位。
        g.commitments["M-A3"].lead_time_days = 0
        rep_unconfirmed = simulate_impact(g, DAY, horizon_weeks=1)
        self.assertEqual(
            rep_unconfirmed.total_impacted_units,
            rep_before.total_impacted_units,
        )

    def test_online_confirmation_makes_capacity_available(self):
        g = build_disrupted()
        g.commitments["M-A3"].lead_time_days = 0
        g.commitments["M-A3"].capacity_per_week = 200
        # 丙配确认承诺：200 件/周现货产能进入池，可覆盖三车型全部剩余需求。
        summary = confirm_commitment(g, "M-A3")
        self.assertTrue(summary["confirmed"])
        rep = simulate_impact(g, DAY, horizon_weeks=1)
        # 三车型 150 件齿轮需求由已确认的丙配接住（其基线已供 90 件，
        # 剩余产能接住断供主供的 60 件），缺口清零。
        self.assertEqual(rep.total_impacted_units, 0)

    def test_other_supplier_cannot_confirm(self):
        g = build_disrupted()
        other = g.registry.resolve("本地甲配")
        with self.assertRaises(ConfirmationError):
            confirm_commitment(g, "M-A3", supplier_id=other)

    def test_confirm_unknown_commitment(self):
        g = build_disrupted()
        with self.assertRaises(ConfirmationError):
            confirm_commitment(g, "M-GHOST")


if __name__ == "__main__":
    unittest.main()
