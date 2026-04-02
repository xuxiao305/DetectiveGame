# Architect 架构审查：Local DeepSeek 集成现状 v0.3

版本：v0.3  
日期：2026-04-03  
角色：Architect  
接收方：CodeExpert  
更新说明：v0.3 新增缺失 G（suspect 间歇性 fallback 根因分析）及对应实施项

---

## 1. 任务目标

对 Local DeepSeek 集成的当前实现做一次架构完整性审查，逐项确认：哪些实现已就位、哪些存在架构缺失或边界冲突、哪些接口定义不清需要修正。产出修正结论和具体实施项，供 CodeExpert 据此完成剩余工作。

---

## 2. 已确认约定（继承自 v0.1 handoff，未变更）

1. 回合因果链冻结：detective → suspect 顺序调用，不可并行。
2. 架构边界冻结：仅扩展 LLMGateway 与配置层，不改动游戏规则与状态机。
3. 兼容性要求：保留 bytedance、anthropic_compatible、fallback 逻辑。
4. 可观测性要求：保留 timing 日志，新增 provider 选择与降级链路日志。
5. 本地容器锁定 Ollama，默认端点 `http://127.0.0.1:11434/v1`。
6. 本地模型锁定 `deepseek-r1-14b-q4`（Q4_K_L 量化版）。

---

## 3. 术语映射

| 日常用语 | 正式标识 |
|---|---|
| 架构师agent / 架构师 | Architect |
| 设计师agent / 设计师 | AIDesigner |
| CodeExpert / 编码专家 / coder | CodeExpert |
| Local Deepseek | 本地 provider（local_openai_compatible）|
| Remote | 远端 provider（bytedance / anthropic_compatible）|
| Fallack | safe_fallback 硬编码兜底 |

---

## 4. 当前结论：架构审查发现

### 4.1 ✅ 已正确就位

| 项目 | 状态 | 所在文件 |
|---|---|---|
| local_openai_compatible provider 实现 | ✅ | llm_gateway.py `_generate_local_openai_compatible` |
| Ollama native /api/chat 降级路径 | ✅ | llm_gateway.py `_generate_ollama_api_chat` |
| `<think>` 标签清洗 | ✅ | llm_gateway.py `_sanitize_model_text` |
| provider 路由（主→次→fallback） | ✅ | llm_gateway.py `generate()` 主循环 |
| 来源标记（Local Deepseek / Remote / Fallack）| ✅ | llm_gateway.py `_source_label` / `_append_source_tag` |
| config 默认本地优先（provider=local_openai_compatible）| ✅ | config.py |
| local_base_url 硬编码默认值 | ✅ | config.py / GenerationOptions |
| 历史摘要截断（防上下文膨胀）| ✅ | prompt_composer.py `_truncate` |
| controller 完整透传本地配置 | ✅ | controller.py |
| bytedance temperature/max_tokens 已补入 | ✅ | llm_gateway.py `_generate_bytedance` |
| Exception 全捕获（含 OSError/HTTPError）| ✅ | llm_gateway.py retry loop |

### 4.2 ❌ 架构缺失

#### 缺失 A：Prompt 未携带案件核心上下文

**严重程度：高（功能性缺失，直接导致模型输出跑题）**

当前 system prompt 仅说"你是审讯对话引擎，输出 JSON"，user prompt 仅传递 `role / round / goal / detective_question / constraint / history`。

**缺失内容：**
- 案件名称、背景
- 嫌疑人身份、侦探身份
- 嫌疑人需要维护的谎言（suspect_lie）
- 嫌疑人实际真相（suspect_truth）
- 侦探已知信息（detective_known）

没有这些，模型无法扮演"深夜的河边"案件中的李建国或陈明远。模型会自编角色（从日志看，出现了"张三""XX公司文员""废弃工厂"等完全偏离案件的内容）。

**影响范围：**
- `_generate_local_openai_compatible` 和 `_generate_ollama_api_chat` 中的 system_text / user_text 构造
- 所有远端 provider 的 prompt 构造同样缺失（`_generate_bytedance`、`_generate_anthropic_compatible`）
- PromptComposer 已正确构造了 prompt dict，但 LLMGateway 内部重新构造 prompt 时**完全丢弃了 PromptComposer 传入的关键字段**

