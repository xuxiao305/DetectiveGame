# Handoff to CodeExpert: Local DeepSeek Integration v0.1

版本：v0.1  
日期：2026-04-02  
移交角色：Architect  
接收角色：CodeExpert

## 0. 需求评审（Architect 先行评审结论）

### 0.1 需求目标
在不破坏现有审讯回合因果链（先警官后嫌疑人）的前提下，新增本地模型推理路径，优先解决远端调用高延迟与超时问题，并保留远端 provider 作为兜底。

### 0.2 对既有阶段的影响
1. Phase（当前 MVP 实现）不改序号、不新增阶段；仅扩展“模型调用层”能力范围。  
2. 对外行为不变：CLI 操作、回合上限、证据注入、矛盾检测逻辑维持现状。  
3. 需要补充一轮性能回归与稳定性回归，作为本次改动验收门槛。

### 0.3 关键歧义与默认处理
1. 本地模型运行容器已确定（Ollama）。  
结论：用户本机已完成安装与实测，`ollama create` / `ollama run` 可用；实现侧按 OpenAI 兼容接口接入。  
2. 本地模型已锁定为 DeepSeek-R1-Distill-Qwen-14B。  
默认：优先使用该模型的量化版本（建议 4bit），并保持 model_name 可配置以便后续灰度。  
3. 失败切换策略未明确。  
默认：本地 provider 失败后，按配置决定是否 fallback 到远端 provider，再失败则走 safe fallback。
4. 本地模型文件路径已确认。  
默认：优先使用 `D:\AI\Models\DeepSeek-R1-Distill-Qwen-14B-Q4_K_L` 作为本地加载目录（Q4_K_L 量化版，已确认可用）。

## 1. 任务目标

CodeExpert 在既定架构边界内实现“本地模型 provider 接入 + 路由与降级 + 可观测性增强”，使单回合平均时延显著下降，并可通过日志定位本地/远端瓶颈。

## 2. 已确认约定

1. 回合因果链冻结：嫌疑人回复必须依赖警官本轮发问，不允许并行生成双角色回答。  
2. 架构边界冻结：仅扩展 LLMGateway 与配置层，不改动游戏规则与状态机语义。  
3. 兼容性要求：保留现有 bytedance、anthropic_compatible、fallback 逻辑。  
4. 可观测性要求：保留当前 timing 日志，并新增 provider 选择与降级链路日志。  
5. 文件命名英文、文档内容中文。
6. 本地容器约定：当前环境锁定 Ollama，默认接入端点 `http://127.0.0.1:11434/v1`。

## 3. 术语映射

- 架构师agent / 架构师 = Architect  
- 设计师agent / 设计师 = AIDesigner  
- CodeExpert / 编码专家 / coder = CodeExpert

## 4. 当前结论

### 4.1 现状诊断结论（基于日志）
1. payload_bytes 很小（数百字节量级），排除提示词膨胀。  
2. 远端 bytedance 调用存在高延迟与超时重试，单回合被重试拉长至约 50s+。  
3. 本地 Python 逻辑耗时几乎可忽略，瓶颈集中在外部模型服务。

### 4.2 架构决策
1. 新增 provider 类型：local_openai_compatible（名称可调整，但语义需清晰）。  
2. 统一通过 LLMGateway.generate 入口调用，不新增平行调用入口。  
3. 采用“主 provider + 可选二级 provider + safe fallback”三级降级。  
4. 在日志中明确记录：selected_provider、fallback_provider、最终输出来源。
5. 本地默认模型基线：DeepSeek-R1-Distill-Qwen-14B（来源：https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-14B/tree/main）。
6. 本地文件基线路径：`D:\AI\Models\DeepSeek-R1-Distill-Qwen-14B-Q4_K_L`，若运行容器支持目录直载则直接挂载该路径（Q4_K_L 量化版，已由用户确认下载完毕）。

## 5. 改动点清单（CodeExpert 实施项）

### 5.1 配置层
1. 扩展 ModelConfig（src/interrogation_mvp/config.py）：
- primary_provider（默认 local_openai_compatible 或 bytedance，按用户环境）
- secondary_provider（可空）
- local_base_url_env（如 LOCAL_LLM_BASE_URL）
- local_api_key_env（如 LOCAL_LLM_API_KEY，可为空）
- local_model_name
- local_model_path（默认指向 D:\\AI\\Models\\DeepSeek-R1-Distill-Qwen-14B-Q4_K_L）
- local_request_timeout_seconds（可与全局 timeout 分离）
- local_max_tokens、local_temperature（可选）

