"""测试报告模块配置（统一后的实现）。

与「用例生成」共用同一份 LLM 配置（`.env` 基线 + `storage/data/llm_config.json` 运行时覆盖），
这样测试工程师只需要在一处配置大模型即可同时用于两条链路。

本模块只额外维护「发版判定阈值」——它存在 `storage/data/report_config.json`，
逐项回落到 `.env`，界面可改可存、可一键恢复。
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.context import get_current_project_id

APP_NAME = "测试工程师助手平台"
APP_SUBTITLE = "AI 用例生成 · 测试报告"

DEFAULT_INSTRUCTION = "生成测试总结、风险分析、缺陷归纳和下一步建议。"

DEFAULT_TITLE_PREFIX = "测试报告"

KNOWN_PROVIDERS = {
    "api.deepseek.com": "DeepSeek",
    "dashscope.aliyuncs.com": "阿里云百炼",
    "api.openai.com": "OpenAI",
    "api.moonshot.cn": "Moonshot",
    "open.bigmodel.cn": "智谱 AI",
    "api.siliconflow.cn": "SiliconFlow",
}

THRESHOLD_FIELDS = ("fail_rate", "blocked_rate", "execution_floor", "pass_line")

RUNTIME_CONFIG_FILENAME = "report_config.json"


def provider_label(host: str) -> str:
    """把 base_url 的主机名翻成界面能读的服务商标签。

    自建/本地部署时主机名往往就是一个 IP，直接显示 127.0.0.1 没有信息量。
    """
    if not host:
        return "自定义"
    if host in KNOWN_PROVIDERS:
        return KNOWN_PROVIDERS[host]
    if host == "localhost" or host.endswith(".local"):
        return "本地服务"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if address.is_loopback or address.is_private or address.is_link_local:
        return "本地服务"
    return host


@dataclass(frozen=True)
class VerdictThresholds:
    """发版判定的阈值。不同业务的发版标准差别很大，所以不写死在规则里。"""

    fail_rate: float = 0.05
    blocked_rate: float = 0.05
    execution_floor: float = 0.9
    pass_line: float = 0.95

    def as_dict(self) -> dict[str, float]:
        return {key: float(getattr(self, key)) for key in THRESHOLD_FIELDS}


def _settings() -> Settings:
    return get_settings()


def data_dir() -> Path:
    settings = _settings()
    project_id = get_current_project_id()
    if project_id and (
        project_id != "PRJ-default" or settings.project_isolation_enabled
    ):
        path = settings.project_storage_dir(project_id) / "data"
    else:
        path = settings.data_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "reports.db"


def runtime_config_path() -> Path:
    return data_dir() / RUNTIME_CONFIG_FILENAME


def env_defaults() -> dict[str, float]:
    """`.env` 提供的判定阈值默认值，也是「留空即回落」的目标。"""
    settings = _settings()
    return {
        "fail_rate": float(settings.verdict_fail_rate),
        "blocked_rate": float(settings.verdict_blocked_rate),
        "execution_floor": float(settings.verdict_execution_floor),
        "pass_line": float(settings.verdict_pass_line),
    }


def _clamp(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(max(float(value), 0.0), 1.0)


def saved_thresholds() -> dict[str, float]:
    """界面保存的阈值覆盖项（读取失败一律忽略，不影响服务启动）。"""
    path = runtime_config_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, float] = {}
    for key in THRESHOLD_FIELDS:
        value = _clamp(raw.get(key))
        if value is not None:
            result[key] = value
    return result


def thresholds_source() -> dict[str, str]:
    """每个阈值字段的来源（saved / env），界面据此显示「已保存」或「.env 默认」。"""
    saved = saved_thresholds()
    return {key: ("saved" if key in saved else "env") for key in THRESHOLD_FIELDS}


def verdict_thresholds() -> VerdictThresholds:
    """发版判定阈值：界面保存的优先，逐项回落到 .env。"""
    merged = dict(env_defaults())
    merged.update(saved_thresholds())
    return VerdictThresholds(**merged)


def save_thresholds(values: dict[str, Any]) -> dict[str, float]:
    """写入阈值覆盖。值为 None / 非法 → 删除该项（回落 .env）。"""
    current = saved_thresholds()
    for key in THRESHOLD_FIELDS:
        if key not in values:
            continue
        value = _clamp(values.get(key))
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value

    path = runtime_config_path()
    if current:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f"{path.name}.tmp"
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    elif path.exists():
        path.unlink()
    return current


def clear_thresholds() -> None:
    """清空阈值覆盖，全部回到 .env 默认。"""
    path = runtime_config_path()
    if path.exists():
        path.unlink()
