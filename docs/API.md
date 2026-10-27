<p align="center">
  <img src="assets/doc-banner.svg" alt="测试工程师助手平台 API 文档" width="100%">
</p>

# API 参考

本文是当前 REST API 的完整入口索引。服务启动后可使用 Swagger 查看实时 schema：

- Swagger：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

以下路径默认省略统一前缀 `/api/v1`。

## 通用约定

### 响应

成功：

```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "data": {}
}
```

失败：

```json
{
  "success": false,
  "code": "BAD_REQUEST",
  "message": "请求参数不合法",
  "detail": {}
}
```

### 请求头

| 请求头 | 说明 |
| --- | --- |
| `X-Project-ID` | 项目分区 ID |
| `X-API-Key` | `AUTH_ENABLED=true` 时的访问令牌 |
| `Content-Type` | JSON、multipart 或流式请求对应类型 |

文件上传字段统一使用 `file`。

## 健康、总览与模型

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 应用状态、模型能力、设计方法、导出格式与执行限制 |
| GET | `/overview` | 首页总览数据 |
| GET | `/llm/config` | 当前生效模型配置 |
| PUT | `/llm/config` | 保存运行时模型覆盖 |
| DELETE | `/llm/config` | 恢复 `.env` 基线 |
| POST | `/llm/config/test` | 模型连通性测试 |
| GET | `/llm/models` | 候选模型列表 |
| GET | `/llm/prompts` | Prompt 注册表与版本 |
| GET | `/llm/routing` | 模型路由预览 |

### 配置模型

```json
{
  "provider": "openai_compatible",
  "base_url": "https://example.invalid/v1",
  "model": "demo-model",
  "api_key": "replace-with-secret"
}
```

响应只返回脱敏配置，不回显完整 Key。

## 文档与需求

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/documents/upload` | 上传并解析文档或图片 |
| GET | `/documents` | 最近文档 |
| GET | `/documents/{doc_id}` | 文档详情 |
| GET | `/documents/{doc_id}/download` | 下载原文 |
| GET | `/documents/{doc_id}/images/{filename}` | 查看文档内图片 |
| POST | `/documents/{doc_id}/images/recognize` | 重新识别图片 |
| GET | `/documents/vision/capabilities` | 当前图片识别能力 |
| DELETE | `/documents/{doc_id}` | 删除文档、原文和解析结果 |
| POST | `/documents/batch-delete` | 批量删除文档 |
| POST | `/requirements/parse` | 将文本或已上传文档解析为结构化需求 |
| GET | `/requirements/{doc_id}` | 读取结构化需求 |
| POST | `/requirements/{doc_id}/testcases` | 基于已解析需求生成用例 |
| GET | `/requirements/{doc_id}/diff` | 需求版本差异 |
| GET | `/requirements/{doc_id}/traceability` | 需求与用例双向追溯 |
| DELETE | `/requirements/{doc_id}` | 删除结构化需求 |
| GET | `/vision/config` | 图片识别运行时配置 |
| PUT | `/vision/config` | 保存图片识别配置 |
| DELETE | `/vision/config` | 恢复 `.env` 基线 |
| POST | `/vision/config/test` | 图片识别探针 |

### 上传文档

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/documents/upload" `
  -H "X-Project-ID: PRJ-demo" `
  -F "file=@examples/sample_requirement.md"
```

### 解析需求

```json
{
  "doc_id": "DOC-demo",
  "title": "登录接口需求",
  "use_llm": true,
  "max_items": 8
}
```

## 用例生成、分析与导出

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/pipeline/generate` | 一键完成文档解析、需求结构化与用例生成 |
| GET | `/testcases/methods` | 六种设计方法及实现状态 |
| POST | `/testcases/generate` | 从文本或文档生成用例集 |
| GET | `/testcases/suites` | 用例集列表 |
| GET | `/testcases/{suite_id}` | 用例集详情 |
| GET | `/testcases/{suite_id}/coverage` | 字段、边界、规则覆盖率 |
| DELETE | `/testcases/{suite_id}` | 删除用例集 |
| POST | `/testcases/batch-delete` | 批量删除用例集 |
| GET | `/export/formats` | 可用导出格式 |
| POST | `/export` | 导出用例集文件流 |
| GET | `/export/{suite_id}/{fmt}` | 路径式导出 |

### 生成用例

```json
{
  "doc_id": "DOC-demo",
  "methods": [
    "equivalence",
    "boundary",
    "scenario",
    "decision_table",
    "cause_effect",
    "orthogonal"
  ],
  "use_llm": true,
  "use_llm_in_design": true,
  "llm_design_mode": "review",
  "max_items": 8,
  "max_cases_per_requirement": 200
}
```

可用导出格式：`excel`、`json`、`csv`、`xmind`、`testlink`。

## 接口资产

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api-specs/import` | 导入 OpenAPI 3 JSON/YAML |
| GET | `/api-specs` | 接口规范列表 |
| GET | `/api-specs/{spec_id}` | 规范详情 |
| GET | `/api-specs/{spec_id}/operations` | operation 列表 |
| GET | `/api-specs/{spec_id}/operations/{operation_id}` | operation 详情 |
| GET | `/api-specs/{spec_id}/cases` | 接口用例列表 |
| POST | `/api-specs/{spec_id}/review` | 大模型只读复核 |
| GET | `/api-specs/{spec_id}/export/postman` | 导出 Postman Collection 2.1 |
| DELETE | `/api-specs/{spec_id}` | 删除规范及派生用例 |

