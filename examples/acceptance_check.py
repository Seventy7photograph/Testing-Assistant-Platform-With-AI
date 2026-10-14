"""黑盒验收脚本：启动真实 uvicorn 服务，通过 HTTP 跑通端到端链路。

运行：
    python examples/acceptance_check.py

覆盖两种运行形态：
    场景一 LLM_PROVIDER=deepseek 且未配置密钥  ->  纯规则引擎降级链路
    场景二 LLM_PROVIDER=fake                  ->  启用 LLM 链路（无需真实密钥）

说明：
    - 客户端显式设置 trust_env=False，避免企业代理拦截 127.0.0.1 本地请求；
    - 脚本会自动挑选空闲端口，运行结束后自动关闭服务进程。
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
SAMPLE = ROOT / "examples" / "sample_requirement.md"

try:
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


def start_server(port: int, extra_env: dict[str, str]) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(extra_env)
    env["PYTHONIOENCODING"] = "utf-8"
    # 每个场景用独立的临时 storage：既隔离界面上保存的运行时覆盖配置，
    # 也避免验收数据写进用户真实的文档 / 用例集库。
    env["STORAGE_DIR"] = tempfile.mkdtemp(prefix="tap-accept-")
    kwargs: dict = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "env": env, "cwd": str(ROOT)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", f"--port={port}", "--log-level", "warning"],
        **kwargs,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            httpx.get(f"{base}/api/v1/health", timeout=2.0, trust_env=False)
            return proc
        except Exception:  # noqa: BLE001
            if proc.poll() is not None:
                break
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("服务启动超时，请检查依赖是否安装完整（pip install -r requirements.txt）")


def run_scenario(title: str, env: dict[str, str], *, expect_llm: bool, min_items: int) -> None:
    print(f"\n=== {title} ===")
    port = free_port()
    proc = start_server(port, env)
    base = f"http://127.0.0.1:{port}"
    api = f"{base}/api/v1"
    try:
        with httpx.Client(timeout=120.0, trust_env=False) as client:
            health = client.get(f"{api}/health").json()["data"]
            check("健康检查可用", health["status"] == "ok")
            check("LLM 可用状态与预期一致", health["llm_available"] is expect_llm,
                  f"provider={health['llm_provider']} available={health['llm_available']}")
            # V2.0：六种设计方法全部落地，"预留未实现"不再是预期状态。
            check("六种设计方法均已实现",
                  {m["name"] for m in health["methods"] if m["implemented"]}
                  >= {"equivalence", "boundary", "scenario", "decision_table", "cause_effect", "orthogonal"})
            check("导出格式含 excel/json/csv/xmind/testlink",
                  {f["name"] for f in health["export_formats"]}
                  == {"excel", "json", "csv", "xmind", "testlink"})
            check("支持 docx/pdf/xlsx/txt/md/图片",
                  {"docx", "pdf", "xlsx", "txt", "md", "png", "jpg"} <= set(health["supported_extensions"]))
            check("图片识别能力已上报",
                  "vision" in health and bool(health["vision"].get("extractor")),
                  f"extractor={health.get('vision', {}).get('extractor')}")

            sample = SAMPLE.read_text(encoding="utf-8")
            upload = client.post(f"{api}/documents/upload",
                                 files={"file": ("sample_requirement.md", sample.encode("utf-8"), "text/markdown")})
            check("文档上传成功", upload.status_code == 200, upload.json().get("message", ""))
            doc_id = upload.json()["data"]["doc_id"]

            pipeline = client.post(f"{api}/pipeline/generate", json={
                "doc_id": doc_id,
                "methods": ["equivalence", "boundary", "scenario"],
                "use_llm": True,
                "max_items": 10,
            })
            check("一键流水线 HTTP 200", pipeline.status_code == 200, pipeline.text[:120])
            data = pipeline.json()["data"]
            suite = data["suite"]
            requirement = data["requirement_doc"]

            check("生成用例数 > 0", suite["stats"]["total"] > 0, f"total={suite['stats']['total']}")
            check(f"需求条目 >= {min_items}", len(requirement["items"]) >= min_items,
                  f"items={[item['title'] for item in requirement['items']]}")
            check("三种方法均有产出",
                  all(name in suite["stats"]["by_method"] for name in ("等价类划分", "边界值分析", "场景法")))
            check("用例编号唯一", len({case["case_id"] for case in suite["cases"]}) == suite["stats"]["total"])
            check("需求解析 LLM 标记正确", requirement["parse_meta"]["llm_used"] is expect_llm,
                  f"provider={requirement['parse_meta']['provider']}"
                  + ("" if expect_llm else " (降级原因已记录)" if requirement["parse_meta"]["fallback_used"] else ""))

            excel = client.post(f"{api}/export", json={"suite_id": suite["suite_id"], "format": "excel"})
            check("Excel 导出成功", excel.status_code == 200 and excel.content[:2] == b"PK", f"{len(excel.content)} bytes")
            check("下载文件名含中文", "filename*=UTF-8''" in excel.headers.get("content-disposition", ""))

            exported_json = client.get(f"{api}/export/{suite['suite_id']}/json")
            check("JSON 导出可解析",
                  exported_json.status_code == 200
                  and json.loads(exported_json.content)["suite_id"] == suite["suite_id"])

            # V2.0：三种新方法要能真的产出用例（不再返回 501）。
            v2_text = (
                "# 会员注册\n\n## 会员注册\n手机号：11位数字，必填\n年龄：18~120\n"
                "会员等级：普通/白银/黄金\n注册渠道：小程序/APP/Web\n\n"
                "业务规则：\n- 若手机号已注册则提示直接登录\n- 不允许使用黑名单渠道注册\n"
            )
            v2_ok = True
            v2_detail: list[str] = []
            for method in ("decision_table", "cause_effect", "orthogonal"):
                response = client.post(f"{api}/testcases/generate",
                                       json={"text": v2_text, "methods": [method], "use_llm": False})
                cases = response.json().get("data", {}).get("cases", []) if response.status_code == 200 else []
                if not cases:
                    v2_ok = False
                v2_detail.append(f"{method}={len(cases)}")
            check("V2.0 三种新方法可生成用例", v2_ok, "、".join(v2_detail))

            check("未知方法返回 404",
                  client.post(f"{api}/testcases/generate",
                              json={"text": "x", "methods": ["not_a_method"]}).status_code == 404)

            missing = client.post(f"{api}/export", json={"suite_id": "SUITE-nope", "format": "excel"})
            check("不存在的用例集返回 404", missing.status_code == 404)

            # V2.0 起 .xlsx 已支持：损坏内容应报「解析失败」而不是「格式不支持」。
            broken_excel = client.post(f"{api}/documents/upload",
                                       files={"file": ("a.xlsx", b"x", "application/vnd.ms-excel")})
            check("损坏的 Excel 返回 422", broken_excel.status_code == 422,
                  f"HTTP {broken_excel.status_code}")
            unsupported = client.post(f"{api}/documents/upload",
                                      files={"file": ("a.zip", b"x", "application/zip")})
            check("不支持的格式返回 415", unsupported.status_code == 415)

            bad_body = client.post(f"{api}/testcases/generate", json={"methods": ["boundary"]})
            check("缺少来源返回 400", bad_body.status_code == 400 and bad_body.json()["code"] == "BAD_REQUEST")

            index = client.get(f"{base}/")
            check("演示页可访问", index.status_code == 200 and "测试工程师助手平台" in index.text)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()


def main() -> int:
    if not SAMPLE.exists():
        print(f"[ERROR] 缺少示例需求文件：{SAMPLE}")
        return 1

    run_scenario(
        "场景一：默认配置（未配置 LLM_API_KEY → 自动降级为纯规则引擎）",
        {"LLM_PROVIDER": "deepseek", "LLM_API_KEY": ""},
        expect_llm=False,
        min_items=3,
    )
    run_scenario(
        "场景二：LLM_PROVIDER=fake（验证 LLM 链路可插拔，无需真实密钥）",
        {"LLM_PROVIDER": "fake", "LLM_API_KEY": ""},
        expect_llm=True,
        min_items=1,
    )

    print("\n" + "=" * 64)
    if FAILURES:
        print(f"验收失败 {len(FAILURES)} 项：" + "；".join(FAILURES))
        return 1
    print("全部验收项通过 ✅  端到端链路可用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
