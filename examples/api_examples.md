# 接口调用示例

服务地址统一为 `http://127.0.0.1:8000`，接口前缀 `/api/v1`。

统一响应结构：

```json
{ "success": true, "code": "OK", "message": "OK", "data": { } }
```

失败时：

```json
{ "success": false, "code": "UNSUPPORTED_FORMAT", "message": "暂不支持 .xlsx 格式。当前支持：...", "detail": { } }
```

---

## 0. 健康检查与能力清单

```bash
curl http://127.0.0.1:8000/api/v1/health
```

关键字段：`llm_available`（是否真的能用大模型）、`llm_degraded_reason`（降级原因）、
`methods`（六种设计方法，`implemented` 由后端如实上报，**界面可用性以此为准**）、
`export_formats`（excel / json / csv / xmind / testlink）、`supported_extensions`、
`vision`（图片识别通道与降级原因）、`limits`（生效的引擎上限，如 `max_cases_per_requirement`）。

---

## 1. 上传文档

```bash
curl -X POST http://127.0.0.1:8000/api/v1/documents/upload \
  -F "file=@examples/sample_requirement.md"
```

PowerShell：

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/documents/upload `
  -F "file=@examples/sample_requirement.md"
```

返回：

```json
{
  "success": true,
  "code": "OK",
  "message": "文档解析成功",
  "data": {
    "doc_id": "DOC-1a2b3c4d",
    "filename": "sample_requirement.md",
    "extension": "md",
    "char_count": 1248,
    "parser": "text",
    "table_count": 0,
    "warnings": [],
    "preview": "# 电商订单系统需求说明书（示例）..."
  }
}
```

---

## 2. 解析需求（文档 ID 或直接粘贴文本）

```bash
# 按已上传文档解析
curl -X POST http://127.0.0.1:8000/api/v1/requirements/parse \
  -H "Content-Type: application/json" \
  -d '{"doc_id": "DOC-1a2b3c4d", "use_llm": true, "max_items": 10}'

# 直接粘贴文本
curl -X POST http://127.0.0.1:8000/api/v1/requirements/parse \
  -H "Content-Type: application/json" \
  -d '{"text": "## 用户注册\n手机号：11位数字，必填\n年龄：18~120", "title": "注册需求", "use_llm": true}'
```

返回（截断）：

```json
{
  "data": {
    "doc_id": "DOC-1a2b3c4d",
    "title": "注册需求",
    "summary": "共解析出 1 条需求、2 个可测字段，覆盖模块：默认模块",
    "items": [
      {
        "id": "REQ-001",
        "title": "用户注册",
        "module": "默认模块",
        "fields": [
          { "name": "手机号", "data_type": "string", "required": true,
            "min_length": 11, "max_length": 11, "pattern": "^1[3-9]\\d{9}$" },
          { "name": "年龄", "data_type": "integer", "min_value": 18, "max_value": 120 }
        ],
        "main_flow": [],
        "business_rules": []
      }
    ],
    "parse_meta": {
      "provider": "rule",
      "llm_used": false,
      "fallback_used": true,
      "fallback_reason": "未配置 LLM_API_KEY，已自动降级为纯规则引擎（provider=deepseek）。..."
    }
  }
}
```

> `parse_meta` 是判断"结果可信度"的关键：`provider=rule` + `fallback_used=true` 表示当前是规则引擎结果。

---

## 3. 一键生成用例（推荐）

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pipeline/generate \
  -H "Content-Type: application/json" \
  -d '{
        "doc_id": "DOC-1a2b3c4d",
        "methods": ["equivalence", "boundary", "scenario"],
        "use_llm": true,
        "max_items": 10,
        "use_llm_in_design": false
      }'
```

只生成部分方法：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/pipeline/generate \
  -H "Content-Type: application/json" \
  -d '{"text": "## 登录\n- 密码：8-20位，必填", "methods": ["boundary"], "use_llm": false}'
```

返回（截断）：

