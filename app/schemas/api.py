"""HTTP 接口契约：统一响应包裹。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from app.schemas.requirement import RequirementDoc
from app.schemas.testcase import TestCaseSuite

DataT = TypeVar("DataT")


class ApiResponse(BaseModel, Generic[DataT]):
    """统一响应体：前端只需判断 success 字段。"""

    success: bool = True
    code: str = "OK"
    message: str = "OK"
    data: DataT | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    code: str
    message: str
    detail: Any = None


class RequirementParseRequest(BaseModel):
    """需求解析请求：doc_id 与 text 二选一。"""

    doc_id: str | None = Field(default=None, description="已上传文档 ID")
    text: str | None = Field(default=None, description="或直接粘贴需求文本")
    title: str = Field(default="粘贴的需求文本", description="需求文档标题")
    use_llm: bool = Field(default=True, description="是否尝试使用大模型解析（失败自动降级规则引擎）")
    max_items: int = Field(default=8, ge=1, le=50, description="最多解析出的需求条目数")


class GenerateRequest(BaseModel):
    """生成测试用例请求。"""

    doc_id: str | None = Field(default=None, description="已上传文档 ID")
    text: str | None = Field(default=None, description="或直接提供需求文本")
    title: str = "粘贴的需求文本"
    methods: list[str] = Field(
        default_factory=lambda: ["equivalence", "boundary", "scenario"],
        description="设计方法；可选 equivalence / boundary / scenario",
    )
    use_llm: bool = Field(default=True, description="是否用大模型增强（失败自动降级）")
    max_items: int = Field(default=8, ge=1, le=50)
    use_llm_in_design: bool = Field(default=False, description="场景法是否调用 LLM 补充用例")


class ExportRequest(BaseModel):
    suite_id: str = Field(..., description="用例集 ID")
    format: str = Field(default="excel", description="导出格式：excel / json")


class MethodInfo(BaseModel):
    name: str
    label: str
    implemented: bool
    description: str = ""


class ExportFormatInfo(BaseModel):
    name: str
    label: str
    media_type: str
    extension: str


class HealthInfo(BaseModel):
    app_name: str
    version: str
    status: str = "ok"
    llm_provider: str
    llm_model: str = ""
    llm_base_url: str = ""
    llm_available: bool = False
    llm_degraded_reason: str = ""
    llm_source: str = Field(default="env", description="env=来自 .env 基线；runtime=被界面覆盖")
    methods: list[MethodInfo] = Field(default_factory=list)
    export_formats: list[ExportFormatInfo] = Field(default_factory=list)
    supported_extensions: list[str] = Field(default_factory=list)

class GenerateResult(BaseModel):
    """一键生成的完整产物：结构化需求 + 用例集 + 告警。"""

    requirement_doc: RequirementDoc
    suite: TestCaseSuite
    warnings: list[str] = Field(default_factory=list)


class IntegrationInfo(BaseModel):
    name: str
    label: str
    implemented: bool


class BatchDeleteRequest(BaseModel):
    """批量删除请求：一次最多 200 条，重复 ID 自动去重。"""

    ids: list[str] = Field(default_factory=list, max_length=200, description="待删除的资源 ID 列表")


class BatchDeleteResult(BaseModel):
    deleted: int = 0
    missing: list[str] = Field(
        default_factory=list, description="未找到或已删除的 ID，便于界面如实反馈"
    )


def ok(data: Any = None, message: str = "OK") -> dict[str, Any]:
    """构造统一成功响应。"""
    return {"success": True, "code": "OK", "message": message, "data": data}
