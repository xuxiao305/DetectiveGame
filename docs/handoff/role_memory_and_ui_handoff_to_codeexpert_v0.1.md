# 激活角色记忆 + UI 双视角改版 — Handoff to CodeExpert v0.1

## 任务目标

两项并行改进：

1. **激活 RoleMemory**：让 `models.py` 中已定义但从未使用的 `RoleMemory` 真正参与每轮对话的上下文构建，实现跨回合结构化记忆。
2. **UI 双视角改版**：将 `gui.py` 的单列对话区重构为左右双面板（侦探 / 嫌疑人），分别展示对话、内心活动和结构化记忆。

## 已确认约定

- `models.py` 中 `RoleMemory` 和 `GameState` 的现有字段定义不做修改，只利用已有字段
- `controller.py` 的公开接口签名不变
- 改动后现有单元测试 `tests/test_llm_gateway.py` 必须全部通过
- 不改动 `_clean_speech()`、`_dedup_repeating_blocks()` 等已落地的后置清洗逻辑
- 文件开头已有的说明注释需保留并按需更新

## 术语映射

| 术语 | 含义 |
|---|---|
| RoleMemory | `models.py` 中的 `@dataclass RoleMemory`，含 `immutable_facts`、`recent_claims`、`strategy_notes`、`summary` 四个字段 |
| 结构化记忆 | 从 `RoleMemory` 提取、格式化后注入 prompt 的约束性上下文块 |
| 双面板 | GUI 中左右分栏，分别对应侦探视角和嫌疑人视角 |
| 说辞列表 | `recent_claims` 中积累的角色历史发言关键摘要 |

## 第一部分：激活 RoleMemory

### 1.1 当前问题

```
RoleMemory 数据流（当前）

case_loader.py                          orchestrator.py
┌────────────────────┐                 ┌─────────────────────────┐
│ detective_memory =  │                │                         │
│   RoleMemory(       │──写入State──→  │  run_turn()             │
│     immutable_facts,│                │    ├── build_context()   │
│     strategy_notes  │                │    │   └── 不读RoleMemory │
│   )                 │                │    └── 不更新RoleMemory   │
│                     │                │                         │
│ suspect_memory =    │                └─────────────────────────┘
│   RoleMemory(...)   │
└────────────────────┘

问题：
- RoleMemory 初始化后再也没人读写，是完全的死代码
- prompt_composer 中 suspect_claims 是从 state.turns 即时提取的，不经过 RoleMemory
- 侦探没有自己的策略记忆，每轮 prompt 都是无状态重建
- 嫌疑人的 goal 始终是固定文本，不随压力变化
```

### 1.2 目标数据流

```
每轮结束后
┌──────────────────────────────────────────────────────────┐
│  orchestrator.run_turn()                                 │
│    ├── 生成对话                                          │
│    ├── 更新 state.suspect_memory                         │
│    │     ├── recent_claims += 嫌疑人本轮答复摘要          │
│    │     └── summary = 根据矛盾数动态生成防御状态描述      │
│    ├── 更新 state.detective_memory                       │
│    │     ├── recent_claims += 记录嫌疑人本轮说辞          │
│    │     └── strategy_notes 保留（不自动修改）            │
│    └── build_context 从 RoleMemory 读取 → 注入 prompt    │
└──────────────────────────────────────────────────────────┘
```

### 1.3 改动明细

#### 文件1：`src/interrogation_mvp/orchestrator.py`

**改动**：在 `run_turn()` 的 `state.turns.append(turn)` 之后、状态判定之前，插入记忆更新逻辑。

**设计意图**：
- 每轮结束后将嫌疑人答复的关键内容追加到双方的 `recent_claims`
- 嫌疑人的 `summary` 根据矛盾计数动态更新，反映心理压力梯度
- 记忆上限控制：`recent_claims` 最多保留 10 条，超出时丢弃最早的

**目标代码**：

```python
# 在 state.turns.append(turn) 之后插入

# ── 更新角色记忆 ──
claim_text = turn.suspect_answer.strip()
if claim_text:
    claim_entry = f"R{next_round}: {claim_text[:80]}"
    state.suspect_memory.recent_claims.append(claim_entry)
    state.detective_memory.recent_claims.append(claim_entry)
    # 上限控制：只保留最近 10 条
    if len(state.suspect_memory.recent_claims) > 10:
        state.suspect_memory.recent_claims = state.suspect_memory.recent_claims[-10:]
    if len(state.detective_memory.recent_claims) > 10:
        state.detective_memory.recent_claims = state.detective_memory.recent_claims[-10:]

# 嫌疑人心理压力梯度
contradiction_count = len(state.contradictions)
if contradiction_count == 0:
    state.suspect_memory.summary = "坚决否认，维持不在场说法。"
elif contradiction_count <= 2:
    state.suspect_memory.summary = "说辞出现漏洞，需要小心应对，可以局部松口但不能认罪。"
else:
    state.suspect_memory.summary = "多处矛盾被揭穿，防线即将崩溃，考虑换一种辩解方式。"
```

