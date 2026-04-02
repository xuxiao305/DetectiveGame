"""Core domain models for the InterrogationRoom MVP runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class SessionStatus(str, Enum):
    INIT = "INIT"
    RUNNING = "RUNNING"
    SOFT_LIMIT = "SOFT_LIMIT"
    HARD_LIMIT = "HARD_LIMIT"
    ENDED = "ENDED"


@dataclass
class RoleMemory:
    immutable_facts: List[str] = field(default_factory=list)
    recent_claims: List[str] = field(default_factory=list)
    strategy_notes: List[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class ContradictionItem:
    id: str
    category: str
    description: str
    round_index: int
    related_round_indexes: List[int]
    severity: str


@dataclass
class DialogueTurn:
    round_index: int
    detective_thought: str
    detective_question: str
    suspect_thought: str
    suspect_answer: str
    injected_evidence_id: Optional[str] = None
    new_contradictions: List[str] = field(default_factory=list)
    detective_source: str = ""
    suspect_source: str = ""


@dataclass
class EvidenceItem:
    evidence_id: str
    title: str
    content: str


@dataclass
class CaseData:
    case_name: str
    background: str
    detective_name: str
    suspect_name: str
    suspect_truth: List[str]
    suspect_lie: List[str]
    detective_known: List[str]
    evidence_items: List[EvidenceItem]


@dataclass
class GameState:
    session_id: str
    status: SessionStatus
    round_index: int
    round_limit_soft: int
    round_limit_hard: int
    detective_memory: RoleMemory
    suspect_memory: RoleMemory
    pending_evidence_ids: List[str] = field(default_factory=list)
    used_evidence_ids: List[str] = field(default_factory=list)
    contradictions: List[ContradictionItem] = field(default_factory=list)
    turns: List[DialogueTurn] = field(default_factory=list)
    case_data: Optional[CaseData] = None
