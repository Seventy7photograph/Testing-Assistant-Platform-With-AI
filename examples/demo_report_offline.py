"""测试报告链路 · 离线端到端验证（不消耗任何 API 额度）。

流程：
    1. 启动本地假模型服务（scripts/mock_llm.py）
    2. 启动真实 uvicorn 服务，指向假模型
    3. 走完整链路：状态 -> 指标 -> 样例 -> 生成报告 -> 流式生成 -> 存档列表 -> 详情
       -> 趋势 -> 导出 md/html/docx/json -> 删除

运行：
    python examples/demo_report_offline.py

退出码 0 表示全部通过。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "/api/v1/report"

try:  # 让 Windows 控制台正确显示中文
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if not condition:
        FAILURES.append(label)
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start(module: str, port: int, env: dict[str, str] | None = None, args: list[str] | None = None) -> subprocess.Popen:
    merged = os.environ.copy()
    merged.update(env or {})
    merged["PYTHONIOENCODING"] = "utf-8"
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": merged,
        "cwd": str(ROOT),
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen([sys.executable, *module.split(), *(args or [])], **kwargs)


def wait_ready(url: str, proc: subprocess.Popen, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            httpx.get(url, timeout=2.0, trust_env=False)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


SAMPLE = json.dumps(
    {
        "version": "4.2.0",
        "total_cases": 500,
        "passed": 468,
        "failed": 22,
        "blocked": 10,
        "defects": [
            {"id": "BUG-001", "priority": "P0", "module": "案件管理", "status": "open"},
            {"id": "BUG-002", "priority": "P1", "module": "权限管理", "status": "open"},
        ],
    },
    ensure_ascii=False,
)


def main() -> int:
    print("=" * 78)
    print("测试工程师助手平台 · 测试报告链路离线端到端验证")
    print("=" * 78)

    mock_port = free_port()
    app_port = free_port()
    # 报告演示要和本机真实配置隔离：storage 指向临时目录，
    # 既避免界面上保存的覆盖配置把请求从假模型改指到真实端点，
    # 也避免演示产生的报告 / 导出混进用户真实存档。
    storage_dir = tempfile.mkdtemp(prefix="tap-demo-report-")
    mock = start("scripts/mock_llm.py", mock_port, args=["--port", str(mock_port)])
    app_proc: subprocess.Popen | None = None
    passed = False
    try:
        if not wait_ready(f"http://127.0.0.1:{mock_port}/health", mock):
            print("[ERROR] 假模型服务启动失败")
            return 1
        print(f"\n[准备] 假模型服务：http://127.0.0.1:{mock_port}")

        app_proc = start(
            "-m uvicorn app.main:app",
            app_port,
            env={
                "LLM_PROVIDER": "openai_compatible",
                "LLM_API_KEY": "mock-key",
                "LLM_BASE_URL": f"http://127.0.0.1:{mock_port}",
                "LLM_MODEL": "mock-report-model",
                "LLM_TIMEOUT": "30",
                "STORAGE_DIR": storage_dir,
            },
            args=["--host", "127.0.0.1", f"--port={app_port}", "--log-level", "warning"],
        )
        if not wait_ready(f"http://127.0.0.1:{app_port}/api/v1/health", app_proc):
            print("[ERROR] 平台服务启动失败")
            return 1
        base = f"http://127.0.0.1:{app_port}{API}"
        print(f"[准备] 平台服务：http://127.0.0.1:{app_port}/\n")

        with httpx.Client(timeout=90.0, trust_env=False) as client:
            print("=== 1. 状态与指标 ===")
            status = client.get(f"{base}/status").json()["data"]
            check("模型已配置", status["llm_configured"] is True)
            check("模型名生效", status["model"] == "mock-report-model", status["model"])

            metrics = client.post(f"{base}/metrics", json={"test_data": SAMPLE}).json()["data"]["metrics"]
            check("用例总数 500", metrics["total"] == 500)
            check("通过率 93.6%", round(metrics["pass_rate"] * 100, 1) == 93.6)
            check("未关闭缺陷 2 条", metrics["defects_open"] == 2)

            samples = client.get(f"{base}/samples").json()["data"]
            check("内置样例 >= 4 套", len(samples) >= 4)

            print("\n=== 2. 生成报告（一次性）===")
            analyzed = client.post(
                f"{base}/analyze",
                json={"test_data": SAMPLE, "instruction": "重点关注 P0 缺陷", "save": True},
            ).json()
            check("接口返回成功", analyzed["success"] is True)
            report_id = analyzed["data"]["id"]
            check("报告已存档", bool(report_id), report_id or "")
            check("正文非空", len(analyzed["data"]["report"]) > 50)

            print("\n=== 3. 流式生成 ===")
            chunks: list[str] = []
            events: list[str] = []
            with client.stream(
                "POST",
                f"{base}/analyze/stream",
                json={"test_data": SAMPLE, "save": True},
            ) as response:
                current = ""
                for line in response.iter_lines():
                    if line.startswith("event:"):
                        current = line.split(":", 1)[1].strip()
                        events.append(current)
                    elif line.startswith("data:") and current == "delta":
                        chunks.append(json.loads(line[5:].strip())["text"])
            check("收到 meta / metrics 事件", {"meta", "metrics"}.issubset(set(events)))
            check("收到 delta 增量", len(chunks) > 3, f"{len(chunks)} 段")
            check("以 done 结束", events[-1] == "done")

            print("\n=== 4. 存档、趋势与导出 ===")
            listing = client.get(f"{base}/reports", params={"limit": 20}).json()["data"]
            check("存档列表非空", listing["total"] >= 1)
            check("列表项带判定", listing["items"][0]["verdict"] in {"pass", "conditional", "reject", "unknown"})

            detail = client.get(f"{base}/reports/{report_id}").json()["data"]
            check("详情含指标", detail["metrics"] is not None)
            check("详情含正文", bool(detail["report"]))

            trends = client.get(f"{base}/trends", params={"limit": 12}).json()["data"]
            check("趋势点可读", isinstance(trends, list) and len(trends) >= 1)

            for fmt, signature in (("md", b"# "), ("html", b"<!doctype html>"), ("docx", b"PK"), ("json", b"{")):
                blob = client.get(f"{base}/reports/{report_id}/export", params={"format": fmt}).content
                check(f"导出 {fmt} 有效", blob.startswith(signature), f"{len(blob)} 字节")

            print("\n=== 5. 判定阈值 ===")
            saved = client.put(f"{base}/thresholds", json={"fail_rate": 0.25}).json()["data"]
            check("阈值可保存", abs(saved["thresholds"]["fail_rate"] - 0.25) < 1e-9)
            reset = client.delete(f"{base}/thresholds").json()["data"]
            check("阈值可恢复 .env", reset["sources"]["fail_rate"] == "env")

            print("\n=== 6. 删除与 404 ===")
            deleted = client.delete(f"{base}/reports/{report_id}").json()
            check("删除返回成功", deleted["success"] is True)
            missing = client.get(f"{base}/reports/{report_id}")
            check("删除后再取为 404", missing.status_code == 404)
            check("404 也走统一错误体", missing.json()["code"] == "NOT_FOUND")

        passed = not FAILURES
    finally:
        for proc in (app_proc, mock):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except Exception:  # noqa: BLE001
                    proc.kill()

    print("\n" + "=" * 78)
    if passed:
        print("全部通过：报告链路端到端可用。")
        return 0
    print(f"存在 {len(FAILURES)} 项失败：")
    for item in FAILURES:
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