2. 控制器透传（src/interrogation_mvp/controller.py）：
- 将新增配置完整注入 GenerationOptions。

### 5.2 网关层
1. 扩展 GenerationOptions（src/interrogation_mvp/llm_gateway.py）：
- 增加 local_openai_compatible 相关字段。

2. 新增 provider 实现：
- _generate_local_openai_compatible(role, prompt)
- 请求协议遵循 OpenAI Chat/Responses 兼容格式（二选一即可，但需与本地服务一致）。

3. 增强 provider 路由：
- _raw_generate_payload 按 provider 分发到 local/bd/anthropic/fallback。

4. 增强降级策略：
- 首选 provider 失败后，如 secondary_provider 已配置则自动尝试。
- secondary 仍失败，进入 safe fallback。
- 日志中必须能还原完整降级链。

5. 保持输出契约：
- 继续保证 thought/speech/anchors 归一化。
- 禁止因 provider 变化破坏上层 TurnOrchestrator 接口。

6. 修复豆包 provider 缺失推理参数（src/interrogation_mvp/llm_gateway.py）：
- `_generate_bytedance` 当前调用 `/responses` endpoint 时未传 `temperature` 和 `max_tokens`，导致模型使用服务端默认值，增加不可控的生成长度与延迟。
- 需在 payload 中补充 `temperature`（建议 0.7）和 `max_tokens`（建议 500）两个字段。
- 参数值应可通过 `ModelConfig` / `GenerationOptions` 配置，不可硬编码。

### 5.3 提示词与流程层
1. 保持当前链式顺序（src/interrogation_mvp/orchestrator.py）：
- detective -> suspect，不可并行。

2. 保持嫌疑人 prompt 包含 detective_question（src/interrogation_mvp/prompt_composer.py）：
- 不可回退到无因果依赖版本。

### 5.4 日志与可观测性
1. 保留已有日志：
- llm_request
- llm_generate_success
- llm_generate_retry
- llm_generate_fallback
- turn_timing

2. 新增日志字段建议：
- selected_provider
- secondary_provider
- output_source（primary/secondary/safe_fallback）
- round_id（可复用 round）

## 6. 配置项清单（运行时）

建议最小环境变量集合：
1. LOCAL_LLM_BASE_URL（示例：http://127.0.0.1:11434/v1 或本地网关地址）  
2. LOCAL_LLM_API_KEY（若本地服务不校验，可留空并在代码容错）  
3. LOCAL_LLM_MODEL（示例：deepseek-r1-14b-q4，建议与 `ollama create` 的模型名一致）  
4. LOCAL_LLM_MODEL_PATH（默认：D:\AI\Models\DeepSeek-R1-Distill-Qwen-14B-Q4_K_L）  
5. INTERROGATION_LOG_LEVEL  
6. INTERROGATION_LOG_FILE

实现注意：
1. Windows 路径在配置文件中使用双反斜杠转义，或统一改用正斜杠。  
2. 若本地容器不需要 path（仅需要 model 名称），仍保留 path 字段用于日志和排障。  
3. 日志中建议输出 model_path_exists=true/false，便于快速定位路径配置错误。

远端兜底保留：
1. ByteDance_API_Key（或 BYTEDANCE_API_KEY）  
2. ANTHROPIC_BASE_URL、ANTHROPIC_AUTH_TOKEN（如使用 anthropic_compatible）

## 7. 回归测试点（必须覆盖）

### 7.1 功能正确性
1. 正常链路：本地 provider 可成功生成 detective + suspect 输出。  
2. 因果链路：suspect 输出受到 detective_question 影响（抽样人工验证）。  
3. 失败降级：本地失败时可按配置切到 secondary；secondary 失败后 safe fallback。  
4. 回合状态：12/15 回合限制逻辑不受影响。  
5. 证据注入：下一回合证据引用行为不回归。

### 7.2 稳定性与容错
1. 本地服务未启动：错误可读，且降级可用。  
2. 本地接口返回非 JSON/空输出：可重试并最终可降级。  
3. 超时策略：local timeout 生效，不出现无限等待。  
4. 重试次数：严格遵守配置，不额外隐式重试。

### 7.3 性能
1. 同案件同回合数对比：
- 远端基线 vs 本地 provider 平均时延
- P95 单次调用时延

2. 目标建议：
- 单回合总时延较远端基线下降 >= 40%（设备与模型允许条件下）
- 超时率显著低于当前远端链路

