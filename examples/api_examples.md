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
`methods`（含 `implemented=false` 的 未实现项）、`export_formats`、`supported_extensions`。

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

# 可用格式
curl http://127.0.0.1:8000/api/v1/export/formats
```

PowerShell 下载：

```powershell
curl.exe -OJ "http://127.0.0.1:8000/api/v1/export/SUITE-9f8e7d6c/excel"
```

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
| 500 | `EXPORT_FAILED` | Excel 导出失败（如文件被占用） |
| 501 | `FEATURE_NOT_AVAILABLE` | 调用预留但未实现的能力（判定表/因果图/正交实验等） |
| 502 | `LLM_ERROR` / `LLM_RESPONSE_INVALID` | 大模型调用失败 / 多次重试后仍非合法 JSON |