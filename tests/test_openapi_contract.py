"""系统 OpenAPI 文档完整性回归。"""
from __future__ import annotations

import re

from app.design.api_cases import generate_api_cases
from app.parsers.openapi_parser import parse_openapi

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "trace"}


def operations(schema: dict) -> list[tuple[str, str, dict]]:
    return [
        (method, path, operation)
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    ]


def test_system_openapi_has_servers_descriptions_and_declared_path_parameters(client) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["servers"] == [
        {
            "url": "http://127.0.0.1:8000",
            "description": "平台公开访问地址（PUBLIC_BASE_URL）",
        }
    ]
    assert schema["info"]["x-authentication-required"] is False

    for method, path, operation in operations(schema):
        label = f"{method.upper()} {path}"
        assert operation.get("description"), f"{label} 缺少 description"
        assert operation.get("summary"), f"{label} 缺少 summary"
        for parameter in operation.get("parameters") or []:
            assert parameter.get("description"), f"{label} 参数 {parameter.get('name')} 缺少说明"
            if parameter.get("in") == "path":
                assert parameter.get("required") is True
        for path_param in re.findall(r"{([^}]+)}", path):
            assert any(
                item.get("in") == "path" and item.get("name") == path_param
                for item in operation.get("parameters") or []
            ), f"{label} 未声明路径参数 {path_param}"


def test_system_openapi_documents_errors_files_and_sse(client) -> None:
    schema = client.get("/openapi.json").json()
    all_operations = operations(schema)
    assert all("500" in operation["responses"] for _, _, operation in all_operations)
    assert all(
        operation["responses"]["500"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/AppError"
        for _, _, operation in all_operations
    )

    for path, path_item in schema["paths"].items():
        if not any(name in path for name in ("{doc_id}", "{suite_id}", "{report_id}", "{spec_id}")):
            continue
        for method, operation in path_item.items():
            if method in HTTP_METHODS:
                assert "404" in operation["responses"], f"{method.upper()} {path} 缺少 404"

    sse = schema["paths"]["/api/v1/report/analyze/stream"]["post"]["responses"]["200"]
    assert set(sse["content"]) == {"text/event-stream"}

    download = schema["paths"]["/api/v1/documents/{doc_id}/download"]["get"]["responses"]["200"]
    assert "application/octet-stream" in download["content"]
    assert download["content"]["application/octet-stream"]["schema"]["$ref"].endswith("/BinaryFile")

    report_export = schema["paths"]["/api/v1/report/reports/{report_id}/export"]["get"]["responses"]["200"]
    assert {"text/markdown", "text/html", "application/json"} <= set(report_export["content"])

    review = schema["paths"]["/api/v1/api-specs/{spec_id}/review"]["post"]["responses"]
    assert {"404", "500", "503"} <= set(review)


def test_improved_system_spec_is_importable_without_response_schema_gaps(client) -> None:
    payload = client.get("/openapi.json").content
    spec = parse_openapi(payload, filename="system-openapi.json", spec_id="API-contract")
    result = generate_api_cases(spec)
    assert spec.servers
    assert not any("未声明 servers" in warning for warning in spec.warnings)
    assert not [
        (operation.method, operation.path, response.status_code)
        for operation in spec.operations
        for response in operation.responses
        if not any(media.schema_ for media in response.content)
    ]
    assert all(
        any(case.operation_id == operation.operation_id and case.category == "positive" for case in result.cases)
        for operation in spec.operations
    )
