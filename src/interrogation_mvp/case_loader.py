"""Load fixed MVP case and create an initial session state."""

from __future__ import annotations

import uuid

from .models import CaseData, EvidenceItem, GameState, RoleMemory, SessionStatus


def load_fixed_case() -> CaseData:
    return CaseData(
        case_name="深夜的河边",
        background=(
            "受害者王某于晚11点被发现死于河边。嫌疑人李建国是受害者合伙人，"
            "双方存在财产纠纷。"
        ),
        detective_name="陈明远",
        suspect_name="李建国",
        suspect_truth=[
            "当晚11点在河边与受害者争执，失手将其推入河中后逃离。",
            "动机与挪用公款证据暴露有关。",
        ],
        suspect_lie=[
            "当晚在家睡觉，11点前已入睡。",
        ],
        detective_known=[
            "死亡时间在晚上10点至12点之间。",
            "李建国手机定位在河边附近。",
        ],
        evidence_items=[
            EvidenceItem("e1", "便利店监控", "当晚该时段无李建国出现记录。"),
            EvidenceItem("e2", "邻居证词", "听到李建国深夜开车出去。"),
            EvidenceItem("e3", "受害者手机", "最后通话记录显示与李建国通话。"),
            EvidenceItem("e4", "银行记录", "李建国账户存在异常转账。"),
        ],
    )


def create_initial_state(round_soft_limit: int = 12, round_hard_limit: int = 15) -> GameState:
    case_data = load_fixed_case()
    return GameState(
        session_id=str(uuid.uuid4()),
        status=SessionStatus.INIT,
        round_index=0,
        round_limit_soft=round_soft_limit,
        round_limit_hard=round_hard_limit,
        detective_memory=RoleMemory(
            immutable_facts=case_data.detective_known.copy(),
            strategy_notes=["围绕时间线、地点、动机、证据持续追问。"],
            summary="初始审讯准备状态。",
        ),
        suspect_memory=RoleMemory(
            immutable_facts=case_data.suspect_lie.copy(),
            strategy_notes=["保持防御，不主动完整认罪。"],
            summary="维持不在场说法并回避关键细节。",
        ),
        case_data=case_data,
    )