**根因：**
PromptComposer 产出的 prompt dict 包含 `role / goal / forced_constraint / history / round` 等字段，但不包含案件数据。而 LLMGateway 内部在各个 `_generate_*` 方法里自行拼接了 system_text 和 user_text，与 PromptComposer 产出的字段做了映射（`prompt.get('goal')` 等），但没有任何地方把 `CaseData` 信息注入到发给模型的文本中。

PromptContext 持有 `case_data`，但 PromptComposer.build_detective_prompt / build_suspect_prompt 从未把案件信息写入产出的 Dict。


#### 缺失 B：Ollama /v1/chat/completions 404 应直接跳过而非先试再降级

**严重程度：中**

当前代码先请求 `/v1/chat/completions`，收到 404 后再调用 `_generate_ollama_api_chat`（Ollama native `/api/chat`）。这是每次调用都会走的冗余 HTTP 往返。

Ollama 的 OpenAI 兼容层在某些版本不支持 `/v1/chat/completions`，但支持 `/v1/chat/completions` 的版本也同样支持 `/api/chat`。应该直接使用 `/api/chat` 作为 Ollama 的唯一入口，省掉一次 404 往返。


#### 缺失 C：`num_ctx` 未通过 API 参数传入

**严重程度：中**

虽然 Modelfile 里设了 `PARAMETER num_ctx 8192`，但如果用户忘记重建模型或者使用不同模型名，就会回到默认 2048。应该在 `/api/chat` 请求的 `options` 中显式传入 `num_ctx`，确保运行时控制。


#### 缺失 D：来源标记混入对话历史

**严重程度：中**

当前 `_append_source_tag` 把 `(Local Deepseek)` / `(Fallack)` 追加到 `speech` 字段末尾。这个 speech 随后被存入 `DialogueTurn.detective_question` 和 `DialogueTurn.suspect_answer`，再被 `build_context` 构造为历史摘要送入下一轮 prompt。

结果：模型收到的历史文本里会出现 `(Local Deepseek)` 这种调试标记，污染上下文。

来源标记应该：
- 存在 `GeneratedRoleOutput` 的独立字段中（如新增 `source: str`）
- 仅在展示层（CLI `_print_turn`）追加到用户可见文本
- 不写入 `DialogueTurn` 持久字段


#### 缺失 G：`local_max_tokens=512` 导致 suspect 间歇性返回空内容

**严重程度：高（直接导致嫌疑人回答频繁走 fallback）**

**现象：** 从 `logs/session_20260402_231557.log` 看，suspect 角色间歇性出现 `"Empty content from ollama /api/chat provider"` 错误，重试后仍然为空，最终走 safe_fallback。而 detective 同期大多成功。

**故障链路：**
```
1. _generate_local_openai_compatible 先请求 /v1/chat/completions → 404
2. 降级到 _generate_ollama_api_chat（/api/chat）
3. Ollama 返回内容，但全部是 <think>…</think> 推理块
4. _sanitize_model_text 剥掉 <think> 后，剩余内容为空
5. 抛出 "Empty content from ollama /api/chat provider"
6. 重试一次 → 同样结果
7. secondary_provider（bytedance）无 API key → 也失败
8. 进入 safe_fallback → 每次输出固定模板句
```

**根因：** DeepSeek-R1 是推理模型，会先在 `<think>` 块中进行长段推理，再输出最终回答。当前 `num_predict`（即 `local_max_tokens`）仅为 **512**，对 suspect 角色的请求经常不够用：

- suspect prompt 比 detective 更重（额外包含完整的 `detective_question` 文本，侦探回答经常上千字符）
- 模型把 512 个 token 全部花在 `<think>` 推理上，还没来得及输出实际 JSON 就被截断
- `_sanitize_model_text` 剥掉 `<think>` 后内容为空 → 触发错误

**日志证据（摘要）：**

| 回合 | detective | suspect | suspect 错误 |
|---|---|---|---|
| R1 | ✅ success 10888ms | ✅ success 7930ms | — |
| R2 | ✅ success 451ms | ❌ fallback | Empty content × 2 |
| R3 | ❌ fallback | ❌ fallback | Empty content × 2 |
| R4 | ✅ success 414ms | ✅ success 7801ms | — |
| R5 | ❌ fallback | ❌ fallback | Empty content × 2 |
| R6 | ✅ success 6298ms | ✅ success 5288ms | — |
| R7 | ✅ success 4815ms | ✅ success 6075ms | — |
| R8 | ✅ success 7935ms | ✅ success 5064ms | — |

