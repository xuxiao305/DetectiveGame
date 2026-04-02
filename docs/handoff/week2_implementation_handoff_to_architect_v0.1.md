# Handoff to Architect: InterrogationRoom Week2 Implementation Status

版本：v0.1  
日期：2026-04-02  
移交角色：CodeExpert  
接收角色：Architect

## 1. 任务目标

向 Architect 回传《审讯室》MVP 在 Week1-Week2 阶段的实现落地情况、测试结果、未决问题与后续审查重点，用于进行架构一致性审查与 Week3 启动决策。

## 2. 已确认约定（沿用冻结项）

1. 回合推进：手动推进，每轮完整展示四段文本后进入下一轮。
2. 回合上限：软上限 12，硬上限 15。
3. 认罪边界：禁止主动完整认罪，允许阶段性松口。
4. 矛盾检测频率：每回合检测并即时显示，结束时去重汇总。
5. 模型参数方向：稳定优先、一致性优先、戏剧性次之。

## 3. 术语映射

- “架构师agent”“架构师” = Architect
- “设计师agent”“设计师” = AIDesigner
- “CodeExpert”“编码专家”“coder” = CodeExpert

## 4. 当前结论

### 4.1 已实现模块
- CaseLoader（固定案件、固定证据）
- StateStore（内存态 load/save）
- GameController（start/next/inject/end）
- TurnOrchestrator（单轮完整编排与状态迁移）
- PromptComposer（双角色模板 + 证据强制引用）
- LLMGateway（超时、重试、输出规范化、容错降级）
- TurnGuard（侦探推进守卫 + 认罪边界守卫）
- ContradictionDetector（规则层 + 去重）
- TranscriptExporter（完整对话 + 去重矛盾 + 使用证据）
- CLI（n/i/e 交互）

### 4.2 已完成 TODO 映射（来自 handoff v0.2）
- TODO-GC-01/02/03/04：已完成。
- TODO-SS-01/02/03：已完成（内存态原子写入）。
- TODO-TO-01/02/03/04：已完成。
- TODO-PC-01/02/03/04：已完成。
- TODO-LG-01/02/03：已完成。
- TODO-EI-01/02/03：已完成。
- TODO-CD-01/02/03：已完成（规则层版本）。
- TODO-TE-01/02/03：已完成。

### 4.3 测试结果
- 单元测试：7/7 通过。
- 冒烟测试：通过（10 回合稳定、注入证据后下一回合引用、认罪边界保持）。

## 5. 未决问题（建议 Architect 拍板）

1. Week3 的“语义复核层”是否在本迭代接入，还是继续维持纯规则检测。
2. 运行形态是否从 CLI 迁移为轻量 Web（当前默认兜底是 CLI）。
3. 状态持久化是否在 Week3 增加本地文件落盘（当前为内存态）。
4. 模型网关是否接入真实 SDK（当前为 deterministic fallback + 统一网关接口）。

## 6. 相关文档与实现文件

### 6.1 协作与需求文档
- docs/handoff/mvp_interrogation_handoff_to_codeexpert_v0.2.md

### 6.2 核心实现
- main.py
- src/interrogation_mvp/controller.py
- src/interrogation_mvp/orchestrator.py
- src/interrogation_mvp/llm_gateway.py
- src/interrogation_mvp/guardrails.py
- src/interrogation_mvp/contradiction.py
- src/interrogation_mvp/exporter.py
- src/interrogation_mvp/cli.py

### 6.3 测试与验证
- scripts/week2_smoke_test.py
- tests/test_controller_and_limits.py
- tests/test_evidence_and_guardrails.py
- tests/test_llm_gateway.py

## 7. 禁止事项（继续沿用）

1. 不改动 5 项冻结架构决策。
2. 不将手动推进改为自动推进。
3. 不新增多案件、评分、复盘分析等非 MVP 能力。
4. 不在未审查前调整状态机核心语义与外部接口契约。

## 8. 建议 Architect 审查重点

1. 当前 TurnGuard 是否充分覆盖“侦探追问不断链”约束。
2. 矛盾检测规则类别与严重级别是否满足 Week3 目标。
3. 真实模型接入后是否需要新增输出格式二次校验层。
4. 是否批准 Week3 优先项：矛盾检测细化 + 展示分级。

## 9. 当前已知风险

1. 目前对话生成为 deterministic fallback，真实模型接入后稳定性需重新验证。
2. 规则矛盾检测对隐喻与复杂改写的覆盖有限。
3. 内存态会话不可跨进程持久化。
