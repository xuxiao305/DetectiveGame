# Handoff to CodeExpert: InterrogationRoom MVP v0.2 (Execution)

版本：v0.2  
日期：2026-04-02  
移交角色：Architect  
接收角色：CodeExpert

## 1. 任务目标

在既定 MVP 范围与既定架构约束下，实现可演示、可回放、可测试的《审讯室》原型：
- 固定单案件加载
- 手动回合推进
- 证据注入（固定列表）
- 每回合矛盾检测与即时显示
- 结束页导出（完整对话 + 去重矛盾 + 使用证据）

## 2. 已确认约定（冻结）

1. 回合推进方式：手动推进，每轮完整展示四段文本后才允许下一轮。
2. 回合上限：软上限 12，硬上限 15；第 12 轮提示收束，第 15 轮强制结算。
3. 认罪边界：禁止主动完整认罪；允许阶段性松口；高压条件下仅进入“接近认罪”。
4. 矛盾检测频率：每回合检测并即时展示；结束时全局去重汇总。
5. 模型参数方向：稳定优先、一致性优先、戏剧性次之（低随机、低发散）。

## 3. 术语映射

- “架构师agent”“架构师” = Architect
- “设计师agent”“设计师” = AIDesigner
- “CodeExpert”“编码专家”“coder” = CodeExpert

## 4. 当前结论（实现基线）

### 4.1 模块清单
- UI/GameController
- CaseLoader
- StateStore
- TurnOrchestrator
- PromptComposer
- LLMGateway
- EvidenceInjectionHandler
- ContradictionDetector
- TranscriptExporter

### 4.2 P0/P1/P2 优先级
- P0：端到端链路可跑通（开始 -> 多轮 -> 注入 -> 结束导出）。
- P1：回合守卫、输出格式规范化、错误重试。
- P2：矛盾检测精度优化与去重质量优化。

### 4.3 交付定义（DoD）
- 连续 10 回合稳定，无明显脱离案件世界观。
- 注入证据后下一回合必定出现证据语义引用。
- 12/15 回合行为准确。
- 结束页三类输出完整且可读。

## 5. 接口级 TODO（CodeExpert 直接按此开发）

## 5.1 GameController
- TODO-GC-01：实现 `startSession()` 初始化入口。
- TODO-GC-02：实现 `nextTurn()` 手动推进入口。
- TODO-GC-03：实现 `injectEvidence(evidenceId)` 注入入口。
- TODO-GC-04：实现 `endSession(reason)` 结束入口。

约束：
- `nextTurn()` 必须先检查 `status` 与硬上限。
- 在 `status=HARD_LIMIT` 时禁止继续生成。

## 5.2 StateStore
- TODO-SS-01：定义 `GameState`、`DialogueTurn`、`ContradictionItem`。
- TODO-SS-02：提供 `loadState(sessionId)`、`saveState(state)`。
- TODO-SS-03：实现回合原子写入，避免“显示成功但状态未提交”。

约束：
- MVP 可用内存态，但接口需兼容未来文件落盘。

## 5.3 TurnOrchestrator
- TODO-TO-01：实现 `runTurn(sessionId)` 主流程。
- TODO-TO-02：按顺序生成四段内容：侦探内心 -> 侦探提问 -> 嫌疑人内心 -> 嫌疑人回答。
- TODO-TO-03：在本轮末调用矛盾检测并返回 `newContradictions`。
- TODO-TO-04：执行回合上限状态迁移（RUNNING -> SOFT_LIMIT -> HARD_LIMIT）。

## 5.4 PromptComposer
- TODO-PC-01：实现 `buildDetectivePrompt(context)`。
- TODO-PC-02：实现 `buildSuspectPrompt(context)`。
- TODO-PC-03：实现证据注入后的“下一轮强制引用”规则。
- TODO-PC-04：实现认罪边界规则注入（禁止完整认罪）。

## 5.5 LLMGateway
- TODO-LG-01：实现统一调用 `generate(role, prompt, options)`。
- TODO-LG-02：实现超时和单次重试。
- TODO-LG-03：实现输出规范化，保证 `thought/speech/anchors` 可解析。

## 5.6 EvidenceInjectionHandler
- TODO-EI-01：实现证据可用性校验（未使用才可注入）。
- TODO-EI-02：注入后写入 `pendingEvidenceIds`。
- TODO-EI-03：消费后写入 `usedEvidenceIds`。

## 5.7 ContradictionDetector
- TODO-CD-01：实现规则层检测：TIME/LOCATION/BEHAVIOR/ALIBI/MOTIVE。
- TODO-CD-02：实现新增矛盾与历史矛盾去重逻辑。
- TODO-CD-03：返回当轮新增项与全局更新结果。

## 5.8 TranscriptExporter
- TODO-TE-01：实现 `exportSession(sessionId)`。
- TODO-TE-02：输出完整对话（含内心独白）。
- TODO-TE-03：输出去重后矛盾列表与证据使用列表。

## 6. Week1-Week4 执行计划（接口级）

### Week 1（P0 基础链路）
- 完成 `GameController` 四个入口。
- 完成 `StateStore` 内存态读写。
- 完成 `TurnOrchestrator` 单轮流程。
- 完成最简文本 UI（开始/下一轮/结束）。

周验收：
- 单回合四段文本可稳定输出。
- 会话状态可创建、更新、结束。

### Week 2（稳定与约束）
- 完成 `PromptComposer` 双角色模板。
- 完成 `LLMGateway` 超时、重试、输出规范化。
- 接入回合上限状态机（12/15）。
- 增加回合守卫（侦探追问不断链、嫌疑人不完整认罪）。

周验收：
- 连续 10 回合可跑通。
- 第 12 轮提示、第 15 轮强制结束生效。

### Week 3（证据与矛盾）
- 完成 `EvidenceInjectionHandler` 全链路。
- 完成 `ContradictionDetector` 规则层检测与去重。
- UI 展示“当轮新增矛盾”。

周验收：
- 注入证据后下一轮可见明确引用。
- 至少识别 3 类关键矛盾。

### Week 4（导出与联调）
- 完成 `TranscriptExporter`。
- 完成端到端联调与异常路径补测。
- 输出 5 轮内部测试结果与问题清单。

周验收：
- 结束页输出完整、结构化、可读。
- 已知高优先级问题有修复或明确标注。

## 7. 未决问题（需先确认）

1. 运行形态：CLI 文本界面 or 轻量 Web。
2. 具体模型与 SDK：OpenAI/其他网关。
3. 状态持久化：仅内存 or 文件落盘。
4. 语义复核层：本期是否上线，还是留到下一迭代。

若以上未决项未明确，默认采用：CLI + 单模型 SDK + 内存态 + 仅规则检测。

## 8. 相关文档

1. 《审讯室》MVP 原型文档（需求边界与验证标准）
2. MVP_Technical_Design_v0.1（架构、状态机、时序、配置）

## 9. 禁止事项

1. 不得改动 5 项冻结架构决策。
2. 不得将手动推进改为自动推进。
3. 不得新增多案件、评分、复盘分析等非 MVP 能力。
4. 不得私自改动状态机定义与对外接口契约。
5. 不得为了戏剧化提高随机性到破坏一致性。

## 10. 提交与回传要求（CodeExpert -> Architect）

每周回传包最少包含：
- 本周完成的 TODO 编号列表
- 关键文件清单与变更说明
- 未完成 TODO 与阻塞原因
- 一组可复现实验步骤

最终回传包追加：
- 10 回合样例输出（至少 1 组）
- 5 轮内部测试记录
- 已知问题与下一步建议
