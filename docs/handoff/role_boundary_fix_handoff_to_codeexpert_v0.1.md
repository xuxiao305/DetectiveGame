# 角色边界与输出约束修复方案 — Handoff to CodeExpert v0.1

## 任务目标

解决两个核心缺陷：
1. **角色错位**：侦探替嫌疑人说话、输出分析框架而非直接提问
2. **单次调用多轮循环**：模型在一次生成中反复自问自答导致 token 耗尽

## 已确认约定

- 修改范围限于 `src/interrogation_mvp/llm_gateway.py` 和 `src/interrogation_mvp/prompt_composer.py`
- 不改动 `models.py`、`controller.py`、`orchestrator.py` 的接口签名
- 改动后现有单元测试 `tests/test_llm_gateway.py` 必须全部通过
- 文件开头已有的说明注释需保留并按需更新

## 术语映射

| 术语 | 含义 |
|---|---|
| System Prompt | `_system_prompt()` 返回的系统指令文本 |
| User Prompt | `_build_user_text()` 返回的用户指令文本 |
| 后置清洗 | `_normalize_output()` 内对 speech 的文本校验与截断 |
| 角色错位 | 侦探输出中包含嫌疑人台词，或嫌疑人输出中包含侦探台词 |
| 多轮循环 | 单次 LLM 调用中模型自行生成多轮问答导致内容重复膨胀 |

## 根因分析

三个薄弱层叠加导致问题：

```
LLM 输入                              LLM 输出
┌─────────────┐                      ┌─────────────────┐
│ System Prompt│──缺角色锁定──────→   │ 角色错位         │
│  (层1)       │  缺字数限制          │ 自言自语         │
├─────────────┤                      │ 分析框架代替提问  │
│ User Prompt  │──缺身份隔离指令──→   │                  │
│  (层2)       │  缺对话对象明示      │ 多轮循环生成      │
├─────────────┤                      │                  │
│ 后置清洗     │──无──────────────→   │ 脏数据直接输出    │
│  (层3)       │                      └─────────────────┘
└─────────────┘
```

## 修复方案：三层防御

### 层1：强化 System Prompt（`_system_prompt()`）

**文件**：`src/interrogation_mvp/llm_gateway.py`

**改动**：替换 `_system_prompt()` 方法体

**设计意图**：
- 用编号规则而非自然段落描述约束，降低模型忽略率
- 加入字数硬限（speech ≤ 100 字，thought ≤ 50 字）
- 加入**正确示例**和**错误示例**（negative example 对小模型纠偏效果最强）
- 显式禁止元叙述（"作为XX我会……"）和跨角色扮演

**目标输出**：

```python
def _system_prompt(self) -> str:
    return (
        "你是审讯对话引擎。严格遵守以下规则：\n"
        '1. 只输出一个JSON对象，格式：{"thought":"...","speech":"...","anchors":"..."}\n'
        "2. speech 是你这个角色说出口的一句话，必须直接对对方说，不超过100字\n"
        "3. 禁止在 speech 中扮演对方角色，禁止出现对方的名字+冒号+对方台词\n"
        "4. 禁止输出多轮对话、分析框架、编号列表、审讯计划\n"
        '5. 禁止输出"作为XX我会……"这类元叙述，直接说话\n'
        "6. thought 是内心独白，不超过50字\n"
        '正确示例：{"thought":"他的时间线有破绽","speech":"你说11点在家，但邻居听到你开车出去了，怎么解释？","anchors":"时间线矛盾"}\n'
        '错误示例：{"speech":"作为侦探陈明远，我会首先询问……1.时间线 2.地点"}\n'
        '错误示例：{"speech":"李建国：警官您搞错了……陈明远：请你解释……"}'
    )
```

### 层2：强化 User Prompt（`_build_user_text()`）

**文件**：`src/interrogation_mvp/llm_gateway.py`

**改动**：在 `_build_user_text()` 开头注入角色隔离指令

**设计意图**：
- 明确告诉模型"你是谁"和"你在对谁说话"
- 侦探 prompt 强调"直接提问"，嫌疑人 prompt 强调"直接回答"
- 把角色身份放在 user prompt 最前面，确保模型优先看到

**目标输出**：

```python
def _build_user_text(self, role: str, prompt: Dict[str, str]) -> str:
    character_name = prompt.get("character_name", "")

    if role == "detective":
        role_instruction = (
            f"【你的身份】你是侦探{character_name}，正在审讯嫌疑人。\n"
            f"【输出要求】直接对嫌疑人说一句提问，不要自言自语，"
            f"不要替嫌疑人回答，不要输出分析计划。\n"
        )
    else:
        role_instruction = (
            f"【你的身份】你是嫌疑人{character_name}，正在被侦探审讯。\n"
            f"【输出要求】直接回答侦探的问题，只说一句话或一段话，"
            f"不要替侦探提问，不要自问自答。\n"
        )

    # ... 拼装其余字段（case_name, background, etc.），role_instruction 置顶 ...
    parts = [
        role_instruction,
        f"案件:{case_name}" if case_name else "",
        # ... 其余字段不变 ...
    ]
    return "\n".join(p for p in parts if p)
```

