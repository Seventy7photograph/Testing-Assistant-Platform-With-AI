"""样例数据。用于界面上的「载入样例」，全部是演示值，不是真实项目数据。"""

from __future__ import annotations

import json

from .schemas import SampleDataset

_SAMPLE_BASIC = {
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
}

_SAMPLE_REGRESSION = {
    "version": "4.3.0-rc1",
    "total_cases": 812,
    "passed": 741,
    "failed": 41,
    "blocked": 18,
    "skipped": 12,
    "defects": [
        {"id": "BUG-101", "title": "批量导入超过 5000 行时超时", "severity": "P0", "component": "数据导入", "status": "open"},
        {"id": "BUG-102", "title": "权限变更后缓存未失效", "severity": "P1", "component": "权限管理", "status": "open"},
        {"id": "BUG-103", "title": "导出 Excel 金额列格式错误", "severity": "P1", "component": "报表导出", "status": "open"},
        {"id": "BUG-104", "title": "移动端列表分页错位", "severity": "P2", "component": "移动端", "status": "open"},
        {"id": "BUG-105", "title": "日志时间戳时区偏差 8 小时", "severity": "P2", "component": "基础设施", "status": "resolved"},
        {"id": "BUG-106", "title": "按钮文案错别字", "severity": "P3", "component": "案件管理", "status": "resolved"},
    ],
}

_SAMPLE_RELEASE = {
    "版本": "4.3.0",
    "用例总数": 640,
    "通过": 634,
    "失败": 4,
    "阻塞": 2,
    "缺陷": [
        {"编号": "BUG-201", "标题": "并发提交重复建单", "优先级": "P1", "模块": "案件管理", "状态": "已修复"},
        {"编号": "BUG-202", "标题": "搜索关键字高亮丢失", "优先级": "P2", "模块": "全局搜索", "状态": "已修复"},
    ],
}

_SAMPLE_TEXT = """测试执行记录（4.4.0 冒烟）
执行时间：2026-10-05 14:20
执行人：QA
用例总数 120，通过 96，失败 19，阻塞 5。
失败集中在支付回调与订单状态同步两个模块。
已知问题：BUG-301 支付回调丢单（P0，未修复）；BUG-302 订单状态延迟（P2，处理中）。
"""

SAMPLES: list[SampleDataset] = [
    SampleDataset(
        id="basic",
        name="基础样例",
        description="500 条用例 / 22 条失败 / 3 条缺陷（英文键名 JSON）",
        content=json.dumps(_SAMPLE_BASIC, ensure_ascii=False, indent=2),
    ),
    SampleDataset(
        id="regression",
        name="回归轮次",
        description="812 条用例 / 6 条缺陷，含未执行项，字段用 severity / component",
        content=json.dumps(_SAMPLE_REGRESSION, ensure_ascii=False, indent=2),
    ),
    SampleDataset(
        id="release",
        name="中文键名",
        description="640 条用例 / 2 条缺陷，全部字段为中文键名",
        content=json.dumps(_SAMPLE_RELEASE, ensure_ascii=False, indent=2),
    ),
    SampleDataset(
        id="text",
        name="纯文本记录",
        description="没有 JSON 结构，用于验证「算不出指标时如实说明」",
        content=_SAMPLE_TEXT,
    ),
]


def get_sample(sample_id: str) -> SampleDataset | None:
    return next((item for item in SAMPLES if item.id == sample_id), None)