#### 文件2：`src/interrogation_mvp/prompt_composer.py`

**改动**：
1. `PromptContext` 新增 `detective_memory` 和 `suspect_memory` 字段
2. `build_context()` 从 `state.detective_memory` / `state.suspect_memory` 读取数据填充
3. `build_detective_prompt()` 使用 `detective_memory.recent_claims` 替代当前的即时提取
4. `build_suspect_prompt()` 使用 `suspect_memory.recent_claims` + `suspect_memory.summary` 动态生成 goal

**设计意图**：
- `suspect_claims` 字段不删除（保持兼容），但数据源从 `state.turns` 即时提取改为从 `RoleMemory.recent_claims` 读取
- 嫌疑人的 `goal` 不再是固定的"保持防御叙述"，而是从 `suspect_memory.summary` 读取

**目标代码片段**：

```python
@dataclass
class PromptContext:
    round_index: int
    case_data: CaseData
    recent_turn_summaries: List[str]
    pending_evidence_text: Optional[str]
    contradiction_count: int
    suspect_claims: List[str] = None  # type: ignore[assignment]
    detective_claims: List[str] = None  # type: ignore[assignment]  ← 新增
    suspect_pressure_summary: str = ""  # ← 新增

    def __post_init__(self) -> None:
        if self.suspect_claims is None:
            self.suspect_claims = []
        if self.detective_claims is None:
            self.detective_claims = []


def build_context(state: GameState, pending_evidence_text: Optional[str]) -> PromptContext:
    summaries = [
        f"R{turn.round_index}:侦探问[{_truncate(turn.detective_question)}] 嫌疑人答[{_truncate(turn.suspect_answer)}]"
        for turn in state.turns
    ]
    # 优先从 RoleMemory 读取；为空时降级到即时提取（兼容旧数据）
    suspect_claims = list(state.suspect_memory.recent_claims)
    if not suspect_claims:
        suspect_claims = [
            f"R{turn.round_index}: {_truncate(turn.suspect_answer, max_chars=80)}"
            for turn in state.turns
            if turn.suspect_answer.strip()
        ]
    detective_claims = list(state.detective_memory.recent_claims)

    return PromptContext(
        round_index=state.round_index + 1,
        case_data=state.case_data,
        recent_turn_summaries=summaries,
        pending_evidence_text=pending_evidence_text,
        contradiction_count=len(state.contradictions),
        suspect_claims=suspect_claims,
        detective_claims=detective_claims,
        suspect_pressure_summary=state.suspect_memory.summary,
    )
```

`build_suspect_prompt()` 中 goal 改为动态：

```python
def build_suspect_prompt(self, context, detective_question="") -> Dict[str, str]:
    # ...现有逻辑...
    goal = context.suspect_pressure_summary or "保持防御叙述，不主动完整认罪。"
    return {
        # ...
        "goal": goal,  # ← 替换原来的固定文本
        # ...
    }
```

#### 文件3：`src/interrogation_mvp/llm_gateway.py`

**改动**：`_system_prompt()` 拆分为 `_system_prompt(role)` 接收角色参数，针对侦探/嫌疑人输出不同的系统指令。

**设计意图**：
- 侦探的 system prompt 强调"你是审讯者，追问矛盾"
- 嫌疑人的 system prompt 强调"你是被审讯者，维持说辞一致性"
- 消除两个角色共用同一 system prompt 导致的信息泄漏风险

**目标代码**：