导入示例：

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/api-specs/import" `
  -H "X-Project-ID: PRJ-demo" `
  -F "file=@examples/openapi-demo.yml"
```

## 自动化资产与执行

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/automation/artifacts` | 生成版本化 pytest 资产 |
| GET | `/automation/artifacts` | 资产列表 |
| GET | `/automation/artifacts/{artifact_id}` | 资产详情与安全校验 |
| GET | `/automation/artifacts/{artifact_id}/cases` | 资产内用例摘要、风险与所需变量 |
| GET | `/automation/artifacts/{artifact_id}/download` | 下载通过校验的 zip |
| DELETE | `/automation/artifacts/{artifact_id}` | 删除未关联执行的资产 |
| POST | `/automation/runs/import` | 导入 JUnit XML |
| GET | `/automation/runs` | 执行记录列表 |
| GET | `/automation/runs/{run_id}` | 执行记录详情 |
| DELETE | `/automation/runs/{run_id}` | 删除执行记录 |
| GET | `/automation/runs/{run_id}/report-source` | 转换报告数据源 |
| POST | `/automation/runs/{run_id}/follow-up` | 创建失败跟进事项 |
| GET | `/automation/events` | 查询结构化事件 |
| GET / POST | `/execution/environments` | 项目接口测试环境列表 / 创建 |
| PUT / DELETE | `/execution/environments/{environment_id}` | 更新 / 删除环境 |
| POST | `/execution/http` | 受控执行资产中的接口用例 |

### 生成自动化资产

```json
{
  "spec_id": "SPEC-demo",
  "case_ids": ["API-GET-001", "API-POST-002"],
  "name": "demo-api-suite"
}
```

### 受控执行

```json
{
  "artifact_id": "AUTO-demo",
  "case_ids": ["API-GET-001"],
  "environment": {
    "BASE_URL": "https://example.invalid"
  },
  "base_url": "https://example.invalid",
  "allow_all_cases": false,
  "idempotency_key": "demo-run-001"
}
```

`case_ids=[]` 时必须显式设置 `allow_all_cases=true`。缺少路径或请求变量的用例会记为
`skipped`，不会发送包含 `{{变量}}` 的请求。单次最多执行 2000 条，并继续受并发、
单请求超时和响应体上限保护。

## 受控 AI 建议

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/automation/ai/reviews` | 创建四类只读建议 |
| GET | `/automation/ai/reviews` | 建议列表 |
| GET | `/automation/ai/reviews/{review_id}` | 建议详情 |
| PUT | `/automation/ai/reviews/{review_id}/findings/{finding_id}` | 采纳/驳回单条意见 |
| PUT | `/automation/ai/reviews/{review_id}/decision` | 采纳/驳回配方整体 |
| POST | `/automation/ai/reviews/{review_id}/apply` | 派生新资产版本 |
| GET | `/automation/ai/reviews/{review_id}/recipe` | 下载脱敏配方 |

任务类型：

- `operation_gap`
- `failure_assertion`
- `fixture_recipe`
- `script_review`

