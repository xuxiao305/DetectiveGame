"""关键说辞提取器，从长文本中提取时间、地点、人证等关键承诺。

设计意图：
- 替换简单截断，提升 RoleMemory.recent_claims 的信息密度
- 使用正则匹配 + 启发式评分，避免引入 LLM 调用成本
- 可独立测试，后续可替换为更复杂的提取策略
"""

from __future__ import annotations

import re
from typing import List, Tuple


class ClaimExtractor:
    """
    从嫌疑人回答中提取关键承诺句，优先保留含时间、地点、人名、断言的句子。
    """

    # 时间特征（权重 3）
    TIME_PATTERNS = r'(点|分|早上|晚上|中午|凌晨|\d+月\d+日|当天|那天|昨天|今天)'

    # 地点特征（权重 3）
    PLACE_PATTERNS = r'(在家|河边|公司|路上|店里|车上|房间|现场|附近)'

    # 人名特征（权重 2）
    # 中文姓氏 + 1-3字名字，或英文名
    NAME_PATTERNS = r'([张李王刘陈杨赵黄周吴]\w{1,3}|[A-Z][a-z]+)'

    # 断言特征（权重 2）
    ASSERTION_PATTERNS = r'(没有|从来|一直|根本|确实|可以作证|保证|肯定|绝对|从未)'

    def extract_key_claims(self, text: str, max_chars: int = 80) -> str:
        """
        从长文本中提取关键承诺句。

        Args:
            text: 嫌疑人原始回答
            max_chars: 提取结果的最大字数

        Returns:
            提取的关键句，多句用 " | " 连接
            若无高价值句，降级为简单截断
        """
        # 0. 短文本直接返回（避免切句丢失标点）
        if len(text) <= max_chars:
            return text

        # 1. 切句
        sentences = self._split_sentences(text)

        # 2. 评分
        scored: List[Tuple[int, str]] = []
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 5:  # 过滤无意义短句
                continue
            score = self._score_sentence(sent)
            scored.append((score, sent))

        # 3. 降级处理：无有效句时直接截断
        if not scored:
            return text[:max_chars]

        # 4. 按分数降序排序
        scored.sort(reverse=True, key=lambda x: x[0])

        # 5. 贪心拼接（优先取高分句，直到达到字数上限）
        result: List[str] = []
        current_len = 0

        for score, sent in scored:
            # 预估拼接后长度（含分隔符 " | "）
            needed = len(sent) + (3 if result else 0)
            if current_len + needed <= max_chars:
                result.append(sent)
                current_len += needed
            # 达到 90% 容量即可停止（避免浪费低分句）
            if current_len >= max_chars * 0.9:
                break

        return " | ".join(result) if result else text[:max_chars]

    def _split_sentences(self, text: str) -> List[str]:
        """按中文句号、问号、感叹号切分句子"""
        return [s.strip() for s in re.split(r'[。！？]', text) if s.strip()]

    def _score_sentence(self, sent: str) -> int:
        """
        为句子打分，含关键特征的句子分数更高。

        评分规则：
        - 时间词：+3 分
        - 地点词：+3 分
        - 人名：+2 分
        - 断言词：+2 分
        """
        score = 0
        if re.search(self.TIME_PATTERNS, sent):
            score += 3
        if re.search(self.PLACE_PATTERNS, sent):
            score += 3
        if re.search(self.NAME_PATTERNS, sent):
            score += 2
        if re.search(self.ASSERTION_PATTERNS, sent):
            score += 2
        return score
