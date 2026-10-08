"""大模型运行时配置：覆盖优先级、掩码、Provider 重建与接口契约。"""
from __future__ import annotations

import pytest

from app.llm.factory import (
    get_effective_settings,
    get_llm_provider,
    get_runtime_config_store,
    reset_llm_provider_cache,
)
from app.llm.runtime_config import mask_api_key
from app.api.routes.llm import resolve_models_endpoint
from app.core.config import Settings
from app.llm.catalog import provider_option

API = "/api/v1"


@pytest.fixture(autouse=True)
def clean_runtime_config():
    """每个用例前后都清空界面覆盖，避免用例互相污染。"""
    store = get_runtime_config_store()
    store.clear()
    reset_llm_provider_cache()
    yield
    store.clear()
    reset_llm_provider_cache()


def test_default_uses_env_baseline() -> None:
    """没有界面覆盖时，生效配置应与 .env 基线一致（测试里为 fake）。"""
    settings = get_effective_settings()
    assert settings.llm_provider == "fake"
    assert get_runtime_config_store().read() == {}
    assert get_llm_provider().name == "fake"


def test_runtime_override_wins_over_env() -> None:
    get_runtime_config_store().save({"llm_provider": "none"})
    settings = get_effective_settings()
    assert settings.llm_provider == "none"
    provider = get_llm_provider()
    assert provider.available is False
    assert "纯规则引擎" in provider.degraded_reason


def test_clear_restores_env_baseline() -> None:
    store = get_runtime_config_store()
    store.save({"llm_provider": "none"})
    assert get_effective_settings().llm_provider == "none"
    assert store.clear() is True
    assert get_effective_settings().llm_provider == "fake"
    assert store.clear() is False


