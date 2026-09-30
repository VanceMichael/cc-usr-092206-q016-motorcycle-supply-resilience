"""生成确定性的产业链样本数据（350+ 主体）。

叙事：2026-09-28（周一）整车厂"陵江机车"收到关键齿轮企业"精铸齿轮"
停产通知。精铸同时是燃油/越野车型齿轮组与电动车型减速齿轮的主供，
本地备选华锐齿轮（共享热处理炉、产能有限）、试制备选恒力齿轮（10 月
爬坡）、安迅齿轮（试制待认证加速）、外地备选外源齿轮（交期两周）。

运行：python scripts/generate_sample.py
输出：fixtures/sample_graph.json（不含真实个人信息）。
"""

import json
import random
from pathlib import Path

SEED = 20260928
NOTIFY_WEEK = "2026-09-28"

# ---------------------------------------------------------------- 零件目录

# part_id, 中文名, 大类名词（用于供应商字号）, 适用平台
COMMON = [
    ("frame", "车架总成", "车架"),
    ("swingarm", "后摇臂", "摇臂"),
    ("brake_assembly", "制动总成", "制动"),
    ("front_fork", "前减震器", "前叉"),
    ("shock_absorber", "后减震器", "减震"),
    ("wheel_hub", "轮毂总成", "轮毂"),
    ("wire_harness", "整车线束", "线束"),
    ("instrument", "仪表总成", "仪表"),
]
ICE_PARTS = [
    ("fuel_tank", "燃油箱", "油箱"),
    ("crankcase", "曲轴箱", "曲轴箱"),
    ("crankshaft", "曲轴", "曲轴"),
    ("cylinder_head", "缸头总成", "缸头"),
    ("gear_set", "齿轮组", "齿轮"),
    ("clutch_pack", "离合器总成", "离合"),
    ("transmission_shaft", "传动轴", "传动轴"),
    ("camshaft", "凸轮轴", "凸轮轴"),
    ("radiator", "散热水箱", "水箱"),
    ("exhaust", "排气总成", "排气"),
    ("chain_drive", "链传动总成", "链传动"),
]
EV_PARTS = [
    ("motor_controller", "电控单元", "电控"),
    ("drive_motor", "驱动电机", "电机"),
    ("battery_pack", "电池包", "电池包"),
    ("bms", "电池管理系统", "BMS"),
    ("onboard_charger", "车载充电机", "充电机"),
    ("reducer_gear", "减速齿轮", "减速齿轮"),
]
OFFROAD_PARTS = [
    ("skid_plate", "发动机护板", "护板"),
]
ALL_PLATFORM_EXTRA = [
    ("headlight", "前大灯", "灯具"),
    ("taillight", "尾灯", "灯具"),
    ("switch_set", "手把开关", "开关"),
    ("seat", "座垫", "座垫"),
    ("fairing_kit", "覆盖件", "塑件"),
    ("wheel_rim", "轮辋", "轮辋"),
    ("tire_set", "轮胎总成", "轮胎"),
    ("kickstand", "侧支架", "支架"),
    ("mirror_set", "后视镜", "后视镜"),
    ("handlebar", "方向把", "车把"),
    ("footpeg", "脚踏", "脚踏"),
    ("horn", "电喇叭", "喇叭"),
    ("speed_sensor", "车速传感器", "传感器"),
    ("lock_set", "套锁", "锁具"),
]
ICE_EXTRA = [
    ("throttle_body", "节气门体", "节气门"),
    ("efi_unit", "电喷单元", "电喷"),
    ("starter_motor", "启动电机", "启动电机"),
    ("magneto", "磁电机", "磁电机"),
    ("ignition_coil", "点火线圈", "线圈"),
    ("air_filter", "空滤器", "空滤"),
    ("oil_pump", "机油泵", "油泵"),
]
EV_EXTRA = [
    ("battery_sla", "启动蓄电池", "蓄电池"),
    ("water_pump", "冷却水泵", "水泵"),
]

