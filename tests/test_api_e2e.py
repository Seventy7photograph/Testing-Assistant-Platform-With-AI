"""端到端接口测试：上传 -> 解析 -> 生成 -> 导出，以及关键异常路径。

使用 sessions 级 TestClient（会触发 lifespan），LLM 走 FakeProvider，
因此整条链路在无网络、无 API Key 的情况下也能确定性验证。
"""
from __future__ import annotations

from urllib.parse import unquote

API = "/api/v1"

REQUIREMENT_MD = """# 用户注册需求

## 1、用户注册
手机号：11位数字，必填
年龄：18~120

主流程：
1. 进入注册页
2. 填写手机号
3. 提交注册

异常场景：
- 短信通道异常
"""

#: V2.0 三种新方法（判定表 / 因果图 / 正交实验）需要「多条件 + 多因子水平」，
#: 上面那份最小需求只有一个带多水平的字段，正交实验自然产不出用例 ——
#: 这是正确行为，因此单独准备一份更接近真实 PRD 的需求文本。
V2_REQUIREMENT_MD = """# 会员注册需求

## 1、会员注册
手机号：11位数字，必填
年龄：18~120
会员等级：普通/白银/黄金
注册渠道：小程序/APP/Web

业务规则：
- 若手机号已注册则提示直接登录
- 不允许使用黑名单渠道注册

异常场景：
- 短信通道异常
"""


def _upload(client, content: str = REQUIREMENT_MD, filename: str = "需求.md"):
    return client.post(
        f"{API}/documents/upload",
        files={"file": (filename, content.encode("utf-8"), "text/markdown")},
    )


def _find_document(client, doc_id: str) -> dict:
    """从列表里取出指定文档的摘要——列表才是「文档库」页真正渲染的东西。"""
    body = client.get(f"{API}/documents", params={"limit": 100}).json()
    return next(item for item in body["data"] if item["doc_id"] == doc_id)


