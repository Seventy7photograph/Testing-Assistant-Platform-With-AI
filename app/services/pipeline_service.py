"""端到端流水线：文档/文本 -> 结构化需求 -> 测试用例集 -> 落盘。

这条链路是 V1.0 的主干，各步骤之间通过显式依赖注入解耦：
    DocumentService / RequirementService / DesignEngine / Repository
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import Settings, get_settings
from app.core.exceptions import BadRequestError
from app.core.logging import get_logger
from app.design.engine import DesignEngine
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.repository import Repository, get_repository
from app.schemas.requirement import RequirementDoc
from app.schemas.testcase import TestCaseSuite
from app.services.document_service import DocumentService
from app.services.requirement_service import RequirementService

logger = get_logger(__name__)


@dataclass
class PipelineResult:
    requirement_doc: RequirementDoc
    suite: TestCaseSuite
    warnings: list[str] = field(default_factory=list)


class PipelineService:
    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMProvider | None = None,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or get_llm_provider()
        self.repository = repository or get_repository()
        self.documents = DocumentService(self.settings, self.repository)
        self.requirements = RequirementService(self.settings, self.llm, self.repository)
        self.engine = DesignEngine(self.settings)

    # ------------------------------------------------------------------ #
    async def run(
        self,
        *,
        doc_id: str | None = None,
        text: str | None = None,
        title: str = "粘贴的需求文本",
        methods: list[str] | None = None,
        use_llm: bool = True,
        use_llm_in_design: bool = False,
        max_items: int = 8,
    ) -> PipelineResult:
        """一键生成：输入文档 ID 或原始文本，输出用例集（已落盘）。"""
        if not doc_id and not (text or "").strip():
            raise BadRequestError(
                "请提供 doc_id 或 text 之一作为需求来源。",
                detail={"doc_id": doc_id},
            )

        source_text = text or ""
        source_title = title
        source_file = ""
        source_type = "text"
        if doc_id:
            record = self.repository.documents.get(doc_id)
            source_text = record.text
            source_title = title if title != "粘贴的需求文本" else record.filename
            source_file = record.filename
            source_type = record.extension

        requirement_doc = await self.requirements.parse_text(
            source_text,
            title=source_title,
            doc_id=doc_id,
            source_file=source_file,
            source_type=source_type,
            use_llm=use_llm,
            max_items=max_items,
        )
        suite = await self.generate_from_requirement(
            requirement_doc, methods=methods, use_llm_in_design=use_llm_in_design
        )
        return PipelineResult(
            requirement_doc=requirement_doc,
            suite=suite,
            warnings=[*requirement_doc.parse_meta.warnings, *suite.generation_meta.warnings],
        )

    async def generate_from_requirement(
        self,
        requirement_doc: RequirementDoc,
        *,
        methods: list[str] | None = None,
        use_llm_in_design: bool = False,
    ) -> TestCaseSuite:
        """基于已解析的需求模型生成用例（供"需求已解析后再生成"场景复用）。"""
        suite = await self.engine.generate(
            requirement_doc,
            methods,
            llm=self.llm,
            use_llm=use_llm_in_design,
        )
        # 把解析阶段口径快照进用例集，供导出层如实展示「解析/生成」两阶段是否用了 LLM。
        suite.parse_meta = requirement_doc.parse_meta
        self.repository.suites.save(suite)
        logger.info("用例集已入库：%s（%d 条）", suite.suite_id, suite.stats.total)
        return suite