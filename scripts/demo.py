"""断供通知情景演示。

用法：
    python scripts/demo.py [YYYY-MM-DD]

默认评估日为样本叙事的通知日 2026-09-28。脚本打印：
  1) 主体归并结果；
  2) 整车企业视角：燃油/电动/越野受影响订单与替代组合；
  3) 园区视角：单点依赖、真实本地配套率、扶持前后交付能力（无成本字段）。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.resilience import build_graph
from src.resilience.views import Viewer, oem_dashboard, park_dashboard

FIXTURE = Path("fixtures/sample_graph.json")
PLATFORM_LABEL = {"fuel": "燃油", "electric": "智能电动", "offroad": "越野"}


def main(day: str = "2026-09-28"):
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    graph = build_graph(raw)

    merge = graph.registry.merge_report()
    print("=" * 68)
    print("一、主体归并")
    print("=" * 68)
    print(f"原始登记 {merge['raw_records']} 条 → 规范主体 {merge['companies']} 家"
          f"（消除重复名称 {merge['duplicates_collapsed']} 个）")
    jingzhu = graph.registry.resolve("精铸齿轮")
    print("示例：以下写法全部指向同一主体", graph.registry.get(jingzhu).canonical_name)
    for name in ("精铸齿轮", "重庆精铸齿轮有限公司",
                 "（重庆）精铸齿轮股份有限公司", "精铸齿轮总厂"):
        print(f"  - {name} → {graph.registry.resolve(name)}")

    print()
    print("=" * 68)
    print(f"二、整车企业视角（评估日 {day}，收到停产通知后）")
    print("=" * 68)
    oem = Viewer("oem", graph.registry.resolve("陵江机车"))
    dash = oem_dashboard(graph, oem, day)
    for line in dash["answer"]:
        print("●", line)

    print("\n受影响订单（按交付周）:")
    for row in dash["weekly"]:
        flag = f"短缺 {row['short_units']} 台" if row["short_units"] else "可足额交付"
        print(f"  {row['week']} 当周需求 {row['demand_units']} 台 → {flag}")

    print("\n替代组合（关键齿轮）:")
    for plan in dash["substitution_plans"]:
        status = "可完全替代" if plan["feasible"] else \
            f"残余缺口 {plan['residual_gap']} 件"
        print(f"\n  [{plan['part']} / {plan['variant_id']}] {status}")
        print(f"    主供原报价 {plan['primary_price']} 元/件，"
              f"一次性切换成本 {plan['one_time_switch_cost']:.0f} 元，"
              f"替代差价合计 {plan['extra_unit_cost']:.0f} 元")
        for a in plan["allocations"]:
            tag = "备选" if a["alternate"] else "在供"
            print(f"    - {a['supplier']}（{tag}）承接 {a['qty']} 件，"
                  f"周产能 {a['weekly_capacity']}，报价 {a['unit_price']} 元，"
                  f"交期 {a['lead_time_days']} 天")

    print()
    print("=" * 68)
    print("三、园区产业服务部门视角（商业字段已屏蔽）")
    print("=" * 68)
    park = park_dashboard(graph, Viewer("park"), day)
    print("真实本地配套率（按当前可用认证产能、需求加权）："
          f"{park['real_local_content_rate']['overall_real_local_rate']:.2%}")
    print("\n单点依赖：")
    for sp in park["single_point_dependencies"]:
        scope = "本地" if sp["local"] else "外地"
        print(f"  - {sp['part']} ← {sp['supplier']}（{scope}）/{sp['variant_id']}")

    ba = park["delivery_before_after_support"]
    print("\n扶持措施前后交付能力：")
    print(f"  扶持前受影响 {ba['before']['impacted_units']} 台，"
          f"残余缺口 {ba['before']['residual_gap']} 件")
    print(f"  扶持后受影响 {ba['after']['impacted_units']} 台，"
          f"残余缺口 {ba['after']['residual_gap']} 件")
    print(f"  改善 {ba['improved_units']} 台，缺口收敛 {ba['gap_closed']} 件")
    print("  在效措施：")
    for ms in ba["measures_in_force"]:
        print(f"    - {ms['measure_id']} {ms['note']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-09-28")
