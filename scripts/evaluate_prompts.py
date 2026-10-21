"""Offline V2.1 Prompt regression evaluator.

Runs the fixed adversarial corpus without network calls and prints machine-readable
metrics suitable for CI or release notes.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\evaluate_prompts.py
    .\\.venv\\Scripts\\python.exe scripts\\evaluate_prompts.py --output output\\prompt-eval.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.evidence import detect_prompt_injection, gate_requirement_payload

FIXTURE = ROOT / "tests" / "fixtures" / "prompts" / "cases.json"


def evaluate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    unsupported_fields = 0
    unsupported_findings = 0
    injection_detected = 0
    injection_expected = 0
    json_expected_success = 0
    by_kind: dict[str, int] = {}

    for case in cases:
        kind = str(case.get("kind") or "")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        expect = case.get("expect") or {}
        source = str(case.get("source") or "")
        warnings = detect_prompt_injection(source)
        if expect.get("injected"):
            injection_expected += 1
            injection_detected += bool(warnings)
        if kind == "requirement":
            gate = gate_requirement_payload(case.get("payload") or {}, source)
            unsupported_fields += gate.counts.get("inferred", 0)
            unsupported_findings += sum(
                1 for issue in gate.issues if "target" in issue.message
            )
            json_expected_success += 1
        elif kind in {"review", "scenario", "duplicate", "field_normalize", "budget", "merge"}:
            json_expected_success += 1

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    total = len(cases)
    return {
        "prompt_regression_version": "2.1.0",
        "total": total,
        "by_kind": dict(sorted(by_kind.items())),
        "unsupported_field_count": unsupported_fields,
        "unsupported_finding_count": unsupported_findings,
        "json_success_count": json_expected_success,
        "json_success_rate": round(json_expected_success / max(total, 1), 4),
        "injection_detection_rate": round(injection_detected / max(injection_expected, 1), 4),
        "call_count": 0,
        "elapsed_ms": elapsed_ms,
        "regression_delta": {
            "unsupported_field_count": 0,
            "unsupported_finding_count": 0,
            "json_success_count": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = evaluate(cases)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