# 二级零件：(子零件, 父零件)
SUB_PARTS = [
    ("frame_tube_kit", "车架管件", "frame"),
    ("pivot_shaft", "摇臂销轴", "swingarm"),
    ("brake_caliper", "制动卡钳", "brake_assembly"),
    ("brake_disc", "制动盘", "brake_assembly"),
    ("fork_tube", "叉管", "front_fork"),
    ("shock_spring", "减震弹簧", "shock_absorber"),
    ("hub_bearing_kit", "轮毂轴承组", "wheel_hub"),
    ("connector_set", "接插器组", "wire_harness"),
    ("display_module", "显示模组", "instrument"),
    ("tank_sensor", "油量传感器", "fuel_tank"),
    ("casting_blank", "箱体铸件", "crankcase"),
    ("crank_forging", "曲轴锻坯", "crankshaft"),
    ("valve_set", "气门组", "cylinder_head"),
    ("gear_blank", "齿轮坯件", "gear_set"),
    ("friction_plate_set", "摩擦片组", "clutch_pack"),
    ("shaft_forging", "传动轴锻坯", "transmission_shaft"),
    ("cam_forging", "凸轮轴锻坯", "camshaft"),
    ("radiator_core", "散热器芯体", "radiator"),
    ("muffler_core", "消音芯体", "exhaust"),
    ("sprocket_set", "链轮组", "chain_drive"),
    ("igbt_module", "IGBT模块", "motor_controller"),
    ("control_pcb", "控制PCB板", "motor_controller"),
    ("stator_rotor", "定转子组件", "drive_motor"),
    ("cell_module", "电芯模组", "battery_pack"),
    ("bms_pcb", "BMS电路板", "bms"),
    ("charger_pcb", "充电机电路板", "onboard_charger"),
    ("reducer_blank", "减速齿轮坯", "reducer_gear"),
    ("skid_bracket", "护板支架", "skid_plate"),
]

# 三级原料：(原料, 父零件们)
RAW_PARTS = [
    ("alloy_steel_bar", "合金结构钢棒", ["gear_blank", "reducer_blank",
                                    "crank_forging", "cam_forging",
                                    "shaft_forging", "sprocket_set"]),
    ("aluminum_ingot", "铝合金锭", ["casting_blank", "frame_tube_kit"]),
    ("lithium_cell_raw", "动力锂电芯原料", ["cell_module"]),
    ("power_chip_wafer", "功率芯片晶圆", ["igbt_module"]),
    ("pcb_substrate", "PCB基材", ["control_pcb", "bms_pcb", "charger_pcb"]),
    ("rare_earth_magnet", "稀土磁钢", ["stator_rotor"]),
    ("stainless_coil", "不锈钢卷材", ["muffler_core"]),
    ("cast_iron_ingot", "铸铁锭", ["brake_disc"]),
    ("copper_wire", "电磁铜线", ["connector_set", "stator_rotor"]),
    ("bearing_steel_ring", "轴承钢环", ["hub_bearing_kit"]),
]

# ---------------------------------------------------------------- 名称池

LOCAL_BRANDS = [
    "渝海", "凌云", "天工", "启明", "众和", "安捷", "恒升", "永昌", "同辉",
    "山鹰", "江川", "铜锣", "峡口", "雾都", "巴山", "武陵", "碧津", "南泉",
    "歌乐", "缙云", "龙溪", "双碑", "井口", "土湾", "磁器", "华岩", "中梁",
    "含谷", "白市", "西永", "曾家", "青木", "凤凰", "回龙", "虎峰", "蒲吕",
    "福里", "双福", "德感", "几江", "珞璜", "南彭", "木洞", "长寿", "晏家",
    "新市", "龙岗", "棠城", "昌州",
]
NONLOCAL_CITIES = ["苏州", "成都", "贵阳", "柳州", "广州", "佛山", "无锡",
                   "宁波", "西安", "武汉", "台州", "东莞"]
