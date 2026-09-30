import unittest

from src.resilience.registry import Registry, normalize_name, build_registry


class NormalizeTest(unittest.TestCase):
    def test_strips_region_and_suffix(self):
        self.assertEqual(normalize_name("重庆精铸齿轮有限公司"), "精铸齿轮")
        self.assertEqual(normalize_name("重庆市精铸齿轮有限责任公司"), "精铸齿轮")
        self.assertEqual(normalize_name("（重庆）精铸齿轮股份有限公司"), "精铸齿轮")
        self.assertEqual(normalize_name("精铸齿轮集团"), "精铸齿轮")

    def test_distinct_names_stay_distinct(self):
        self.assertNotEqual(normalize_name("重庆华锐齿轮有限公司"),
                            normalize_name("重庆恒力齿轮有限公司"))


class RegistryTest(unittest.TestCase):
    def _records(self):
        return [
            {"company_id": "C1", "reg_code": "91X", "name": "重庆精铸齿轮有限公司",
             "short_name": "精铸齿轮", "local": True},
            # 同一注册代码、不同写法。
            {"company_id": "C1", "reg_code": "91X",
             "name": "（重庆）精铸齿轮股份有限公司",
             "short_name": "精铸齿轮", "local": True},
            # 仅靠归一化名称归并。
            {"company_id": "C9", "reg_code": "", "name": "精铸齿轮总厂",
             "short_name": "精铸齿轮", "local": True,
             "aliases": ["精铸齿轮"]},
        ]

    def test_merges_to_one_company(self):
        reg = build_registry(self._records())
        self.assertEqual(len(reg), 1)
        cid = reg.resolve("精铸齿轮")
        self.assertEqual(reg.resolve("91X"), cid)
        self.assertEqual(reg.resolve("精铸齿轮总厂"), cid)
        self.assertEqual(reg.resolve("（重庆）精铸齿轮股份有限公司"), cid)
        company = reg.get(cid)
        self.assertIn("精铸齿轮总厂", company.seen_as)

    def test_unknown_reference_raises(self):
        reg = build_registry(self._records())
        with self.assertRaises(KeyError):
            reg.resolve("不存在的企业")

    def test_conflicting_reg_code_non_strict_keeps_first(self):
        records = [
            {"company_id": "C1", "reg_code": "91A", "name": "甲企业有限公司",
             "short_name": "甲企业", "local": True},
            {"company_id": "C2", "reg_code": "91B", "name": "甲企业股份有限公司",
             "short_name": "甲企业", "local": True},
        ]
        reg = Registry()
        reports = reg.register(records)
        self.assertEqual(len(reg), 1)
        self.assertEqual(reports[1]["action"], "merged")
        self.assertTrue(reports[1]["conflicts"])

    def test_strict_conflict_raises(self):
        records = [
            {"company_id": "C1", "reg_code": "91A", "name": "甲企业有限公司",
             "short_name": "甲企业", "local": True},
            {"company_id": "C2", "reg_code": "91B", "name": "甲企业股份有限公司",
             "short_name": "甲企业", "local": True},
        ]
        with self.assertRaises(ValueError):
            build_registry(records, strict=True)


if __name__ == "__main__":
    unittest.main()
