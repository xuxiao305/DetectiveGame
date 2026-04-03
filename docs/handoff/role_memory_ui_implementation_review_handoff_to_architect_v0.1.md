# RoleMemory + UI 实现完成 → 请求架构审查
**移交方**: CodeExpert  
**接收方**: Architect  
**日期**: 2026-04-03  
**版本**: v0.1

---

## 1. 任务目标
请求 Architect 对已完成的 RoleMemory 激活 + UI 双面板重构进行架构一致性审查，确认实现符合设计意图，评估潜在回归风险。

---

## 2. 已确认约定
- **术语映射**: "架构师agent"/"架构师" = Architect；"编码专家"/"coder" = CodeExpert
- **职责边界**: CodeExpert 负责实现，Architect 负责架构一致性审查和设计约束核对
- **RoleMemory 结构**: 
  - `immutable_facts`: list[str] (不可变事实)
  - `recent_claims`: list[str] (最近主张，上限 10 条)
  - `strategy_notes`: list[str] (策略笔记)
  - `summary`: str (动态状态总结)
- **双面板布局**: 
  - 左列：侦探对话区、内心独白、记忆面板
  - 右列：嫌疑人对话区、内心独白、记忆面板
  - 底部：矛盾提示区（横跨两列）

---

## 3. 当前结论（实现完成）

### Part 1: RoleMemory 激活 ✅
**修改文件**: orchestrator.py, prompt_composer.py, llm_gateway.py

#### orchestrator.py - 写入 RoleMemory
```python
# 在 state.turns.append(turn) 之后新增：
# 1. 更新侦探记忆
detective_claims = state.detective_memory.recent_claims
detective_claims.append(turn.detective_question)
if len(detective_claims) > 10:
    detective_claims.pop(0)

# 2. 更新嫌疑人记忆
suspect_claims = state.suspect_memory.recent_claims
suspect_claims.append(turn.suspect_answer)
if len(suspect_claims) > 10:
    suspect_claims.pop(0)

# 3. 动态生成嫌疑人压力总结
contradiction_count = len(state.contradictions)
if contradiction_count == 0:
    state.suspect_memory.summary = "坚决否认，防线完整"
elif contradiction_count <= 2:
    state.suspect_memory.summary = "局部松口，试图调整说辞"
else:
    state.suspect_memory.summary = "防线崩溃，多处矛盾暴露"
```

#### prompt_composer.py - 读取 RoleMemory
```python
# PromptContext 新增字段:
detective_claims: list[str]  # 侦探历史提问
suspect_pressure_summary: str  # 嫌疑人压力状态

# build_context() 优先从 RoleMemory 读取:
detective_claims = list(state.detective_memory.recent_claims) if state.detective_memory.recent_claims else [...]
suspect_pressure_summary = state.suspect_memory.summary or "嫌疑人处于防御状态"

# build_suspect_prompt() 动态目标:
goal = f"【当前状态】{ctx.suspect_pressure_summary}\n【目标】维持说辞一致性..."
```

#### llm_gateway.py - 角色分化系统提示
```python
def _system_prompt(self, role: str) -> str:
    if role == "detective":
        return "你扮演侦探，目标是通过追问揭露矛盾..."
    else:  # suspect
        return "你扮演嫌疑人，目标是保持说辞一致，避免暴露..."
```

**测试结果**: 8/8 llm_gateway 测试通过

---

### Part 2: UI 双面板重构 ✅
**修改文件**: gui.py

#### 新增控件（6 个）
- `_detective_chat` / `_suspect_chat`: ScrolledText (分角色对话区)
- `_detective_thought_var` / `_suspect_thought_var`: StringVar (实时内心独白)
- `_detective_memory_text` / `_suspect_memory_text`: ScrolledText (RoleMemory 显示)
- `_contradiction_text`: ScrolledText (矛盾提示统一显示)

#### 布局结构（Grid 2×4）
| 列 0 (侦探)           | 列 1 (嫌疑人)         |
|---------------------|---------------------|
| Row 0: "侦探视角"      | Row 0: "嫌疑人视角"    |
| Row 1: 对话历史       | Row 1: 对话历史       |
| Row 2: 内心独白       | Row 2: 内心独白       |
| Row 3: colspan=2 矛盾提示区                |