```json
{
  "data": {
    "requirement_doc": { "doc_id": "DOC-...", "items": [ ... ] },
    "suite": {
      "suite_id": "SUITE-9f8e7d6c",
      "doc_id": "DOC-...",
      "methods": ["equivalence", "boundary", "scenario"],
      "stats": {
        "total": 42,
        "duplicate_removed": 0,
        "by_method": { "等价类划分": 18, "边界值分析": 16, "场景法": 8 },
        "by_type": { "异常": 21, "功能": 11, "边界": 6, "场景": 4 },
        "by_priority": { "P1": 9, "P2": 33 },
        "requirement_coverage": { "REQ-001": 42 }
      },
      "parse_meta": { "provider": "rule", "llm_used": false, "fallback_used": true, "fallback_reason": "未配置 LLM_API_KEY" },
      "generation_meta": { "methods": ["equivalence", "boundary", "scenario"], "llm_used": false, "llm_provider": "rule", "fallback_used": true, "warnings": [ ] },
      "cases": [
        {
          "case_id": "TC-BV-001",
          "title": "[边界值] 登录｜密码 最小长度-1",
          "module": "默认模块",
          "requirement_ids": ["REQ-001"],
          "design_method": "boundary",
          "case_type": "异常",
          "priority": "P1",
          "preconditions": [],
          "steps": [{ "no": 1, "action": "在「登录」中，密码 输入 长度 7 的字符串（长度7（最小长度-1））后提交", "expected": "提交被拒绝，提示取值超出允许范围（长度7（最小长度-1））" }],
          "expected_result": "系统拒绝越界取值（长度7（最小长度-1））并给出明确错误提示。约束：必填，长度 8~20",
          "test_data": { "密码": "AAAAAAA" },
          "tags": ["边界值分析", "密码", "越界"],
          "source": "rule",
          "checksum": "9f2c1a4b7e0d3f56",
          "covered_methods": ["equivalence", "boundary"]
        }
      ]
    },
    "warnings": []
  }
}
```

---

## 4. 生成与查询的其它接口

```bash
# 仅生成用例（不返回需求模型）
curl -X POST http://127.0.0.1:8000/api/v1/testcases/generate \
  -H "Content-Type: application/json" -d '{"doc_id": "DOC-xxx", "methods": ["equivalence"]}'

# 设计方法清单（含 未实现项）
curl http://127.0.0.1:8000/api/v1/testcases/methods

# 最近生成的用例集
curl "http://127.0.0.1:8000/api/v1/testcases/suites?limit=5"

# 用例集详情
curl http://127.0.0.1:8000/api/v1/testcases/SUITE-9f8e7d6c

# 基于已解析需求重新生成（切换设计方法时不重复调用 LLM 解析）
curl -X POST "http://127.0.0.1:8000/api/v1/requirements/DOC-xxx/testcases?use_llm_in_design=true" \
  -H "Content-Type: application/json" -d '["equivalence", "boundary", "scenario"]'
```

---

## 5. 导出

```bash
# 方式一：POST 获取文件流
curl -X POST http://127.0.0.1:8000/api/v1/export \
  -H "Content-Type: application/json" \
  -d '{"suite_id": "SUITE-9f8e7d6c", "format": "excel"}' \
  -o 测试用例.xlsx

# 方式二：浏览器/下载器直接 GET
curl -OJ http://127.0.0.1:8000/api/v1/export/SUITE-9f8e7d6c/excel
curl -OJ http://127.0.0.1:8000/api/v1/export/SUITE-9f8e7d6c/json
curl -OJ http://127.0.0.1:8000/api/v1/export/SUITE-9f8e7d6c/csv
curl -OJ http://127.0.0.1:8000/api/v1/export/SUITE-9f8e7d6c/xmind
curl -OJ http://127.0.0.1:8000/api/v1/export/SUITE-9f8e7d6c/testlink

# 可用格式
curl http://127.0.0.1:8000/api/v1/export/formats
```

> 格式名以注册表为准：Excel 是 **`excel`**（不是文件后缀 `xlsx`），拼错会返回 404。

PowerShell 下载：

```powershell
curl.exe -OJ "http://127.0.0.1:8000/api/v1/export/SUITE-9f8e7d6c/excel"
```

---

## 5.1 V2.0 新增接口速查

