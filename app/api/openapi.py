"""系统 OpenAPI 契约补全。

FastAPI 自动生成的 schema 已经覆盖路由、模型和 422 校验错误，但对以下内容
默认信息不足：
  - 文件下载、动态导出与 SSE 的真实 Content-Type；
  - 业务层全局异常出口会返回的 400 / 404 / 500；
  - Path / Query 参数的业务含义；
  - 未显式填写 description 的 operation。

这里只在 OpenAPI 层补文档，不改变任何路由的运行时行为。
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.core.config import Settings

APP_ERROR_SCHEMA = "AppError"
BINARY_SCHEMA = "BinaryFile"
SSE_SCHEMA = "ServerSentEvents"

_PARAMETER_DESCRIPTIONS: dict[str, str] = {
    "doc_id": "文档 ID；来自文档上传或粘贴文本入库后的记录。",
    "suite_id": "用例集 ID。",
    "report_id": "报告存档 ID。",
    "spec_id": "接口规范 ID。",
    "artifact_id": "自动化资产 ID。",
    "run_id": "执行记录 ID。",
    "work_item_id": "工作事项 ID。",
    "review_id": "自动化受控 AI 建议 ID。",
    "finding_id": "单条 AI 建议 ID。",
    "kind": "自动化 AI 任务类型：operation_gap / failure_assertion / fixture_recipe / script_review。",
    "operation_id": "OpenAPI operation ID。",
    "filename": "文档附件文件名。",
    "fmt": "导出格式注册名，例如 excel / json / csv / xmind / testlink。",
    "view": "工作事项视图：inbox / today / upcoming / overdue / all / completed。",
    "status": "工作事项状态或执行结果状态。",
    "priority": "优先级 P0–P3。",
    "tag": "工作事项标签。",
    "format": "导出格式，例如 md / html / docx / json。",
    "limit": "本次最多返回的记录数。",
    "offset": "分页偏移量。",
    "q": "按标题、版本、模型或正文检索。",
    "verdict": "按报告判定过滤。",
    "provider": "大模型服务商名称。",
    "base_url": "OpenAI 兼容端点地址。",
    "against": "用于对比的旧需求或文档 ID。",
    "methods": "逗号分隔的测试设计方法。",
    "use_llm_in_design": "是否启用生成阶段的大模型参与。",
}

_RESOURCE_PATH_NAMES = {
    "doc_id",
    "suite_id",
    "report_id",
    "spec_id",
    "artifact_id",
    "run_id",
    "work_item_id",
    "review_id",
    "finding_id",
    "operation_id",
    "filename",
    "fmt",
}

_BINARY_200_PATHS = {
    ("GET", "/api/v1/documents/{doc_id}/download"),
    ("GET", "/api/v1/documents/{doc_id}/images/{filename}"),
    ("POST", "/api/v1/export"),
    ("GET", "/api/v1/export/{suite_id}/{fmt}"),
    ("GET", "/api/v1/automation/artifacts/{artifact_id}/download"),
    ("GET", "/api/v1/automation/ai/reviews/{review_id}/recipe"),
}

_REPORT_EXPORT_PATH = "/api/v1/report/reports/{report_id}/export"
_SSE_PATH = "/api/v1/report/analyze/stream"
_POSTMAN_PATH = "/api/v1/api-specs/{spec_id}/export/postman"


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _error_response(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"schema": _ref(APP_ERROR_SCHEMA)}},
    }


def _ensure_common_schemas(schema: dict[str, Any]) -> None:
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas.setdefault(
        APP_ERROR_SCHEMA,
        {
            "type": "object",
            "required": ["success", "code", "message"],
            "properties": {
                "success": {"type": "boolean", "enum": [False]},
                "code": {"type": "string", "description": "机器可读错误码。"},
                "message": {"type": "string", "description": "面向使用者的错误说明。"},
                "detail": {
                    "description": "可选的字段级错误或上下文信息，JSON 类型由具体错误决定。",
                },
            },
        },
    )
    schemas.setdefault(
        BINARY_SCHEMA,
        {"type": "string", "format": "binary", "description": "二进制文件内容。"},
    )
    schemas.setdefault(
        SSE_SCHEMA,
        {
            "type": "string",
            "description": "text/event-stream；事件顺序为 meta → metrics → delta* → done/error。",
        },
    )


def _enrich_parameters(operation: dict[str, Any]) -> None:
    for parameter in operation.get("parameters") or []:
        if not isinstance(parameter, dict):
            continue
        name = str(parameter.get("name") or "")
        location = str(parameter.get("in") or "")
        if not parameter.get("description"):
            parameter["description"] = _PARAMETER_DESCRIPTIONS.get(
                name,
                f"{location or '请求'} 参数 `{name}`。",
            )


def _add_error(
    operation: dict[str, Any],
    status: str,
    description: str,
) -> None:
    responses = operation.setdefault("responses", {})
    if status not in responses:
        responses[status] = _error_response(description)


def _replace_success_content(operation: dict[str, Any], content: dict[str, Any]) -> None:
    success = operation.setdefault("responses", {}).setdefault("200", {"description": "操作成功"})
    success["content"] = content


def _enrich_responses(
    method: str,
    path: str,
    operation: dict[str, Any],
) -> None:
    path_parameters = {
        str(item.get("name"))
        for item in operation.get("parameters") or []
        if isinstance(item, dict) and item.get("in") == "path"
    }
    if path_parameters & _RESOURCE_PATH_NAMES:
        _add_error(operation, "404", "资源不存在、已删除或编号非法。")

    if method.lower() in {"post", "put", "patch"} and operation.get("requestBody"):
        _add_error(operation, "400", "业务参数不合法或请求无法处理。")

    if path in {
        "/api/v1/documents/upload",
        "/api/v1/api-specs/import",
        "/api/v1/automation/runs/import",
    }:
        _add_error(operation, "413", "上传文件超过服务端大小限制。")
        _add_error(operation, "415", "上传文件格式不受支持。")
        _add_error(operation, "422", "文件内容或结构化数据校验失败。")

    if path in {
        "/api/v1/requirements/parse",
        "/api/v1/testcases/generate",
        "/api/v1/pipeline/generate",
        "/api/v1/api-specs/import",
    }:
        _add_error(operation, "400", "业务参数组合不合法或缺少必要来源。")

    if path in {
        "/api/v1/report/analyze",
        "/api/v1/report/analyze/stream",
        "/api/v1/report/probe",
    }:
        _add_error(operation, "502", "大模型服务调用失败。")
        _add_error(operation, "503", "大模型服务尚未配置或不可用。")

    if path == "/api/v1/api-specs/{spec_id}/review":
        _add_error(operation, "409", "同一接口规范已有复核任务执行中，或已完成复核。")
        _add_error(operation, "503", "大模型服务尚未配置或不可用。")

    if path == "/api/v1/automation/ai/reviews":
        _add_error(operation, "409", "同类自动化 AI 建议任务正在执行。")
        _add_error(operation, "503", "大模型服务尚未配置或不可用。")
    if path.startswith("/api/v1/automation/ai/reviews/{review_id}"):
        _add_error(operation, "409", "建议仍在运行或已完成，状态不允许当前人工决定。")

    if path == "/api/v1/automation/artifacts/{artifact_id}":
        _add_error(operation, "409", "资产已关联执行记录，不能直接删除。")
    if path == "/api/v1/automation/artifacts/{artifact_id}/download":
        _add_error(operation, "409", "资产未通过静态安全校验，禁止下载。")
    if path.startswith("/api/v1/work-items"):
        _add_error(operation, "422", "工作事项字段、日期、标签或关联资源校验失败。")

    _add_error(operation, "500", "服务内部错误。")

    binary_content = {
        "application/octet-stream": {"schema": _ref(BINARY_SCHEMA)},
        "application/json": {"schema": {"type": "object"}},
        "text/csv": {"schema": _ref(BINARY_SCHEMA)},
        "application/xml": {"schema": _ref(BINARY_SCHEMA)},
        "application/vnd.xmind.workbook": {"schema": _ref(BINARY_SCHEMA)},
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
            "schema": _ref(BINARY_SCHEMA)
        },
    }
    if (method.upper(), path) in _BINARY_200_PATHS:
        _replace_success_content(operation, binary_content)

    if path == _REPORT_EXPORT_PATH:
        _replace_success_content(
            operation,
            {
                "text/markdown": {"schema": {"type": "string"}},
                "text/html": {"schema": {"type": "string"}},
                "application/json": {"schema": {"type": "object"}},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
                    "schema": _ref(BINARY_SCHEMA)
                },
            },
        )
        _add_error(operation, "400", "导出格式不受支持。")

    if path == _SSE_PATH:
        _replace_success_content(
            operation,
            {"text/event-stream": {"schema": _ref(SSE_SCHEMA)}},
        )

    if path == _POSTMAN_PATH:
        _replace_success_content(
            operation,
            {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "description": "Postman Collection 2.1 JSON。",
                    }
                }
            },
        )


def install_openapi(app: FastAPI, settings: Settings) -> None:
    """安装系统 OpenAPI 生成器并补全公共契约。"""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema["servers"] = [
            {
                "url": settings.public_base_url.rstrip("/"),
                "description": "平台公开访问地址（PUBLIC_BASE_URL）",
            }
        ]
        info = schema.setdefault("info", {})
        info["description"] = (
            str(info.get("description") or "").rstrip()
            + "\n\n接口统一响应结构为 `{success, code, message, detail, data}`；"
            "文件下载、动态导出与 SSE 流式接口按各自 Content-Type 返回。"
            "\n\n项目身份通过 `X-Project-ID` 传递。平台鉴权可通过 `AUTH_ENABLED` 配置；"
            "启用后使用 `X-API-Key`，令牌与项目、角色在服务端绑定。"
        ).strip()
        info["x-authentication-required"] = settings.auth_enabled
        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["ApiKeyAuth"] = {
            "type": "apiKey",
            "in": "header",
            "name": settings.auth_header,
        }
        security_schemes["ProjectHeader"] = {
            "type": "apiKey",
            "in": "header",
            "name": settings.project_header,
        }
        if settings.auth_enabled:
            schema["security"] = [{"ApiKeyAuth": []}, {"ProjectHeader": []}]

        _ensure_common_schemas(schema)
        for path, path_item in (schema.get("paths") or {}).items():
            for method, operation in path_item.items():
                if method.lower() not in {"get", "put", "post", "delete", "options", "head", "patch", "trace"}:
                    continue
                if not isinstance(operation, dict):
                    continue
                if not operation.get("description"):
                    operation["description"] = str(operation.get("summary") or f"{method.upper()} {path}")
                _enrich_parameters(operation)
                _enrich_responses(method, path, operation)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


__all__ = ["install_openapi"]