#### 核心方法重构
```python
# 新增辅助方法
_append_to_widget(widget, text)  # 通用追加
_set_widget_text(widget, text)  # 通用替换
_refresh_memory_panels()  # 从 GameState 刷新记忆面板

# 重写事件处理
_append_turn(turn, contradictions):
    - 左列填充侦探提问
    - 右列填充嫌疑人回答
    - 更新双方内心独白
    - 追加矛盾到底部
    - 调用 _refresh_memory_panels()

_handle_message(msg):
    - "inject_ok" → _detective_chat
    - "ended" → _contradiction_text (审讯记录)
    - "error" → _contradiction_text
    - 所有 _append_text() 改为 _append_to_widget()
```

**测试结果**: GUI 烟雾测试通过（所有新控件存在，旧 `_chat` 已移除）

---

## 4. 未决问题（需 Architect 审查）

### 4.1 架构一致性
1. **RoleMemory 读写分离是否合理？**
   - 写入：orchestrator 在每回合后更新
   - 读取：prompt_composer 在构建提示时读取
   - 问题：是否需要单独的 memory manager 模块？

2. **系统提示分化位置是否正确？**
   - 当前实现：llm_gateway._system_prompt(role) 直接分支
   - 问题：系统提示是否应该由 prompt_composer 统一管理？

3. **UI 布局是否符合 MVC 分层？**
   - 当前实现：gui.py 直接读取 GameState
   - 问题：是否需要 ViewModel 中间层解耦？

### 4.2 回归风险评估
1. **原有单元测试覆盖不足**
   - llm_gateway 测试通过，但 orchestrator/prompt_composer 修改未被测试覆盖
   - GUI 无自动化测试，仅手动烟雾测试

2. **多线程安全性**
   - GUI 通过队列 + 后台线程调用 controller
   - RoleMemory 是否在并发修改时安全？（list.append 非原子操作）

3. **降级兼容性**
   - 若 `state.detective_memory.recent_claims` 为空（旧会话），是否有正确 fallback？
   - 当前实现：prompt_composer 有 fallback 逻辑

---

## 5. 相关文档
- **上游需求**: [role_memory_and_ui_handoff_to_codeexpert_v0.1.md](./role_memory_and_ui_handoff_to_codeexpert_v0.1.md)
- **实现文件**:
  - [orchestrator.py](../../src/interrogation_mvp/orchestrator.py)
  - [prompt_composer.py](../../src/interrogation_mvp/prompt_composer.py)
  - [llm_gateway.py](../../src/interrogation_mvp/llm_gateway.py)
  - [gui.py](../../src/interrogation_mvp/gui.py)
- **测试脚本**: [gui_smoke_test.py](../../scripts/gui_smoke_test.py)

---

## 6. 禁止事项
1. **不要重新实现代码** - 当前实现功能正常，仅需审查架构合理性
2. **不要修改 RoleMemory 数据结构** - 已在 models.py 中固化
3. **不要删除 fallback 逻辑** - prompt_composer 的 fallback 保证兼容性
4. **不要引入新依赖** - 保持 tkinter 原生实现

---

## 7. 期望输出
1. **架构审查意见**:
   - RoleMemory 读写分离是否需要优化？
   - 系统提示管理是否需要重构？
   - UI 层是否需要增加 ViewModel？

2. **风险评估**:
   - 并发安全问题是否需要加锁？
   - 测试覆盖不足的高危区域在哪里？
   - 是否有潜在的边界条件未处理？

3. **下一步建议**:
   - 如需架构调整，提供具体方案或新 handoff 给 CodeExpert
   - 如认为当前实现合理，明确说明"架构审查通过，可进入 Week 4 内部测试"

---

## 8. 补充信息
- **开发环境**: Windows, Python 3.12.8, tkinter
- **当前进度**: Week 3/4（内部集成与 UI 开发）
- **下一阶段**: Week 4 内部测试（需 Architect 确认当前实现可进入测试）