```bash
# 覆盖率分析（字段 / 边界 / 规则三维 + 缺口清单）
curl http://127.0.0.1:8000/api/v1/testcases/SUITE-9f8e7d6c/coverage

# 需求变更差异（doc_id 为新版，against 为旧版，两者都需已解析）
curl "http://127.0.0.1:8000/api/v1/requirements/DOC-new/diff?against=DOC-old"

# 需求-用例双向追溯矩阵
curl http://127.0.0.1:8000/api/v1/requirements/DOC-xxx/traceability

# 图片识别通道配置（读写与探针；清图片配置不影响大模型配置）
curl http://127.0.0.1:8000/api/v1/vision/config
curl -X POST http://127.0.0.1:8000/api/v1/vision/config/test

# 文档里的图片：查看某一张 / 重新识别全部
curl -OJ http://127.0.0.1:8000/api/v1/documents/DOC-xxx/images/img-001.png
curl -X POST http://127.0.0.1:8000/api/v1/documents/DOC-xxx/images/recognize
```

按次覆盖单条需求用例上限（省略则用服务端 `MAX_CASES_PER_REQUIREMENT`）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/testcases/generate \
  -H "Content-Type: application/json" \
  -d '{"text": "## 登录\n- 密码：8-20位，必填", "methods": ["equivalence", "orthogonal"], "use_llm": false, "max_cases_per_requirement": 120}'
```

---

## 5.2 V2.3 自动化交付与工作事项

生成受控自动化资产（`case_ids` 省略时使用该规范全部接口用例）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/automation/artifacts \
  -H "Content-Type: application/json" \
  -d '{"spec_id": "API-912338d6", "case_ids": ["API-GET-6EB7EEAE24"]}'
```

下载通过的 zip：

```powershell
$artifact = (Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:8000/api/v1/automation/artifacts?spec_id=API-912338d6").data |
  Select-Object -First 1
Invoke-WebRequest `
  -Uri "http://127.0.0.1:8000/api/v1/automation/artifacts/$($artifact.artifact_id)/download" `
  -OutFile "api-tests-$($artifact.artifact_id).zip"
```

运行生成的 pytest 项目并把结果导回平台：

```powershell
Expand-Archive .\api-tests-AUTO-xxxx.zip -DestinationPath .\api-tests
Set-Location .\api-tests
$env:baseUrl = "http://127.0.0.1:8000"
$env:authToken = "<local token>"
python -m pytest --junitxml=result.xml
Set-Location ..
curl.exe -X POST http://127.0.0.1:8000/api/v1/automation/runs/import `
  -F "file=@api-tests/result.xml" `
  -F "artifact_id=AUTO-xxxx"
```

创建、完成与查询工作事项：

```powershell
$item = (Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/work-items" `
  -ContentType "application/json" `
  -Body (@{
    item_type = "task"
    title = "跟进支付接口失败"
    status = "todo"
    priority = "P1"
    remind_at = (Get-Date).AddHours(1).ToString("o")
    tags = @("回归", "支付")
  } | ConvertTo-Json)).data

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/work-items/$($item.work_item_id)/complete"

Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/work-items?view=today"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/work-items/reminders/due"
```

从失败运行一键创建关联事项、读取可送入报告工作台的执行数据：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/automation/runs/RUN-xxxx/follow-up \
  -H "Content-Type: application/json" -d '{"priority":"P1"}'
curl http://127.0.0.1:8000/api/v1/automation/runs/RUN-xxxx/report-source
curl "http://127.0.0.1:8000/api/v1/automation/events?run_id=RUN-xxxx"
```

> 平台不会执行下载的 pytest 项目。JUnit 未匹配 case 不会丢弃；资产未通过静态安全校验时下载返回 409。

---

## 5.3 自动化受控 AI 增强

四种任务共用同一个入口，模型只返回建议，不会修改资产：

```powershell
$review = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/automation/ai/reviews" `
  -ContentType "application/json" `
  -Body (@{
    kind = "operation_gap"
    spec_id = "API-912338d6"
    artifact_id = "AUTO-xxxx"
    focus = "优先检查幂等和重复创建"
  } | ConvertTo-Json)

$review.data.findings | Format-Table severity,operation_id,target,issue,suggestion
```

可用的 `kind`：

| kind | 必要上下文 | 输出 |
| --- | --- | --- |
| `operation_gap` | `spec_id`，可选 `artifact_id` | 未覆盖 operation 的人工补充场景建议 |
| `failure_assertion` | `spec_id` + `run_id` | 失败 case 的待确认断言提案 |
| `fixture_recipe` | `spec_id`，可选 `artifact_id` | 环境变量、fixture 与测试数据结构 |
| `script_review` | `spec_id` + 已通过校验的 `artifact_id` | 现有脚本的只读审查意见 |

