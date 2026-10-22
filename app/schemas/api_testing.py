"""OpenAPI 接口测试资产模型。

接口用例刻意与通用 :class:`app.schemas.testcase.TestCase` 分离：
HTTP 请求、响应 schema 与契约断言属于接口域，不能反向污染六种通用测试设计
方法的数据模型。两类用例通过 ``case_id`` / ``requirement_ids`` 建立追溯关系。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.utils import now_iso


class ApiServer(BaseModel):
    url: str
    description: str = ""


class ApiSecurityScheme(BaseModel):
    name: str
    type: str = ""
    scheme: str = ""
    location: str = ""
    parameter_name: str = ""
    bearer_format: str = ""
    description: str = ""


class ApiParameter(BaseModel):
    """规范化后的 operation 参数。"""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    location: Literal["path", "query", "header", "cookie"] = "query"
    required: bool = False
    description: str = ""
    deprecated: bool = False
    example: Any = None
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    source_ref: str = ""


class ApiMediaType(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content_type: str
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    example: Any = None
    examples: dict[str, Any] = Field(default_factory=dict)
    source_ref: str = ""


class ApiRequestBody(BaseModel):
    required: bool = False
    description: str = ""
    content: list[ApiMediaType] = Field(default_factory=list)
    source_ref: str = ""


class ApiResponseDefinition(BaseModel):
    status_code: str
    description: str = ""
    content: list[ApiMediaType] = Field(default_factory=list)
    headers: list[ApiParameter] = Field(default_factory=list)
    source_ref: str = ""


class ApiOperation(BaseModel):
    operation_id: str
    method: str
    path: str
    summary: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    deprecated: bool = False
    parameters: list[ApiParameter] = Field(default_factory=list)
    request_body: ApiRequestBody | None = None
    responses: list[ApiResponseDefinition] = Field(default_factory=list)
    security: list[dict[str, list[str]]] = Field(default_factory=list)
    servers: list[ApiServer] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    source_ref: str = ""
    warnings: list[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.method.upper()} {self.path}"


class ApiSpecStats(BaseModel):
    operations: int = 0
    cases: int = 0
    positive_cases: int = 0
    negative_cases: int = 0
    contract_assertions: int = 0
    manual_assertions: int = 0
    operation_gaps: int = 0


class ApiReviewFinding(BaseModel):
    """大模型对接口用例的只读复核意见。"""

    severity: Literal["info", "warning"] = "info"
    kind: Literal["case_gap", "assertion_gap", "documentation"] = "case_gap"
    operation_id: str
    target: str = ""
    issue: str
    suggestion: str = ""
    source_ref: str = ""
    claim_status: Literal["inferred", "verified", "rejected"] = "inferred"
    uncertainty_reason: str = ""


class ApiReviewMeta(BaseModel):
    requested: bool = True
    used: bool = False
    status: Literal["running", "completed", "failed"] = "completed"
    provider: str = ""
    model: str = ""
    prompt_id: str = ""
    prompt_version: str = ""
    temperature: float | None = None
    llm_calls: int = 0
    reviewed_operations: int = 0
    elapsed_ms: int = 0
    warnings: list[str] = Field(default_factory=list)


class ApiReviewResult(BaseModel):
    spec_id: str
    findings: list[ApiReviewFinding] = Field(default_factory=list)
    meta: ApiReviewMeta = Field(default_factory=ApiReviewMeta)
    created_at: str = Field(default_factory=now_iso)


class ApiSpec(BaseModel):
    spec_id: str
    title: str
    version: str = ""
    openapi_version: str = ""
    description: str = ""
    source_file: str = ""
    source_format: str = ""
    source_hash: str = ""
    size_bytes: int = 0
    servers: list[ApiServer] = Field(default_factory=list)
    security_schemes: list[ApiSecurityScheme] = Field(default_factory=list)
    operations: list[ApiOperation] = Field(default_factory=list)
    stats: ApiSpecStats = Field(default_factory=ApiSpecStats)
    ai_review: ApiReviewResult | None = Field(
        default=None,
        description="最近一次显式触发的大模型只读复核结果；不会改写用例。",
    )
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)

    def summary(self) -> "ApiSpecSummary":
        return ApiSpecSummary(
            spec_id=self.spec_id,
            title=self.title,
            version=self.version,
            openapi_version=self.openapi_version,
            description=self.description,
            source_file=self.source_file,
            source_format=self.source_format,
            size_bytes=self.size_bytes,
            stats=self.stats,
            warnings=self.warnings,
            created_at=self.created_at,
        )


class ApiSpecSummary(BaseModel):
    spec_id: str
    title: str
    version: str = ""
    openapi_version: str = ""
    description: str = ""
    source_file: str = ""
    source_format: str = ""
    size_bytes: int = 0
    stats: ApiSpecStats = Field(default_factory=ApiSpecStats)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class ExecutionSpec(BaseModel):
    """供 Postman / 后续自动化生成器消费的受控执行描述。"""

    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)
    path_params: dict[str, str] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    body_kind: str = ""
    environment_variables: list[dict[str, Any]] = Field(default_factory=list)


class ApiAssertion(BaseModel):
    """单条契约断言；``manual`` 表示规范信息不足，必须人工补充。"""

    kind: Literal["status", "header", "json"] = "json"
    path: str = ""
    operator: str = ""
    expected: Any = None
    description: str = ""
    source_ref: str = ""
    status: Literal["defined", "manual"] = "defined"


class ApiCaseSpec(BaseModel):
    case_id: str
    spec_id: str
    operation_id: str
    title: str
    method: str
    path: str
    category: Literal["positive", "negative", "boundary", "security", "contract"] = "positive"
    priority: str = "P2"
    preconditions: list[str] = Field(default_factory=list)
    execution: ExecutionSpec
    assertions: list[ApiAssertion] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_ref: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class ApiCaseCollection(BaseModel):
    spec_id: str
    operation_id: str | None = None
    cases: list[ApiCaseSpec] = Field(default_factory=list)


class ApiImportResult(BaseModel):
    spec: ApiSpec
    cases: list[ApiCaseSpec] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ApiSpecDeleteResult(BaseModel):
    deleted: bool = False
    spec_id: str
    deleted_cases: int = 0


__all__ = [
    "ApiAssertion",
    "ApiCaseCollection",
    "ApiCaseSpec",
    "ApiImportResult",
    "ApiMediaType",
    "ApiOperation",
    "ApiParameter",
    "ApiRequestBody",
    "ApiReviewFinding",
    "ApiReviewMeta",
    "ApiReviewResult",
    "ApiResponseDefinition",
    "ApiSecurityScheme",
    "ApiServer",
    "ApiSpec",
    "ApiSpecDeleteResult",
    "ApiSpecStats",
    "ApiSpecSummary",
    "ExecutionSpec",
]
