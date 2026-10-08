"""测试报告模块：指标、阈值、存档与接口契约。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.report import store
from app.report.config import verdict_thresholds
from app.report.metrics import compute_metrics

BASIC = json.dumps(
    {
        "version": "4.2.0",
        "total_cases": 500,
        "passed": 468,
        "failed": 22,
        "blocked": 10,
        "defects": [
            {"id": "BUG-001", "priority": "P0", "module": "案件管理", "status": "open"},
            {"id": "BUG-002", "priority": "P1", "module": "权限管理", "status": "open"},
            {"id": "BUG-003", "priority": "P1", "module": "接口", "status": "resolved"},
        ],
    },
    ensure_ascii=False,
)


def test_metrics_basic_numbers():
    result = compute_metrics(BASIC, verdict_thresholds())
    metrics = result.metrics
    assert metrics is not None
    assert metrics.total == 500
    assert metrics.passed == 468
    assert metrics.failed == 22
    assert metrics.blocked == 10
    assert metrics.executed == 490
    assert metrics.pass_rate == pytest.approx(0.936)
    assert metrics.execution_rate == pytest.approx(0.98)
    assert metrics.defects_total == 3
    assert metrics.defects_open == 2
    assert metrics.open_p0 == 1
    assert metrics.verdict in {"pass", "conditional", "reject"}
    assert result.version == "4.2.0"


def test_open_p0_forces_reject():
    data = json.dumps(
        {
            "total_cases": 100,
            "passed": 100,
            "failed": 0,
            "defects": [{"id": "B-1", "priority": "P0", "status": "未修复"}],
        },
        ensure_ascii=False,
    )
    result = compute_metrics(data, verdict_thresholds())
    assert result.metrics is not None
    assert result.metrics.verdict == "reject"


def test_negated_status_is_not_treated_as_resolved():
    data = json.dumps(
        {
            "total_cases": 10,
            "passed": 10,
            "failed": 0,
            "defects": [{"id": "B-1", "priority": "P0", "status": "unresolved"}],
        },
        ensure_ascii=False,
    )
    result = compute_metrics(data, verdict_thresholds())
    assert result.metrics is not None
    assert result.metrics.open_p0 == 1
    assert result.metrics.verdict == "reject"


def test_plain_text_without_counts_reports_honestly():
    result = compute_metrics("本轮测试未提供结构化计数。", verdict_thresholds())
    assert result.metrics is None
    assert result.warnings


def test_store_roundtrip():
    report_id = store.save_report(
        {
            "title": "单元测试报告",
            "model": "mock",
            "provider": "本地服务",
            "report": "## 概况\n一切正常",
            "metrics": {"verdict": "pass", "verdict_label": "通过", "pass_rate": 0.99, "total": 100},
            "defects": [],
            "warnings": [],
            "elapsed_ms": 12,
        }
    )
    record = store.get_report(report_id)
    assert record is not None
    assert record["title"] == "单元测试报告"
    assert record["verdict"] == "pass"
    assert store.delete_report(report_id) is True
    assert store.get_report(report_id) is None


def test_report_endpoints(client: TestClient):
    status = client.get("/api/v1/report/status")
    assert status.status_code == 200
    assert status.json()["success"] is True

    metrics = client.post("/api/v1/report/metrics", json={"test_data": BASIC})
    assert metrics.status_code == 200
    assert metrics.json()["data"]["metrics"]["total"] == 500

    samples = client.get("/api/v1/report/samples")
    assert samples.status_code == 200
    assert len(samples.json()["data"]) >= 4

    listing = client.get("/api/v1/report/reports")
    assert listing.status_code == 200
    assert "items" in listing.json()["data"]


def test_thresholds_roundtrip(client: TestClient):
    original = client.get("/api/v1/report/thresholds").json()["data"]
    assert set(original["thresholds"]) == {"fail_rate", "blocked_rate", "execution_floor", "pass_line"}

    saved = client.put("/api/v1/report/thresholds", json={"fail_rate": 0.2})
    assert saved.status_code == 200
    assert saved.json()["data"]["thresholds"]["fail_rate"] == pytest.approx(0.2)
    assert saved.json()["data"]["sources"]["fail_rate"] == "saved"

    reset = client.delete("/api/v1/report/thresholds")
    assert reset.status_code == 200
    assert reset.json()["data"]["sources"]["fail_rate"] == "env"
    assert reset.json()["data"]["thresholds"]["fail_rate"] == pytest.approx(
        original["defaults"]["fail_rate"]
    )


def test_analyze_without_key_returns_503(client: TestClient):
    response = client.post(
        "/api/v1/report/analyze",
        json={"test_data": BASIC, "save": False},
    )
    assert response.status_code == 503
    assert response.json()["success"] is False


def test_overview_endpoint(client: TestClient):
    response = client.get("/api/v1/overview")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["platform"]["version"]
    assert "counts" in data and "capabilities" in data
    # 迭代排期属于内部规划，不对使用者展示：总览不再下发任何路线数据
    assert "roadmap" not in data


def test_roadmap_endpoint_is_removed(client: TestClient):
    """迭代路线功能整体下线：接口与界面都已撤下，访问应返回 404。"""
    assert client.get("/api/v1/roadmap").status_code == 404