### 层3：后置清洗（`_normalize_output()` + 新增 `_clean_speech()`）

**文件**：`src/interrogation_mvp/llm_gateway.py`

**改动**：
1. 在 `_normalize_output()` 中对 `speech` 调用新的 `_clean_speech()` 方法
2. 新增 `_clean_speech()` 和 `_dedup_repeating_blocks()` 两个私有方法

**设计意图**：
- 即使模型违反 prompt 约束，仍能在输出层兜底
- 四道清洗规则按优先级依次执行：去元叙述前缀 → 去跨角色台词 → 去编号列表 → 去循环重复
- 最终硬截断 150 字，防止 token 爆炸的残留文本流入对话历史

**目标输出**：

```python
def _clean_speech(self, text: str) -> str:
    """后置清洗：去除角色错位、多轮循环、分析框架"""
    # 1. 去掉"作为XX，我会……"元叙述前缀
    text = re.sub(r'^作为\S{1,10}[，,]?\s*(我会|我将|我要|我需要).*?[，。,\.]\s*', '', text)
    # 2. 去掉"姓名：台词"格式的跨角色台词行
    text = re.sub(r'\n?\S{2,5}[：:].+', '', text)
    # 3. 去掉"1. xxx："编号列表
    text = re.sub(r'\d+\.\s*\S+[：:].+', '', text)
    # 4. 去重复循环块
    text = self._dedup_repeating_blocks(text)
    # 5. 硬截断 150 字
    text = text.strip()
    if len(text) > 150:
        text = text[:147] + "……"
    return text

def _dedup_repeating_blocks(self, text: str) -> str:
    """检测并去除重复循环块，只保留首次出现"""
    lines = text.strip().split('\n')
    if len(lines) <= 2:
        return text
    seen: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in seen:
            break  # 循环开始，截断后续
        seen.append(stripped)
    return '\n'.join(seen)
```

**调用点**：在 `_normalize_output()` 中，speech 解析完成后立即调用：

```python
def _normalize_output(self, payload: Any) -> GeneratedRoleOutput:
    # ... 现有解析逻辑提取 thought / speech / anchors ...

    speech = self._clean_speech(speech)  # ← 新增这一行

    if not speech:
        raise ValueError("Model output normalization failed: speech is empty")
    # ... 后续不变 ...
```

### 层4：跨回合上下文结构化（`build_context()` + `PromptContext`）

**文件**：`src/interrogation_mvp/prompt_composer.py`

**当前做法的问题**：

```
当前 history 传递方式：
R3:侦探问[你当晚几点出门？…] 嫌疑人答[我9点多就睡下了…]
R4:侦探问[邻居说听到你开车…] 嫌疑人答[可能听错了吧…]
R5:侦探问[受害者手机显示…]  嫌疑人答[我没见过受害者…]

问题：
- 侦探只看最近 3 轮，嫌疑人只看最近 2 轮，早期说辞完全丢失
- 截断到 60 字的摘要只保留了表面内容，关键承诺被截掉
- 模型需要在混杂的问答流中自己提炼哪些是对方已承诺的说辞
- 到后期回合，嫌疑人容易说出与早期矛盾的话，但侦探看不到早期记录也无法追问
```

**设计意图**：
- 将关键说辞从对话历史中提炼出来，形成结构化的"已承诺说辞列表"
- 这个列表作为硬约束显式注入 prompt 最前部，模型不需要在长文中自己搜索
- 侦探看到的是"嫌疑人已承诺的说辞"（用于发现矛盾和追问）
- 嫌疑人看到的是"自己已承诺的说辞"（用于保持一致性，不自相矛盾）

**改动**：

1. `PromptContext` 新增字段 `suspect_claims: List[str]`
2. `build_context()` 从历史对话中提取嫌疑人的关键说辞
3. `build_detective_prompt()` 和 `build_suspect_prompt()` 将说辞列表注入 prompt

**目标输出**：

```python
# prompt_composer.py

@dataclass
class PromptContext:
    round_index: int
    case_data: CaseData
    recent_turn_summaries: List[str]
    pending_evidence_text: Optional[str]
    contradiction_count: int
    suspect_claims: List[str]       # ← 新增：嫌疑人已承诺的关键说辞


def build_context(state: GameState, pending_evidence_text: Optional[str]) -> PromptContext:
    summaries = [
        f"R{turn.round_index}:侦探问[{_truncate(turn.detective_question)}] 嫌疑人答[{_truncate(turn.suspect_answer)}]"
        for turn in state.turns
    ]
    # 提取嫌疑人每轮的核心说辞（截断但保留关键信息）
    suspect_claims = [
        f"R{turn.round_index}: {_truncate(turn.suspect_answer, max_chars=80)}"
        for turn in state.turns
        if turn.suspect_answer.strip()
    ]
    return PromptContext(
        round_index=state.round_index + 1,
        case_data=state.case_data,
        recent_turn_summaries=summaries,
        pending_evidence_text=pending_evidence_text,
        contradiction_count=len(state.contradictions),
        suspect_claims=suspect_claims,
    )
```

