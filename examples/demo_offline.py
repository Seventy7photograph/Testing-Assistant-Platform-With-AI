"""离线端到端演示：不依赖任何大模型 API，也能跑通「需求 -> 用例 -> Excel」。

运行：
    python examples/demo_offline.py

产物：
    output/<文档名>_测试用例_<时间戳>.xlsx
    output/<文档名>_测试用例_<时间戳>.json

说明：
    本脚本模拟"未配置 LLM_API_KEY"的真实场景，验证规则引擎兜底链路。
    如需验证 LLM 链路，可设置环境变量：
        LLM_PROVIDER=deepseek  LLM_API_KEY=sk-xxx
    或使用离线假模型（结构固定、便于查看链路）：
        LLM_PROVIDER=fake
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# 允许直接以 `python examples/demo_offline.py` 方式运行
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 演示必须可复现：显式关掉大模型，并把 storage 指向临时目录。
# 这样本机 .env 里的 Key、以及界面上保存过的覆盖配置都不会改变演示结果，
# 演示产物也不会落进用户的真实文档 / 用例集库。
os.environ["LLM_PROVIDER"] = "none"
os.environ["LLM_API_KEY"] = ""
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="tap-demo-offline-")

try:  # 让 Windows 控制台正确显示中文
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

from app import __version__  # noqa: E402
from app.services.export_service import ExportService  # noqa: E402
from app.services.pipeline_service import PipelineService  # noqa: E402

SAMPLE = PROJECT_ROOT / "examples" / "sample_requirement.md"
OUTPUT_DIR = PROJECT_ROOT / "output"


async def main() -> int:
    if not SAMPLE.exists():
        print(f"[ERROR] 找不到示例需求文件：{SAMPLE}")
        return 1

    text = SAMPLE.read_text(encoding="utf-8")
    print("=" * 78)
    print(f"测试工程师助手平台 v{__version__} · 用例生成链路离线演示")
    print("=" * 78)
    print(f"需求文档：{SAMPLE.name}（{len(text)} 字符）")

    pipeline = PipelineService()
    result = await pipeline.run(
        text=text,
        title="电商订单系统需求说明书",
        methods=["equivalence", "boundary", "scenario"],
        use_llm=True,
        max_items=10,
    )

    doc, suite = result.requirement_doc, result.suite
    print("\n[1/3] 需求解析")
    print(f"  解析方式：{doc.parse_meta.provider}"
          + ("（降级）" if doc.parse_meta.fallback_used else "")
          + f" | 耗时 {doc.parse_meta.elapsed_ms}ms")
    if doc.parse_meta.fallback_reason:
        print(f"  降级原因：{doc.parse_meta.fallback_reason}")
    for item in doc.items:
        print(f"  - {item.id} {item.title}（模块：{item.module}，字段 {len(item.fields)} 个，"
              f"主流程 {len(item.main_flow)} 步，异常 {len(item.exceptions)} 条）")

    print("\n[2/3] 用例生成")
    print(f"  用例总数：{suite.stats.total}（去重剔除 {suite.stats.duplicate_removed}）")
    print(f"  按方法：{json.dumps(suite.stats.by_method, ensure_ascii=False)}")
    print(f"  按类型：{json.dumps(suite.stats.by_type, ensure_ascii=False)}")
    print(f"  按优先级：{json.dumps(suite.stats.by_priority, ensure_ascii=False)}")
    print("  示例用例：")
    for case in suite.cases[:6]:
        data = "、".join(f"{k}={v or '(空)'}" for k, v in case.test_data.items()) or "-"
        print(f"    {case.case_id} [{case.design_method.label}] {case.title}")
        print(f"        数据：{data} | 预期：{case.expected_result[:48]}")

    if result.warnings:
        print(f"\n  告警 {len(result.warnings)} 条：")
        for warning in result.warnings[:6]:
            print(f"    ! {warning}")

    print("\n[3/3] 导出")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    service = ExportService()
    for fmt in ("excel", "json"):
        exported = service.export(suite, fmt)
        target = OUTPUT_DIR / exported.filename
        target.write_bytes(exported.content)
        print(f"  {fmt:6s} -> {target}（{exported.size_bytes} 字节）")

    print("\n完成。可直接打开 Excel 查看用例明细、统计与需求追溯。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
