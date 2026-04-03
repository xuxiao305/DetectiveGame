# 关键说辞智能提取 — Handoff to CodeExpert v0.1
**移交方**: Architect  
**接收方**: CodeExpert  
**日期**: 2026-04-03  
**版本**: v0.1

---

## 1. 任务目标
实现关键说辞智能提取器，替换 orchestrator.py 中的简单截断逻辑，提升 RoleMemory.recent_claims 的信息密度和可用性。

---

## 2. 已确认约定
- **术语映射**: "编码专家"/"coder" = CodeExpert；"架构师" = Architect
- **不修改接口**: orchestrator.py 的公开方法签名不变
- **新增模块**: `src/interrogation_mvp/claim_extractor.py`（独立可测试）
- **回归测试**: 现有单元测试必须全部通过
- **字数上限**: 提取结果不超过 80 字（与当前截断一致）

---

## 3. 当前问题
### 简单截断的局限
```python
# orchestrator.py L117（当前实现）
claim_entry = f"R{next_round}: {claim_text[:80]}"  # 暴力截断
```

**问题场景**：
```
嫌疑人回答（150字）：
"警官您误会了，我那天晚上根本没有出门。您说的什么河边，我从来没去过。
我当时在家里看电视，大概9点多就睡了。第二天早上7点起床去公司，
张三可以给我作证，我们一起吃的早餐。至于您说的手机定位，可能是我老婆拿了我手机出去买东西吧。"

截断后（80字）：
"警官您误会了，我那天晚上根本没有出门。您说的什么河边，我从来没去过。
我当时在家里看电视，大概9点多就睡了。第二天早上7点起床去公..."

丢失的关键信息：
❌ "张三可以作证"（人证）
❌ "一起吃的早餐"（时间细节）  
❌ "手机可能是老婆拿的"（关键辩解）
```

**影响**：
- 侦探在后续回合看不到完整的历史承诺
- 无法有效追问"张三否认了，你怎么解释？"
- 嫌疑人可能自相矛盾但未被系统捕获

---

## 4. 架构设计

### 模块划分
```
src/interrogation_mvp/
├── claim_extractor.py（新增）
│   └── ClaimExtractor 类
│       ├── extract_key_claims(text, max_chars) → str
│       ├── _score_sentence(sent) → int
│       └── TIME_PATTERNS / PLACE_PATTERNS（正则常量）
│
├── orchestrator.py（修改）
│   └── run_turn() 中调用 ClaimExtractor
│
└── tests/
    └── test_claim_extractor.py（新增）
```

### 提取策略：正则 + 启发式排序
**核心思路**：
1. 按句切分嫌疑人回答（以 `。！？` 为分隔符）
2. 为每句打分，优先保留"高价值句"
3. 高价值特征：
   - 含时间词（+3 分）：`点|分|早上|晚上|中午|凌晨|\d+月\d+日|当天|那天`
   - 含地点词（+3 分）：`在家|河边|公司|路上|店里|车上|房间`
   - 含人名（+2 分）：`[张李王刘陈]\w{1,3}`（2-4 字中文名）
   - 含断言词（+2 分）：`没有|从来|一直|根本|确实|可以作证`
4. 按分数降序排列，依次拼接直到达到 max_chars

**示例输出**：
```python
输入：
"警官您误会了，我那天晚上根本没有出门。您说的什么河边，我从来没去过。
我当时在家里看电视，大概9点多就睡了。第二天早上7点起床去公司，
张三可以给我作证，我们一起吃的早餐。"

输出（80字内）：
"我那天晚上根本没有出门 | 大概9点多就睡了 | 张三可以给我作证 | 第二天早上7点起床去公司"
```

---

## 5. 实现要求

### ClaimExtractor 类（claim_extractor.py）

```python
"""关键说辞提取器，从长文本中提取时间、地点、人证等关键承诺。"""

import re
from typing import List, Tuple


class ClaimExtractor:
    """
    从嫌疑人回答中提取关键承诺句，优先保留含时间、地点、人名、断言的句子。
    
    设计意图：
    - 替换简单截断，提升 RoleMemory.recent_claims 的信息密度
    - 使用正则匹配 + 启发式评分，避免引入 LLM 调用成本
    - 可独立测试，后续可替换为更复杂的提取策略
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
```

### orchestrator.py 调用改动

**修改位置**: `run_turn()` 方法中更新 RoleMemory 的部分（当前 L117-124）

```python
# orchestrator.py

from .claim_extractor import ClaimExtractor

class Orchestrator:
    def __init__(
        self,
        llm_gateway: LLMGateway,
        prompt_composer: PromptComposer,
        detector: ContradictionDetector,
        guard: GuardRails,
    ) -> None:
        self._llm = llm_gateway
        self._prompt = prompt_composer
        self._detector = detector
        self._guard = guard
        self._claim_extractor = ClaimExtractor()  # ← 新增
    
    def run_turn(self, state: GameState, evidence_id: str = "") -> TurnResult:
        # ...（前面逻辑不变）...
        
        state.turns.append(turn)
        state.round_index = next_round

        # ── 更新角色记忆（改进版）──
        claim_text = turn.suspect_answer.strip()
        if claim_text:
            # 智能提取关键承诺（替换原有的简单截断）
            extracted = self._claim_extractor.extract_key_claims(claim_text, max_chars=80)
            claim_entry = f"R{next_round}: {extracted}"
            
            state.suspect_memory.recent_claims.append(claim_entry)
            state.detective_memory.recent_claims.append(claim_entry)
            
            # 上限控制：只保留最近 10 条
            if len(state.suspect_memory.recent_claims) > 10:
                state.suspect_memory.recent_claims = state.suspect_memory.recent_claims[-10:]
            if len(state.detective_memory.recent_claims) > 10:
                state.detective_memory.recent_claims = state.detective_memory.recent_claims[-10:]
        
        # ...（后续逻辑不变）...
```

