"""主体归并：消除同一企业的多个名称。

同一社会信用代码即视为同一主体；显式别名与归一化名称用于在没有代码、
或来源材料只给名称时再次收敛。所有下游对象只持有规范主体 id。
"""

import re
from dataclasses import dataclass, field

from .timeutil import as_date

# 名称归一化时统一去掉的地区前缀与组织形式后缀。
_REGION_PREFIX = (
    "重庆市", "重庆", "两江新区", "渝北区", "江北区", "九龙坡区", "巴南区",
    "大渡口区", "沙坪坝区", "璧山区", "江津区", "永川区",
)
_COMPANY_SUFFIX = (
    "股份有限公司", "有限责任公司", "集团有限公司", "有限公司", "股份公司", "集团", "公司",
)
# 名称里需要剥离的标点与空白。
_PUNCT = re.compile(r"[\s·・()（）\-—_./、,，]+")


def normalize_name(name: str) -> str:
    """把各种写法归一到可比较的核心名称。

    例： "重庆精铸齿轮有限公司" 与 "（重庆）精铸齿轮股份有限公司" 都归到 "精铸齿轮"。
    """
    text = _PUNCT.sub("", name.strip())
    for prefix in _REGION_PREFIX:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    # 后缀可能套两层（如"集团有限公司"已在元组中按长到短尝试）。
    changed = True
    while changed:
        changed = False
        for suffix in sorted(_COMPANY_SUFFIX, key=len, reverse=True):
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
                changed = True
                break
    return text.lower()


@dataclass
class Company:
    """规范企业主体。"""

    company_id: str
    reg_code: str
    canonical_name: str
    short_name: str
    local: bool
    aliases: list[str] = field(default_factory=list)
    seen_as: list[str] = field(default_factory=list)

    @property
    def all_names(self) -> set[str]:
        names = {self.canonical_name, self.short_name, *self.aliases}
        return {n for n in names if n}


@dataclass
class _Staging:
    company: Company
    norm_names: set[str]


class Registry:
    """主体登记表：原始记录进来，规范主体出去。"""

    def __init__(self):
        self._by_id: dict[str, _Staging] = {}
        self._by_reg: dict[str, str] = {}
        self._by_norm: dict[str, str] = {}

    # -- 登记 -------------------------------------------------------------

    def register(
        self,
        records: list[dict],
        strict: bool = False,
    ) -> list[dict]:
        """登记一批企业原始记录，返回每条记录解析出的归并报告。

        每条记录形如：
          {"company_id": "C001", "reg_code": "9150...", "name": "...",
           "short_name": "精铸齿轮", "local": true, "aliases": ["..."]}

        归并依据（按优先级）：相同 reg_code → 相同归一化名称/别名。
        reg_code 为空时仅按名称归并。strict 下冲突的代码/地域属性会报错，
        默认只记录冲突并以先登记记录为准。
        """
        reports = []
        for raw in records:
            reports.append(self._register_one(raw, strict))
        return reports

    def _register_one(self, raw: dict, strict: bool) -> dict:
        name = raw["name"].strip()
        reg_code = (raw.get("reg_code") or "").strip()
        company_id = raw.get("company_id") or (f"C{len(self._by_id) + 1:03d}")
        aliases = [a.strip() for a in raw.get("aliases", []) if a.strip()]
        local = bool(raw.get("local", False))

        target_id = None
        reasons = []
        if reg_code and reg_code in self._by_reg:
            target_id = self._by_reg[reg_code]
            reasons.append("reg_code")

        norm = normalize_name(name)
        if target_id is None and norm in self._by_norm:
            target_id = self._by_norm[norm]
            reasons.append("name")

        for alias in aliases:
            anchor = self._by_norm.get(normalize_name(alias))
            if anchor is not None and target_id is None:
                target_id = anchor
                reasons.append("alias")

        if target_id is None:
            company = Company(
                company_id=company_id,
                reg_code=reg_code,
                canonical_name=name,
                short_name=raw.get("short_name") or name,
                local=local,
                aliases=list(aliases),
                seen_as=[name],
            )
            staging = _Staging(company, {norm})
            self._by_id[company_id] = staging
            if reg_code:
                self._by_reg[reg_code] = company_id
            self._by_norm[norm] = company_id
            for a in aliases:
                self._by_norm.setdefault(normalize_name(a), company_id)
            if raw.get("short_name"):
                self._by_norm.setdefault(
                    normalize_name(raw["short_name"]), company_id
                )
            return {
                "input_name": name,
                "company_id": company_id,
                "action": "created",
                "matched_by": [],
            }

        staging = self._by_id[target_id]
        company = staging.company
        conflicts = []
        if reg_code and company.reg_code and reg_code != company.reg_code:
            conflicts.append(f"reg_code {reg_code} != {company.reg_code}")
        if strict and conflicts:
            raise ValueError(f"主体 {target_id} 归并冲突: {conflicts}")
        if not company.reg_code and reg_code:
            company.reg_code = reg_code
            self._by_reg[reg_code] = target_id

        if name not in company.all_names:
            company.aliases.append(name)
        company.seen_as.append(name)
        staging.norm_names.add(norm)
        self._by_norm.setdefault(norm, target_id)
        for a in aliases:
            na = normalize_name(a)
            if na not in self._by_norm:
                self._by_norm[na] = target_id
                company.aliases.append(a)
            staging.norm_names.add(na)
        return {
            "input_name": name,
            "company_id": target_id,
            "action": "merged",
            "matched_by": reasons,
            "conflicts": conflicts,
        }

    # -- 查询 -------------------------------------------------------------

    def resolve(self, ref: str) -> str:
        """把任意引用（company_id、注册代码、原名、别名）解析为规范 id。"""
        if ref in self._by_id:
            return ref
        if ref in self._by_reg:
            return self._by_reg[ref]
        norm = normalize_name(ref)
        if norm in self._by_norm:
            return self._by_norm[norm]
        if ref in self._by_norm:
            return self._by_norm[ref]
        raise KeyError(f"无法识别的企业引用: {ref}")

    def get(self, ref: str) -> Company:
        return self._by_id[self.resolve(ref)].company

    def companies(self) -> list[Company]:
        return [s.company for s in self._by_id.values()]

    def __len__(self) -> int:
        return len(self._by_id)

    def merge_report(self) -> dict:
        """供数据质量检查：多少原始名称被收敛到了多少主体。"""
        total_names = sum(len(c.seen_as) for c in self.companies())
        return {
            "companies": len(self),
            "raw_records": total_names,
            "duplicates_collapsed": total_names - len(self),
        }


def build_registry(company_records: list[dict], strict: bool = False) -> Registry:
    """从原始企业记录构建登记表。"""
    registry = Registry()
    registry.register(company_records, strict=strict)
    return registry