人工决定单条建议：

```powershell
Invoke-RestMethod -Method Put `
  -Uri "http://127.0.0.1:8000/api/v1/automation/ai/reviews/$($review.data.review_id)/findings/$($review.data.findings[0].finding_id)" `
  -ContentType "application/json" `
  -Body '{"disposition":"accepted"}'
```

将已采纳建议应用为新资产版本：

```powershell
$derived = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/automation/ai/reviews/$($review.data.review_id)/apply"

$derived.data | Select-Object artifact_id,revision,status,parent_artifact_id,change_summary
```

应用规则：

- 原资产和源 case 不修改，只创建新的 `v2`、`v3`。
- operation 提案生成新的 `API-AI-*` case；失败断言复制目标 case 后追加 assertion。
- recipe 在派生资产中写入 `fixtures.json`、`test_data.json` 并更新 `.env.example`。
- 新资产重新执行 AST、语法、危险调用和密钥扫描；失败时标记 `rejected` 并禁止下载。

生成并下载 fixture / 测试数据配方：

```powershell
$recipe = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/automation/ai/reviews" `
  -ContentType "application/json" `
  -Body (@{
    kind = "fixture_recipe"
    spec_id = "API-912338d6"
    artifact_id = "AUTO-xxxx"
  } | ConvertTo-Json)

Invoke-WebRequest `
  -Uri "http://127.0.0.1:8000/api/v1/automation/ai/reviews/$($recipe.data.review_id)/recipe" `
  -OutFile "fixture-recipe.json"
```

> 配方必须通过明文密钥和可执行代码扫描；operation / case / source_ref 越界的建议会被丢弃。
> 采纳只是人工确认状态，不会自动写入下载项目。

---

## 6. Python 客户端示例

```python
import httpx

BASE = "http://127.0.0.1:8000/api/v1"

with httpx.Client(timeout=120) as client:
    # 1) 一键生成
    response = client.post(
        f"{BASE}/pipeline/generate",
        json={
            "text": open("examples/sample_requirement.md", encoding="utf-8").read(),
            "title": "电商订单系统需求说明书",
            "methods": ["equivalence", "boundary", "scenario"],
            "use_llm": True,
        },
    )
    response.raise_for_status()
    suite = response.json()["data"]["suite"]
    print("用例数：", suite["stats"]["total"])

    # 2) 导出 Excel
    export = client.post(f"{BASE}/export", json={"suite_id": suite["suite_id"], "format": "excel"})
    export.raise_for_status()
    with open("测试用例.xlsx", "wb") as fh:
        fh.write(export.content)
    print("已导出 测试用例.xlsx")
```

---

## 7. 错误码速查

| HTTP | code | 场景 |
| --- | --- | --- |
| 400 | `BAD_REQUEST` | 未提供 `doc_id` 或 `text` |
| 404 | `NOT_FOUND` | `suite_id` / `doc_id` 不存在，或设计方法名错误 |
| 413 | `PAYLOAD_TOO_LARGE` | 上传文件超过 `MAX_UPLOAD_SIZE_MB` |
| 415 | `UNSUPPORTED_FORMAT` | 不支持的文件扩展名 |
| 422 | `DOCUMENT_PARSE_FAILED` / `DOCUMENT_EMPTY` | 文档损坏 / 抽不到有效文本 |
| 422 | `VALIDATION_ERROR` | 请求体字段类型或取值范围不合法 |
| 422 | `JUNIT_PARSE_FAILED` | JUnit XML 畸形、根节点错误或不是 pytest 兼容格式 |
| 422 | `SCHEMA_VALIDATION_FAILED` | 工作事项日期、标签或关联字段校验失败 |
| 409 | `CONFLICT` | 资产未通过安全校验、有关联运行尚不能删除，或执行中任务重复 |
| 500 | `EXPORT_FAILED` | Excel 导出失败（如文件被占用） |
| 501 | `FEATURE_NOT_AVAILABLE` | 调用预留但未实现的能力（判定表/因果图/正交实验等） |
| 502 | `LLM_ERROR` / `LLM_RESPONSE_INVALID` | 大模型调用失败 / 多次重试后仍非合法 JSON |