def test_health_reports_capabilities(client) -> None:
    response = client.get(f"{API}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["llm_provider"] == "fake"
    assert data["llm_available"] is True
    methods = {item["name"]: item["implemented"] for item in data["methods"]}
    assert methods["equivalence"] and methods["boundary"] and methods["scenario"]
    # V2.0 起六种设计方法全部落地：能力清单必须如实反映「已实现」。
    assert methods["decision_table"] and methods["cause_effect"] and methods["orthogonal"]
    assert "excel" in {item["name"] for item in data["export_formats"]}
    assert {"csv", "xmind", "testlink"} <= {item["name"] for item in data["export_formats"]}
    assert "postman" in {item["name"] for item in data["export_formats"]}
    assert "docx" in data["supported_extensions"]


def test_integrations_are_planned_not_implemented(client) -> None:
    body = client.get(f"{API}/integrations").json()
    mapping = {item["name"]: item["implemented"] for item in body["data"]}
    assert mapping == {"zentao": False, "jira": False}


def test_full_pipeline_via_upload(client) -> None:
    upload = _upload(client)
    assert upload.status_code == 200
    doc = upload.json()["data"]
    assert doc["char_count"] > 0
    doc_id = doc["doc_id"]

    parsed = client.post(
        f"{API}/requirements/parse", json={"doc_id": doc_id, "use_llm": True, "max_items": 5}
    )
    assert parsed.status_code == 200
    requirement = parsed.json()["data"]
    assert requirement["doc_id"] == doc_id
    assert requirement["items"]

    generated = client.post(
        f"{API}/testcases/generate",
        json={
            "doc_id": doc_id,
            "methods": ["equivalence", "boundary", "scenario"],
            "use_llm": True,
            "max_items": 5,
        },
    )
    assert generated.status_code == 200
    suite = generated.json()["data"]
    assert suite["stats"]["total"] > 0
    assert suite["doc_id"] == doc_id

    detail = client.get(f"{API}/testcases/{suite['suite_id']}")
    assert detail.json()["data"]["stats"]["total"] == suite["stats"]["total"]


def test_pipeline_endpoint_returns_requirement_and_suite(client) -> None:
    response = client.post(
        f"{API}/pipeline/generate",
        json={
            "text": REQUIREMENT_MD,
            "title": "注册需求",
            "methods": ["equivalence", "boundary", "scenario"],
            "use_llm": True,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["requirement_doc"]["items"]
    assert data["suite"]["cases"]
    assert isinstance(data["warnings"], list)
    assert data["suite"]["generation_meta"]["methods"] == ["equivalence", "boundary", "scenario"]
    doc_id = data["requirement_doc"]["doc_id"]
    document = client.get(f"{API}/documents/{doc_id}")
    assert document.status_code == 200
    summary = document.json()["data"]
    assert summary["filename"] == "注册需求.txt"
    assert summary["parser"] == "pasted_text"
    assert summary["has_requirement"] is True
    downloaded = client.get(f"{API}/documents/{doc_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content.decode("utf-8") == REQUIREMENT_MD


def test_requirement_parse_text_is_recorded_in_document_library(client) -> None:
    text = "# 粘贴解析需求\n\n## 登录\n手机号：11位数字，必填\n"
    response = client.post(
        f"{API}/requirements/parse",
        json={"text": text, "title": "粘贴来源", "use_llm": False, "max_items": 5},
    )
    assert response.status_code == 200, response.text
    doc_id = response.json()["data"]["doc_id"]

    document = client.get(f"{API}/documents/{doc_id}").json()["data"]
    assert document["filename"] == "粘贴来源.txt"
    assert document["char_count"] == len(text)
    assert document["has_requirement"] is True
    assert document["requirement_items"] >= 1


def test_export_excel_and_json(client) -> None:
    suite = client.post(
        f"{API}/pipeline/generate",
        json={"text": REQUIREMENT_MD, "title": "导出用例", "methods": ["boundary"], "use_llm": False},
    ).json()["data"]["suite"]

    excel = client.post(f"{API}/export", json={"suite_id": suite["suite_id"], "format": "excel"})
    assert excel.status_code == 200
    assert excel.content[:2] == b"PK"
    disposition = excel.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert "测试用例" in unquote(disposition)

    download = client.get(f"{API}/export/{suite['suite_id']}/json")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")

    formats = client.get(f"{API}/export/formats").json()["data"]
    assert {item["name"] for item in formats} == {
        "excel",
        "json",
        "csv",
        "xmind",
        "testlink",
        "postman",
    }


def test_export_unknown_suite_returns_404(client) -> None:
    response = client.post(f"{API}/export", json={"suite_id": "SUITE-nope", "format": "excel"})
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False and body["code"] == "NOT_FOUND"


def test_export_unknown_format_returns_404(client) -> None:
    suite = client.post(
        f"{API}/pipeline/generate", json={"text": REQUIREMENT_MD, "methods": ["boundary"], "use_llm": False}
    ).json()["data"]["suite"]
    response = client.post(f"{API}/export", json={"suite_id": suite["suite_id"], "format": "docx"})
    assert response.status_code == 404


def test_upload_unsupported_format_returns_415(client) -> None:
    response = client.post(
        f"{API}/documents/upload",
        files={"file": ("需求.zip", b"binary", "application/zip")},
    )
    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_FORMAT"


def test_upload_empty_file_returns_422(client) -> None:
    response = client.post(f"{API}/documents/upload", files={"file": ("empty.txt", b"", "text/plain")})
    assert response.status_code == 422
    assert response.json()["code"] == "DOCUMENT_PARSE_FAILED"


def test_v2_design_methods_generate_cases(client) -> None:
    """V2.0 的三种方法必须能端到端生成用例（不再返回 501）。"""
    for method in ("decision_table", "cause_effect", "orthogonal"):
        response = client.post(
            f"{API}/testcases/generate",
            json={"text": V2_REQUIREMENT_MD, "methods": [method], "use_llm": False},
        )
        assert response.status_code == 200, (method, response.text)
        suite = response.json()["data"]
        assert suite["cases"], f"{method} 未产出任何用例"
        assert {case["design_method"] for case in suite["cases"]} == {method}


def test_unknown_method_returns_404(client) -> None:
    response = client.post(
        f"{API}/testcases/generate", json={"text": REQUIREMENT_MD, "methods": ["nope"], "use_llm": False}
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_missing_source_returns_400(client) -> None:
    """
    测试缺少源代码时API是否返回400错误状态码
    该测试验证当请求中缺少必要的源代码参数时，
    API是否会正确返回400 Bad Request响应。
    参数:
        client: 测试HTTP客户端，用于发送API请求
    返回:
        None
    """
    # 发送POST请求到测试用例生成API端点，仅包含methods参数
    response = client.post(f"{API}/testcases/generate", json={"methods": ["boundary"]})
    # 验证响应状态码是否为400（Bad Request）
    assert response.status_code == 400
    # 验证响应JSON中的错误代码是否为"BAD_REQUEST"
    assert response.json()["code"] == "BAD_REQUEST"


def test_validation_error_returns_422_envelope(client) -> None:
    response = client.post(f"{API}/requirements/parse", json={"max_items": 999})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["success"] is False


def test_requirement_not_found(client) -> None:
    response = client.get(f"{API}/requirements/DOC-missing")
    assert response.status_code == 404


def test_documents_listing(client) -> None:
    """
    测试文档列表功能
    验证能够获取文档列表，并且列表至少包含一个文档
    """
    # 上传一个测试文档，内容为Markdown格式，包含标题和描述
    _upload(client, "# 列表需求\n## 功能A\n描述A\n", "list.md")
    # 发送GET请求获取文档列表，限制返回数量为5
    body = client.get(f"{API}/documents", params={"limit": 5}).json()
    # 验证请求是否成功
    assert body["success"] is True
    # 验证返回的文档列表至少包含一个文档
    assert len(body["data"]) >= 1


def test_document_summary_reports_requirement_state(client) -> None:
    """列表必须能看出「解析过了没」——否则想回看只能重新解析一遍。"""
    doc_id = _upload(client, "# 状态需求\n## 功能B\n描述B\n", "state.md").json()["data"]["doc_id"]

    fresh = _find_document(client, doc_id)
    assert fresh["has_requirement"] is False
    assert fresh["requirement_items"] == 0
    assert fresh["parse_meta"] is None, "未解析就不该有任何解析口径"

    client.post(f"{API}/requirements/parse", json={"doc_id": doc_id, "use_llm": False, "max_items": 5})

    parsed = _find_document(client, doc_id)
    assert parsed["has_requirement"] is True
    assert parsed["requirement_items"] > 0
    # 列表页要能直接说出「这条需求是谁解析的」：换个模型结果就会变，
    # 复盘时第一个要问的就是它，藏在详情页里等于没有。
    assert parsed["parse_meta"] is not None
    assert parsed["parse_meta"]["llm_used"] is False


def test_document_download_returns_original_bytes(client) -> None:
    """原文要能原样取回：需求文档常要拿去评审 / 归档 / 跨版本比对。"""
    content = "# 可下载需求\n## 功能C\n描述C\n"
    doc_id = _upload(client, content, "下载需求.md").json()["data"]["doc_id"]

    response = client.get(f"{API}/documents/{doc_id}/download")

    assert response.status_code == 200
    assert response.content == content.encode("utf-8")
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert unquote(disposition.split("UTF-8''")[1]) == "下载需求.md"


def test_document_download_missing_returns_404(client) -> None:
    assert client.get(f"{API}/documents/DOC-missing/download").status_code == 404


def test_index_page_served(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "测试工程师助手平台" in response.text


def test_pipeline_exposes_both_llm_stages(client) -> None:
    """展示口径回归：解析阶段与生成阶段必须分别可观测，不能混为一谈。"""
    data = client.post(
        f"{API}/pipeline/generate",
        json={
            "text": REQUIREMENT_MD,
            "title": "两阶段口径",
            "methods": ["equivalence", "boundary", "scenario"],
            "use_llm": True,
            "use_llm_in_design": True,
        },
    ).json()["data"]

    assert data["requirement_doc"]["parse_meta"]["llm_used"] is True
    assert data["suite"]["generation_meta"]["llm_used"] is True
    # 解析口径快照应随用例集一同落盘，供导出/展示复用
    assert data["suite"]["parse_meta"]["llm_used"] is True
    assert data["suite"]["parse_meta"]["provider"] == "fake"


def test_pipeline_rule_only_design_reports_rule_engine(client) -> None:
    """未开启生成阶段 LLM 时，生成口径必须如实显示为规则引擎。"""
    data = client.post(
        f"{API}/pipeline/generate",
        json={
            "text": REQUIREMENT_MD,
            "title": "纯规则生成",
            "methods": ["equivalence"],
            "use_llm": True,
            "use_llm_in_design": False,
        },
    ).json()["data"]

    assert data["suite"]["generation_meta"]["llm_used"] is False
    assert data["requirement_doc"]["parse_meta"]["llm_used"] is True


def test_persisted_suite_keeps_parse_snapshot(client) -> None:
    """用例集详情接口也应返回解析口径快照（前端展示依赖它）。"""
    suite = client.post(
        f"{API}/pipeline/generate",
        json={"text": REQUIREMENT_MD, "title": "口径快照", "methods": ["boundary"], "use_llm": True},
    ).json()["data"]["suite"]
    detail = client.get(f"{API}/testcases/{suite['suite_id']}").json()["data"]
    assert detail["parse_meta"]["llm_used"] is True


def test_generate_from_parsed_respects_methods_query(client) -> None:
    """设计方法以逗号分隔 query 传入时必须生效。

    回归：该参数曾被 FastAPI 当成 requestBody，导致前端 ?methods=boundary 被静默忽略，
    实际总是按全部方法生成。
    """
    doc_id = _upload(client).json()["data"]["doc_id"]
    client.post(
        f"{API}/requirements/parse", json={"doc_id": doc_id, "use_llm": False, "max_items": 5}
    )

    single = client.post(
        f"{API}/requirements/{doc_id}/testcases?methods=boundary&use_llm_in_design=false"
    )
    assert single.status_code == 200, single.text
    assert single.json()["data"]["methods"] == ["boundary"]

    multi = client.post(
        f"{API}/requirements/{doc_id}/testcases?methods=boundary,scenario"
    )
    assert multi.status_code == 200, multi.text
    assert multi.json()["data"]["methods"] == ["boundary", "scenario"]


def test_suite_list_is_summary_only(client) -> None:
    """列表接口只带统计与元信息，用例明细必须走详情接口。

    回归：列表与总览曾直接 `model_dump()` 整份用例集，50 份用例集会返回数百 KB
    前端根本用不到的用例明细（列表页只读 `stats`）。
    """
    suite = client.post(
        f"{API}/pipeline/generate",
        json={
            "text": REQUIREMENT_MD,
            "title": "列表口径",
            "methods": ["equivalence", "boundary"],
            "use_llm": False,
        },
    ).json()["data"]["suite"]
    assert suite["cases"], "用例明细应存在于生成结果中"

    listed = client.get(f"{API}/testcases/suites", params={"limit": 50}).json()["data"]
    target = next(item for item in listed if item["suite_id"] == suite["suite_id"])
    assert "cases" not in target
    assert target["stats"]["total"] == suite["stats"]["total"]
    assert target["doc_title"] == suite["doc_title"]

    # 详情接口仍然返回完整用例
    detail = client.get(f"{API}/testcases/{suite['suite_id']}").json()["data"]
    assert len(detail["cases"]) == suite["stats"]["total"]

    overview = client.get(f"{API}/overview").json()["data"]
    assert overview["recent"]["suites"]
    assert all("cases" not in item for item in overview["recent"]["suites"])
    assert overview["counts"]["cases"] >= suite["stats"]["total"]


def test_suite_list_filters_by_source_requirement(client) -> None:
    """列表要能按来源需求反查，且过滤发生在 limit 截断之前。

    需求页要靠它列出「这条需求生成过哪些用例集」。顺序反了，该需求明明生成过
    三份，接口只翻最近 N 份 / 全局文件再筛，就会漏成一份甚至零份。
    """
    doc_id = _upload(client, "# 追溯需求\n## 功能D\n描述D\n", "trace.md").json()["data"]["doc_id"]
    client.post(f"{API}/requirements/parse", json={"doc_id": doc_id, "use_llm": False, "max_items": 5})

    made = {
        client.post(f"{API}/requirements/{doc_id}/testcases?methods={method}").json()["data"]["suite_id"]
        for method in ("equivalence", "boundary", "scenario")
    }
    assert len(made) == 3

    capped = client.get(f"{API}/testcases/suites", params={"doc_id": doc_id, "limit": 2}).json()["data"]
    assert len(capped) == 2
    assert all(item["doc_id"] == doc_id for item in capped)

    full = client.get(f"{API}/testcases/suites", params={"doc_id": doc_id, "limit": 50}).json()["data"]
    assert {item["suite_id"] for item in full} == made
    # 列表项仍必须带上「来源需求 + 生成引擎」这两个口径，前端才标得出来
    assert all(item["doc_id"] == doc_id for item in full)
    assert all("generation_meta" in item for item in full)


def test_batch_delete_suites_reports_missing_and_cleans_orphans(client) -> None:
    """批量删除要如实报告未找到的 ID，并回收没有源文档的孤立解析结果。

    回归：粘贴文本现在同时进入文档库，因此删除用例集不能把仍有文档入口的需求清掉。
    对于历史遗留或源文档已被手动删除的孤儿需求，批量删除仍要负责回收。
    """
    from app.repository import get_repository

    repository = get_repository()

    def generate(title: str) -> dict:
        return client.post(
            f"{API}/pipeline/generate",
            json={
                "text": REQUIREMENT_MD,
                "title": title,
                "methods": ["equivalence"],
                "use_llm": False,
            },
        ).json()["data"]["suite"]

    first = generate("孤立回收 A")
    second = generate("孤立回收 B")
    doc_id = first["doc_id"]
    assert second["doc_id"] != doc_id, "粘贴文本每次都会合成独立的需求 ID"

    body = client.post(
        f"{API}/testcases/batch-delete",
        json={"ids": [first["suite_id"], "SUITE-does-not-exist", first["suite_id"]]},
    ).json()
    assert body["success"] is True
    result = body["data"]
    assert result["deleted"] == 1, "重复 ID 只应删除一次"
    assert result["missing"] == ["SUITE-does-not-exist"]
    assert repository.requirements.exists(doc_id), "粘贴文本已进入文档库，不得当成孤儿删除"
    assert repository.documents.exists(doc_id), "粘贴文本的文档记录应保留"
    assert repository.requirements.exists(second["doc_id"]), "仍被引用的需求不得回收"

    # 模拟历史遗留的孤立需求：源文档已不存在且没有用例集引用。
    repository.documents.delete(doc_id)
    client.post(
        f"{API}/testcases/batch-delete",
        json={"ids": ["SUITE-does-not-exist"]},
    )
    assert not repository.requirements.exists(doc_id), "无文档且无引用的需求应被回收"