**Prompt 注入方式**：

```python
# build_detective_prompt() 中新增字段
def build_detective_prompt(self, context: PromptContext) -> Dict[str, str]:
    # ...现有逻辑...
    claims_text = "\n".join(context.suspect_claims) if context.suspect_claims else "暂无"
    return {
        # ...现有字段...
        "suspect_claims": claims_text,   # ← 新增
    }

# build_suspect_prompt() 中新增字段
def build_suspect_prompt(self, context, detective_question="") -> Dict[str, str]:
    # ...现有逻辑...
    claims_text = "\n".join(context.suspect_claims) if context.suspect_claims else "暂无"
    return {
        # ...现有字段...
        "my_previous_claims": claims_text,   # ← 新增
    }
```

**在 `_build_user_text()` 中渲染**（`llm_gateway.py`）：

```python
# 侦探视角
"【嫌疑人已承诺的说辞 - 注意矛盾】\n" + prompt.get("suspect_claims", "暂无")

# 嫌疑人视角
"【你之前说过的话 - 不可自相矛盾】\n" + prompt.get("my_previous_claims", "暂无")
```

**预期效果**：

模型在第 10 轮收到的 prompt 不再只有最近 2-3 轮的模糊摘要，而是：

```
【你之前说过的话 - 不可自相矛盾】
R1: 当晚9点多就睡下了
R3: 张三可以作证我在家
R5: 没有见过受害者
R7: 那天晚上根本没出过门
R9: 手机可能是忘在车上了

案件:深夜的河边
背景:受害者王某于晚11点被发现死于河边……
警官提问:你说没出过门，但你手机定位在河边，怎么解释？
历史: R8:侦探问[...] 嫌疑人答[...] | R9:侦探问[...] 嫌疑人答[...]
```

## 四层协同关系

```
请求阶段                                        响应阶段
┌──────────────────────────────────┐           ┌──────────────────┐
│ 层1: System Prompt               │           │                  │
│ 约束模型行为规则（格式、字数）     │           │ 层3: 后置清洗     │
│                                  │──LLM──→  │ 兜底过滤脏输出     │
│ 层2: User Prompt                 │           │                  │
│ 注入角色身份隔离（你是谁、对谁说） │           └──────────────────┘
│                                  │
│ 层4: 结构化上下文                 │
│ 注入已承诺说辞列表（跨回合记忆）   │
└──────────────────────────────────┘
```

| 层次 | 防御对象 | 失效场景 | 下一层兜底 |
|---|---|---|---|
| 层1 System Prompt | 大部分格式违规 | 小模型忽略系统指令 | 层2 重复强调 |
| 层2 User Prompt | 角色身份混淆 | 模型仍跑偏 | 层3 后置截断 |
| 层3 后置清洗 | 所有残留问题 | 清洗规则未覆盖的新模式 | 人工观察日志补充规则 |
| 层4 结构化上下文 | 跨回合说辞遗忘、自相矛盾 | 提取的说辞不够精准 | 矛盾检测器仍可事后捕获 |

## 未决问题

1. `_clean_speech()` 中"姓名：台词"的正则 `\S{2,5}` 假设姓名长度 2-5 字，如果角色名超出范围需要调整
2. 硬截断 150 字可能截断合理的长回答——是否需要根据 role 分别设限（侦探提问 ≤ 100，嫌疑人回答 ≤ 150）
3. 如果清洗后 speech 变空，当前会触发 ValueError 走 fallback——这是期望行为还是需要更优雅的降级
4. 层4 的说辞提取目前是直接截断嫌疑人原文，后续是否需要用更智能的方式提炼关键承诺（如只保留含时间、地点、人名的句子）
5. 说辞列表随回合增长会占用越来越多 token，是否需要设上限（如只保留最重要的 8-10 条）

## 相关文档

- 已有架构审查：`docs/handoff/architect_review_local_deepseek_v0.2.md`
- 上一版实现 handoff：`docs/handoff/mvp_interrogation_handoff_to_codeexpert_v0.2.md`
- 问题 Log：`logs/session_20260403_011847.log`

## 禁止事项

- 不得修改 `models.py` 中 `GameState`、`DialogueTurn` 等数据结构
- 不得改变 `orchestrator.py` 中的调用流程和时序
- 不得移除现有的 `_extract_json_from_text()` JSON 救回逻辑
- 不得删除 `_sanitize_model_text()` 中的 think-tag 清理功能
- 后置清洗不得修改 `thought` 和 `anchors` 字段，只处理 `speech`