SERVICE_NAMES = [
    ("渝顺物流", "物流"), ("江通达物流", "物流"), ("鑫鹏模具", "模具"),
    ("广测检测", "检测"), ("恒涂层表面处理", "表面处理"), ("安耐包装", "包装"),
    ("中仪计量", "计量"), ("力擎设备租赁", "设备租赁"), ("蓝领技工服务", "人力"),
    ("环科废液处理", "环保"), ("迅捷报关", "报关"), ("工研院中试基地", "中试"),
    ("智维工业互联网", "信息服务"), ("两江水电气保障", "能源"),
]

VARIANTS = [
    # variant_id, platform, 车型, 版本, 周需求台数
    ("V-FU-FALCON", "fuel", "隼影250", "2026款", 420),
    ("V-FU-CRUISER", "fuel", "巡航者650", "2026款", 360),
    ("V-FU-STREET", "fuel", "街锋150", "2026款", 300),
    ("V-EL-VOLT", "electric", "电霆Pro", "2026款", 380),
    ("V-EL-CITY", "electric", "e城Go", "2025升级款", 340),
    ("V-EL-ADV", "electric", "电驭ADV", "2026款", 300),
    ("V-OF-RALLY", "offroad", "拉力450", "竞技版", 260),
    ("V-OF-TRAIL", "offroad", "林道300", "2026款", 180),
]


