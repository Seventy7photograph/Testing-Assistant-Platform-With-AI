"""pytest 公共夹具。

关键点：
  - 在任何 app 模块被导入之前，先把 STORAGE_DIR 指向临时目录、
    LLM_PROVIDER 设为 fake，保证测试确定性且不污染仓库；
  - pydantic-settings 的优先级是「环境变量 > .env」，因此这里的设置一定生效。
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP_STORAGE = Path(tempfile.mkdtemp(prefix="aitc-tests-"))

os.environ["STORAGE_DIR"] = str(_TMP_STORAGE)
os.environ["LLM_PROVIDER"] = "fake"
os.environ["LLM_API_KEY"] = ""
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["DEBUG"] = "false"


@pytest.fixture(scope="session")
def storage_dir() -> Path:
    return _TMP_STORAGE


@pytest.fixture(scope="session")
def settings():
    from app.core.config import get_settings

    return get_settings()


@pytest.fixture(scope="session")
def llm():
    from app.llm.factory import get_llm_provider

    return get_llm_provider()


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    shutil.rmtree(_TMP_STORAGE, ignore_errors=True)


SAMPLE_TEXT = """# 订单系统需求说明

## 1、用户注册
手机号：11位数字，必填
年龄：18~120
状态：待激活/已激活/已冻结

| 字段名 | 类型 | 必填 | 取值范围 | 说明 |
| --- | --- | --- | --- | --- |
| 昵称 | 字符串 | 是 | 2-20位 | 用户昵称 |
| 余额 | 小数 | 否 | 0~99999.99 | 账户余额 |

主流程：
1. 进入注册页
2. 填写手机号与昵称
3. 提交注册

备选流程：
- 手机号已注册时提示直接登录

异常场景：
- 短信通道异常

业务规则：
- 不允许昵称包含敏感词

验收标准：
- 注册成功后自动跳转首页
"""


@pytest.fixture(scope="session")
def sample_text() -> str:
    return SAMPLE_TEXT


@pytest.fixture(scope="session")
def sample_item():
    """构造一个字段约束齐全的需求条目，用于设计策略单测。"""
    from app.schemas.common import DataType, Priority
    from app.schemas.requirement import FieldConstraint, RequirementItem

    return RequirementItem(
        id="REQ-001",
        title="用户注册",
        module="用户中心",
        description="用户提交手机号与年龄完成注册。",
        priority=Priority.P1,
        fields=[
            FieldConstraint(
                name="phone",
                label="手机号",
                data_type=DataType.STRING,
                required=True,
                nullable=False,
                min_length=11,
                max_length=11,
                pattern=r"^1[3-9]\d{9}$",
            ),
            FieldConstraint(
                name="age",
                label="年龄",
                data_type=DataType.INTEGER,
                required=False,
                min_value=18,
                max_value=120,
                unit="岁",
            ),
            FieldConstraint(
                name="status",
                label="状态",
                data_type=DataType.ENUM,
                enum_values=["待激活", "已激活", "已冻结"],
            ),
        ],
        business_rules=["同一手机号不可重复注册"],
        preconditions=["系统正常运行"],
        main_flow=["进入注册页", "填写信息", "提交"],
        alternative_flows=["手机号已注册时提示登录"],
        exceptions=["短信通道异常"],
        acceptance_criteria=["注册成功后自动登录"],
    )