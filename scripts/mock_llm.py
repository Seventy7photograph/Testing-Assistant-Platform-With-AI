"""本地假模型服务：验证完整链路，不消耗任何 API 额度。

它实现 OpenAI-compatible 的 `POST /chat/completions`（含流式），
返回一份格式正确、数字取自请求内容的报告。

用法：
    python scripts/mock_llm.py --port 8011
    # 另开一个终端
    set LLM_API_KEY=mock
    set LLM_BASE_URL=http://127.0.0.1:8011
    uvicorn app:app --reload
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="Mock LLM")

_REPORT = """## 测试概况
本轮共执行 {total} 条用例，通过 {passed} 条、失败 {failed} 条、阻塞 {blocked} 条。
受检版本为 {version}，本次数据来源为结构化 JSON。

## 关键指标解读
通过率 {pass_rate}，执行率 {execution_rate}。系统判定为**{verdict}**。
{verdict_reasons}

## 主要缺陷与风险
{defect_section}

## 风险判断依据
判定完全基于输入中的事实：用例计数与缺陷清单。失败用例的绝对数量为 {failed} 条，
占全部用例的 {fail_rate}；未关闭缺陷 {open_defects} 条，其中 P0 级 {open_p0} 条。

## 建议与下一步
1. 优先关闭 P0/P1 缺陷，并在修复后对相关模块做一次专项回归。
2. 将本轮失败集中的模块纳入下一轮冒烟集。
3. 对阻塞用例补齐环境依赖后重新执行，避免结论覆盖不到这部分范围。

> 说明：本回复由本地假模型服务生成，仅用于验证链路与界面，不代表真实模型输出。"""


def _field(prompt: str, label: str) -> str | None:
    match = re.search(rf"{label}：([^\n]+)", prompt)
    return match.group(1).strip() if match else None


def _completion(model: str, content: str) -> dict[str, Any]:
    return {
        "id": "mock-1",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 800, "completion_tokens": 420, "total_tokens": 1220},
    }


def build_report(prompt: str) -> str:
    total = _field(prompt, "用例总数") or "—"
    passed = (_field(prompt, "通过") or "—").split("（")[0]
    failed = (_field(prompt, "失败") or "—").split("（")[0]
    blocked = _field(prompt, "阻塞") or "—"
    pass_rate = (_field(prompt, "通过") or "").split("（")[-1].rstrip("）") or "—"
    fail_rate = (_field(prompt, "失败") or "").split("（")[-1].rstrip("）") or "—"
    execution = _field(prompt, "执行率") or "—"
    verdict = _field(prompt, "系统判定") or "无法判定"
    reasons = _field(prompt, "判定依据") or ""
    defects = _field(prompt, "缺陷") or ""
    version = _field(prompt, "受检版本") or _field(prompt, "版本") or "未标注"
    if version == "未标注":
        match = re.search(r'"version"\s*:\s*"([^"]+)"', prompt)
        version = match.group(1) if match else "未标注"

    open_match = re.search(r"未关闭\s*(\d+)\s*条", defects)
    p0_match = re.search(r"P0\s*未关闭\s*(\d+)", defects)
    open_defects = open_match.group(1) if open_match else "0"
    open_p0 = p0_match.group(1) if p0_match else "0"

    if defects and "缺陷：" not in defects:
        defect_section = f"输入给出缺陷统计：{defects}。建议按优先级从高到低处理。"
    else:
        defect_section = "输入未提供结构化缺陷清单，因此不对具体缺陷做推断；风险判断仅依据用例执行结果。"

    return _REPORT.format(
        total=total,
        passed=passed,
        failed=failed,
        blocked=blocked,
        version=version,
        pass_rate=pass_rate,
        fail_rate=fail_rate,
        execution_rate=execution,
        verdict=verdict,
        verdict_reasons=f"判定依据：{reasons}。" if reasons else "",
        defect_section=defect_section,
        open_defects=open_defects,
        open_p0=open_p0,
    ).strip()


@app.post("/chat/completions")
async def chat_completions(request: Request) -> Any:
    body = await request.json()
    prompt = ""
    for message in body.get("messages", []):
        if message.get("role") == "user":
            prompt += str(message.get("content", ""))
    model = body.get("model", "mock-model")

    # 探活请求（max_tokens 很小）只回一个 "ok"，别回整篇报告
    if body.get("max_tokens") and int(body["max_tokens"]) <= 16:
        return _completion(model, "ok")

    report = build_report(prompt)

    if not body.get("stream"):
        return _completion(model, report)

    async def stream():
        step = 12
        for index in range(0, len(report), step):
            chunk = report[index : index + step]
            payload = {
                "id": "mock-1",
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.012)
        yield f"data: {json.dumps({'id': 'mock-1', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "ts": time.time()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
