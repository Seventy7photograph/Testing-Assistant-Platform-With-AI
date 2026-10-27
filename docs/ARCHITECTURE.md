<p align="center">
  <img src="assets/doc-banner.svg" alt="测试工程师助手平台架构与设计" width="100%">
</p>

# 架构与设计

## 系统分层

```text
HTTP 路由
    │ 参数校验、身份上下文、响应包装
    ▼
应用服务
    │ 业务编排、权限、审计、降级策略
    ▼
领域能力
    │ 解析、设计、导出、模型、指标、知识检索
    ▼
持久化与外部连接
    │ JSON / SQLite / Jira / 禅道 / DeepSeek / OCR
```

后端目录：

| 目录 | 责任 |
| --- | --- |
| `app/api/routes` | REST 路由 |
| `app/services` | 应用编排 |
| `app/schemas` | Pydantic 契约 |
| `app/parsers` | 文档解析 |
| `app/vision` | 图片识别通道 |
| `app/design` | 六种测试设计方法与优化 |
| `app/exporters` | 用例导出器 |
| `app/report` | 指标、报告、存档与趋势 |
| `app/automation` | pytest 模板与静态安全门禁 |
| `app/execution` | JUnit 与受控 HTTP 执行 |
| `app/knowledge` | SQLite FTS5 知识索引 |
| `app/agent` | 只读助手工具 |
| `app/assistant` | Search/Fetch 客户端 |
| `app/integrations` | Jira / 禅道适配器 |
| `app/repository.py` | JSON / SQLite 持久化门面 |

## 确定性事实与模型边界

平台将数据和模型输出分开处理：

- 指标、阈值、状态、配额、编号、安全门禁与资产版本由服务端确定性计算。
- 模型只负责抽取、复核、归纳、建议、问答和代码建议。
- 模型不能直接改写规则用例、权威指标、项目资产或执行状态。
- 模型失败时返回规则结果和明确降级原因。

自动化 AI 采用“建议 → 人工决定 → 派生新版本”的流程。原资产和源 case 始终不可变。

## Prompt 可信工程

每个模型任务使用独立 Prompt：

| Prompt | 任务 | 关键边界 |
| --- | --- | --- |
| `requirement.extract` | 需求抽取 | 原文只作为测试素材 |
| `design.scenario_enrichment` | 场景补缺 | 单条需求与已有用例标题 |
| `design.generation_review` | 规则产出复核 | 只提意见，不改写 |
| `report.summarize` | 报告归纳 | 指标由服务端提供 |
| `api.case_review` | 接口用例复核 | 不含密钥和完整请求体 |
| `automation.operation_gap` | operation 缺口 | 只允许引用来源结构 |
| `automation.failure_assertion` | 失败断言 | 失败摘要与来源 case |
| `automation.fixture_recipe` | 数据配方 | 不发送真实请求值 |
| `automation.script_review` | 脚本只读审查 | 仅安全校验通过的资产 |
| `assistant.answer` | 测试问答与代码建议 | 网页与用户输入均为不可信数据 |

证据校验会做字符归一化，输出 `verified`、`inferred`、`rejected`。无效证据不进入确定性流程。

## 项目隔离与审计

- 项目身份从鉴权后的请求上下文进入业务层。
- 项目模式隔离文档、需求、用例、接口资产、执行记录、报告、知识索引和审计。
- 助手会话、知识检索和工具调用都校验项目边界。
- 模型、联网、外部连接和工具调用记录状态、摘要与错误，不记录完整密钥或请求凭据。

## 扩展点

| 扩展点 | 抽象与注册表 |
| --- | --- |
| 文档解析 | `DocumentParser` + parser registry |
| 图片识别 | `ImageTextExtractor` + vision registry |
| 测试设计 | `DesignStrategy` + design registry |
| 用例导出 | `Exporter` + exporter registry |
| 模型提供方 | `LLMProvider` + provider factory |
| 外部集成 | `ExternalSyncAdapter` |

新增实现应通过注册表进入能力清单，前端从服务端读取，不硬编码。

## 数据存储

- 默认 JSON 存储适合单机、零依赖运行。
- SQLite 存储适合更集中的事务和查询。
- 两种后端对业务层提供一致接口。
- 项目模式使用 `storage/projects/<project_id>/`。
- 知识索引使用 SQLite FTS5。
- 报告存档使用 SQLite。
- 上传原文、导出文件与运行日志按受控目录保存。

## 工作台

前端采用 Vue 3 + TypeScript + Pinia。

```text
AppShell
├── SideRail        主导航
├── TopBar          项目、搜索、密度、主题、帮助
├── Router Views    业务工作区
├── AssistantRail   右侧助手入口
└── AssistantPanel  持久会话与引用
```

当前主要页面：

- 总览
- 用例生成
- 文档与需求
- 结构化需求
- 接口资产
- 接口详情
- 用例集
- 用例集详情
- 测试报告
- 报告存档
- 报告详情
- 自动化资产
- 执行记录
- 工作事项
- 项目
- 外部连接
- 运行任务
- 知识索引
- 模型设置

## 视觉与界面

界面视觉、真实截图、布局、组件、动效和文案规则统一维护在 [设计系统](../DESIGN.md)。
设计文档中的截图来自独立临时存储、Fake 模型和合成数据，不包含真实业务信息。

## 安全边界

- 不执行任意 Python、shell 或用户代码。
- 自动化资产通过静态门禁后才可下载。
- 受控 HTTP 执行限制目标主机、方法、超时、并发、用例数和响应体。
- Markdown 渲染先整体转义，再恢复白名单记号。
- 网页正文只作为不可信资料进入 Prompt。
- 密钥只通过环境变量注入。
- 外部集成缺失时返回明确错误，不伪造连接成功。
