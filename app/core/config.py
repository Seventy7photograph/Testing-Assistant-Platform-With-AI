"""全局配置。

配置优先级：环境变量 > .env 文件 > 代码默认值。
所有密钥类配置（如 LLM_API_KEY）只能通过环境变量注入，禁止硬编码。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

# 项目根目录（app/core/config.py -> app/core -> app -> 项目根）
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

# none = 显式选择「纯规则引擎」，与「未配置 Key 自动降级」区分开，便于界面表达意图。
LLMProviderName = Literal["deepseek", "openai_compatible", "fake", "none"]


class Settings(BaseSettings):
    """应用配置模型。字段名对应环境变量名（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 应用 ----------
    app_name: str = "测试工程师助手平台"
    api_prefix: str = "/api/v1"
    debug: bool = False
    log_level: str = "INFO"

    # ---------- 存储 ----------
    storage_dir: Path = Field(default=PROJECT_ROOT / "storage")
    max_upload_size_mb: int = 20
    #: 持久化后端：json（默认，零依赖、与既有数据完全兼容）/ sqlite（SQLAlchemy）。
    #: 切换是一次显式动作，且需先用 scripts/migrate_json_to_sqlite.py 迁移既有数据。
    storage_backend: str = "json"

    # ---------- LLM ----------
    llm_provider: LLMProviderName = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    llm_timeout: float = 60.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.2
    #: 单次补全的输出上限。不要低于 8192：推理型模型（如 deepseek-flash）会先花掉上千个
    #: reasoning token，预算太小会让结构化 JSON 直接被截断。
    llm_max_tokens: int = 8192
    #: 报告归纳温度独立于用例解析 / 复核。后两者由 PromptSpec 固定为低温度。
    report_temperature: float = 0.3

    # ---------- 设计引擎 ----------
    #: 生成阶段大模型的参与方式（基线；界面可按次覆盖）。
    #:   scenario —— 只让场景法补充用例（默认，与 V1.0 行为一致）
    #:   review   —— 六种方法都覆盖：模型复核规则产出并给出意见（不改写用例，一次调用/需求）
    #:   enhance  —— review + 允许补充用例（带来源标记与数量上限）
    llm_design_mode: str = "scenario"
    #: 单次生成允许调用大模型的总次数上限（成本护栏）。
    llm_max_calls_per_generation: int = 20
    #: 单条需求最多生成多少条用例（跨全部设计方法）。
    #: 它是一道防爆护栏，不是"推荐产量"：V2.0 加入判定表 / 因果图 / 正交实验后，
    #: 结构完整的需求自然产出 65~75 条是常态，60 会让护栏几乎每次都触发。
    #: 200 仍能拦住病态输入（例如 40 字段表单的边界值组合），但不再日常报警。
    #: 界面可按次覆盖（GenerateRequest.max_cases_per_requirement）。
    max_cases_per_requirement: int = 200

    # ---------- 图片识别（V2.0 多模态 OCR） ----------
    #: 识别通道：auto（默认，按 多模态模型 -> 本地 OCR -> 云端 OCR 依次降级）
    #: / vlm / local-ocr / cloud-ocr / none。
    vision_provider: str = "auto"
    #: 多模态模型的输出形态：text（只要图里的文字）/ describe（描述界面与流程要素）/ both。
    vision_mode: str = "text"
    #: 留空时复用 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL。
    vision_api_key: str = ""
    vision_base_url: str = ""
    vision_model: str = ""
    vision_timeout: float = 90.0
    #: 本地 OCR 引擎（留空=自动探测）与识别语言。
    vision_ocr_backend: str = ""
    vision_languages: str = "chi_sim+eng"
    #: 云端 OCR（通用契约，见 app/vision/cloud_ocr.py）。
    vision_cloud_url: str = ""
    vision_cloud_key: str = ""
    vision_cloud_field: str = "text"
    #: 单份文档最多识别的图片数（含内嵌图与整页扫描），防止批量图片把额度烧穿。
    vision_max_images: int = 20
    #: 提交给多模态模型前的长边上限（下采样，控制 token 与费用）。
    vision_max_side: int = 1600
    #: 小于该像素面积的图片（图标、logo、分隔线）直接跳过识别。
    vision_min_pixels: int = 4096

    # ---------- 测试报告：发版判定阈值 ----------
    # 不同团队的发版标准差别很大，所以不写死在规则里；
    # 界面「判定阈值」面板可改可存，逐项回落这里的基线值。
    verdict_fail_rate: float = 0.05
    verdict_blocked_rate: float = 0.05
    verdict_execution_floor: float = 0.9
    verdict_pass_line: float = 0.95

    @field_validator(
        "verdict_fail_rate",
        "verdict_blocked_rate",
        "verdict_execution_floor",
        "verdict_pass_line",
        mode="before",
    )
    @classmethod
    def _clamp_ratio(cls, value: object) -> float:
        """比例型阈值：夹在 0–1。写 5 或 -1 都不能把判定搞乱。"""
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return min(max(number, 0.0), 1.0)

    @field_validator("storage_dir", mode="before")
    @classmethod
    def _resolve_storage_dir(cls, value: object) -> Path:
        """相对路径统一解析为「项目根目录下的绝对路径」，避免受启动目录影响。"""
        path = Path(str(value)).expanduser()
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    # ---------- 派生路径 ----------
    @property
    def app_version(self) -> str:
        """版本号以代码为准（app/__init__.py），避免旧 .env 里的 APP_VERSION 覆盖出错误版本。"""
        return __version__

    @property
    def upload_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def export_dir(self) -> Path:
        return self.storage_dir / "exports"

    @property
    def data_dir(self) -> Path:
        return self.storage_dir / "data"

    @property
    def db_path(self) -> Path:
        """SQLite 数据库文件（选用 sqlite 后端时使用）。"""
        return self.data_dir / "platform.db"

    @property
    def asset_dir(self) -> Path:
        """文档内嵌图片/整页截图等附件的落盘目录（V2.0 多模态 OCR）。"""
        return self.upload_dir / "assets"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        """确保运行时目录存在（幂等）。"""
        for path in (
            self.storage_dir,
            self.upload_dir,
            self.export_dir,
            self.data_dir,
            self.asset_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def with_llm_overrides(self, overrides: dict[str, object]) -> "Settings":
        """基于当前配置生成一份带 LLM 覆盖的副本（不改动全局单例）。"""
        return self.model_copy(update=dict(overrides))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局唯一配置实例（带缓存）。"""
    settings = Settings()
    settings.ensure_dirs()
    return settings


def reset_settings_cache() -> None:
    """清除配置缓存（测试用）。"""
    get_settings.cache_clear()