规律：suspect 成功时耗时 5000–8000ms（模型有足够空间完成推理+输出），失败时耗时仅 130–350ms（模型在极短时间内就被 token 上限截断）。

**修复方案：** 将 `local_max_tokens` 从 512 提高到 **1024**，同时在 `/api/chat` 的 `options` 中传入 `num_ctx: 8192` 确保上下文窗口足够。


### 4.3 ⚠️ 边界冲突

#### 冲突 E：GenerationOptions 与 ModelConfig 字段重复且默认值不一致

**严重程度：低**

`GenerationOptions` 的 `provider` 默认值是 `"bytedance"`，但 `ModelConfig` 的 `provider` 默认值是 `"local_openai_compatible"`。运行时因为 controller 会用 ModelConfig 覆盖，所以不影响实际行为。但 `GenerationOptions` 自身的默认值产生了误导：直接 `GenerationOptions()` 实例化时会走 bytedance，与项目当前意图（本地优先）矛盾。

同样，`local_model_name` 在 `GenerationOptions` 中默认是 `"deepseek-r1-distill-qwen-14b"`，在 `ModelConfig` 中是 `"deepseek-r1-14b-q4"`。


#### 冲突 F：guardrails 在 source tag 之后执行，可能覆盖标记

**严重程度：低**

`TurnOrchestrator.run_turn` 中，先调 `gateway.generate()`（已附加 source tag），再调 `guard.apply()`。如果 guardrails 的 `_enforce_confession_boundary` 触发，会整体替换 `speech`，source tag 会丢失。

这在缺失 D 修复后不再是问题（source tag 不再存于 speech），但在修复前是一个边界冲突。

---

## 5. 未决问题

| 编号 | 问题 | 阻塞程度 | 建议处理 |
|---|---|---|---|
| Q1 | 案件上下文未注入 prompt 是设计遗漏还是有意为之？ | 阻塞 | Architect 判定为遗漏，必须修复（见缺失 A）|
| Q2 | source tag 应该存在 speech 还是独立字段？ | 半阻塞 | Architect 结论：独立字段，展示层追加 |
| Q3 | 是否需要在 `/api/chat` 的 options 中强制传 `num_ctx`？ | 非阻塞 | 建议传入，值来自配置，默认 8192 |
| Q4 | `GenerationOptions` 默认值是否需要与 `ModelConfig` 对齐？ | 非阻塞 | 建议对齐，减少混淆 |
| Q5 | Ollama 是否可以完全弃用 `/v1/chat/completions` 只走 `/api/chat`？ | 非阻塞 | 建议简化为仅 `/api/chat` |
| Q6 | `local_max_tokens=512` 是否足够 DeepSeek-R1 完成推理+输出？ | 阻塞 | 不够，必须提高到 1024+（见缺失 G）|

---

## 6. 相关文档

1. `docs/handoff/local_deepseek_integration_handoff_to_codeexpert_v0.1.md`（原始 handoff）
2. `docs/handoff/mvp_interrogation_handoff_to_codeexpert_v0.2.md`（MVP 基线）
3. `logs/session_20260402_231557.log`（上一轮全 15 回合实跑日志，可观察模型跑题现象）

---

## 7. 禁止事项

1. 不得改动回合因果链为并行双角色生成。
2. 不得删除现有远端 provider 能力。
3. 不得改变 TurnOrchestrator 对外行为契约。
4. 不得修改 Phase 序号。
5. 不得在 speech 持久字段中保留调试标记（source tag 等）。

---

## 8. CodeExpert 实施项（按优先级排序）

### P0-a：提高 local_max_tokens 并传入 num_ctx（缺失 G + 缺失 C）

**这是当前最紧迫的修复项——直接决定 suspect 能否稳定出结果。**

1. `config.py` 的 `ModelConfig`：`local_max_tokens` 从 `512` 改为 `1024`。
2. `llm_gateway.py` 的 `GenerationOptions`：`local_max_tokens` 从 `512` 改为 `1024`。
3. `ModelConfig` 和 `GenerationOptions` 新增字段：`local_num_ctx: int = 8192`。
4. `controller.py` 透传 `local_num_ctx` 到 `GenerationOptions`。
5. `/api/chat` 请求 payload 的 `options` 中加入 `"num_ctx": int(prompt.get("local_num_ctx", 8192))`。