```python
def _system_prompt(self, role: str = "detective") -> str:
    base = (
        "你是审讯对话引擎。严格遵守以下规则：\n"
        '1. 只输出一个JSON对象，格式：{"thought":"...","speech":"...","anchors":"..."}\n'
        "2. speech 是你这个角色说出口的一句话，必须直接对对方说，不超过100字\n"
        "3. 禁止在 speech 中扮演对方角色，禁止出现对方的名字+冒号+对方台词\n"
        "4. 禁止输出多轮对话、分析框架、编号列表、审讯计划\n"
        '5. 禁止输出"作为XX我会……"这类元叙述，直接说话\n'
        "6. thought 是内心独白，不超过50字\n"
    )
    if role == "detective":
        role_hint = (
            "7. 你的任务是作为侦探审讯嫌疑人，通过提问揭露矛盾\n"
            '正确示例：{"thought":"他的时间线有破绽","speech":"你说11点在家，但邻居听到你开车出去了，怎么解释？","anchors":"时间线矛盾"}\n'
            '错误示例：{"speech":"作为侦探陈明远，我会首先询问……1.时间线 2.地点"}'
        )
    else:
        role_hint = (
            "7. 你的任务是作为嫌疑人回应侦探的审讯，保持说辞一致\n"
            '正确示例：{"thought":"不能承认出过门","speech":"警官，我真的在家睡觉，可能邻居听错了。","anchors":"否认出门"}\n'
            '错误示例：{"speech":"李建国：警官您搞错了……陈明远：请你解释……"}'
        )
    return base + role_hint
```

**调用点改动**：所有调用 `self._system_prompt()` 的地方改为 `self._system_prompt(role)`。涉及：
- `_generate_local_openai_compatible()`
- `_generate_bytedance()`
- `_generate_anthropic_compatible()`

每处的改动都是相同模式：`system_text = self._system_prompt()` → `system_text = self._system_prompt(role)`

## 第二部分：UI 双视角改版

### 2.1 当前问题

```
当前 GUI 布局：
┌──────────────────────────────────────────┐
│ 标题栏                                   │
├──────────────────────────────────────────┤
│ 案件信息 LabelFrame                      │
├──────────────────────────────────────────┤
│                                          │
│   单列 ScrolledText                      │
│   所有角色对话混排                         │
│   [侦探内心] ...                          │
│   侦探：...                              │
│   [嫌疑人内心] ...                        │
│   嫌疑人：...                             │
│                                          │
├──────────────────────────────────────────┤
│ 证据注入行                               │
├──────────────────────────────────────────┤
│ 操作按钮行                               │
└──────────────────────────────────────────┘

问题：
- 无法一眼对比两个角色的状态
- 内心独白和对话台词混在一起，视觉层次不清
- 没有展示结构化记忆的位置
- 回合数多了之后很难回溯某个角色的完整说辞链
```

### 2.2 目标布局

```
┌──────────────────────────────────────────────────────────────┐
│ 审讯室 — 深夜的河边            [第 N 回合]                    │
├──────────────────────────────────────────────────────────────┤
│ 案件信息                                                     │
├─────────────────────────┬────────────────────────────────────┤
│    🔍 侦探 · 陈明远      │    🎭 嫌疑人 · 李建国              │
├─────────────────────────┤────────────────────────────────────┤
│                         │                                    │
│  [对话区 - 侦探发言]     │  [对话区 - 嫌疑人发言]              │
│  R1: 你当晚几点...       │  R1: 我9点多就睡了...              │
│  R2: 邻居说听到你...     │  R2: 可能听错了吧...               │
│                         │                                    │
├─────────────────────────┤────────────────────────────────────┤
│  💭 侦探内心              │  💭 嫌疑人内心                     │
│  "他的时间线有破绽"       │  "不能承认出过门"                  │
├─────────────────────────┤────────────────────────────────────┤
│  📋 掌握的嫌疑人说辞      │  📋 我说过的话（不可矛盾）          │
│  R1: 9点多就睡下了       │  R1: 9点多就睡下了                 │
│  R3: 张三可以作证        │  R3: 张三可以作证                  │
│  R5: 没见过受害者        │  R5: 没见过受害者                  │
│  [策略] 围绕时间线追问    │  [状态] 说辞出现漏洞，小心应对      │
├─────────────────────────┴────────────────────────────────────┤
│ ⚠️ 矛盾：[时间线/高] 嫌疑人称9点睡觉但邻居11点听到车声        │
├──────────────────────────────────────────────────────────────┤
│ 证据注入：[下拉菜单]                           [注入证据]     │
│ [下一回合]                                    [结束审讯]     │
└──────────────────────────────────────────────────────────────┘
```

### 2.3 改动明细

#### 文件：`src/interrogation_mvp/gui.py`

**改动范围**：重写 `_build_ui()` 方法和 `_append_turn()` 方法

**设计意图**：
- 用 `tk.PanedWindow` 或两列 `Frame` 实现左右分栏
- 每侧包含三个区域：对话历史（ScrolledText）、当前内心独白（Label）、结构化记忆（ScrolledText 或 Listbox）
- 矛盾信息放在底部中间横跨两栏，全局可见
- 结构化记忆区在每轮结束后刷新，数据来源于 `GameState.detective_memory` / `suspect_memory`