### 7.4 测试文件建议
1. 扩展 tests/test_llm_gateway.py：
- provider 路由、降级链、输出归一化
- 本地 provider 的异常分支
- 豆包 payload 中 temperature/max_tokens 字段存在性验证

2. 视情况扩展：
- tests/test_controller_and_limits.py（确认状态机未回归）
- tests/test_evidence_and_guardrails.py（确认证据与守卫未受影响）

### 7.5 本地联调验收清单（Ollama）
1. 本地可用性：
- `LOCAL_LLM_BASE_URL=http://127.0.0.1:11434/v1` 时，`local_openai_compatible` 能稳定生成 detective + suspect。
- `LOCAL_LLM_MODEL=deepseek-r1-14b-q4`（或用户当前模型别名）能被正确使用，日志可见 model 名称。

2. 首字延迟与总时延：
- 记录本地 provider 的 TTFT（首字延迟）与整次调用耗时，至少抽样 10 次。
- 与远端 bytedance 基线对比，输出平均时延与 P95。

3. 超时与降级：
- 人为停止 Ollama 服务后，请求应在 local timeout 内失败，并按 secondary -> safe fallback 链路降级。
- 日志需明确包含 selected_provider、secondary_provider、output_source。

4. 回合与因果链保护：
- 验证仍为 detective -> suspect 顺序调用，不可并行。
- 验证 suspect prompt 继续包含 detective_question，且回答内容受其影响。

---

## 附：低优先级独立任务 — Fake Typewriter 打字机效果

**优先级**：低（不阻塞本 handoff 主任务，可独立执行）  
**范围**：仅涉及输出展示层，不改动 LLMGateway、TurnOrchestrator 及任何游戏逻辑。

### 背景与判断

流式输出（stream=True）在当前架构下有结构性障碍：
- 模型被要求输出严格 JSON（thought/speech/anchors），流式 chunk 中间态无法解析，流到一半的内容无法直接展示。
- 真正的逐字流式需要改 prompt 结构或在 gateway 内部积累 chunk，属于 v0.2 范畴。

Fake Typewriter 的做法：拿到完整 `GeneratedRoleOutput` 后，在展示层把 `speech` 字段逐字打印，无需改动任何后端逻辑，可立即获得打字机体验。

### 实现要点

1. 修改 `src/interrogation_mvp/cli.py` 的 `_print_turn` 函数：
   - `detective_question` 和 `suspect_answer` 两个字段改为逐字输出。
   - 每字之间加约 30–50ms 延迟（`time.sleep`），延迟值可通过环境变量 `INTERROGATION_TYPEWRITER_DELAY_MS` 控制，默认 40ms，设为 0 则关闭效果。
   - `thought`、`anchors` 等调试字段维持原样一次性打印，不加延迟。

2. 修改 `src/interrogation_mvp/gui.py`（如有展示 speech 的位置）：
   - 视 GUI 框架决定是用定时器逐字插入，还是保持一次性显示；GUI 改动优先级低于 CLI。

3. 不得因此任务改动 `GeneratedRoleOutput`、`TurnResult`、`TurnOrchestrator` 或任何测试文件。

## 8. 未决问题

1. 备用容器策略是否需要在后续版本支持（LM Studio / 其他 OpenAI 兼容服务，作为 Ollama 备选）。  
2. local provider 是否作为默认 primary（建议由环境变量控制，不硬编码）。  
3. 14B 在用户本机显存与上下文长度下的最稳量化规格（Q4/Q5）与上下文上限。  
4. 质量门槛：速度提升与回答质量之间的验收平衡标准（需用户最终拍板）。

## 9. 相关文档

1. README（运行说明与性能日志说明）  
2. docs/handoff/mvp_interrogation_handoff_to_codeexpert_v0.2.md（既有 MVP 移交基线）

## 10. 禁止事项

1. 不得改动回合因果链为并行双角色生成。  
2. 不得删除现有远端 provider 能力。  
3. 不得改变 TurnOrchestrator 对外行为契约。  
4. 不得在未评审情况下扩展非本任务范围功能（如多案件、自动推进、评分系统）。  
5. 不得修改 Phase 序号或新增/删除 Phase。

## 11. CodeExpert 回传要求

1. 变更清单：具体文件与核心改动说明。  
2. 配置样例：本地 provider 最小可运行配置（含环境变量示例）。  
3. 回归结果：功能、稳定性、性能三类测试结论。  
4. 风险列表：已知问题、触发条件、建议后续优化方向。
