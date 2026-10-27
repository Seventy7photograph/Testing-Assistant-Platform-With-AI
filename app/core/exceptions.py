"""统一异常体系。

设计原则：
1. 业务异常一律继承 AppError，并携带机器可读的 code 与 HTTP 状态码；
2. 路由层不做 try/except 撒网，由 main.py 的全局异常处理器统一转换为
   {success, code, message, detail} 结构，前后端契约稳定。
"""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    """所有业务异常的基类。"""

    code: str = "APP_ERROR"
    http_status: int = 500
    default_message: str = "服务内部错误"

    def __init__(self, message: str | None = None, *, detail: Any = None) -> None:
        self.message = message or self.default_message
        self.detail = detail
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": False,
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


class BadRequestError(AppError):
    code = "BAD_REQUEST"
    http_status = 400
    default_message = "请求参数不合法"


class ConflictError(AppError):
    code = "CONFLICT"
    http_status = 409
    default_message = "资源正在处理中"


class RateLimitError(AppError):
    code = "RATE_LIMITED"
    http_status = 429
    default_message = "请求频率超过限制，请稍后再试"


class ExternalServiceError(AppError):
    code = "EXTERNAL_SERVICE_ERROR"
    http_status = 502
    default_message = "外部服务调用失败"


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404
    default_message = "资源不存在"


class PayloadTooLargeError(AppError):
    code = "PAYLOAD_TOO_LARGE"
    http_status = 413
    default_message = "上传文件超过大小限制"


class UnsupportedFormatError(AppError):
    code = "UNSUPPORTED_FORMAT"
    http_status = 415
    default_message = "不支持的文件格式"


class DocumentParseError(AppError):
    code = "DOCUMENT_PARSE_FAILED"
    http_status = 422
    default_message = "文档解析失败"


class OpenApiParseError(AppError):
    code = "OPENAPI_PARSE_FAILED"
    http_status = 422
    default_message = "OpenAPI 规范解析失败"


class EmptyDocumentError(DocumentParseError):
    code = "DOCUMENT_EMPTY"
    default_message = "文档内容为空或无法抽取有效文本"


class LLMError(AppError):
    code = "LLM_ERROR"
    http_status = 502
    default_message = "大模型调用失败"


class LLMNotConfiguredError(LLMError):
    code = "LLM_NOT_CONFIGURED"
    http_status = 503
    default_message = "未配置大模型 API Key，请设置环境变量 LLM_API_KEY"


class LLMResponseFormatError(LLMError):
    code = "LLM_RESPONSE_INVALID"
    default_message = "大模型返回内容不是合法 JSON"


class SchemaValidationError(AppError):
    code = "SCHEMA_VALIDATION_FAILED"
    http_status = 422
    default_message = "数据结构校验失败"


class ExportError(AppError):
    code = "EXPORT_FAILED"
    http_status = 500
    default_message = "导出失败"


class FeatureNotAvailableError(AppError):
    """接口已预留但功能尚未实现的占位异常。"""

    code = "FEATURE_NOT_AVAILABLE"
    http_status = 501
    default_message = "该功能当前版本尚未实现。"


class VisionUnavailableError(AppError):
    """图片识别通道不可用（未配置多模态模型，也未安装任何本地 OCR 引擎）。

    只在「使用者明确要求识别图片」时抛出：自动解析链路里遇到这种情况是**降级 + 告警**，
    不能因为一份文档里夹了张图就让整份需求解析失败。
    """

    code = "VISION_UNAVAILABLE"
    http_status = 501
    default_message = "当前没有可用的图片识别通道。"
