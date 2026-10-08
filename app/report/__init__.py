"""测试报告模块（由 ai_test_report_assistant 整合而来）。

职责：把测试执行数据变成可核对、可归档的测试报告。
  - 指标（通过率 / 执行率 / 缺陷分布 / 发版判定）由 metrics 确定性计算；
  - 大模型只负责归纳、风险解释与建议；
  - 报告落到本地 SQLite（storage/data/reports.db），可列表、可趋势、可对比、可导出。

与「用例生成」链路共用同一份 LLM 配置与 Provider 抽象。
"""

from .config import APP_NAME, APP_SUBTITLE, db_path, verdict_thresholds

__all__ = ["APP_NAME", "APP_SUBTITLE", "db_path", "verdict_thresholds"]
