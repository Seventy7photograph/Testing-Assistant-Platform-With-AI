"""从规范化 OpenAPI operation 生成可审查的接口用例。

约束原则：
  - 只使用规范里出现的参数、schema、security 与响应定义；
  - 规范信息不足时不编造具体边界，而是生成显式“待补充”用例/断言；
  - 响应示例只用于展示，不作为固定返回值断言。
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.utils import now_iso, short_hash
from app.schemas.api_testing import (
    ApiAssertion,
    ApiCaseSpec,
    ApiMediaType,
    ApiOperation,
    ApiParameter,
    ApiResponseDefinition,
    ApiSecurityScheme,
    ApiSpec,
    ExecutionSpec,
)

_SECRET_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[-_]?key|cookie|authorization|credential)",
    flags=re.IGNORECASE,
)
_SUCCESS_STATUS_RE = re.compile(r"^2\d\d$")
_ERROR_STATUS_RE = re.compile(r"^[45]\d\d$")


@dataclass(slots=True)
class ApiCaseGenerationResult:
    cases: list[ApiCaseSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _merge_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    branches = schema.get("allOf")
    if not isinstance(branches, list):
        return schema
    merged: dict[str, Any] = {}
    required: list[str] = []
    properties: dict[str, Any] = {}
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        flat = _merge_schema(branch)
        merged.update({key: value for key, value in flat.items() if key not in {"required", "properties"}})
        required.extend(str(item) for item in flat.get("required") or [])
        if isinstance(flat.get("properties"), dict):
            properties.update(flat["properties"])
    merged.update({key: value for key, value in schema.items() if key != "allOf"})
    required.extend(str(item) for item in schema.get("required") or [])
    if properties:
        merged["properties"] = properties
    if required:
        merged["required"] = list(dict.fromkeys(required))
    return merged


def _schema_branch(schema: dict[str, Any]) -> tuple[dict[str, Any], str]:
    flat = _merge_schema(schema)
    raw_type = flat.get("type")
    if isinstance(raw_type, list):
        non_null_types = [item for item in raw_type if item != "null"]
        if len(non_null_types) == 1:
            flat = copy.deepcopy(flat)
            flat["type"] = non_null_types[0]
            flat["nullable"] = True
    for key in ("oneOf", "anyOf"):
        branches = flat.get(key)
        if isinstance(branches, list) and branches:
            non_null = [
                item
                for item in branches
                if isinstance(item, dict) and item.get("type") != "null"
            ]
            has_null = any(
                isinstance(item, dict) and item.get("type") == "null"
                for item in branches
            )
            if has_null and len(non_null) == 1:
                merged = _merge_schema(non_null[0])
                merged["nullable"] = True
                return merged, ""
            first = non_null[0] if non_null else (
                branches[0] if isinstance(branches[0], dict) else {}
            )
            return _merge_schema(first), f"{key} 仅取首个分支，其余分支需人工补充断言"
    return flat, ""


def _media_for_request(operation: ApiOperation) -> ApiMediaType | None:
    media = operation.request_body.content if operation.request_body else []
    if not media:
        return None
    return next((item for item in media if "json" in item.content_type.lower()), media[0])


def _success_response(operation: ApiOperation) -> ApiResponseDefinition | None:
    return next(
        (item for item in operation.responses if _SUCCESS_STATUS_RE.match(item.status_code)),
        operation.responses[0] if operation.responses else None,
    )


def _error_response(operation: ApiOperation) -> ApiResponseDefinition | None:
    # 业务异常优先使用 4xx。500 是所有接口都可能出现的兜底错误，不能拿来当
    # “缺少必填字段”的确定预期；若规范只声明 500，宁可保留人工补充用例。
    return next(
        (
            item
            for item in operation.responses
            if _ERROR_STATUS_RE.match(item.status_code) and item.status_code.startswith("4")
        ),
        None,
    )


def _response_media(response: ApiResponseDefinition | None) -> ApiMediaType | None:
    if response is None or not response.content:
        return None
    return next((item for item in response.content if "json" in item.content_type.lower()), response.content[0])


def _placeholder(name: str, *, secret: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "description": "敏感信息占位符，运行时在本地环境中填写" if secret else "运行时环境变量",
        "secret": secret,
    }


def _env_add(target: list[dict[str, Any]], item: dict[str, Any]) -> None:
    if not any(existing["name"] == item["name"] for existing in target):
        target.append(item)


def _secret_placeholder(key: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z]+", "_", key).strip("_") or "credential"
    if clean.lower().endswith("key"):
        clean += "Value"
    return f"{{{{{clean}}}}}"


def _sanitize_example(value: Any, *, env: list[dict[str, Any]]) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if _SECRET_KEY_RE.search(str(key)):
                env_name = re.sub(r"[^0-9A-Za-z]+", "_", str(key)).strip("_") or "credential"
                _env_add(env, _placeholder(env_name, secret=True))
                sanitized[key] = f"{{{{{env_name}}}}}"
            else:
                sanitized[key] = _sanitize_example(item, env=env)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_example(item, env=env) for item in value]
    return copy.deepcopy(value)


def _sample_value(
    schema: dict[str, Any] | None,
    *,
    name: str,
    env: list[dict[str, Any]],
    depth: int = 0,
) -> Any:
    schema, _ = _schema_branch(schema or {})
    if depth > 10 or schema.get("x-circular-ref"):
        return {}
    if _SECRET_KEY_RE.search(name):
        leaf_name = name.rsplit(".", 1)[-1]
        env_name = re.sub(r"[^0-9A-Za-z]+", "_", leaf_name).strip("_") or "credential"
        _env_add(env, _placeholder(env_name, secret=True))
        return _secret_placeholder(env_name)
    if "const" in schema:
        return copy.deepcopy(schema["const"])
    if schema.get("enum"):
        return copy.deepcopy(schema["enum"][0])
    if "example" in schema:
        return _sanitize_example(schema["example"], env=env)
    if "default" in schema:
        return _sanitize_example(schema["default"], env=env)

    schema_type = str(schema.get("type") or "")
    if schema_type == "object" or isinstance(schema.get("properties"), dict):
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = {str(item) for item in schema.get("required") or []}
        result: dict[str, Any] = {}
        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict) or prop_schema.get("readOnly"):
                continue
            if required and prop_name not in required:
                continue
            result[prop_name] = _sample_value(
                prop_schema,
                name=f"{name}.{prop_name}",
                env=env,
                depth=depth + 1,
            )
        return result
    if schema_type == "array" or isinstance(schema.get("items"), dict):
        return [_sample_value(
            schema.get("items") if isinstance(schema.get("items"), dict) else {},
            name=f"{name}[]",
            env=env,
            depth=depth + 1,
        )]
    if schema_type in ("integer", "number"):
        if "minimum" in schema:
            return schema["minimum"]
        if "maximum" in schema:
            return schema["maximum"]
        return 1
    if schema_type == "boolean":
        return True
    if schema_type == "string":
        minimum = int(schema.get("minLength") or 0)
        return "a" * max(minimum, 1)
    env_name = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_") or "value"
    _env_add(env, _placeholder(env_name))
    return f"{{{{{env_name}}}}}"


def _parameter_value(
    parameter: ApiParameter,
    *,
    env: list[dict[str, Any]],
) -> str:
    if _SECRET_KEY_RE.search(parameter.name):
        env_name = re.sub(r"[^0-9A-Za-z]+", "_", parameter.name).strip("_") or "credential"
        _env_add(env, _placeholder(env_name, secret=True))
        return _secret_placeholder(env_name)
    if parameter.example is not None:
        value = parameter.example
    else:
        value = _sample_value(parameter.schema_, name=parameter.name, env=env)
    if isinstance(value, (dict, list)):
        return str(value)
    return str(value)


def _auth_headers(
    operation: ApiOperation,
    schemes: dict[str, ApiSecurityScheme],
    *,
    query: dict[str, str],
    headers: dict[str, str],
    cookies: dict[str, str],
    env: list[dict[str, Any]],
    preconditions: list[str],
) -> None:
    if not operation.security:
        return
    requirement = operation.security[0]
    for scheme_name in requirement:
        scheme = schemes.get(scheme_name)
        if scheme is None:
            env_name = re.sub(r"[^0-9A-Za-z]+", "_", scheme_name).strip("_") or "auth"
            _env_add(env, _placeholder(env_name, secret=True))
            headers["Authorization"] = f"Bearer {{{{{env_name}}}}}"
            preconditions.append(f"准备未记录到规范的鉴权信息：{scheme_name}")
            continue
        if scheme.type == "http" and scheme.scheme.lower() == "basic":
            _env_add(env, _placeholder("basicAuth", secret=True))
            headers["Authorization"] = "Basic {{basicAuth}}"
            preconditions.append("准备 HTTP Basic 凭据（basicAuth）")
        elif scheme.type == "http":
            _env_add(env, _placeholder("authToken", secret=True))
            headers["Authorization"] = "Bearer {{authToken}}"
            preconditions.append("准备 Bearer Token（authToken）")
        elif scheme.type == "apiKey":
            env_name = re.sub(r"[^0-9A-Za-z]+", "_", scheme.name).strip("_") or "apiKey"
            _env_add(env, _placeholder(env_name, secret=True))
            value = f"{{{{{env_name}}}}}"
            if scheme.location == "query":
                query[scheme.parameter_name or scheme.name] = value
            elif scheme.location == "cookie":
                cookies[scheme.parameter_name or scheme.name] = value
            else:
                headers[scheme.parameter_name or "X-API-Key"] = value
            preconditions.append(f"准备 API Key（{env_name}）")
        elif scheme.type == "openIdConnect":
            _env_add(env, _placeholder("openIdToken", secret=True))
            headers["Authorization"] = "Bearer {{openIdToken}}"
            preconditions.append("准备 OpenID Connect Bearer Token（openIdToken）")
        else:
            preconditions.append(f"按安全方案 {scheme.name} 准备鉴权前置条件")


def _execution(
    operation: ApiOperation,
    spec: ApiSpec,
    *,
    body_override: Any = None,
    omit_body: bool = False,
    content_type_override: str | None = None,
) -> tuple[ExecutionSpec, list[str], list[dict[str, Any]]]:
    env: list[dict[str, Any]] = [_placeholder("baseUrl")]
    headers: dict[str, str] = {}
    query: dict[str, str] = {}
    path_params: dict[str, str] = {}
    cookies: dict[str, str] = {}
    preconditions: list[str] = []

    for parameter in operation.parameters:
        if not parameter.required:
            continue
        value = _parameter_value(parameter, env=env)
        if parameter.location == "query":
            query[parameter.name] = value
        elif parameter.location == "header":
            headers[parameter.name] = value
        elif parameter.location == "cookie":
            cookies[parameter.name] = value
        else:
            path_params[parameter.name] = value

    media = _media_for_request(operation)
    if media is not None and not omit_body:
        content_type = content_type_override if content_type_override is not None else media.content_type
        if content_type:
            headers["Content-Type"] = content_type
        body = copy.deepcopy(body_override) if body_override is not None else _sample_value(
            media.schema_,
            name="requestBody",
            env=env,
        )
    else:
        body = None

    response_media = _response_media(_success_response(operation))
    if response_media is not None and response_media.content_type:
        headers.setdefault("Accept", response_media.content_type)

    schemes = {item.name: item for item in spec.security_schemes}
    _auth_headers(
        operation,
        schemes,
        query=query,
        headers=headers,
        cookies=cookies,
        env=env,
        preconditions=preconditions,
    )

    url_path = operation.path
    for name in path_params:
        url_path = url_path.replace(f"{{{name}}}", f"{{{{{name}}}}}")
        _env_add(env, _placeholder(name))
    base_url = "{{baseUrl}}"
    url = f"{base_url}{url_path}"

    execution = ExecutionSpec(
        method=operation.method,
        url=url,
        headers=headers,
        query=query,
        path_params=path_params,
        cookies=cookies,
        body=body,
        body_kind="json" if media is not None and "json" in (media.content_type or "").lower() else (
            "raw" if media is not None else ""
        ),
        environment_variables=env,
    )
    return execution, preconditions, env


def _json_path(parent: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return f"{parent}.{key}"
    escaped = key.replace("'", "\\'")
    return f"{parent}['{escaped}']"


def _schema_assertions(
    schema: dict[str, Any] | None,
    *,
    response: ApiResponseDefinition,
    source_prefix: str,
    json_path: str = "$",
    depth: int = 0,
    allow_absent: bool = False,
) -> list[ApiAssertion]:
    if depth > 12 or not isinstance(schema, dict):
        return [
            ApiAssertion(
                kind="json",
                path=json_path,
                operator="manual",
                allow_absent=allow_absent,
                description="schema 层级过深或缺失，需人工补充断言",
                source_ref=source_prefix,
                status="manual",
            )
        ]
    flat, branch_note = _schema_branch(schema)
    assertions: list[ApiAssertion] = []
    if flat.get("x-circular-ref"):
        assertions.append(
            ApiAssertion(
                kind="json",
                path=json_path,
                operator="manual",
                allow_absent=allow_absent,
                description=f"循环引用 {flat['x-circular-ref']}，需人工补充有限深度断言",
                source_ref=source_prefix,
                status="manual",
            )
        )
        return assertions
    if branch_note:
        assertions.append(
            ApiAssertion(
                kind="json",
                path=json_path,
                operator="manual",
                allow_absent=allow_absent,
                description=branch_note,
                source_ref=source_prefix,
                status="manual",
            )
        )

    schema_type = flat.get("type")
    if schema_type:
        assertions.append(
            ApiAssertion(
                kind="json",
                path=json_path,
                operator="type",
                expected=schema_type,
                allow_absent=allow_absent,
                allow_null=bool(flat.get("nullable")),
                description=f"{json_path} 类型为 {schema_type}",
                source_ref=source_prefix,
            )
        )
    if schema_type == "object" or isinstance(flat.get("properties"), dict):
        properties = flat.get("properties") if isinstance(flat.get("properties"), dict) else {}
        required = [str(item) for item in flat.get("required") or []]
        for name in required:
            assertions.append(
                ApiAssertion(
                    kind="json",
                    path=_json_path(json_path, name),
                    operator="exists",
                    expected=True,
                    allow_absent=allow_absent,
                    description=f"必需字段 {name} 存在",
                    source_ref=f"{source_prefix}#/required/{name}",
                )
            )
        for name, child in properties.items():
            if not isinstance(child, dict) or child.get("writeOnly"):
                continue
            child_path = _json_path(json_path, name)
            assertions.extend(
                _schema_assertions(
                    child,
                    response=response,
                    source_prefix=f"{source_prefix}#/properties/{name}",
                    json_path=child_path,
                    depth=depth + 1,
                    allow_absent=allow_absent or name not in required,
                )
            )
    elif schema_type == "array" and isinstance(flat.get("items"), dict):
        assertions.extend(
            _schema_assertions(
                flat["items"],
                response=response,
                source_prefix=f"{source_prefix}#/items",
                json_path=f"{json_path}[*]",
                depth=depth + 1,
                allow_absent=allow_absent,
            )
        )
    if flat.get("nullable"):
        assertions.append(
            ApiAssertion(
                kind="json",
                path=json_path,
                operator="nullable",
                expected=True,
                allow_absent=allow_absent,
                description=f"{json_path} 允许为 null",
                source_ref=f"{source_prefix}#/nullable",
            )
        )
    if flat.get("enum"):
        assertions.append(
            ApiAssertion(
                kind="json",
                path=json_path,
                operator="in",
                expected=copy.deepcopy(flat["enum"]),
                allow_absent=allow_absent,
                description=f"{json_path} 取值来自枚举",
                source_ref=f"{source_prefix}#/enum",
            )
        )
    if flat.get("pattern"):
        assertions.append(
            ApiAssertion(
                kind="json",
                path=json_path,
                operator="matches",
                expected=str(flat["pattern"]),
                allow_absent=allow_absent,
                description=f"{json_path} 匹配规范正则",
                source_ref=f"{source_prefix}#/pattern",
            )
        )
    if "minimum" in flat:
        assertions.append(
            ApiAssertion(
                kind="json",
                path=json_path,
                operator="gte",
                expected=flat["minimum"],
                allow_absent=allow_absent,
                description=f"{json_path} 不小于 {flat['minimum']}",
                source_ref=f"{source_prefix}#/minimum",
            )
        )
    if "maximum" in flat:
        assertions.append(
            ApiAssertion(
                kind="json",
                path=json_path,
                operator="lte",
                expected=flat["maximum"],
                allow_absent=allow_absent,
                description=f"{json_path} 不大于 {flat['maximum']}",
                source_ref=f"{source_prefix}#/maximum",
            )
        )
    return assertions


def _response_assertions(
    response: ApiResponseDefinition | None,
    *,
    manual_reason: str = "",
) -> list[ApiAssertion]:
    if response is None:
        return [
            ApiAssertion(
                kind="status",
                operator="manual",
                description=manual_reason or "规范未声明响应状态，需人工补充",
                status="manual",
            )
        ]
    assertions: list[ApiAssertion] = []
    if response.status_code.isdigit():
        assertions.append(
            ApiAssertion(
                kind="status",
                operator="equals",
                expected=int(response.status_code),
                description=f"响应状态码为 {response.status_code}",
                source_ref=response.source_ref,
            )
        )
    else:
        assertions.append(
            ApiAssertion(
                kind="status",
                operator="manual",
                expected=response.status_code,
                description=f"响应状态码为 {response.status_code or 'default'}，需人工确认具体值",
                source_ref=response.source_ref,
                status="manual",
            )
        )
    for header in response.headers:
        assertions.append(
            ApiAssertion(
                kind="header",
                path=header.name,
                operator="exists",
                description=f"响应头 {header.name} 存在",
                source_ref=header.source_ref,
            )
        )
    media = _response_media(response)
    if media is None:
        assertions.append(
            ApiAssertion(
                kind="json",
                operator="manual",
                description="响应未声明 content/schema，需人工补充字段断言",
                source_ref=response.source_ref,
                status="manual",
            )
        )
    elif "json" in media.content_type.lower():
        schema_assertions = _schema_assertions(
            media.schema_,
            response=response,
            source_prefix=media.source_ref,
        )
        if not schema_assertions:
            assertions.append(
                ApiAssertion(
                    kind="json",
                    operator="manual",
                    description="响应 schema 为空，需人工补充字段断言",
                    source_ref=media.source_ref,
                    status="manual",
                )
            )
        assertions.extend(schema_assertions)
    return assertions


def _case_id(operation: ApiOperation, category: str, discriminator: str) -> str:
    method = re.sub(r"[^A-Z0-9]+", "", operation.method.upper())[:4] or "API"
    token = short_hash(operation.operation_id, category, discriminator, length=10).upper()
    return f"API-{method}-{token}"


def _case(
    spec: ApiSpec,
    operation: ApiOperation,
    *,
    title: str,
    category: str,
    discriminator: str,
    execution: ExecutionSpec,
    preconditions: list[str],
    assertions: list[ApiAssertion],
    warnings: list[str] | None = None,
    priority: str = "P2",
) -> ApiCaseSpec:
    return ApiCaseSpec(
        case_id=_case_id(operation, category, discriminator),
        spec_id=spec.spec_id,
        operation_id=operation.operation_id,
        title=title,
        method=operation.method,
        path=operation.path,
        category=category,  # type: ignore[arg-type]
        priority=priority,
        preconditions=preconditions,
        execution=execution,
        assertions=assertions,
        requirement_ids=list(operation.requirement_ids),
        tags=list(dict.fromkeys([*operation.tags, "接口", category])),
        source_ref=operation.source_ref,
        warnings=list(warnings or []),
        created_at=now_iso(),
    )


def _field_catalog(
    schema: dict[str, Any] | None,
    *,
    path: str = "",
    depth: int = 0,
) -> list[tuple[str, dict[str, Any], bool]]:
    if depth > 8 or not isinstance(schema, dict):
        return []
    flat, _ = _schema_branch(schema)
    if not isinstance(flat.get("properties"), dict):
        return []
    required = {str(item) for item in flat.get("required") or []}
    fields: list[tuple[str, dict[str, Any], bool]] = []
    for name, child in flat["properties"].items():
        if not isinstance(child, dict) or child.get("readOnly"):
            continue
        field_path = f"{path}.{name}".strip(".")
        fields.append((field_path, child, name in required))
        if isinstance(child.get("properties"), dict):
            fields.extend(_field_catalog(child, path=field_path, depth=depth + 1))
    return fields


def _get_parent(value: Any, path: str) -> tuple[Any, str] | None:
    parts = path.split(".")
    current = value
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return (current, parts[-1]) if isinstance(current, dict) else None


def _mutate_body(body: Any, path: str, mutation: str) -> Any:
    updated = copy.deepcopy(body)
    parent = _get_parent(updated, path)
    if parent is None:
        return updated
    container, key = parent
    if mutation == "remove":
        container.pop(key, None)
    elif mutation == "type":
        current = container.get(key)
        container[key] = "invalid-type" if not isinstance(current, str) else 123456
    elif mutation.startswith("set:"):
        container[key] = mutation.split(":", 1)[1]
    return updated


def _attach_error_assertions(
    assertions: list[ApiAssertion],
    operation: ApiOperation,
) -> list[ApiAssertion]:
    error = _error_response(operation)
    return [*assertions, *_response_assertions(error)]


def _generate_operation(
    spec: ApiSpec,
    operation: ApiOperation,
) -> ApiCaseGenerationResult:
    result = ApiCaseGenerationResult()
    success = _success_response(operation)
    positive_execution, preconditions, _ = _execution(operation, spec)
    positive_assertions = _response_assertions(
        success,
        manual_reason="operation 未声明响应，正向状态码与字段断言需人工补充",
    )
    positive = _case(
        spec,
        operation,
        title=f"[正向] {operation.method} {operation.path} {operation.summary}".strip(),
        category="positive",
        discriminator="positive",
        execution=positive_execution,
        preconditions=preconditions,
        assertions=positive_assertions,
        priority="P1",
    )
    result.cases.append(positive)

    request_media = _media_for_request(operation)
    request_schema = _merge_schema(request_media.schema_ if request_media else {})
    field_catalog = _field_catalog(request_schema)
    negative_specs: list[tuple[str, str, ExecutionSpec, list[str], list[ApiAssertion]]] = []

    for parameter in operation.parameters:
        if not parameter.required or parameter.location == "path":
            continue
        altered = copy.deepcopy(positive_execution)
        if parameter.location == "query":
            altered.query.pop(parameter.name, None)
            location = "查询参数"
        elif parameter.location == "header":
            altered.headers.pop(parameter.name, None)
            location = "请求头"
        else:
            altered.cookies.pop(parameter.name, None)
            location = "Cookie"
        negative_specs.append(
            (
                f"[异常] {operation.method} {operation.path} 缺少必填{location} {parameter.name}",
                f"missing-param-{parameter.location}-{parameter.name}",
                altered,
                [f"必填{location} {parameter.name} 缺失"],
                _attach_error_assertions([], operation),
            )
        )

    for parameter in operation.parameters:
        parameter_schema = _merge_schema(parameter.schema_)
        constraints: list[tuple[str, str]] = []
        if parameter_schema.get("enum"):
            constraints.append(("枚举越界", "invalid-enum"))
        if parameter_schema.get("minimum") is not None:
            constraints.append(("小于最小值", str(parameter_schema["minimum"] - 1)))
        if parameter_schema.get("maximum") is not None:
            constraints.append(("大于最大值", str(parameter_schema["maximum"] + 1)))
        if parameter_schema.get("minLength") is not None and int(parameter_schema["minLength"]) > 0:
            constraints.append(("小于最小长度", "a" * max(int(parameter_schema["minLength"]) - 1, 0)))
        if parameter_schema.get("maxLength") is not None:
            constraints.append(
                ("大于最大长度", "a" * min(int(parameter_schema["maxLength"]) + 1, 2048))
            )
        if parameter_schema.get("pattern"):
            constraints.append(("不匹配正则", "__invalid_pattern__"))
        for label, value in constraints[:8]:
            altered = copy.deepcopy(positive_execution)
            if parameter.location == "query":
                altered.query[parameter.name] = value
            elif parameter.location == "header":
                altered.headers[parameter.name] = value
            elif parameter.location == "cookie":
                altered.cookies[parameter.name] = value
            else:
                altered.path_params[parameter.name] = value
                altered.url = altered.url.replace(
                    f"{{{{{parameter.name}}}}}",
                    value,
                )
            negative_specs.append(
                (
                    f"[边界] {operation.method} {operation.path} 参数 {parameter.name} {label}",
                    f"parameter-{label}-{parameter.name}",
                    altered,
                    [f"{parameter.name} 的取值超出规范约束：{label}"],
                    _attach_error_assertions([], operation),
                )
            )

    if operation.request_body and operation.request_body.required:
        missing_execution, missing_pre, _ = _execution(operation, spec, omit_body=True)
        negative_specs.append(
            (
                f"[异常] {operation.method} {operation.path} 缺少必填请求体",
                "missing-body",
                missing_execution,
                [*missing_pre, "requestBody 为必填但请求不携带 body"],
                _attach_error_assertions([], operation),
            )
        )

    if request_media and positive_execution.body is not None:
        if isinstance(positive_execution.body, dict):
            for field_path, field_schema, required in field_catalog:
                if not required:
                    continue
                missing_body = _mutate_body(positive_execution.body, field_path, "remove")
                execution, pre, _ = _execution(operation, spec, body_override=missing_body)
                negative_specs.append(
                    (
                        f"[异常] {operation.method} {operation.path} 缺少必填字段 {field_path}",
                        f"missing-field-{field_path}",
                        execution,
                        [*pre, f"请求体缺少必填字段 {field_path}"],
                        _attach_error_assertions([], operation),
                    )
                )
                if len([item for item in negative_specs if "missing-field" in item[1]]) >= 8:
                    break

            type_field = next(
                (
                    (path, schema)
                    for path, schema, _ in field_catalog
                    if schema.get("type") in {"string", "integer", "number", "boolean", "array", "object"}
                    and not schema.get("enum")
                ),
                None,
            )
            if type_field:
                invalid_body = _mutate_body(positive_execution.body, type_field[0], "type")
                execution, pre, _ = _execution(operation, spec, body_override=invalid_body)
                negative_specs.append(
                    (
                        f"[异常] {operation.method} {operation.path} 字段 {type_field[0]} 类型错误",
                        f"invalid-type-{type_field[0]}",
                        execution,
                        [*pre, f"字段 {type_field[0]} 使用错误 JSON 类型"],
                        _attach_error_assertions([], operation),
                    )
                )

            enum_fields = [
                (path, schema)
                for path, schema, _ in field_catalog
                if schema.get("enum")
            ]
            for path, schema in enum_fields[:4]:
                invalid_body = _mutate_body(
                    positive_execution.body,
                    path,
                    "set:__invalid_enum__",
                )
                execution, pre, _ = _execution(operation, spec, body_override=invalid_body)
                negative_specs.append(
                    (
                        f"[异常] {operation.method} {operation.path} 字段 {path} 枚举越界",
                        f"invalid-enum-{path}",
                        execution,
                        [*pre, f"字段 {path} 使用枚举外值"],
                        _attach_error_assertions([], operation),
                    )
                )

            for path, schema, _ in field_catalog:
                minimum = schema.get("minimum")
                maximum = schema.get("maximum")
                min_length = schema.get("minLength")
                max_length = schema.get("maxLength")
                if min_length is not None and int(min_length) > 0:
                    invalid_body = _mutate_body(
                        positive_execution.body,
                        path,
                        "set:" + ("a" * max(int(min_length) - 1, 0)),
                    )
                    execution, pre, _ = _execution(operation, spec, body_override=invalid_body)
                    negative_specs.append(
                        (
                            f"[边界] {operation.method} {operation.path} 字段 {path} 小于最小长度",
                            f"min-length-{path}",
                            execution,
                            [*pre, f"{path} 长度取规范最小值 - 1"],
                            _attach_error_assertions([], operation),
                        )
                    )
                if max_length is not None:
                    invalid_body = _mutate_body(
                        positive_execution.body,
                        path,
                        "set:" + ("a" * min(int(max_length) + 1, 1000)),
                    )
                    execution, pre, _ = _execution(operation, spec, body_override=invalid_body)
                    negative_specs.append(
                        (
                            f"[边界] {operation.method} {operation.path} 字段 {path} 大于最大长度",
                            f"max-length-{path}",
                            execution,
                            [*pre, f"{path} 长度取规范最大值 + 1"],
                            _attach_error_assertions([], operation),
                        )
                    )
                if minimum is not None:
                    invalid_body = _mutate_body(positive_execution.body, path, f"set:{minimum - 1}")
                    execution, pre, _ = _execution(operation, spec, body_override=invalid_body)
                    negative_specs.append(
                        (
                            f"[边界] {operation.method} {operation.path} 字段 {path} 小于最小值",
                            f"minimum-{path}",
                            execution,
                            [*pre, f"{path} 取规范最小值 - 1"],
                            _attach_error_assertions([], operation),
                        )
                    )
                if maximum is not None:
                    invalid_body = _mutate_body(positive_execution.body, path, f"set:{maximum + 1}")
                    execution, pre, _ = _execution(operation, spec, body_override=invalid_body)
                    negative_specs.append(
                        (
                            f"[边界] {operation.method} {operation.path} 字段 {path} 大于最大值",
                            f"maximum-{path}",
                            execution,
                            [*pre, f"{path} 取规范最大值 + 1"],
                            _attach_error_assertions([], operation),
                        )
                    )
                pattern = schema.get("pattern")
                if pattern:
                    invalid_body = _mutate_body(
                        positive_execution.body,
                        path,
                        "set:__invalid_pattern__",
                    )
                    execution, pre, _ = _execution(operation, spec, body_override=invalid_body)
                    negative_specs.append(
                        (
                            f"[异常] {operation.method} {operation.path} 字段 {path} 不匹配正则",
                            f"pattern-{path}",
                            execution,
                            [*pre, f"{path} 使用不匹配 pattern 的值"],
                            _attach_error_assertions([], operation),
                        )
                    )

        non_json = next(
            (
                item.content_type
                for item in (operation.request_body.content if operation.request_body else [])
                if "json" not in item.content_type.lower()
            ),
            "text/plain",
        )
        execution, pre, _ = _execution(
            operation,
            spec,
            body_override=positive_execution.body,
            content_type_override=non_json,
        )
        negative_specs.append(
            (
                f"[异常] {operation.method} {operation.path} Content-Type 不受支持",
                "invalid-content-type",
                execution,
                [*pre, f"请求声明 {non_json}，而规范请求体为 JSON"],
                _attach_error_assertions([], operation),
            )
        )

    if operation.security:
        unauth = copy.deepcopy(positive_execution)
        unauth.headers.pop("Authorization", None)
        unauth.query = {
            key: value
            for key, value in unauth.query.items()
            if not _SECRET_KEY_RE.search(key)
        }
        unauth.cookies = {
            key: value
            for key, value in unauth.cookies.items()
            if not _SECRET_KEY_RE.search(key)
        }
        negative_specs.append(
            (
                f"[安全] {operation.method} {operation.path} 缺少鉴权凭据",
                "missing-auth",
                unauth,
                ["不携带规范要求的鉴权信息"],
                _attach_error_assertions([], operation),
            )
        )

    if not negative_specs:
        manual_reason = (
            "规范未声明必填参数、请求体约束或鉴权条件，异常场景无法由规范确定性构造，"
            "已保留待补充用例。"
        )
        operation.warnings.append(manual_reason)
        negative_specs.append(
            (
                f"[待补充] {operation.method} {operation.path} 异常场景",
                "manual-negative",
                copy.deepcopy(positive_execution),
                ["规范约束不足，异常输入需人工补充"],
                [
                    ApiAssertion(
                        kind="status",
                        operator="manual",
                        description="异常状态码待人工补充",
                        source_ref=operation.source_ref,
                        status="manual",
                    )
                ],
            )
        )
        result.warnings.append(f"{operation.method} {operation.path}：{manual_reason}")

    normal_error = _error_response(operation)
    if normal_error is None and any(not item.status_code.isdigit() for item in operation.responses):
        result.warnings.append(
            f"{operation.method} {operation.path} 只有 default 响应，异常状态码无法静态确定。"
        )
    for title, discriminator, execution, preconditions, assertions in negative_specs:
        category = (
            "security" if discriminator == "missing-auth"
            else "boundary" if title.startswith("[边界]")
            else "negative"
        )
        result.cases.append(
            _case(
                spec,
                operation,
                title=title,
                category=category,
                discriminator=discriminator,
                execution=execution,
                preconditions=preconditions,
                assertions=assertions,
                warnings=["异常值来自规范约束"] if category != "negative" or "待补充" not in title else [
                    "规范约束不足，本用例需要人工补充具体异常输入与断言"
                ],
            )
        )

    if request_media and not request_schema.get("properties") and request_schema.get("type") == "object":
        operation.warnings.append("请求体 schema 未声明字段属性，无法生成字段级异常用例。")
    if not request_media and not operation.parameters and not operation.security:
        pass
    return result


def recount_api_stats(spec: ApiSpec, cases: list[ApiCaseSpec]) -> None:
    assertions = [assertion for case in cases for assertion in case.assertions]
    spec.stats.operations = len(spec.operations)
    spec.stats.cases = len(cases)
    spec.stats.positive_cases = sum(1 for case in cases if case.category == "positive")
    spec.stats.negative_cases = len(cases) - spec.stats.positive_cases
    spec.stats.contract_assertions = sum(
        1 for assertion in assertions if assertion.status == "defined"
    )
    spec.stats.manual_assertions = sum(
        1 for assertion in assertions if assertion.status == "manual"
    )
    spec.stats.operation_gaps = sum(1 for operation in spec.operations if operation.warnings)


def generate_api_cases(spec: ApiSpec) -> ApiCaseGenerationResult:
    """为每个 operation 至少生成一条正向与一条异常用例。"""
    combined = ApiCaseGenerationResult()
    seen_case_ids: set[str] = set()
    for operation in spec.operations:
        operation.warnings = list(dict.fromkeys(operation.warnings))
        result = _generate_operation(spec, operation)
        combined.warnings.extend(result.warnings)
        for case in result.cases:
            if case.case_id in seen_case_ids:
                case.case_id = f"{case.case_id}-{short_hash(case.title, length=4).upper()}"
            seen_case_ids.add(case.case_id)
            combined.cases.append(case)
        operation.warnings = list(dict.fromkeys(operation.warnings))
    spec.warnings.extend(
        warning for warning in combined.warnings if warning not in spec.warnings
    )
    recount_api_stats(spec, combined.cases)
    return combined


__all__ = ["ApiCaseGenerationResult", "generate_api_cases", "recount_api_stats"]