## 工作事项

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/work-items` | 列表与筛选 |
| POST | `/work-items` | 创建 note/task |
| GET | `/work-items/{work_item_id}` | 详情 |
| PUT | `/work-items/{work_item_id}` | 更新 |
| DELETE | `/work-items/{work_item_id}` | 删除 |
| POST | `/work-items/{work_item_id}/complete` | 完成 |
| POST | `/work-items/{work_item_id}/archive` | 归档 |
| GET | `/work-items/summary` | 收件箱、今日、近期、逾期与完成摘要 |
| GET | `/work-items/reminders/due` | 到期提醒 |
| POST | `/work-items/reminders/ack` | 幂等确认提醒 |

创建示例：

```json
{
  "kind": "task",
  "title": "补齐登录接口异常断言",
  "body": "补充 401、423 与 429 响应断言。",
  "priority": "P1",
  "due_at": "2026-11-01T18:00:00+08:00",
  "tags": ["api", "regression"],
  "pinned": true
}
```

## 测试报告

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/report/status` | 报告模块状态 |
| POST | `/report/metrics` | 只计算指标 |
| GET | `/report/samples` | 内置示例数据 |
| POST | `/report/analyze` | 指标与 AI 报告 |
| POST | `/report/analyze/stream` | SSE 流式报告 |
| POST | `/report/probe` | 报告模型探活 |
| GET | `/report/reports` | 报告列表 |
| GET | `/report/reports/{report_id}` | 报告详情 |
| DELETE | `/report/reports/{report_id}` | 删除报告 |
| POST | `/report/reports/batch-delete` | 批量删除 |
| GET | `/report/reports/{report_id}/export` | 导出 `md`、`html`、`docx`、`json` |
| GET | `/report/trends` | 趋势数据 |
| GET | `/report/thresholds` | 发版阈值 |
| PUT | `/report/thresholds` | 保存阈值 |
| DELETE | `/report/thresholds` | 恢复阈值基线 |

流式接口返回 `text/event-stream`，事件类型包含进度、正文增量、完成和错误。

## 项目、外部连接与任务

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/projects` | 项目列表 |
| POST | `/projects` | 创建项目 |
| GET | `/projects/current` | 当前请求项目上下文 |
| PATCH | `/projects/{project_id}` | 更新项目与配额 |
| GET | `/projects/{project_id}/audit` | 项目审计 |
| GET | `/integrations` | 外部集成清单 |
| GET | `/integrations/capabilities` | 适配器能力 |
| POST | `/integrations/{name}/health` | 健康检查 |
| POST | `/integrations/{name}/requirements/pull` | 拉取外部需求 |
| POST | `/integrations/{name}/requirements/import` | fixture 导入 |
| POST | `/integrations/{name}/requirements/file` | JSON 文件导入 |
| POST | `/integrations/{name}/suites/{suite_id}/push` | 用例回写 |
| GET | `/integrations/{name}/requirements/{external_id}/status` | 状态回读 |
| POST | `/jobs` | 登记任务 |
| GET | `/jobs` | 任务历史 |
| GET | `/jobs/{job_id}` | 任务详情 |
| POST | `/jobs/{job_id}/cancel` | 取消未结束任务 |
| GET | `/jobs/{job_id}/events` | 事件时间线 |
| POST | `/schedules` | 登记调度定义 |
| GET | `/schedules` | 调度定义列表 |
| GET | `/agent-runs` | Agent 运行历史 |
| GET | `/tool-calls` | 工具调用审计 |

## 知识库与助手

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/knowledge/stats` | 当前项目索引统计 |
| POST | `/knowledge/search` | FTS5 检索 |
| POST | `/knowledge/sync` | 重建项目索引 |
| GET | `/assistant/tools` | 只读工具白名单 |
| GET | `/assistant/status` | 模型、联网、上下文与预算状态 |
| GET | `/assistant/conversations` | 会话列表 |
| GET | `/assistant/conversations/{conversation_id}` | 会话详情 |
| POST | `/assistant/ask` | 持久会话回答 |

### 助手请求

```json
{
  "message": "为一个登录接口设计 Python pytest 测试",
  "current_path": "/apis/SPEC-demo",
  "conversation_id": "CONV-demo",
  "allow_web_search": true
}
```

响应包含：

- 最终回答与状态；
- 当前事实；
- 知识与网页引用；
- 推断与建议；
- 工具调用记录；
- 警告与真实降级原因；
- 会话轮次和上下文用量。

## 错误处理

| HTTP | 典型原因 |
| --- | --- |
| `400` | 参数组合不完整或业务输入不合法 |
| `401/403` | 鉴权失败或项目不匹配 |
| `404` | 项目内资源不存在 |
| `409` | 外部连接缺失、资产未通过校验或版本冲突 |
| `413` | 文件超过上传限制 |
| `415` | 不支持的文件格式 |
| `422` | Pydantic 校验失败、文档或 JUnit XML 无法解析 |
| `429` | 助手请求过快或会话达到限制 |
| `501` | 当前未实现的扩展能力 |
| `502` | 模型或外部服务调用失败 |

助手请求被降级时仍可能返回 `200`，但会设置 `status="degraded"`、`degraded_reason` 和具体
`warnings`。普通安全提示不会单独触发降级。
