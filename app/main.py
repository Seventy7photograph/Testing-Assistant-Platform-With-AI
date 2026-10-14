"""FastAPI 应用装配入口。

启动：
    python run.py
    uvicorn app.main:app --reload
文档：
    http://127.0.0.1:8000/docs  （Swagger UI）
    http://127.0.0.1:8000/      （内置演示页面）
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import mimetypes
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import (
    documents,
    export,
    health,
    llm,
    overview,
    pipeline,
    report as report_routes,
    requirements,
    testcases,
    vision,
)
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger, setup_logging
from app.llm.factory import get_llm_provider
from app.report import store as report_store

# Windows 的 MIME 注册表可能把 .js/.css 映射成 text/plain，
# 导致浏览器以「模块脚本类型不符」拒绝加载前端构建产物。这里显式覆盖。
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".map")

STATIC_DIR = Path(__file__).parent / "static"

logger = get_logger(__name__)

DESCRIPTION = f"""
测试工程师助手平台（v{__version__}）—— 面向测试工程师的一体化工作台。

两条核心链路：
  1. 用例生成：需求文档上传 -> 需求结构化解析 -> 测试设计引擎（等价类/边界值/场景法）-> 用例优化去重 -> Excel / JSON 导出；
  2. 测试报告：测试执行数据 -> 确定性指标（通过率/执行率/缺陷分布/发版判定）-> AI 归纳与建议 -> 存档 / 趋势 / Markdown / HTML / DOCX 导出。

- 未配置 LLM_API_KEY 时，用例生成自动降级为纯规则引擎，报告链路显式提示，功能依然可解释；
- 设计策略、导出器、LLM Provider、外部集成均为插件式接口，新增能力只需注册，不改主干。
"""


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """把 Pydantic 校验错误转成可 JSON 序列化的精简结构。"""
    items: list[dict[str, Any]] = []
    for error in exc.errors():
        items.append(
            {
                "location": [str(part) for part in error.get("loc", [])],
                "message": str(error.get("msg", "")),
                "type": str(error.get("type", "")),
            }
        )
    return items


def register_exception_handlers(app: FastAPI) -> None:
    """统一异常出口：所有错误都返回 {success, code, message, detail}。"""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning("业务异常 %s %s -> %s(%s)", request.method, request.url.path, exc.code, exc.message)
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "code": "VALIDATION_ERROR",
                "message": "请求参数校验失败，请检查字段类型与必填项。",
                "detail": _safe_validation_errors(exc),
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常 %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "code": "INTERNAL_ERROR",
                "message": "服务内部错误，请查看服务端日志。",
                "detail": {"error": str(exc)},
            },
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)
    settings.ensure_dirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_dirs()
        report_store.init_db()
        provider = get_llm_provider()
        logger.info("LLM Provider：%s | available=%s | model=%s", provider.name, provider.available, provider.model)
        if not provider.available:
            logger.warning("当前运行在纯规则引擎模式：%s", provider.degraded_reason)
        logger.info("存储目录：%s", settings.storage_dir)
        yield
        await provider.aclose()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-Export-Filename"],
    )

    for module in (
        health,
        overview,
        llm,
        documents,
        requirements,
        testcases,
        export,
        pipeline,
        report_routes,
        vision,
    ):
        app.include_router(module.router, prefix=settings.api_prefix)

    register_exception_handlers(app)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> Any:
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "api_prefix": settings.api_prefix,
            "docs": "/docs",
        }

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> Any:
        """把非接口路径交给前端路由（Vue Router history 模式）。

        前端构建产物放在 app/static/。命中真实文件就直接返回，
        否则回落 index.html；/api 前缀仍然返回标准 404，避免掩盖接口错误。
        """
        if full_path.startswith(("api/", "openapi.json")) or full_path == "docs":
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "code": "NOT_FOUND",
                    "message": f"接口不存在：/{full_path}",
                    "detail": None,
                },
            )

        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            static_root = STATIC_DIR.resolve()
            candidate = (STATIC_DIR / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(static_root):
                return FileResponse(candidate)
            return FileResponse(index_file)

        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "api_prefix": settings.api_prefix,
            "docs": "/docs",
        }

    return app


app = create_app()
