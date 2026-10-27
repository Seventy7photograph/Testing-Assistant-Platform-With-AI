"""Run a complete current-system OpenAPI workflow and keep all demo data.

This script uses the running application's real ``/openapi.json``. It creates
a dedicated simulation project, uploads synthetic requirement material,
generates a real business suite, imports the current OpenAPI document, creates
an automation asset from safe read-only positive cases, executes that asset,
and leaves every created record in the project for review.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "/api/v1"

SAFE_READ_PATHS = {
    "/api/v1/health",
    "/api/v1/overview",
    "/api/v1/llm/config",
    "/api/v1/llm/models",
    "/api/v1/llm/prompts",
    "/api/v1/llm/routing",
    "/api/v1/projects",
    "/api/v1/projects/current",
    "/api/v1/api-specs",
    "/api/v1/testcases/methods",
    "/api/v1/testcases/suites",
    "/api/v1/export/formats",
    "/api/v1/report/status",
    "/api/v1/report/samples",
    "/api/v1/report/thresholds",
    "/api/v1/report/trends",
    "/api/v1/knowledge/stats",
    "/api/v1/assistant/status",
    "/api/v1/assistant/tools",
    "/api/v1/assistant/conversations",
    "/api/v1/work-items/summary",
    "/api/v1/automation/artifacts",
    "/api/v1/automation/runs",
    "/api/v1/jobs",
    "/api/v1/schedules",
    "/api/v1/agent-runs",
    "/api/v1/tool-calls",
}


def data(response: httpx.Response) -> Any:
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("message") or payload)
    return payload.get("data")


def run(base_origin: str, project_id: str = "") -> dict[str, Any]:
    api_base = f"{base_origin}{API}"
    suffix = datetime.now().strftime("%m%d%H%M%S")
    summary: dict[str, Any] = {"base_origin": base_origin, "created_at": datetime.now().isoformat()}

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        if project_id:
            project = {"project_id": project_id}
        else:
            project = data(
                client.post(
                    f"{api_base}/projects",
                    json={
                        "key": f"SIM-E2E-{suffix}",
                        "name": "系统接口全流程模拟项目",
                        "description": "使用当前系统 OpenAPI 与合成材料生成，保留用于验收。",
                    },
                )
            )
        project_id = project["project_id"]
        headers = {"X-Project-ID": project_id}
        summary["project_id"] = project_id

        requirement_file = (ROOT / "examples" / "sample_requirement.md").read_bytes()
        document = data(
            client.post(
                f"{api_base}/documents/upload",
                headers=headers,
                files={
                    "file": (
                        "SIM-系统接口全流程需求材料.md",
                        requirement_file,
                        "text/markdown",
                    )
                },
            )
        )
        doc_id = document["doc_id"]
        summary["document_id"] = doc_id

        parsed = data(
            client.post(
                f"{api_base}/requirements/parse",
                headers=headers,
                json={
                    "doc_id": doc_id,
                    "title": "SIM 系统接口全流程需求材料",
                    "use_llm": False,
                    "max_items": 8,
                },
            )
        )
        summary["requirement_items"] = len(parsed.get("items") or [])

        generated = data(
            client.post(
                f"{api_base}/testcases/generate",
                headers=headers,
                json={
                    "doc_id": doc_id,
                    "methods": ["equivalence", "boundary", "scenario"],
                    "use_llm": False,
                    "use_llm_in_design": False,
                    "max_items": 8,
                    "max_cases_per_requirement": 200,
                },
            )
        )
        summary["suite_id"] = generated["suite_id"]
        summary["generated_cases"] = len(generated.get("cases") or [])

        samples = data(client.get(f"{api_base}/report/samples", headers=headers))
        if samples:
            sample = next((item for item in samples if item.get("id") == "release"), samples[0])
            report = data(
                client.post(
                    f"{api_base}/report/analyze",
                    headers=headers,
                    json={
                        "test_data": sample["content"],
                        "instruction": "总结系统接口全流程验收结果、风险和后续建议",
                        "title": "SIM 系统接口全流程验收报告",
                        "save": True,
                    },
                )
            )
            summary["report_id"] = report.get("id")
            summary["report_metrics_total"] = (report.get("metrics") or {}).get("total")

        work_item = data(
            client.post(
                f"{api_base}/work-items",
                headers=headers,
                json={
                    "item_type": "note",
                    "title": "SIM 全流程验收记录",
                    "body": f"文档 {doc_id}，用例集 {generated['suite_id']}，资产与运行记录均保留。",
                    "priority": "P2",
                    "tags": ["SIM", "全流程"],
                },
            )
        )
        summary["work_item_id"] = work_item["work_item_id"]

        data(client.post(f"{api_base}/knowledge/sync", headers=headers))
        search = data(
            client.post(
                f"{api_base}/knowledge/search",
                headers=headers,
                json={"query": "SIM 系统接口全流程需求", "limit": 8},
            )
        )
        summary["knowledge_citations"] = len(search.get("citations") or [])

        openapi_document = client.get(f"{base_origin}/openapi.json")
        openapi_document.raise_for_status()
        imported = data(
            client.post(
                f"{api_base}/api-specs/import",
                headers=headers,
                files={
                    "file": (
                        "SIM-current-system-openapi.json",
                        openapi_document.content,
                        "application/json",
                    )
                },
            )
        )
        spec_id = imported["spec"]["spec_id"]
        summary["spec_id"] = spec_id

        case_payload = data(
            client.get(f"{api_base}/api-specs/{spec_id}/cases", headers=headers)
        )
        safe_cases: list[dict[str, Any]] = []
        for case in case_payload.get("cases") or []:
            execution_blob = json.dumps(case.get("execution") or {}, ensure_ascii=False)
            if (
                case.get("method") == "GET"
                and case.get("category") == "positive"
                and case.get("path") in SAFE_READ_PATHS
                and "{{" not in execution_blob.replace("{{baseUrl}}", "")
            ):
                safe_cases.append(case)
        if not safe_cases:
            raise RuntimeError("当前 OpenAPI 未找到可执行的安全只读正向用例。")

        artifact = data(
            client.post(
                f"{api_base}/automation/artifacts",
                headers=headers,
                json={
                    "spec_id": spec_id,
                    "case_ids": [item["case_id"] for item in safe_cases],
                },
            )
        )
        summary["artifact_id"] = artifact["artifact_id"]
        summary["artifact_cases"] = len(artifact.get("case_ids") or [])

        execution = data(
            client.post(
                f"{api_base}/execution/http",
                headers=headers,
                json={
                    "artifact_id": artifact["artifact_id"],
                    "case_ids": artifact["case_ids"],
                    "allow_all_cases": False,
                    "environment": {"baseUrl": base_origin},
                    "idempotency_key": f"sim-current-api-{suffix}",
                },
            )
        )
        summary["job_id"] = execution["job"]["job_id"]
        summary["run_id"] = execution["run"]["run_id"]
        summary["execution"] = {
            "total": execution["run"]["total"],
            "passed": execution["run"]["passed"],
            "failed": execution["run"]["failed"],
            "errors": execution["run"]["errors"],
            "skipped": execution["run"]["skipped"],
        }

    output = ROOT / "output" / "current-api-e2e-summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_file"] = str(output)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project-id", default="")
    args = parser.parse_args()
    result = run(args.base_url.rstrip("/"), args.project_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["execution"]["failed"] or result["execution"]["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