**核心改动点**：

1. **`_build_ui()`**：

```python
# 替换原来的单个 self._chat ScrolledText，改为：

# ── 双面板容器 ──
panels = tk.Frame(self._root)
panels.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
panels.columnconfigure(0, weight=1)
panels.columnconfigure(1, weight=1)
panels.rowconfigure(1, weight=3)  # 对话区占大比例
panels.rowconfigure(2, weight=0)  # 内心独白区
panels.rowconfigure(3, weight=1)  # 记忆区

# ── 左侧标题（侦探） ──
tk.Label(panels, text="🔍 侦探", font=("Helvetica", 12, "bold"),
         fg="#1a5fa8").grid(row=0, column=0, sticky="w", padx=4)

# ── 右侧标题（嫌疑人） ──
tk.Label(panels, text="🎭 嫌疑人", font=("Helvetica", 12, "bold"),
         fg="#444").grid(row=0, column=1, sticky="w", padx=4)

# ── 对话历史区 ──
self._detective_chat = ScrolledText(panels, state=tk.DISABLED, wrap=tk.WORD,
                                     font=("Helvetica", 10), height=10)
self._detective_chat.grid(row=1, column=0, sticky="nsew", padx=(0,2), pady=2)

self._suspect_chat = ScrolledText(panels, state=tk.DISABLED, wrap=tk.WORD,
                                   font=("Helvetica", 10), height=10)
self._suspect_chat.grid(row=1, column=1, sticky="nsew", padx=(2,0), pady=2)

# ── 内心独白区（每轮刷新，只显示最新一条） ──
thought_frame_d = tk.LabelFrame(panels, text="💭 侦探内心", padx=4, pady=2)
thought_frame_d.grid(row=2, column=0, sticky="ew", padx=(0,2), pady=2)
self._detective_thought_var = tk.StringVar(value="—")
tk.Label(thought_frame_d, textvariable=self._detective_thought_var,
         fg="#888", wraplength=340, justify=tk.LEFT).pack(fill=tk.X)

thought_frame_s = tk.LabelFrame(panels, text="💭 嫌疑人内心", padx=4, pady=2)
thought_frame_s.grid(row=2, column=1, sticky="ew", padx=(2,0), pady=2)
self._suspect_thought_var = tk.StringVar(value="—")
tk.Label(thought_frame_s, textvariable=self._suspect_thought_var,
         fg="#888", wraplength=340, justify=tk.LEFT).pack(fill=tk.X)

# ── 结构化记忆区（跨回合累积） ──
memory_frame_d = tk.LabelFrame(panels, text="📋 掌握的嫌疑人说辞", padx=4, pady=2)
memory_frame_d.grid(row=3, column=0, sticky="nsew", padx=(0,2), pady=2)
self._detective_memory_text = ScrolledText(memory_frame_d, state=tk.DISABLED,
                                            wrap=tk.WORD, font=("Helvetica", 9), height=5)
self._detective_memory_text.pack(fill=tk.BOTH, expand=True)

memory_frame_s = tk.LabelFrame(panels, text="📋 我说过的话", padx=4, pady=2)
memory_frame_s.grid(row=3, column=1, sticky="nsew", padx=(2,0), pady=2)
self._suspect_memory_text = ScrolledText(memory_frame_s, state=tk.DISABLED,
                                          wrap=tk.WORD, font=("Helvetica", 9), height=5)
self._suspect_memory_text.pack(fill=tk.BOTH, expand=True)

# ── 矛盾信息区（横跨两栏） ──
self._contradiction_text = ScrolledText(self._root, state=tk.DISABLED, wrap=tk.WORD,
                                         font=("Helvetica", 10), height=2, fg="#cc0000")
self._contradiction_text.pack(fill=tk.X, padx=10, pady=2)
```

2. **`_append_turn()` 重写**：

```python
def _append_turn(self, turn, contradictions: list) -> None:
    # 侦探对话区追加
    self._append_to_widget(
        self._detective_chat,
        f"R{turn.round_index}: {turn.detective_question}\n"
    )
    # 嫌疑人对话区追加
    self._append_to_widget(
        self._suspect_chat,
        f"R{turn.round_index}: {turn.suspect_answer}\n"
    )
    # 刷新内心独白（只显示最新一条）
    self._detective_thought_var.set(turn.detective_thought or "—")
    self._suspect_thought_var.set(turn.suspect_thought or "—")

    # 矛盾信息追加
    for desc in contradictions:
        self._append_to_widget(self._contradiction_text, f"⚠️ {desc}\n")

    # 刷新结构化记忆区
    self._refresh_memory_panels()
```

