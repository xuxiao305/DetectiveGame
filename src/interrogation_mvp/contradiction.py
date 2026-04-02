"""Rule-based contradiction detection for suspect claims."""

from __future__ import annotations

from hashlib import md5
from typing import List, Tuple

from .models import ContradictionItem, GameState


def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(k in text for k in keywords)


HOME_KEYWORDS = ["在家", "回家", "睡了", "入睡"]
OUTSIDE_KEYWORDS = ["出去", "河边", "开车", "买东西", "外面"]
DENY_CONTACT_KEYWORDS = ["没联系", "没有联系", "没打过电话", "不认识", "不熟"]
DENY_FINANCIAL_KEYWORDS = ["没有资金往来", "没有经济纠纷", "没转账", "财务没问题"]


class ContradictionDetector:
    def detect(self, state: GameState, new_answer: str, round_index: int) -> List[ContradictionItem]:
        new_items: List[ContradictionItem] = []
        history_answers = [turn.suspect_answer for turn in state.turns]

        rules_hits = self._run_rules(
            history=history_answers,
            answer=new_answer,
            used_evidence_ids=state.used_evidence_ids,
        )
        for category, description, severity in rules_hits:
            contradiction_id = md5(f"{category}:{description}".encode("utf-8")).hexdigest()[:12]
            existing = next((c for c in state.contradictions if c.id == contradiction_id), None)
            if existing:
                if round_index not in existing.related_round_indexes:
                    existing.related_round_indexes.append(round_index)
                continue
            item = ContradictionItem(
                id=contradiction_id,
                category=category,
                description=description,
                round_index=round_index,
                related_round_indexes=[round_index],
                severity=severity,
            )
            state.contradictions.append(item)
            new_items.append(item)
        return new_items

    def _run_rules(
        self,
        history: List[str],
        answer: str,
        used_evidence_ids: List[str],
    ) -> List[Tuple[str, str, str]]:
        hits: List[Tuple[str, str, str]] = []

        answer_home = _contains_any(answer, HOME_KEYWORDS)
        answer_outside = _contains_any(answer, OUTSIDE_KEYWORDS)

        # Same-turn self-conflict: claims being at home and outside in the same account.
        if answer_home and answer_outside:
            hits.append((
                "LOCATION",
                "同一时段叙述同时包含“在家”与“外出”，地点陈述自冲突。",
                "HIGH",
            ))

        for old in history:
            old_home = _contains_any(old, HOME_KEYWORDS)
            old_outside = _contains_any(old, OUTSIDE_KEYWORDS)

            if old_home and answer_outside:
                hits.append((
                    "ALIBI",
                    "前后陈述对外出与在家状态不一致。",
                    "HIGH",
                ))
            if old_outside and answer_home:
                hits.append((
                    "TIME",
                    "时间线自述出现冲突：既称外出又称固定时段在家。",
                    "MEDIUM",
                ))

        if _contains_any(answer, ["撒了谎", "承认", "吵过"]):
            hits.append((
                "BEHAVIOR",
                "嫌疑人出现阶段性松口，与早期强否认存在行为层冲突。",
                "LOW",
            ))

        # Evidence-aware contradictions.
        if "e1" in used_evidence_ids and _contains_any(answer, ["便利店", "买东西"]):
            hits.append((
                "LOCATION",
                "证据冲突：便利店监控未见其出现，但口供声称外出购物。",
                "HIGH",
            ))
        if "e2" in used_evidence_ids and _contains_any(answer, HOME_KEYWORDS):
            hits.append((
                "ALIBI",
                "证据冲突：邻居证词显示其深夜驾车外出，但口供强调始终在家。",
                "HIGH",
            ))
        if "e3" in used_evidence_ids and _contains_any(answer, DENY_CONTACT_KEYWORDS):
            hits.append((
                "BEHAVIOR",
                "证据冲突：受害者手机显示曾通话，但口供否认接触关系。",
                "MEDIUM",
            ))
        if "e4" in used_evidence_ids and _contains_any(answer, DENY_FINANCIAL_KEYWORDS):
            hits.append((
                "MOTIVE",
                "证据冲突：账户异常转账与口供中的财务否认不一致。",
                "MEDIUM",
            ))

        # Deduplicate within current detection pass.
        dedup = {(c, d, s): (c, d, s) for c, d, s in hits}
        return list(dedup.values())
