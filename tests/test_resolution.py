import json
import unittest
from pathlib import Path

from src.names import normalize_name, resolve_entities
from src.model import load_graph

RAW = json.loads(Path("fixtures/graph.json").read_text(encoding="utf-8"))["raw_directory"]


class NormalizeTest(unittest.TestCase):
    def test_org_suffixes(self):
        self.assertEqual(normalize_name("岚山精密齿轮有限公司"), "岚山精密齿轮")
        self.assertEqual(normalize_name("岚山精密齿轮有限责任公司"), "岚山精密齿轮")
        self.assertEqual(normalize_name("岚山精密齿轮股份有限公司"), "岚山精密齿轮")
        self.assertEqual(normalize_name("岚山精密齿轮厂"), "岚山精密齿轮")
        self.assertEqual(normalize_name("岚山精密齿轮"), "岚山精密齿轮")

    def test_punctuation_and_fullwidth(self):
        self.assertEqual(normalize_name("岚山·精密齿轮（）"), "岚山精密齿轮")
        self.assertEqual(normalize_name(" 岚山 精密齿轮，。"), "岚山精密齿轮")

    def test_different_names_stay_different(self):
        self.assertNotEqual(normalize_name("岚山精密齿轮有限公司"), normalize_name("潼溪齿轮有限公司"))


class ResolveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entities = resolve_entities(RAW)

    def test_scale(self):
        # 三百五十多家主体：归并后仍超过 350 家，且少于原始名录条数。
        self.assertGreaterEqual(len(self.entities), 350)
        self.assertGreater(len(RAW), len(self.entities))

    def test_known_alias_merges(self):
        g1 = next(e for e in self.entities if e["name"] == "岚山精密齿轮有限公司")
        self.assertIn("岚山精密齿轮", g1["aliases"])  # 简称，名称等价归并
        self.assertIn("岚山齿轮厂", g1["aliases"])    # 旧称，same_as 归并
        self.assertGreaterEqual(len(g1["source_records"]), 2)
        hits = [e for e in self.entities if "岚山齿轮厂" in [e["name"], *e["aliases"]]]
        self.assertEqual(len(hits), 1, "旧称只能归并到一个主体")

    def test_no_duplicate_keys(self):
        keys = [normalize_name(e["name"]) for e in self.entities]
        self.assertEqual(len(keys), len(set(keys)))

    def test_same_as_unknown_raises(self):
        with self.assertRaises(ValueError):
            resolve_entities([{"id": "a", "name": "甲有限公司", "same_as": "missing"}])

    def test_duplicate_record_id_raises(self):
        with self.assertRaises(ValueError):
            resolve_entities([
                {"id": "a", "name": "甲有限公司"},
                {"id": "a", "name": "乙有限公司"},
            ])


class LoadGraphTest(unittest.TestCase):
    def test_fixture_loads(self):
        graph = load_graph("fixtures/graph.json")
        self.assertGreaterEqual(len(graph.companies), 350)
        self.assertEqual({m.kind for m in graph.models.values()}, {"fuel", "ev", "offroad"})

    def test_scripted_edge_references(self):
        graph = load_graph("fixtures/graph.json")
        edge = graph.edges["E-F250-GEAR-1"]
        self.assertEqual(edge.supplier, "岚山精密齿轮有限公司")
        self.assertEqual(graph.models[edge.model_code].oem, "苍岚重机有限公司")
        self.assertEqual(graph.companies[edge.supplier].kind, "parts")


if __name__ == "__main__":
    unittest.main()
