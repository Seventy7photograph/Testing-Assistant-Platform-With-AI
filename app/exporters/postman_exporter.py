"""Postman Collection 2.1 导出器。

Collection 只携带环境变量占位符，不写入任何真实 Token / API Key。
响应示例不会变成固定断言；tests 数组只来自 ``ApiCaseSpec.assertions`` 中
可追溯到 schema 的确定性契约。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.core.exceptions import ExportError
from app.core.utils import slugify_filename
from app.exporters.base import Exporter, ExportResult
from app.schemas.api_testing import ApiAssertion, ApiCaseSpec, ApiSpec
from app.schemas.testcase import TestCaseSuite

SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def _test_script(assertions: list[ApiAssertion]) -> list[dict[str, Any]]:
    if not assertions:
        return []
    nullable_paths = {
        item.path
        for item in assertions
        if item.kind == "json" and item.operator == "nullable" and item.expected is True
    }
    lines: list[str] = []
    if any(item.kind == "json" and item.status != "manual" for item in assertions):
        lines.extend(
            [
                "const jsonData = pm.response.json();",
                'function valuesAtPath(root, path) {',
                '  if (path === "$") return [root];',
                '  const tokens = path.replace(/^\\$/, "").match(/(?:\\.[A-Za-z0-9_]+|\\[(?:\\d+|\\*|\'[^\']*\'|"[^"]*")\\])/g) || [];',
                "  let values = [root];",
                "  for (const token of tokens) {",
                "    const next = [];",
                "    for (const value of values) {",
                "      if (value === null || value === undefined) continue;",
                '      if (token === "[*]") {',
                '        if (Array.isArray(value)) next.push(...value);',
                '      } else if (token.startsWith("[")) {',
                '        const raw = token.slice(1, -1).replace(/^[\'"]|[\'"]$/g, "");',
                "        if (value[raw] !== undefined) next.push(value[raw]);",
                "      } else {",
                '        const key = token.slice(1);',
                "        if (value[key] !== undefined) next.push(value[key]);",
                "      }",
                "    }",
                "    values = next;",
                "  }",
                "  return values;",
                "}",
            ]
        )
    for index, assertion in enumerate(assertions):
        description = json.dumps(assertion.description or f"{assertion.kind} assertion", ensure_ascii=False)
        if assertion.status == "manual":
            lines.append(
                f"// TODO {description}: {json.dumps(assertion.expected, ensure_ascii=False)}"
            )
            continue
        if assertion.kind == "status" and assertion.operator == "equals":
            lines.extend(
                [
                    f"pm.test({description}, function () {{",
                    f"  pm.response.to.have.status({int(assertion.expected)});",
                    "});",
                ]
            )
            continue
        if assertion.kind == "header":
            lines.extend(
                [
                    f"pm.test({description}, function () {{",
                    f"  pm.expect(pm.response.headers.has({json.dumps(assertion.path)})).to.eql(true);",
                    "});",
                ]
            )
            continue
        if assertion.kind != "json":
            continue
        path = json.dumps(assertion.path)
        variable = f"values_{index}"
        lines.append(f"const {variable} = valuesAtPath(jsonData, {path});")
        if assertion.operator == "exists":
            lines.extend(
                [
                    f"pm.test({description}, function () {{",
                    f"  pm.expect({variable}.length).to.be.greaterThan(0);",
                    "});",
                ]
            )
        elif assertion.operator == "type":
            schema_type = str(assertion.expected)
            type_check = {
                "integer": "Number.isInteger(value)",
                "number": "typeof value === 'number' && !Number.isNaN(value)",
                "array": "Array.isArray(value)",
                "object": "value !== null && typeof value === 'object' && !Array.isArray(value)",
                "string": "typeof value === 'string'",
                "boolean": "typeof value === 'boolean'",
            }.get(schema_type, "true")
            allow_null = "value === null || " if assertion.path in nullable_paths else ""
            lines.extend(
                [
                    f"pm.test({description}, function () {{",
                    f"  pm.expect({variable}.length).to.be.greaterThan(0);",
                    f"  {variable}.forEach(function (value) {{ pm.expect({allow_null}{type_check}).to.eql(true); }});",
                    "});",
                ]
            )
        elif assertion.operator == "in":
            lines.extend(
                [
                    f"pm.test({description}, function () {{",
                    f"  {variable}.forEach(function (value) {{ pm.expect({json.dumps(assertion.expected, ensure_ascii=False)}).to.include(value); }});",
                    "});",
                ]
            )
        elif assertion.operator == "matches":
            lines.extend(
                [
                    f"pm.test({description}, function () {{",
                    f"  const pattern = new RegExp({json.dumps(str(assertion.expected))});",
                    f"  {variable}.forEach(function (value) {{ pm.expect(String(value)).to.match(pattern); }});",
                    "});",
                ]
            )
        elif assertion.operator in {"gte", "lte"}:
            comparator = "at.least" if assertion.operator == "gte" else "at.most"
            lines.extend(
                [
                    f"pm.test({description}, function () {{",
                    f"  {variable}.forEach(function (value) {{ pm.expect(value).to.be.{comparator}({json.dumps(assertion.expected)}); }});",
                    "});",
                ]
            )
    return [
        {
            "listen": "test",
            "script": {
                "type": "text/javascript",
                "exec": lines,
            },
        }
    ]


def _request_item(spec: ApiSpec, case: ApiCaseSpec) -> dict[str, Any]:
    execution = case.execution
    headers = [
        {"key": key, "value": value, "type": "text"}
        for key, value in execution.headers.items()
    ]
    query = [
        {"key": key, "value": value}
        for key, value in execution.query.items()
    ]
    request: dict[str, Any] = {
        "method": execution.method,
        "header": headers,
        "url": {
            "raw": execution.url,
            "host": ["{{baseUrl}}"],
            "path": [part for part in case.path.strip("/").split("/") if part],
            "query": query,
        },
        "description": "\n".join(
            [
                f"来源：{case.source_ref}",
                f"用例：{case.case_id}",
                f"类别：{case.category} / {case.priority}",
                *case.preconditions,
                *(f"待补充：{warning}" for warning in case.warnings),
                *(f"待补充断言：{item.description}" for item in case.assertions if item.status == "manual"),
            ]
        ).strip(),
    }
    if execution.body_kind == "json":
        request["body"] = {
            "mode": "raw",
            "raw": json.dumps(execution.body, ensure_ascii=False, indent=2),
            "options": {"raw": {"language": "json"}},
        }
    elif execution.body is not None:
        request["body"] = {
            "mode": "raw",
            "raw": str(execution.body),
        }
    return {
        "name": f"{case.case_id} · {case.title}",
        "request": request,
        "event": _test_script(case.assertions),
        "description": f"{case.method} {case.path} · {spec.title}",
    }


class PostmanExporter(Exporter):
    name = "postman"
    label = "Postman Collection 2.1"
    extension = "postman_collection.json"
    media_type = "application/json; charset=utf-8"

    def export(
        self,
        suite: TestCaseSuite,
        *,
        options: dict | None = None,
    ) -> ExportResult:
        """通过 ``options`` 接收接口规格与用例（保持统一导出器注册表）。"""
        options = options or {}
        spec = options.get("api_spec")
        cases = options.get("api_cases")
        if not isinstance(spec, ApiSpec) or not isinstance(cases, list):
            raise ExportError(
                "Postman 导出需要 api_spec 与 api_cases。",
                detail={"exporter": self.name},
            )
        return self.export_api(spec, cases)

    def export_api(self, spec: ApiSpec, cases: list[ApiCaseSpec]) -> ExportResult:
        try:
            grouped: dict[str, list[ApiCaseSpec]] = {}
            for case in cases:
                grouped.setdefault(case.operation_id, []).append(case)

            variables: dict[str, dict[str, Any]] = {
                "baseUrl": {
                    "key": "baseUrl",
                    "value": spec.servers[0].url if spec.servers else "http://127.0.0.1:8000",
                    "type": "string",
                }
            }
            for case in cases:
                for variable in case.execution.environment_variables:
                    name = str(variable.get("name") or "").strip()
                    if not name:
                        continue
                    variables.setdefault(
                        name,
                        {
                            "key": name,
                            "value": "",
                            # Postman Collection 2.1 的 variable.type 只允许
                            # string / boolean / any / number；敏感语义放在 description。
                            "type": "string",
                            "description": str(variable.get("description") or ""),
                        },
                    )

            operation_names = {
                operation.operation_id: f"{operation.method} {operation.path}"
                for operation in spec.operations
            }
            items = []
            for operation in spec.operations:
                operation_cases = grouped.get(operation.operation_id, [])
                if not operation_cases:
                    continue
                items.append(
                    {
                        "name": operation_names[operation.operation_id],
                        "description": "\n".join(operation.warnings),
                        "item": [_request_item(spec, case) for case in operation_cases],
                    }
                )
            collection = {
                "info": {
                    "_postman_id": f"{spec.spec_id}-{spec.source_hash[:12]}",
                    "name": spec.title,
                    "description": (
                        f"{spec.description}\n\n"
                        f"OpenAPI {spec.openapi_version} · 规范版本 {spec.version or '-'} · "
                        f"来源 {spec.source_file}"
                    ).strip(),
                    "schema": SCHEMA_URL,
                },
                "variable": list(variables.values()),
                "item": items,
            }
            content = json.dumps(collection, ensure_ascii=False, indent=2).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ExportError(f"Postman Collection 生成失败：{exc}") from exc
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = slugify_filename(spec.title or "OpenAPI", fallback="openapi")
        return ExportResult(
            content=content,
            filename=f"{stem}_Postman_{stamp}.postman_collection.json",
            media_type=self.media_type,
        )


__all__ = ["PostmanExporter", "SCHEMA_URL"]