**验证方式：** 改完后重跑 `auto_run.py`，日志中 suspect 的 `llm_generate_success` 比例应大幅提升，`"Empty content from ollama /api/chat provider"` 应消失或极少出现。

### P0-b：注入案件上下文到 prompt（缺失 A）

**方案：扩展 PromptComposer 产出字段**

在 `build_detective_prompt` 和 `build_suspect_prompt` 的返回 dict 中新增以下键：
- `case_name`：案件名
- `background`：案件背景
- `character_name`：当前角色名
- `character_known`：该角色已知信息（侦探用 detective_known，嫌疑人用 suspect_lie + suspect_truth 的子集）
- `character_goal_detail`：角色具体目标描述

LLMGateway 各 `_generate_*` 方法的 user_text 构造中，追加这些字段的引用：
```
f"案件:{prompt.get('case_name', '')}\n"
f"背景:{prompt.get('background', '')}\n"
f"你的角色:{prompt.get('character_name', '')}\n"
f"你掌握的信息:{prompt.get('character_known', '')}\n"
```

**注意：**
- 嫌疑人 prompt 应包含 `suspect_lie`（用于维持虚假叙述）和视压力等级选择性暴露的 `suspect_truth` 片段。
- 侦探 prompt 应包含 `detective_known`。
- 这些信息来自 `PromptContext.case_data`，PromptComposer 有权限读取。

### P2：source tag 移出 speech，改为独立字段（缺失 D）

1. `GeneratedRoleOutput` 新增 `source: str = ""`。
2. `generate()` 成功路径：`output.source = self._source_label(provider)`。
3. `generate()` fallback 路径：`fallback_output.source = "Fallack"`。
4. 删除 `_append_source_tag` 的调用。
5. `cli.py` 的 `_print_turn` 中，在打印 speech 时追加 `(turn.source)` 后缀。需要 `DialogueTurn` 也新增 `detective_source` 和 `suspect_source` 字段，由 orchestrator 传入。

### P4：简化 Ollama 调用路径（缺失 B）

将 `_generate_local_openai_compatible` 改为直接调用 `/api/chat`（即当前的 `_generate_ollama_api_chat` 逻辑），不再先试 `/v1/chat/completions` 再 fallback。

方法名可保持 `_generate_local_openai_compatible`，但内部实现直接走 Ollama native 协议。

### P5：传入 num_ctx（已合并到 P0-a）

已合并到 P0-a 一并实施。

### P6：对齐 GenerationOptions 默认值（冲突 E）

将 `GenerationOptions` 的以下默认值与 `ModelConfig` 对齐：
- `provider` → `"local_openai_compatible"`
- `local_model_name` → `"deepseek-r1-14b-q4"`

---

## 9. 验收标准

1. 运行 `python scripts/auto_run.py`（配置本地 Ollama），15 回合输出中：
   - **suspect 不再间歇性走 fallback**：日志中 `role=suspect` 的 `llm_generate_success` 比例 ≥ 90%，`"Empty content from ollama /api/chat provider"` 消失或极少。
   - 侦探提问围绕"深夜的河边"案件，提及陈明远、李建国、王某。
   - 嫌疑人回答围绕其谎言（在家睡觉）和真相（河边争执），不出现"张三""废弃工厂"等无关内容。
   - 每条 speech 不含 `(Local Deepseek)` / `(Fallack)` 等调试标记（标记仅在终端展示行出现）。
   - 日志中 output_source 全部为 primary（非 safe_fallback），除非服务真正故障。
2. 所有单元测试通过。

---

## 10. 实施项优先级总览

| 优先级 | 编号 | 标题 | 对应缺失 | 紧迫度 |
|---|---|---|---|---|
| **P0-a** | 缺失 G + C | 提高 local_max_tokens 到 1024 + 传入 num_ctx | suspect 间歇 fallback | **最高——不改则游戏无法正常运行** |
| **P0-b** | 缺失 A | 注入案件上下文到 prompt | 模型输出跑题 | **最高——不改则角色不对** |
| P2 | 缺失 D | source tag 移出 speech | 上下文污染 | 中 |
| P4 | 缺失 B | 简化 Ollama 调用路径 | 冗余 404 往返 | 中 |
| P6 | 冲突 E | 对齐默认值 | 开发者混淆 | 低 |