---

## 6. 单元测试要求

### test_claim_extractor.py

```python
"""单元测试：ClaimExtractor 关键说辞提取"""

import unittest
from interrogation_mvp.claim_extractor import ClaimExtractor


class ClaimExtractorTest(unittest.TestCase):
    def setUp(self):
        self.extractor = ClaimExtractor()
    
    def test_short_text_unchanged(self):
        """短文本（<80字）直接返回"""
        text = "我那天晚上在家里看电视。"
        result = self.extractor.extract_key_claims(text, max_chars=80)
        self.assertEqual(result, text)
    
    def test_extract_time_and_place(self):
        """提取含时间、地点的高价值句"""
        text = "警官您误会了。我那天晚上根本没有出门。大概9点多就睡了。在家里看电视。"
        result = self.extractor.extract_key_claims(text, max_chars=80)
        # 期望：优先保留含时间/地点/断言的句子
        self.assertIn("9点多", result)
        self.assertIn("在家里", result)
        self.assertIn("根本没有出门", result)
    
    def test_extract_witness_name(self):
        """提取含人证的句子"""
        text = "我当时在公司加班。张三可以给我作证。我们一起吃的晚饭。"
        result = self.extractor.extract_key_claims(text, max_chars=80)
        self.assertIn("张三", result)
        self.assertIn("作证", result)
    
    def test_fallback_to_truncation_when_no_valid_sentence(self):
        """无有效句时降级为简单截断"""
        text = "嗯。啊。这个。那个。" * 30  # 全是无意义短句
        result = self.extractor.extract_key_claims(text, max_chars=80)
        self.assertLessEqual(len(result), 80)
    
    def test_respects_max_chars_limit(self):
        """确保输出不超过字数上限"""
        text = "我在家里看电视。" * 20
        result = self.extractor.extract_key_claims(text, max_chars=50)
        self.assertLessEqual(len(result), 50)
    
    def test_score_sentence_with_multiple_features(self):
        """测试评分逻辑"""
        # 含时间+地点+断言 = 3+3+2 = 8分
        high_score_sent = "我那天晚上在家里根本没有出门"
        score_high = self.extractor._score_sentence(high_score_sent)
        
        # 无特征 = 0分
        low_score_sent = "警官您好"
        score_low = self.extractor._score_sentence(low_score_sent)
        
        self.assertGreater(score_high, score_low)


if __name__ == "__main__":
    unittest.main()
```

---

## 7. 验收标准

### 功能正确性
- ✅ 短文本（<80字）直接返回原文
- ✅ 长文本优先保留含时间、地点、人名、断言的句子
- ✅ 输出长度不超过 max_chars
- ✅ 无有效句时降级为简单截断

### 测试覆盖
- ✅ 5 个单元测试全部通过
- ✅ 现有回归测试（tests/test_llm_gateway.py 等）全部通过
- ✅ 手动烟雾测试：跑 3-5 轮对话，观察 claim 提取效果

### 代码质量
- ✅ 符合项目代码规范（类型注解、docstring）
- ✅ ClaimExtractor 独立可测试，无外部依赖
- ✅ 正则模式可配置（后续可调优）

---

## 8. 未决问题（供后续优化）

1. **正则规则调优**
   - 当前 NAME_PATTERNS 假设姓氏在列表中，可能遗漏冷门姓氏
   - 可根据实测效果增加地点词库（如"超市""医院""银行"）

2. **混合策略**
   - 若简单正则不够准确，可在 >150 字时调用 LLM 提炼
   - 需评估成本（每轮增加 1 次 LLM 调用）

3. **多语言支持**
   - 当前正则针对中文，若需支持英文需调整分句逻辑

---

## 9. 相关文档
- **上游架构审查**: [role_memory_ui_implementation_review_handoff_to_architect_v0.1.md](./role_memory_ui_implementation_review_handoff_to_architect_v0.1.md)
- **角色边界修复**: [role_boundary_fix_handoff_to_codeexpert_v0.1.md](./role_boundary_fix_handoff_to_codeexpert_v0.1.md)
- **实现文件**: [orchestrator.py](../../src/interrogation_mvp/orchestrator.py)

---

## 10. 禁止事项
- ❌ 不得修改 orchestrator.py 的公开接口签名
- ❌ 不得改变 RoleMemory 数据结构
- ❌ 不得引入外部 NLP 依赖库（保持轻量）
- ❌ 不得在提取过程中调用 LLM（方案 A 仅用正则）
