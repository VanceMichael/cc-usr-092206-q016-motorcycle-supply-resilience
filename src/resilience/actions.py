"""图谱上的业务动作：目前实现零部件企业在线确认产能承诺。

承诺在 confirmed=False 时只是草案，时效快照会把该链接判为不可用；
供应商在线确认后，整车企业的断供模拟立即把该备选纳入可用产能池。
"""

from .graph import Graph


class ConfirmationError(ValueError):
    pass


def confirm_commitment(graph: Graph, commitment_id: str, *,
                       supplier_id: str | None = None) -> dict:
    """由所属供应商把承诺标记为已在线确认。

    返回确认后的承诺摘要；supplier_id 给定时校验调用方身份，
    防止一家企业确认另一家的承诺。
    """
    if commitment_id not in graph.commitments:
        raise ConfirmationError(f"承诺不存在: {commitment_id}")
    commitment = graph.commitments[commitment_id]
    if supplier_id is not None and commitment.company_id != supplier_id:
        raise ConfirmationError(
            "只能由承诺所属企业确认："
            f"{commitment_id} 属于 {commitment.company_id}"
        )
    commitment.confirmed = True
    return {
        "commitment_id": commitment.commitment_id,
        "company_id": commitment.company_id,
        "part_id": commitment.part_id,
        "capacity_per_week": commitment.capacity_per_week,
        "confirmed": commitment.confirmed,
    }
