"""LLM 运行时配置：界面覆盖层 + .env 基线。

配置优先级：运行时覆盖（storage/data/llm_config.json） > 环境变量 / .env > 代码默认值。

为什么保留 .env 固定配置、而不是「只能在界面里配」：
  1. 本地 `python run.py` 即可用，无需先打开界面点一遍（开箱即用）；
  2. CI / 无人值守 / 无界面环境同样需要可配置；
  3. 界面配置只是「临时覆盖」，随时可一键恢复 .env 基线。

安全性：覆盖文件位于 storage/（已被 .gitignore 排除），密钥不会进入 git；
接口回显一律使用掩码，日志不打印明文 Key。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import LLMProviderName, Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

RUNTIME_CONFIG_FILENAME = "llm_config.json"

# 允许被界面覆盖、且会被计入 Provider 指纹的字段。
LLM_OVERRIDE_FIELDS: tuple[str, ...] = (
    "llm_provider",
    "llm_api_key",
    "llm_base_url",
    "llm_model",
    "llm_timeout",
    "llm_max_retries",
    "llm_temperature",
    "llm_max_tokens",
)


class LLMOverride(BaseModel):
    """界面可覆盖的 LLM 配置子集；None 表示「沿用更底层（.env）的值」。"""

    model_config = ConfigDict(extra="ignore")

    llm_provider: LLMProviderName | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout: float | None = Field(default=None, gt=0, le=600)
    llm_max_retries: int | None = Field(default=None, ge=0, le=10)
    llm_temperature: float | None = Field(default=None, ge=0, le=2)
    llm_max_tokens: int | None = Field(default=None, ge=16, le=131072)

    def to_overrides(self) -> dict[str, Any]:
        """转成可直接 update 到 Settings 的字典；空值表示未覆盖。"""
        result: dict[str, Any] = {}
        for key, value in self.model_dump().items():
            if value is None:
                continue
            if key == "llm_api_key" and not str(value):
                continue
            result[key] = value
        return result


class LLMRuntimeConfigStore:
    """运行时配置文件的读写（带 mtime 缓存，避免每次请求都读盘）。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._cached: dict[str, Any] = {}
        self._cached_mtime: float | None = None
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> dict[str, Any]:
        if not self._path.exists():
            self._cached, self._cached_mtime, self._loaded = {}, None, True
            return {}
        mtime = self._path.stat().st_mtime
        if self._loaded and self._cached_mtime == mtime:
            return dict(self._cached)
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("运行时 LLM 配置读取失败，已忽略该文件：%s", exc)
            self._cached, self._cached_mtime, self._loaded = {}, mtime, True
            return {}
        try:
            overrides = LLMOverride.model_validate(raw).to_overrides()
        except ValidationError as exc:
            logger.warning("运行时 LLM 配置不合法，已忽略该文件：%s", exc)
            overrides = {}
        self._cached, self._cached_mtime, self._loaded = overrides, mtime, True
        return dict(overrides)

    def save(self, patch: dict[str, Any]) -> dict[str, Any]:
        """把补丁合并进现有覆盖并落盘；值为 None 的字段表示「不修改」。"""
        merged = dict(self.read())
        for key, value in patch.items():
            if key not in LLM_OVERRIDE_FIELDS or value is None:
                continue
            if key == "llm_api_key" and value == "":
                merged.pop(key, None)
                continue
            merged[key] = value

        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.parent / f"{self._path.name}.tmp"
        tmp_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self._path)
        self._invalidate()
        logger.info("已保存运行时 LLM 配置：覆盖字段 %s", sorted(merged))
        return merged

    def clear(self) -> bool:
        if not self._path.exists():
            return False
        self._path.unlink()
        self._invalidate()
        logger.info("已清除运行时 LLM 配置，恢复 .env 基线。")
        return True

    def exists(self) -> bool:
        return self._path.exists()

    def _invalidate(self) -> None:
        self._cached, self._cached_mtime, self._loaded = {}, None, False


def llm_config_fingerprint(settings: Settings) -> str:
    """对生效的 LLM 配置取指纹，用于判断缓存的 Provider 是否已过期。"""
    payload: dict[str, Any] = {key: getattr(settings, key, None) for key in LLM_OVERRIDE_FIELDS}
    api_key = str(payload.pop("llm_api_key", "") or "")
    payload["llm_api_key_sha256"] = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def mask_api_key(api_key: str) -> str:
    """密钥掩码：仅保留前 4 / 后 4 位，中间以圆点代替。"""
    key = (api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{'•' * 6}{key[-4:]}"