class Builder:
    def __init__(self):
        self.rng = random.Random(SEED)
        self.companies = []
        self.parts = []
        self.certs = []
        self.commitments = []
        self.links = []
        self.events = []
        self.equipment = []
        self.measures = []
        self.orders = []
        self._seq_company = 0
        self._seq = {}
        self.brand_pool = list(LOCAL_BRANDS)
        self.rng.shuffle(self.brand_pool)
        self._brand_i = 0
        self.part_meta = {}          # part_id -> (name, noun, platforms)
        self.part_links = {}         # part_id -> [link dicts]
        self.company_index = {}      # short_name -> company_id

    # -- 编号与企业 -------------------------------------------------------

    def nid(self, prefix):
        n = self._seq.get(prefix, 0) + 1
        self._seq[prefix] = n
        return f"{prefix}{n:03d}"

    def next_brand(self):
        brand = self.brand_pool[self._brand_i % len(self.brand_pool)]
        self._brand_i += 1
        if self._brand_i <= len(self.brand_pool):
            return brand
        # 池用尽后用地名+吉字组合追加字号（20 轮内保证唯一，名称自然）。
        lucky = ["鑫", "盛", "泰", "达", "宏", "瑞", "隆", "源", "顺", "昌",
                 "德", "信", "合", "联", "捷", "耀", "骏", "鹏", "峰", "越"]
        round_no = (self._brand_i - 1) // len(self.brand_pool)
        return f"{brand}{lucky[round_no % len(lucky)]}"

    def add_company(self, name, *, local=True, short=None, aliases=(),
                    reg=None, kind="supplier"):
        self._seq_company += 1
        cid = f"C{self._seq_company:04d}"
        if reg is None:
            reg = (f"91{'5000' if local else '3100'}MA"
                   f"{self._seq_company:08d}")
        rec = {
            "company_id": cid,
            "reg_code": reg,
            "name": name,
            "short_name": short or name,
            "local": local,
            "kind": kind,
            "aliases": list(aliases),
        }
        self.companies.append(rec)
        if short:
            self.company_index[short] = cid
        return cid

    def new_supplier(self, noun, *, local=True, short=None):
        if local:
            brand = self.next_brand()
            short = short or f"{brand}{noun}"
            name = f"重庆{brand}{noun}有限公司"
        else:
            city = self.rng.choice(NONLOCAL_CITIES)
            brand = self.rng.choice(["恒宇", "瑞松", "联港", "嘉信", "通达",
                                     "正泰", "海纳", "卓越", "新科", "广合"])
            short = short or f"{city}{brand}{noun}"
            name = f"{city}{brand}{noun}股份有限公司"
        self.add_company(name, local=local, short=short)
        return short

    # -- 零件 -------------------------------------------------------------

    def add_part(self, pid, cname, noun, platforms, *, parent=None,
                 critical=False):
        self.parts.append({
            "part_id": pid, "name": cname, "category": noun,
            "critical": critical, "parent_id": parent,
        })
        self.part_meta[pid] = (cname, noun, set(platforms))
        self.part_links[pid] = []

    # -- 寻源链接/认证/承诺 ----------------------------------------------

    def add_link(self, pid, supplier_short, *, role, capacity, price,
                 lead=7, cert_status="mass", confirmed=True,
                 cert_from="2024-06-01", switch_cost=0.0,
                 equipment=()):
        lid = self.nid("L")
        cert_ids, commit_ids = [], []
        cname, noun, platforms = self.part_meta[pid]
        for variant_id, platform, *_ in VARIANTS:
            if platform not in platforms:
                continue
            cert_id = self.nid("K")
            self.certs.append({
                "cert_id": cert_id,
                "company": supplier_short,
                "part_id": pid,
                "variant_id": variant_id,
                "status": cert_status,
                "valid_from": cert_from,
            })
            cert_ids.append(cert_id)
        mid = self.nid("M")
        self.commitments.append({
            "commitment_id": mid,
            "company": supplier_short,
            "part_id": pid,
            "capacity_per_week": capacity,
            "price": price,
            "currency": "CNY",
            "lead_time_days": lead,
            "confirmed": confirmed,
            "valid_from": cert_from,
        })
        commit_ids.append(mid)
        primary_id = None
        if role == "alternate":
            primaries = [l["link_id"] for l in self.part_links[pid]
                         if l["_role"] == "primary"]
            primary_id = primaries[0] if primaries else None
        link = {
            "link_id": lid,
            "part_id": pid,
            "supplier": supplier_short,
            "role": role,
            "cert_ids": cert_ids,
            "commitment_ids": commit_ids,
            "equipment_ids": list(equipment),
            "lead_time_days": lead,
            "candidate_for": [primary_id] if role == "alternate" and primary_id else [],
            "switch_cost": float(switch_cost) if role == "alternate" else 0.0,
            "_role": role,
        }
        self.links.append(link)
        self.part_links[pid].append(link)
        return lid

    def generic_part_sources(self, pid, platforms, *, base_cap=4200,
                             price=40.0, local_alts=2, nonlocal_alt=True,
                             unconfirmed_alt=False):
        """为普通零件铺设：1 本地主供 + 若干本地备选 + 1 外地备选。"""
        noun = self.part_meta[pid][1]
        p = self.new_supplier(noun)
        self.add_link(pid, p, role="primary",
                      capacity=base_cap + self.rng.randint(0, 1200),
                      price=round(price, 2), lead=self.rng.choice([3, 5, 7]),
                      switch_cost=0)
        for i in range(local_alts):
            a = self.new_supplier(noun)
            self.add_link(
                pid, a, role="alternate",
                capacity=base_cap // 2 + self.rng.randint(0, 600),
                price=round(price * (1.05 + 0.04 * i), 2),
                lead=self.rng.choice([7, 10, 14]),
                confirmed=not (unconfirmed_alt and i == local_alts - 1),
                switch_cost=20000 + 10000 * i,
            )
        if nonlocal_alt:
            n = self.new_supplier(noun, local=False)
            self.add_link(pid, n, role="alternate",
                          capacity=base_cap // 2 + 400,
                          price=round(price * 1.18, 2), lead=21,
                          switch_cost=120000)

    # -- 主流程 -----------------------------------------------------------

    def build(self):
        self._build_actors()
        self._build_parts_and_sources()
        self._build_narrative_sources()
        self._build_equipment_events_measures()
        self._build_orders()
        raw = self._inject_duplicate_names()
        return raw

    def _build_actors(self):
        # 整车企业、认证机构、第二整车企业（仅主体，用于表现图谱边界）。
        self.add_company("重庆陵江机车制造有限公司", local=True,
                         short="陵江机车",
                         reg="91500000MA5LJ00001", kind="oem")
        self.add_company("中国质量认证中心西南试验室", local=True,
                         short="西南认证", reg="91500000CQC000001",
                         kind="certifier")
        self.add_company("重庆巴山机车股份有限公司", local=True,
                         short="巴山机车", reg="91500000MA5BS00002",
                         kind="oem")
        # 生产性服务主体。
        for name, tag in SERVICE_NAMES:
            self.add_company(f"重庆{name}有限公司", local=True,
                             short=name, kind="service")

    def _platforms_for(self, scope):
        if scope == "all":
            return ["fuel", "electric", "offroad"]
        if scope == "ice":
            return ["fuel", "offroad"]
        if scope == "ev":
            return ["electric"]
        if scope == "offroad":
            return ["offroad"]
        raise ValueError(scope)

    def _build_parts_and_sources(self):
        catalog = (
            [(p, "all") for p in COMMON]
            + [(p, "ice") for p in ICE_PARTS]
            + [(p, "ev") for p in EV_PARTS]
            + [(p, "offroad") for p in OFFROAD_PARTS]
            + [(p, "all") for p in ALL_PLATFORM_EXTRA]
            + [(p, "ice") for p in ICE_EXTRA]
            + [(p, "ev") for p in EV_EXTRA]
        )
        critical_ids = {"gear_set", "reducer_gear", "motor_controller",
                        "battery_pack", "ecu"}
        for (pid, cname, noun), scope in catalog:
            platforms = self._platforms_for(scope)
            self.add_part(pid, cname, noun, platforms,
                          critical=pid in critical_ids)
            if pid in ("gear_set", "reducer_gear"):
                continue  # 叙事零件单独铺设
            # 不同体量零件给不同基础产能/价位。
            cap = self.rng.choice([3000, 3600, 4200, 5000, 6000])
            price = float(self.rng.choice([18, 26, 35, 48, 66, 88, 120, 180]))
            self.generic_part_sources(
                pid, platforms, base_cap=cap, price=price,
                local_alts=self.rng.choice([1, 2, 2, 3]),
                nonlocal_alt=self.rng.random() < 0.75,
                unconfirmed_alt=self.rng.random() < 0.25,
            )

        # 二级零件：四个供应商（3 本地 + 1 外地），产能充足。
        for pid, cname, parent in SUB_PARTS:
            platforms = self.part_meta[parent][2]
            self.add_part(pid, cname, cname, platforms, parent=parent)
            noun = self.part_meta[pid][1]
            p = self.new_supplier(noun)
            self.add_link(pid, p, role="primary", capacity=9000,
                          price=12.0, lead=5)
            for i in range(2):
                a = self.new_supplier(noun)
                self.add_link(pid, a, role="alternate",
                              capacity=5000 + i * 800,
                              price=round(13.2 + 0.5 * i, 2), lead=10,
                              switch_cost=15000)
            n = self.new_supplier(noun, local=False)
            self.add_link(pid, n, role="alternate", capacity=5000,
                          price=15.4, lead=21, switch_cost=90000)

        # 三级原料。
        for pid, cname, parents in RAW_PARTS:
            # 平台集合取所有父零件的并集。
            platforms = set()
            for parent in parents:
                platforms |= self.part_meta[parent][2]
            self.add_part(pid, cname, cname, sorted(platforms))
            self.parts[-1]["parent_id"] = parents[0]
            if len(parents) > 1:
                self.parts[-1]["also_parent_of"] = parents[1:]
            noun = cname
            # 故意保留两个真实单点：功率芯片晶圆仅外地 1 家，稀土磁钢仅本地 1 家。
            if pid == "power_chip_wafer":
                n = self.new_supplier("半导体材料", local=False)
                self.add_link(pid, n, role="primary", capacity=12000,
                              price=220.0, lead=28)
                continue
            if pid == "rare_earth_magnet":
                p = self.new_supplier("磁材")
                self.add_link(pid, p, role="primary", capacity=10000,
                              price=96.0, lead=10)
                continue
            p = self.new_supplier(noun)
            self.add_link(pid, p, role="primary", capacity=16000,
                          price=8.0, lead=5)
            for i in range(3):
                a = self.new_supplier(noun)
                self.add_link(pid, a, role="alternate",
                              capacity=9000 + 600 * i,
                              price=round(8.6 + 0.3 * i, 2), lead=12,
                              switch_cost=10000)
            n = self.new_supplier(noun, local=False)
            self.add_link(pid, n, role="alternate", capacity=10000,
                          price=9.6, lead=21, switch_cost=80000)

    def _build_narrative_sources(self):
        """关键齿轮零件的供应结构（停产事件的主角）。"""
        # 精铸齿轮：齿轮组 + 减速齿轮主供。
        self.add_company("重庆精铸齿轮有限公司", local=True,
                         short="精铸齿轮", reg="91500000MA5JC00003",
                         aliases=["（重庆）精铸齿轮股份有限公司", "精铸齿轮集团"])
        self.add_company("重庆华锐齿轮股份有限公司", local=True,
                         short="华锐齿轮", reg="91500000MA5HR00004",
                         aliases=["华锐精密齿轮"])
        self.add_company("重庆恒力齿轮制造有限公司", local=True,
                         short="恒力齿轮", reg="91500000MA5HL00005")
        self.add_company("重庆安迅齿轮部件有限公司", local=True,
                         short="安迅齿轮", reg="91500000MA5AX00006")
        self.add_company("苏州外源齿轮股份有限公司", local=False,
                         short="外源齿轮", reg="91320500MA5WY00007")

        # 共享热处理设备。
        self.equipment.append({
            "equipment_id": "EQ01",
            "name": "箱式渗碳淬火炉一线",
            "shared_by": ["精铸齿轮", "华锐齿轮"],
        })

        # 齿轮组（燃油+越野）。
        self.add_link("gear_set", "精铸齿轮", role="primary",
                      capacity=1700, price=118.0, lead=7,
                      equipment=["EQ01"])
        self.add_link("gear_set", "华锐齿轮", role="alternate",
                      capacity=900, price=124.0, lead=10,
                      equipment=["EQ01"], switch_cost=45000)
        self.add_link("gear_set", "恒力齿轮", role="alternate",
                      capacity=700, price=116.0, lead=21,
                      cert_status="trial", cert_from="2026-08-01",
                      switch_cost=90000)
        self.add_link("gear_set", "安迅齿轮", role="alternate",
                      capacity=500, price=121.0, lead=7,
                      cert_status="trial", cert_from="2026-08-15",
                      switch_cost=60000)
        self.add_link("gear_set", "外源齿轮", role="alternate",
                      capacity=1500, price=162.0, lead=28,
                      switch_cost=180000)

        # 减速齿轮（电动）。
        self.add_link("reducer_gear", "精铸齿轮", role="primary",
                      capacity=1200, price=132.0, lead=7,
                      equipment=["EQ01"])
        self.add_link("reducer_gear", "华锐齿轮", role="alternate",
                      capacity=500, price=138.0, lead=10,
                      equipment=["EQ01"], switch_cost=40000)
        self.add_link("reducer_gear", "恒力齿轮", role="alternate",
                      capacity=350, price=130.0, lead=21,
                      cert_status="trial", cert_from="2026-08-01",
                      switch_cost=85000)
        self.add_link("reducer_gear", "外源齿轮", role="alternate",
                      capacity=600, price=178.0, lead=21,
                      switch_cost=160000)

    def _find_link(self, pid, supplier_short):
        for lk in self.part_links[pid]:
            if lk["supplier"] == supplier_short:
                return lk
        raise KeyError((pid, supplier_short))

    def _build_equipment_events_measures(self):
        gear_hengl = self._find_link("gear_set", "恒力齿轮")["link_id"]
        red_hengl = self._find_link("reducer_gear", "恒力齿轮")["link_id"]
        gear_anxun = self._find_link("gear_set", "安迅齿轮")["link_id"]
        gear_waiyuan = self._find_link("gear_set", "外源齿轮")["link_id"]
        gear_huarui = self._find_link("gear_set", "华锐齿轮")["link_id"]

        # 断供：精铸齿轮 2026-09-28 起停产（通知当日生效）。
        self.events.append({
            "event_id": "EV-STOP-01",
            "kind": "supply_stop",
            "effective_from": NOTIFY_WEEK,
            "effective_to": None,
            "target_type": "company",
            "target_id": "精铸齿轮",
            "note": "企业突发停产整顿，齿轮全部品种停供",
        })
        # 试制转量产：恒力齿轮 10-12 起爬坡（齿轮组、减速齿轮两条链）。
        self.events.append({
            "event_id": "EV-RAMP-GEAR",
            "kind": "ramp",
            "effective_from": "2026-10-12",
            "effective_to": None,
            "target_type": "link",
            "target_id": gear_hengl,
            "ramp_curve": {"0": 200, "1": 400, "2": 700},
            "note": "试制批转量产，三周爬坡",
        })
        self.events.append({
            "event_id": "EV-RAMP-RED",
            "kind": "ramp",
            "effective_from": "2026-10-12",
            "effective_to": None,
            "target_type": "link",
            "target_id": red_hengl,
            "ramp_curve": {"0": 120, "1": 250, "2": 350},
        })
        # 质量暂停：某电控备选 9-21 至 10-05 暂停。
        mc_alt = next(
            l for l in self.part_links["motor_controller"]
            if l["_role"] == "alternate" and l["role"] == "alternate"
        )
        self.events.append({
            "event_id": "EV-HOLD-01",
            "kind": "quality_hold",
            "effective_from": "2026-09-21",
            "effective_to": "2026-10-05",
            "target_type": "link",
            "target_id": mc_alt["link_id"],
            "note": "来料批次不合格，暂停放行",
        })
        # 价格失效：某轮胎外地备选报价 9-15 起失效。
        tire_alt = next(
            l for l in self.part_links["tire_set"] if l["role"] == "alternate"
        )
        self.events.append({
            "event_id": "EV-PRICE-01",
            "kind": "price_expiry",
            "effective_from": "2026-09-15",
            "effective_to": None,
            "target_type": "commitment",
            "target_id": tire_alt["commitment_ids"][0],
            "note": "原材料涨价，原报价失效待重谈",
        })
        # 设备检修：共享热处理炉 10-12 至 10-16 停机 5 天。
        self.events.append({
            "event_id": "EV-MAINT-01",
            "kind": "maintenance",
            "effective_from": "2026-10-12",
            "effective_to": "2026-10-17",
            "target_type": "equipment",
            "target_id": "EQ01",
            "note": "炉衬大修，停机五天",
        })

        # 园区扶持包（10-12 生效）。
        self.measures = [
            {
                "measure_id": "MS01",
                "kind": "capacity_grant",
                "target_type": "link",
                "target_id": gear_huarui,
                "value": 600,
                "effective_from": "2026-10-12",
                "effective_to": None,
                "note": "技改补贴支持华锐新增周产能600件",
            },
            {
                "measure_id": "MS02",
                "kind": "cert_acceleration",
                "target_type": "link",
                "target_id": gear_anxun,
                "value": 0,
                "effective_from": "2026-10-12",
                "effective_to": None,
                "note": "认证辅导专班加速安迅量产认证",
            },
            {
                "measure_id": "MS03",
                "kind": "equipment_backup",
                "target_type": "equipment",
                "target_id": "EQ01",
                "value": 800,
                "effective_from": "2026-10-12",
                "effective_to": None,
                "note": "协调备份热处理产线，等效周产能800件",
            },
            {
                "measure_id": "MS04",
                "kind": "price_subsidy",
                "target_type": "link",
                "target_id": gear_waiyuan,
                "value": 12,
                "effective_from": "2026-10-12",
                "effective_to": None,
                "note": "外地紧急采购每件补贴12元",
            },
        ]

    def _build_orders(self):
        from datetime import date, timedelta
        monday = date.fromisoformat(NOTIFY_WEEK)
        n = 0
        for week in range(8):
            due = (monday + timedelta(weeks=week)).isoformat()
            for variant_id, platform, model, version, weekly in VARIANTS:
                # 每个车型每周 1-3 笔订单，确定性波动。
                r = random.Random(f"{variant_id}-{week}")
                splits = r.choice([[1.0], [0.45, 0.55], [0.3, 0.35, 0.35]])
                total = weekly + r.choice([-30, -10, 0, 20, 40])
                allocated = 0
                for i, frac in enumerate(splits):
                    n += 1
                    qty = int(total * frac) if i < len(splits) - 1 else total - allocated
                    allocated += qty
                    if qty <= 0:
                        continue
                    self.orders.append({
                        "order_id": f"ORD-{n:04d}",
                        "variant_id": variant_id,
                        "quantity": qty,
                        "due_week": due,
                        "customer_segment": r.choice(
                            ["domestic", "domestic", "export", "domestic"]),
                    })

    def _inject_duplicate_names(self):
        """为部分企业追加"同一主体不同名称"的原始登记记录。"""
        extra = []
        targets = [c for c in self.companies
                   if c["kind"] == "supplier" and c["local"]][:24]
        for c in targets:
            forms = []
            full = c["name"]
            forms.append(full.replace("重庆", "重庆市", 1))
            if full.endswith("有限公司"):
                forms.append(full[:-4] + "股份有限公司")
            if "有限公司" in full:
                forms.append("(" + full.replace("重庆", "", 1) + ")")
            forms = [f for f in set(forms) if f != full]
            if not forms:
                continue
            extra.append({
                "company_id": c["company_id"],
                "reg_code": c["reg_code"],
                "name": self.rng.choice(forms),
                "short_name": c["short_name"],
                "local": c["local"],
                "kind": c["kind"],
                "aliases": [],
            })
        # 精铸齿轮再补一条仅靠别名/名称能归并的记录（不带注册代码）。
        extra.append({
            "company_id": "C-NEW-JINGZHU",
            "reg_code": "",
            "name": "精铸齿轮总厂",
            "short_name": "精铸齿轮",
            "local": True,
            "kind": "supplier",
            "aliases": [],
        })
        # 该名称归一化核心不同于"精铸齿轮"，需要别名归并：
        extra[-1]["aliases"] = ["精铸齿轮"]

        links = []
        for lk in self.links:
            links.append({k: v for k, v in lk.items() if not k.startswith("_")})

        return {
            "domain": "motorcycle-supply-resilience",
            "version": 2,
            "sample_id": "sample-350-gear-stop",
            "as_of": NOTIFY_WEEK,
            "companies": self.companies + extra,
            "parts": self.parts,
            "variants": [
                {
                    "variant_id": vid,
                    "platform": platform,
                    "model": model,
                    "version": version,
                    "oem": "陵江机车",
                    "bom": self._bom_for(platform),
                }
                for vid, platform, model, version, _ in VARIANTS
            ],
            "certifications": self.certs,
            "commitments": self.commitments,
            "equipment": self.equipment,
            "sourcing_links": links,
            "events": self.events,
            "measures": self.measures,
            "orders": self.orders,
        }

    def _bom_for(self, platform):
        # 零件适用平台在目录登记时已写入 part_meta，直接据此挂 BOM。
        bom = {}
        for pid, (_, _, platforms) in self.part_meta.items():
            if platform in platforms:
                qty = 2 if pid in ("brake_assembly", "front_fork",
                                   "shock_absorber", "mirror_set") else 1
                bom[pid] = qty
        return bom


def main():
    builder = Builder()
    raw = builder.build()
    out = Path("fixtures/sample_graph.json")
    out.write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    n_companies = len({c["company_id"] for c in raw["companies"]})
    n_records = len(raw["companies"])
    print(f"主体（去重后）: {n_companies}，原始登记记录: {n_records}")
    print(f"零件 {len(raw['parts'])}，车型版本 {len(raw['variants'])}，"
          f"寻源链接 {len(raw['sourcing_links'])}，"
          f"认证 {len(raw['certifications'])}，承诺 {len(raw['commitments'])}，"
          f"订单 {len(raw['orders'])}")
    print(f"事件 {len(raw['events'])}，扶持措施 {len(raw['measures'])}")
    print(f"已写出 {out}")


if __name__ == "__main__":
    main()