3. **新增 `_refresh_memory_panels()` 方法**：

```python
def _refresh_memory_panels(self) -> None:
    """从 GameState 中读取 RoleMemory，刷新底部记忆区。"""
    try:
        state = self._controller.get_state(self._session_id)
    except Exception:
        return

    # 侦探记忆面板
    d_lines = list(state.detective_memory.recent_claims)
    if state.detective_memory.strategy_notes:
        d_lines.append(f"[策略] {state.detective_memory.strategy_notes[0]}")
    self._set_widget_text(self._detective_memory_text, "\n".join(d_lines) or "暂无")

    # 嫌疑人记忆面板
    s_lines = list(state.suspect_memory.recent_claims)
    if state.suspect_memory.summary:
        s_lines.append(f"[状态] {state.suspect_memory.summary}")
    self._set_widget_text(self._suspect_memory_text, "\n".join(s_lines) or "暂无")
```

4. **新增辅助方法**：

```python
def _append_to_widget(self, widget: ScrolledText, text: str) -> None:
    widget.config(state=tk.NORMAL)
    widget.insert(tk.END, text)
    widget.config(state=tk.DISABLED)
    widget.see(tk.END)

def _set_widget_text(self, widget: ScrolledText, text: str) -> None:
    widget.config(state=tk.NORMAL)
    widget.delete("1.0", tk.END)
    widget.insert(tk.END, text)
    widget.config(state=tk.DISABLED)
```

5. **`_handle_message()` 中的 `turn_result` 分支**需适配新方法名（用 `_append_turn` 新签名）。

6. **`_remove_pending()` 和 `_append_pending()`**：可以改为在侦探对话区显示"⏳ 正在生成…"，回合完成后清除。

7. **窗口最小尺寸调大**：`self._root.minsize(960, 720)` 以适应双面板。

### 2.4 视觉标签配置

```python
# 侦探对话区
self._detective_chat.tag_config("speech", foreground="#1a5fa8", font=("Helvetica", 10))

# 嫌疑人对话区
self._suspect_chat.tag_config("speech", foreground="#222222", font=("Helvetica", 10))
```

## 两部分的改动依赖关系

```
第一部分（RoleMemory）              第二部分（UI）
                                  
orchestrator.py ──写入──→ state.detective_memory
                          state.suspect_memory
                              │
prompt_composer.py ──读取──┘   │
                              │
llm_gateway.py ──拆分system──┘ │
                              ↓
                    gui.py ──读取 state.*_memory ──→ 刷新记忆面板
```

第二部分依赖第一部分写入的记忆数据。建议实现顺序：先完成第一部分，验证 `state.*_memory` 在每轮后确实更新，再实现第二部分的 UI 读取。

## 未决问题

1. `recent_claims` 上限设为 10 条是否合适？12-15 轮的 MVP 中最多 15 条，可能不需要裁剪
2. 侦探的 `strategy_notes` 是否需要动态更新？当前方案保守处理（只读不写），后续可扩展
3. 记忆区是否需要支持展开/折叠？MVP 阶段用固定高度的 ScrolledText 即可
4. `_system_prompt(role)` 的签名变更会影响所有 provider 调用点，需要确认三个 `_generate_*` 方法都改到
5. 双面板在小屏幕上可能拥挤，是否需要最小宽度保护或可切换的单列模式

## 相关文档

- 前置修复已落地：`docs/handoff/role_boundary_fix_handoff_to_codeexpert_v0.1.md`（层 1-4 已由 CodeExpert 实现）
- 已有架构审查：`docs/handoff/architect_review_local_deepseek_v0.2.md`
- 数据模型定义：`src/interrogation_mvp/models.py`（`RoleMemory`、`GameState`）
- 初始记忆写入：`src/interrogation_mvp/case_loader.py`

## 禁止事项

- 不得修改 `models.py` 中的字段定义（利用已有的 `RoleMemory` 字段即可）
- 不得改变 `controller.py` 的公开接口签名
- 不得删除 `_clean_speech()`、`_dedup_repeating_blocks()` 等已落地逻辑
- 不得删除 `prompt_composer.py` 中现有的 `suspect_claims` 兼容路径
- 后置清洗仍只处理 `speech` 字段，不扩展到 `thought` 或 `anchors`
- GUI 改版不得引入 tkinter 以外的第三方 UI 库
