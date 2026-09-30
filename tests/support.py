"""测试用小型图谱工厂：手工搭建可精确断言的供应网络。"""

from src.resilience import build_graph


def make_raw():
    """三平台共用齿轮的小网络，含主供与四类备选。"""
    companies = [
        {"company_id": "OEMA", "reg_code": "R-OEMA", "name": "甲整车有限公司",
         "short_name": "甲整车", "local": True, "kind": "oem"},
        {"company_id": "OEMB", "reg_code": "R-OEMB", "name": "乙整车有限公司",
         "short_name": "乙整车", "local": True, "kind": "oem"},
        {"company_id": "P", "reg_code": "R-P", "name": "主城齿轮有限公司",
         "short_name": "主城齿轮", "local": True},
        {"company_id": "A1", "reg_code": "R-A1", "name": "本地甲配有限公司",
         "short_name": "本地甲配", "local": True},
        {"company_id": "A2", "reg_code": "R-A2", "name": "试制乙配有限公司",
         "short_name": "试制乙配", "local": True},
        {"company_id": "A3", "reg_code": "R-A3", "name": "待确认丙配有限公司",
         "short_name": "待确认丙配", "local": True},
        {"company_id": "N1", "reg_code": "R-N1", "name": "远地外源配件股份有限公司",
         "short_name": "远地外源", "local": False},
        {"company_id": "CTL", "reg_code": "R-CTL", "name": "电控独源有限公司",
         "short_name": "电控独源", "local": True},
        {"company_id": "EQC", "reg_code": "R-EQC", "name": "认证机构",
         "short_name": "认证机构", "local": True, "kind": "certifier"},
    ]
    parts = [
        {"part_id": "gear", "name": "共用齿轮", "category": "齿轮",
         "critical": True},
        {"part_id": "controller", "name": "电控", "category": "电控"},
    ]
    variants = [
        {"variant_id": "VF", "platform": "fuel", "model": "燃", "version": "1",
         "oem": "甲整车", "bom": {"gear": 1}},
        {"variant_id": "VE", "platform": "electric", "model": "电", "version": "1",
         "oem": "甲整车", "bom": {"gear": 1, "controller": 1}},
        {"variant_id": "VO", "platform": "offroad", "model": "越", "version": "1",
         "oem": "甲整车", "bom": {"gear": 1}},
        {"variant_id": "VF2", "platform": "fuel", "model": "燃二", "version": "1",
         "oem": "乙整车", "bom": {"gear": 1}},
    ]

    def cert(cid, company, part="gear", status="mass", frm="2025-01-01",
             variants=("VF", "VE", "VO", "VF2")):
        return [
            {"cert_id": f"{cid}-{v}", "company": company, "part_id": part,
             "variant_id": v, "status": status, "valid_from": frm}
            for v in variants
        ]

    certifications = (
        cert("K-P", "主城齿轮")
        + cert("K-A1", "本地甲配")
        + cert("K-A2", "试制乙配", status="trial", frm="2026-08-01")
        + cert("K-A3", "待确认丙配")
        + cert("K-N1", "远地外源", variants=("VF", "VE", "VO", "VF2"))
        + cert("K-CTL", "电控独源", part="controller",
               variants=("VE",))
    )

    def commit(mid, company, part, cap, price, *, confirmed=True, lead=7,
               frm="2025-01-01", to=None):
        m = {"commitment_id": mid, "company": company, "part_id": part,
             "capacity_per_week": cap, "price": price, "currency": "CNY",
             "lead_time_days": lead, "confirmed": confirmed,
             "valid_from": frm}
        if to:
            m["valid_to"] = to
        return m

    commitments = [
        commit("M-P", "主城齿轮", "gear", 60, 100),
        commit("M-A1", "本地甲配", "gear", 50, 110, lead=7),
        commit("M-A2", "试制乙配", "gear", 80, 105, lead=14),
        commit("M-A3", "待确认丙配", "gear", 80, 108, confirmed=False, lead=7),
        commit("M-N1", "远地外源", "gear", 200, 150, lead=21),
        commit("M-CTL", "电控独源", "controller", 500, 300),
    ]
    sourcing_links = [
        {"link_id": "L-P", "part_id": "gear", "supplier": "主城齿轮",
         "role": "primary", "cert_ids": [c["cert_id"] for c in certifications if c["company"] == "主城齿轮"],
         "commitment_ids": ["M-P"], "lead_time_days": 7, "candidate_for": []},
    ]
    alts = [
        ("L-A1", "本地甲配", "M-A1", 30000),
        ("L-A2", "试制乙配", "M-A2", 60000),
        ("L-A3", "待确认丙配", "M-A3", 20000),
        ("L-N1", "远地外源", "M-N1", 120000),
    ]
    for lid, sup, mid, switch in alts:
        sourcing_links.append({
            "link_id": lid, "part_id": "gear", "supplier": sup,
            "role": "alternate",
            "cert_ids": [c["cert_id"] for c in certifications if c["company"] == sup],
            "commitment_ids": [mid], "lead_time_days": next(
                c["lead_time_days"] for c in commitments if c["commitment_id"] == mid
            ),
            "candidate_for": ["L-P"], "switch_cost": switch,
        })
    sourcing_links.append({
        "link_id": "L-CTL", "part_id": "controller", "supplier": "电控独源",
        "role": "primary",
        "cert_ids": ["K-CTL-VE"], "commitment_ids": ["M-CTL"],
        "lead_time_days": 7, "candidate_for": [],
    })
    return {
        "domain": "motorcycle-supply-resilience",
        "version": 2,
        "sample_id": "unit-mini",
        "as_of": "2026-09-28",
        "companies": companies,
        "parts": parts,
        "variants": variants,
        "certifications": certifications,
        "commitments": commitments,
        "equipment": [],
        "sourcing_links": sourcing_links,
        "events": [],
        "measures": [],
        "orders": [],
    }


def make_graph(raw=None):
    return build_graph(raw or make_raw())


def order(oid, variant, qty, week):
    return {"order_id": oid, "variant_id": variant, "quantity": qty,
            "due_week": week, "customer_segment": "domestic"}
