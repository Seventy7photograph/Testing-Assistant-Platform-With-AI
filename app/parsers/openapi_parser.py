"""OpenAPI 3 JSON / YAML 解析器。

解析结果只包含规范里明确存在的内容。无法展开的 ``$ref`` 会直接报错，
循环引用则保留为带 ``x-circular-ref`` 标记的占位节点并记录告警，避免
为了“能导入”而静默丢弃 operation 或 schema 字段。
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from app.core.exceptions import OpenApiParseError
from app.core.utils import decode_bytes, new_id, short_hash
from app.schemas.api_testing import (
    ApiMediaType,
    ApiOperation,
    ApiParameter,
    ApiRequestBody,
    ApiResponseDefinition,
    ApiSecurityScheme,
    ApiServer,
    ApiSpec,
)

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
PARAMETER_LOCATIONS = {"path", "query", "header", "cookie"}
_OPERATION_ID_SAFE = re.compile(r"[^0-9A-Za-z_.-]+")


class _RefResolver:
    """展开本地 JSON Pointer ``$ref``，并显式处理循环引用。"""

    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.warnings: list[str] = []
        self._warning_set: set[str] = set()

    def warn(self, message: str) -> None:
        if message not in self._warning_set:
            self._warning_set.add(message)
            self.warnings.append(message)

    def resolve(self, node: Any, *, stack: tuple[str, ...] = ()) -> Any:
        if isinstance(node, list):
            return [self.resolve(item, stack=stack) for item in node]
        if not isinstance(node, dict):
            return copy.deepcopy(node)

        ref = node.get("$ref")
        siblings = {key: value for key, value in node.items() if key != "$ref"}
        if isinstance(ref, str):
            if ref in stack:
                self.warn(f"检测到循环 $ref，已保留占位节点：{ref}")
                return {
                    "type": "object",
                    "x-circular-ref": ref,
                    **{key: self.resolve(value, stack=stack) for key, value in siblings.items()},
                }
            resolved = self._lookup(ref)
            merged = self.resolve(resolved, stack=(*stack, ref))
            if siblings:
                if isinstance(merged, dict):
                    merged.update(self.resolve(siblings, stack=stack))
                else:
                    raise OpenApiParseError(
                        f"$ref 目标不是对象，无法合并同级字段：{ref}",
                        detail={"ref": ref},
                    )
            return merged

        return {
            key: self.resolve(value, stack=stack)
            for key, value in node.items()
        }

    def _lookup(self, ref: str) -> Any:
        if not ref.startswith("#"):
            raise OpenApiParseError(
                f"不支持外部 $ref：{ref}。请先将外部文件打包为单文件 OpenAPI 规范。",
                detail={"ref": ref, "supported": "本地 #/ JSON Pointer"},
            )
        pointer = unquote(ref[1:])
        if pointer in ("", "/"):
            return self.document
        if not pointer.startswith("/"):
            raise OpenApiParseError(f"非法 JSON Pointer：{ref}", detail={"ref": ref})
        current: Any = self.document
        for raw_part in pointer.lstrip("/").split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and part in current:
                current = current[part]
                continue
            if isinstance(current, list):
                try:
                    current = current[int(part)]
                    continue
                except (ValueError, IndexError):
                    pass
            raise OpenApiParseError(
                f"无法解析 $ref：{ref}，路径片段 '{part}' 不存在。",
                detail={"ref": ref, "missing": part},
            )
        return copy.deepcopy(current)


def _load_document(text: str, filename: str) -> tuple[dict[str, Any], str]:
    payload: Any
    source_format = "json"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as json_error:
        source_format = "yaml"
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - requirements 已声明 PyYAML
            raise OpenApiParseError(
                "当前文件不是 JSON，且服务端未安装 PyYAML，无法解析 YAML。"
                "请安装 requirements 后重试。",
                detail={"filename": filename},
            ) from exc
        try:
            payload = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise OpenApiParseError(
                f"OpenAPI 文件不是合法 JSON 或 YAML：{exc}",
                detail={"filename": filename, "json_error": json_error.msg},
            ) from exc
    if not isinstance(payload, dict):
        raise OpenApiParseError(
            "OpenAPI 根节点必须是对象。",
            detail={"filename": filename, "actual_type": type(payload).__name__},
        )
    return payload, source_format


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _pick_example(node: dict[str, Any]) -> Any:
    if "example" in node:
        return copy.deepcopy(node["example"])
    if "default" in node:
        return copy.deepcopy(node["default"])
    examples = node.get("examples")
    if isinstance(examples, dict):
        for item in examples.values():
            if isinstance(item, dict) and "value" in item:
                return copy.deepcopy(item["value"])
            if item is not None:
                return copy.deepcopy(item)
    return None


def _parse_media_types(
    content: Any,
    *,
    resolver: _RefResolver,
    source_prefix: str,
) -> list[ApiMediaType]:
    if not isinstance(content, dict):
        return []
    media: list[ApiMediaType] = []
    for content_type, raw in content.items():
        resolved = resolver.resolve(raw)
        if not isinstance(resolved, dict):
            raise OpenApiParseError(
                f"{source_prefix} 的 content[{content_type}] 必须是对象。",
                detail={"source_ref": source_prefix, "content_type": content_type},
            )
        schema = resolved.get("schema") if isinstance(resolved.get("schema"), dict) else {}
        raw_examples = resolved.get("examples") if isinstance(resolved.get("examples"), dict) else {}
        examples: dict[str, Any] = {}
        for name, item in raw_examples.items():
            if isinstance(item, dict):
                examples[str(name)] = copy.deepcopy(
                    item.get("value", item.get("externalValue"))
                )
            else:
                examples[str(name)] = copy.deepcopy(item)
        media.append(
            ApiMediaType(
                content_type=str(content_type),
                schema=schema,
                example=_pick_example(resolved),
                examples=examples,
                source_ref=f"{source_prefix}.content.{content_type}",
            )
        )
    return media


def _parse_parameter(
    raw: Any,
    *,
    resolver: _RefResolver,
    source_prefix: str,
) -> ApiParameter:
    resolved = resolver.resolve(raw)
    if not isinstance(resolved, dict):
        raise OpenApiParseError(
            f"{source_prefix} 必须是参数对象。",
            detail={"source_ref": source_prefix},
        )
    location = str(resolved.get("in") or "").lower()
    if location not in PARAMETER_LOCATIONS:
        raise OpenApiParseError(
            f"参数位置不受支持：{location or '(空)'}",
            detail={"source_ref": source_prefix, "parameter": resolved.get("name"), "in": location},
        )
    schema = resolved.get("schema")
    if not isinstance(schema, dict):
        schema = {}
    return ApiParameter(
        name=str(resolved.get("name") or ""),
        location=location,
        required=bool(resolved.get("required")) or location == "path",
        description=str(resolved.get("description") or ""),
        deprecated=bool(resolved.get("deprecated")),
        example=_pick_example(resolved),
        schema=schema,
        source_ref=source_prefix,
    )


def _parse_responses(
    raw_responses: Any,
    *,
    resolver: _RefResolver,
    operation_ref: str,
) -> list[ApiResponseDefinition]:
    if not isinstance(raw_responses, dict):
        return []
    responses: list[ApiResponseDefinition] = []
    for status_code, raw in raw_responses.items():
        item_ref = f"{operation_ref}.responses.{status_code}"
        resolved = resolver.resolve(raw)
        if not isinstance(resolved, dict):
            raise OpenApiParseError(
                f"{item_ref} 必须是响应对象。",
                detail={"source_ref": item_ref},
            )
        headers: list[ApiParameter] = []
        for header_name, header_raw in (resolved.get("headers") or {}).items():
            header = resolver.resolve(header_raw)
            if not isinstance(header, dict):
                continue
            schema = header.get("schema") if isinstance(header.get("schema"), dict) else {}
            headers.append(
                ApiParameter(
                    name=str(header_name),
                    location="header",
                    required=bool(header.get("required")),
                    description=str(header.get("description") or ""),
                    example=_pick_example(header),
                    schema=schema,
                    source_ref=f"{item_ref}.headers.{header_name}",
                )
            )
        responses.append(
            ApiResponseDefinition(
                status_code=str(status_code),
                description=str(resolved.get("description") or ""),
                content=_parse_media_types(
                    resolved.get("content"),
                    resolver=resolver,
                    source_prefix=item_ref,
                ),
                headers=headers,
                source_ref=item_ref,
            )
        )
    return responses


def _parse_request_body(
    raw: Any,
    *,
    resolver: _RefResolver,
    source_ref: str,
) -> ApiRequestBody | None:
    if raw is None:
        return None
    resolved = resolver.resolve(raw)
    if not isinstance(resolved, dict):
        raise OpenApiParseError(
            f"{source_ref} 必须是 requestBody 对象。",
            detail={"source_ref": source_ref},
        )
    return ApiRequestBody(
        required=bool(resolved.get("required")),
        description=str(resolved.get("description") or ""),
        content=_parse_media_types(
            resolved.get("content"),
            resolver=resolver,
            source_prefix=source_ref,
        ),
        source_ref=source_ref,
    )


def _parse_servers(raw: Any, *, fallback: list[ApiServer]) -> list[ApiServer]:
    if not isinstance(raw, list):
        return list(fallback)
    servers: list[ApiServer] = []
    for item in raw:
        if isinstance(item, str):
            servers.append(ApiServer(url=item))
        elif isinstance(item, dict) and item.get("url"):
            servers.append(
                ApiServer(
                    url=str(item["url"]),
                    description=str(item.get("description") or ""),
                )
            )
    return servers or list(fallback)


def _operation_id(method: str, path: str, declared: Any) -> str:
    raw = str(declared or "").strip()
    if raw:
        return raw
    safe = _OPERATION_ID_SAFE.sub("_", f"{method}_{path.strip('/') or 'root'}")
    return f"{safe[:72]}_{short_hash(method, path, length=6)}"


def _requirement_ids(operation: dict[str, Any]) -> list[str]:
    ids = _as_string_list(operation.get("x-requirement-ids"))
    ids.extend(_as_string_list(operation.get("x-requirement-id")))
    for tag in _as_string_list(operation.get("tags")):
        if re.fullmatch(r"(?:REQ|需求)[-_]?[A-Za-z0-9._-]+", tag, flags=re.IGNORECASE):
            ids.append(tag)
    return list(dict.fromkeys(ids))


def _security_requirements(raw: Any) -> list[dict[str, list[str]]]:
    if not isinstance(raw, list):
        return []
    requirements: list[dict[str, list[str]]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        requirements.append(
            {
                str(name): [str(scope) for scope in (scopes if isinstance(scopes, list) else [])]
                for name, scopes in item.items()
            }
        )
    return requirements


def parse_openapi(
    data: bytes,
    *,
    filename: str = "openapi.yaml",
    spec_id: str | None = None,
) -> ApiSpec:
    """解析单文件 OpenAPI 3 规范并规范化全部 operation。"""
    if not data:
        raise OpenApiParseError("OpenAPI 文件为空。", detail={"filename": filename})
    text, _ = decode_bytes(data, ("utf-8-sig", "utf-8", "gb18030"))
    document, source_format = _load_document(text, filename)
    openapi_version = str(document.get("openapi") or "").strip()
    if not openapi_version:
        if str(document.get("swagger") or "").startswith("2"):
            raise OpenApiParseError(
                "当前版本只支持 OpenAPI 3.x，检测到 Swagger 2.0。请先转换为 OpenAPI 3。",
                detail={"swagger": document.get("swagger")},
            )
        raise OpenApiParseError(
            "缺少 openapi 版本字段；仅支持 OpenAPI 3.x。",
            detail={"filename": filename},
        )
    if not openapi_version.startswith("3."):
        raise OpenApiParseError(
            f"不支持的 OpenAPI 版本：{openapi_version}（仅支持 3.x）。",
            detail={"openapi": openapi_version},
        )
    paths = document.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise OpenApiParseError(
            "OpenAPI 规范未声明任何 paths。",
            detail={"filename": filename},
        )

    resolver = _RefResolver(document)
    info = document.get("info") if isinstance(document.get("info"), dict) else {}
    top_servers = _parse_servers(document.get("servers"), fallback=[])
    if not top_servers:
        resolver.warn("规范未声明 servers；执行 URL 使用 {{baseUrl}}，请在环境中配置。")

    security_schemes: list[ApiSecurityScheme] = []
    components = document.get("components") if isinstance(document.get("components"), dict) else {}
    raw_schemes = components.get("securitySchemes") if isinstance(components.get("securitySchemes"), dict) else {}
    for name, raw in raw_schemes.items():
        scheme = resolver.resolve(raw)
        if not isinstance(scheme, dict):
            continue
        security_schemes.append(
            ApiSecurityScheme(
                name=str(name),
                type=str(scheme.get("type") or ""),
                scheme=str(scheme.get("scheme") or ""),
                location=str(scheme.get("in") or ""),
                parameter_name=str(scheme.get("name") or ""),
                bearer_format=str(scheme.get("bearerFormat") or ""),
                description=str(scheme.get("description") or ""),
            )
        )

    global_security = document.get("security") if "security" in document else None
    operations: list[ApiOperation] = []
    for path, raw_path_item in paths.items():
        path_ref = f"paths.{path}"
        path_item = resolver.resolve(raw_path_item)
        if not isinstance(path_item, dict):
            raise OpenApiParseError(
                f"{path_ref} 必须是 path item 对象。",
                detail={"source_ref": path_ref},
            )
        path_parameters = {
            (str((param or {}).get("name") or ""), str((param or {}).get("in") or "")): param
            for param in (path_item.get("parameters") or [])
            if isinstance(param, dict)
        }
        path_servers = _parse_servers(path_item.get("servers"), fallback=top_servers)
        for method in HTTP_METHODS:
            raw_operation = path_item.get(method)
            if raw_operation is None:
                continue
            operation_ref = f"{path_ref}.{method}"
            if not isinstance(raw_operation, dict):
                raise OpenApiParseError(
                    f"{operation_ref} 必须是 operation 对象。",
                    detail={"source_ref": operation_ref},
                )
            operation = resolver.resolve(raw_operation)
            parameters: list[ApiParameter] = []
            merged_params: dict[tuple[str, str], Any] = dict(path_parameters)
            for param in operation.get("parameters") or []:
                if not isinstance(param, dict):
                    raise OpenApiParseError(
                        f"{operation_ref} 包含非对象参数。",
                        detail={"source_ref": operation_ref},
                    )
                key = (str(param.get("name") or ""), str(param.get("in") or ""))
                merged_params[key] = param
            for param in merged_params.values():
                parameters.append(
                    _parse_parameter(
                        param,
                        resolver=resolver,
                        source_prefix=f"{operation_ref}.parameters",
                    )
                )
            request_body = _parse_request_body(
                operation.get("requestBody"),
                resolver=resolver,
                source_ref=f"{operation_ref}.requestBody",
            )
            responses = _parse_responses(
                operation.get("responses"),
                resolver=resolver,
                operation_ref=operation_ref,
            )
            warnings: list[str] = []
            declared_parameters = {(item.name, item.location) for item in parameters}
            for segment in re.findall(r"{([^}]+)}", str(path)):
                if (segment, "path") not in declared_parameters:
                    warnings.append(f"路径参数 {{{segment}}} 未在 parameters 中声明。")
            if not responses:
                warnings.append("operation 未声明 responses，状态码断言需人工补充。")
            resolved_security = (
                operation.get("security")
                if "security" in operation
                else global_security
            )
            operations.append(
                ApiOperation(
                    operation_id=_operation_id(method, str(path), operation.get("operationId")),
                    method=method.upper(),
                    path=str(path),
                    summary=str(operation.get("summary") or ""),
                    description=str(operation.get("description") or ""),
                    tags=_as_string_list(operation.get("tags")),
                    deprecated=bool(operation.get("deprecated")),
                    parameters=parameters,
                    request_body=request_body,
                    responses=responses,
                    security=_security_requirements(resolved_security),
                    servers=_parse_servers(operation.get("servers"), fallback=path_servers),
                    requirement_ids=_requirement_ids(operation),
                    source_ref=operation_ref,
                    warnings=warnings,
                )
            )

    if not operations:
        raise OpenApiParseError(
            "规范里没有可导入的 HTTP operation。",
            detail={"filename": filename, "path_count": len(paths)},
        )

    warnings = list(resolver.warnings)
    gap_count = sum(1 for operation in operations if operation.warnings)
    spec = ApiSpec(
        spec_id=spec_id or new_id("API-"),
        title=str(info.get("title") or Path(filename).stem or "OpenAPI 接口库"),
        version=str(info.get("version") or ""),
        openapi_version=openapi_version,
        description=str(info.get("description") or ""),
        source_file=filename,
        source_format=source_format,
        source_hash=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        servers=top_servers,
        security_schemes=security_schemes,
        operations=operations,
        warnings=warnings,
    )
    spec.stats.operations = len(operations)
    spec.stats.operation_gaps = gap_count
    return spec


__all__ = ["HTTP_METHODS", "parse_openapi"]