def test_corrupt_config_file_is_ignored() -> None:
    store = get_runtime_config_store()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{ not json", encoding="utf-8")
    assert store.read() == {}
    assert get_effective_settings().llm_provider == "fake"


def test_provider_is_rebuilt_when_config_changes() -> None:
    """配置指纹变化后必须重建 Provider，否则界面改完不生效。"""
    first = get_llm_provider()
    assert get_llm_provider() is first
    get_runtime_config_store().save({"llm_temperature": 0.9})
    assert get_llm_provider() is not first


def test_api_key_is_masked() -> None:
    assert mask_api_key("sk-abcdefghijklmnop") == "sk-a••••••mnop"
    assert mask_api_key("short") == "•••••"
    assert mask_api_key("") == ""


def test_config_api_roundtrip(client) -> None:
    initial = client.get(f"{API}/llm/config").json()["data"]
    assert initial["provider"] == "fake"
    assert initial["source"] == "env"
    assert {item["name"] for item in initial["providers"]} >= {
        "deepseek",
        "openai_compatible",
        "fake",
        "none",
    }
    assert "api_key" not in initial["env_defaults"]

    saved = client.put(
        f"{API}/llm/config",
        json={
            "provider": "deepseek",
            "model": "deepseek-reasoner",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-abcdefghijklmnop",
            "temperature": 0.5,
        },
    ).json()["data"]
    assert saved["source"] == "runtime"
    assert saved["model"] == "deepseek-reasoner"
    assert saved["api_key_configured"] is True
    assert saved["api_key_masked"] == "sk-a••••••mnop"
    assert "llm_api_key" in saved["overridden_fields"]

    persisted = client.get(f"{API}/llm/config").json()["data"]
    assert persisted["source"] == "runtime"
    assert persisted["temperature"] == 0.5

    reset = client.delete(f"{API}/llm/config").json()["data"]
    assert reset["source"] == "env"
    assert reset["provider"] == "fake"
    assert reset["api_key_configured"] is False


def test_config_api_clears_key_with_empty_string(client) -> None:
    client.put(
        f"{API}/llm/config",
        json={"provider": "openai_compatible", "base_url": "https://example.com/v1", "api_key": "sk-abcdefghijklmnop"},
    )
    cleared = client.put(f"{API}/llm/config", json={"api_key": ""}).json()["data"]
    assert cleared["api_key_configured"] is False
    assert "llm_api_key" not in cleared["overridden_fields"]


def test_config_api_rejects_unknown_provider(client) -> None:
    response = client.put(f"{API}/llm/config", json={"provider": "not-a-provider"})
    assert response.status_code == 422
    assert response.json()["success"] is False


def test_test_endpoint_uses_submitted_values(client) -> None:
    result = client.post(f"{API}/llm/config/test", json={"provider": "fake"}).json()["data"]
    assert result["ok"] is True
    assert result["provider"] == "fake"
    assert result["reply"]


def test_test_endpoint_reports_unavailable(client) -> None:
    result = client.post(f"{API}/llm/config/test", json={"provider": "none"}).json()["data"]
    assert result["ok"] is False
    assert "纯规则引擎" in result["message"]


def test_models_endpoint_falls_back_to_builtin(client) -> None:
    data = client.get(f"{API}/llm/models", params={"provider": "deepseek"}).json()["data"]
    assert data["source"] == "builtin"
    expected = {item["value"] for item in provider_option("deepseek")["models"]}
    assert {item["value"] for item in data["models"]} == expected


def test_models_endpoint_never_borrows_another_providers_endpoint(client) -> None:
    """切厂商时不能复用别家的端点与 Key。

    这正是「端点已经填成千问的，模型下拉里还是 DeepSeek 两个模型」的根因：
    请求 provider=deepseek 时若沿用已生效的 openai_compatible 端点与 Key，
    就会把千问的地址当成 DeepSeek 去查。
    """
    get_runtime_config_store().save(
        {
            "llm_provider": "openai_compatible",
            "llm_base_url": "https://qwen.example.com/compatible-mode/v1",
            "llm_api_key": "sk-somebody-elses-key",
        }
    )
    reset_llm_provider_cache()

    data = client.get(f"{API}/llm/models", params={"provider": "deepseek"}).json()["data"]

    assert data["source"] == "builtin"
    assert "API Key" in data["message"]
    assert {item["value"] for item in data["models"]} == {
        item["value"] for item in provider_option("deepseek")["models"]
    }


def test_models_endpoint_prefers_the_url_typed_in_the_form() -> None:
    """表单里现填的端点最优先，即使还没保存、且 Key 还是别家的。"""
    effective = Settings(
        llm_provider="deepseek",
        llm_base_url="https://api.deepseek.com",
        llm_api_key="sk-deepseek",
    )
    endpoint, api_key = resolve_models_endpoint(
        "openai_compatible", provider_option("openai_compatible"), effective, "https://qwen.example.com/v1/"
    )
    assert endpoint == "https://qwen.example.com/v1"
    assert api_key == ""


def test_models_endpoint_reuses_saved_config_when_provider_matches() -> None:
    effective = Settings(
        llm_provider="openai_compatible",
        llm_base_url="https://qwen.example.com/v1/",
        llm_api_key="sk-qwen",
    )
    endpoint, api_key = resolve_models_endpoint(
        "openai_compatible", provider_option("openai_compatible"), effective, None
    )
    assert endpoint == "https://qwen.example.com/v1"
    assert api_key == "sk-qwen"


def test_models_endpoint_falls_back_to_catalog_default_without_key() -> None:
    effective = Settings(
        llm_provider="openai_compatible",
        llm_base_url="https://qwen.example.com/v1",
        llm_api_key="sk-qwen",
    )
    endpoint, api_key = resolve_models_endpoint(
        "deepseek", provider_option("deepseek"), effective, None
    )
    assert endpoint == "https://api.deepseek.com"
    assert api_key == ""


def test_health_reports_runtime_source(client) -> None:
    client.put(f"{API}/llm/config", json={"provider": "fake", "model": "fake-model"})
    data = client.get(f"{API}/health").json()["data"]
    assert data["llm_source"] == "runtime"
    client.delete(f"{API}/llm/config")
    assert client.get(f"{API}/health").json()["data"]["llm_source"] == "env"
