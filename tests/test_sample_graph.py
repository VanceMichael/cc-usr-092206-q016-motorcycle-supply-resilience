"""对 350+ 主体确定性样本的端到端集成测试。

样本由 scripts/generate_sample.py 生成；若 fixtures 缺失或结构过旧，
测试自行重建，保证仓库在任何检出上都可独立运行。
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from src.resilience import build_graph
from src.resilience.impact import simulate_impact
from src.resilience.park import (
    find_single_points, local_content_rates, before_after_measures,
)
from src.resilience.views import Viewer, oem_dashboard, park_dashboard

FIXTURE = Path("fixtures/sample_graph.json")
NOTIFY_DAY = "2026-09-28"


def load_sample():
    if not FIXTURE.exists():
        subprocess.run(
            [sys.executable, "scripts/generate_sample.py"], check=True
        )
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class SampleGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = load_sample()
        cls.graph = build_graph(cls.raw)

    def test_over_350_entities_and_duplicates_collapsed(self):
        self.assertGreaterEqual(len(self.graph.registry), 350)
        report = self.graph.registry.merge_report()
        self.assertGreater(report["duplicates_collapsed"], 0)
        # 精铸齿轮的多种写法全部归并到同一主体。
        cid = self.graph.registry.resolve("精铸齿轮")
        for name in ("重庆精铸齿轮有限公司", "（重庆）精铸齿轮股份有限公司",
                     "精铸齿轮总厂"):
            self.assertEqual(self.graph.registry.resolve(name), cid)

    def test_gear_supplier_structure(self):
        g = self.graph
        for pid, min_alts in (("gear_set", 4), ("reducer_gear", 3)):
            alts = [lk for lk in g.links_for_part(pid)
                    if lk.role == "alternate"]
            self.assertGreaterEqual(len(alts), min_alts)
        # 共享热处理设备连接精铸与华锐。
        eq = g.equipment["EQ01"]
        names = {g.registry.get(cid).short_name for cid in eq.shared_by}
        self.assertEqual(names, {"精铸齿轮", "华锐齿轮"})

    def test_notification_day_answer_by_platform(self):
        rep = simulate_impact(self.graph, NOTIFY_DAY, horizon_weeks=8)
        # 三平台在窗口内都有受影响订单（精铸同时供燃油/电动/越野齿轮）。
        for key in ("fuel", "electric", "offroad"):
            self.assertGreater(rep.by_platform[key].impacted_units, 0)
            self.assertGreater(rep.by_platform[key].impacted_orders, 0)
        # 前两周存在刚性缺口。
        self.assertGreater(rep.weekly[0]["short_units"], 0)
        # 四周后爬坡 + 备选就绪，缺口收敛为 0。
        self.assertEqual(rep.weekly[4]["short_units"], 0)
        # 替代计划恒等式。
        for plan in rep.plans:
            self.assertEqual(
                plan.displaced_units,
                plan.substituted_units + plan.residual_gap,
            )

    def test_support_measures_reduce_impact(self):
        ba = before_after_measures(self.graph, NOTIFY_DAY, horizon_weeks=8)
        self.assertGreater(ba["improved_units"], 0)
        self.assertLess(ba["after"]["impacted_units"],
                        ba["before"]["impacted_units"])
        self.assertGreaterEqual(ba["gap_closed"], 0)

    def test_park_single_points_and_real_rate(self):
        points = find_single_points(self.graph, NOTIFY_DAY)
        # 样本故意埋设两个结构性单点：功率芯片晶圆（外地）、稀土磁钢。
        part_names = {p.part_name for p in points}
        self.assertIn("功率芯片晶圆", part_names)
        self.assertIn("稀土磁钢", part_names)
        rates = local_content_rates(self.graph, NOTIFY_DAY)
        self.assertGreater(rates["overall_real_local_rate"], 0.9)
        self.assertLess(rates["overall_real_local_rate"], 1.0)

    def test_role_views_end_to_end(self):
        g = self.graph
        oem = Viewer("oem", g.registry.resolve("陵江机车"))
        dash = oem_dashboard(g, oem, NOTIFY_DAY)
        self.assertEqual(len(dash["answer"]), 3)
        # 含完整替代组合与成本字段。
        blob = json.dumps(dash, ensure_ascii=False)
        self.assertIn("one_time_switch_cost", blob)

        park = park_dashboard(g, Viewer("park"), NOTIFY_DAY)
        park_blob = json.dumps(park, ensure_ascii=False)
        for secret in ("primary_price", "unit_price", "switch_cost",
                       "ORD-"):
            self.assertNotIn(secret, park_blob)


if __name__ == "__main__":
    unittest.main()
