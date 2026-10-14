"""把文档里的图片变成文本（V2.0 多模态 OCR 的粘合层）。

它连接两个互不感知的模块：解析器只负责「把图片抠出来」，识别通道只负责
「把一张图变成文字」；本服务决定**哪些图片值得识别、识别结果放在正文的哪个位置、
以及识别不了时怎么如实告诉使用者**。

三件事必须做对：

  1. **占位回填**：识别结果回填到解析器留下的 ``[图片 N]`` 位置。图片与上下文
     文字的相对顺序是判读需求的关键线索（「这张图挨着哪条约束」），丢掉就白做了；
  2. **描述与原文分流**：OCR 原文写在原位（可参与规则解析），模型对图片的推断
     统一收进文末的 ``[图片描述]`` 段（不参与规则解析）。混在一起会让幻觉变成
     测试数据里的约束；
  3. **不静默降级**：跳过 / 失败 / 通道不可用，三种情况都要落进告警与资产状态，
     界面据此能说清「这张图为什么没识别、该怎么办」。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.utils import Timer
from app.parsers.base import ParsedAsset, ParsedDocument
from app.schemas.document import DocumentAsset
from app.vision.base import (
    DERIVED_KINDS,
    IMAGE_DESC_SECTION,
    ImageTextExtractor,
    ImageTextResult,
)
from app.vision.registry import build_vision_extractor

logger = get_logger(__name__)

#: 同时进行的识别请求数：多模态端点多有并发限制，放开只会换来 429。
MAX_CONCURRENCY = 3

#: 单张图片识别结果写入正文的上限，防止一张超长表格把文档撑爆。
MAX_CHARS_PER_IMAGE = 4000

STATUS_RECOGNIZED = "recognized"
STATUS_EMPTY = "empty"
STATUS_SKIPPED = "skipped"
STATUS_UNAVAILABLE = "unavailable"


@dataclass(slots=True)
class EnrichmentOutcome:
    """一次图片识别的完整产出。"""

    text: str
    assets: list[DocumentAsset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recognized: int = 0
    skipped: int = 0
    failed: int = 0
    elapsed_ms: int = 0

    @property
    def image_count(self) -> int:
        return len(self.assets)


class ImageEnrichmentService:
    def __init__(
        self,
        settings: Settings | None = None,
        extractor: ImageTextExtractor | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.extractor = extractor or build_vision_extractor(self.settings)

    # ------------------------------------------------------------------ #
    async def enrich(self, *, doc_id: str, parsed: ParsedDocument) -> EnrichmentOutcome:
        """识别文档里的全部图片，返回回填后的正文与资产明细。"""
        if not parsed.assets:
            return EnrichmentOutcome(text=parsed.text)

        with Timer() as timer:
            raw = {asset.index: asset.data for asset in parsed.assets}
            assets = persist_assets(self.settings, doc_id, parsed.assets)
            candidates, skipped, warnings = self._filter(assets)
            await self._recognize(candidates, raw, assets)
            text, compose_warnings = self._compose(parsed.text, assets)

        outcome = EnrichmentOutcome(
            text=text,
            assets=assets,
            warnings=[*warnings, *compose_warnings],
            recognized=sum(1 for item in assets if item.status == STATUS_RECOGNIZED),
            skipped=len(skipped),
            failed=sum(1 for item in assets if item.status in (STATUS_EMPTY, STATUS_UNAVAILABLE)),
            elapsed_ms=timer.elapsed_ms,
        )
        logger.info(
            "图片识别完成：doc=%s 共 %d 张，识别 %d 张，跳过 %d 张，未出结果 %d 张，耗时 %dms",
            doc_id,
            len(assets),
            outcome.recognized,
            outcome.skipped,
            outcome.failed,
            outcome.elapsed_ms,
        )
        return outcome

    # ------------------------------------------------------------------ #
    def _filter(
        self, assets: list[DocumentAsset]
    ) -> tuple[list[DocumentAsset], list[DocumentAsset], list[str]]:
        """挑出值得识别的图片；其余标记为跳过并写明原因。"""
        min_pixels = int(getattr(self.settings, "vision_min_pixels", 0) or 0)
        max_images = int(getattr(self.settings, "vision_max_images", 20) or 20)
        candidates: list[DocumentAsset] = []
        skipped: list[DocumentAsset] = []
        seen: dict[str, DocumentAsset] = {}

        for asset in assets:
            # 尺寸过滤只针对**从文档里抠出来的**图：Word/PDF 里成片的 16×16 图标、
            # 分隔线、logo 送去识别纯属浪费。使用者主动上传的那一张不做这个判断 ——
            # 他既然单独上传了，就是想让平台看一眼。
            if (
                min_pixels
                and asset.source != "upload"
                and asset.width
                and asset.height
                and asset.width * asset.height < min_pixels
            ):
                asset.status = STATUS_SKIPPED
                asset.message = (
                    f"图片过小（{asset.width}×{asset.height}），判定为图标/装饰，已跳过识别。"
                )
                skipped.append(asset)
                continue
            duplicate = seen.get(asset.checksum)
            if duplicate is not None:
                # 同一张图在文档里重复出现（页眉 logo、同一原型图多次引用）只识别一次。
                asset.status = STATUS_SKIPPED
                asset.reused_from = duplicate.index
                asset.message = f"与第 {duplicate.index} 张图片内容相同，复用其识别结果。"
                skipped.append(asset)
                continue
            seen[asset.checksum] = asset
            if len(candidates) >= max_images:
                asset.status = STATUS_SKIPPED
                asset.message = (
                    f"超过单文档识别上限（{max_images} 张），未识别。"
                    "可提高 VISION_MAX_IMAGES，或把关键页面拆成单独文件上传。"
                )
                skipped.append(asset)
                continue
            candidates.append(asset)

        warnings: list[str] = []
        if skipped:
            warnings.append(
                f"共 {len(assets)} 张图片，其中 {len(skipped)} 张按规则跳过（过小 / 重复 / 超上限）。"
            )
        return candidates, skipped, warnings

    async def _recognize(
        self,
        candidates: list[DocumentAsset],
        raw: dict[int, bytes],
        assets: list[DocumentAsset],
    ) -> None:
        """并发识别候选图片，结果直接写回资产记录。"""
        if not candidates:
            return
        if not self.extractor.available:
            reason = self.extractor.degraded_reason or "图片识别通道不可用"
            for asset in candidates:
                asset.status = STATUS_UNAVAILABLE
                asset.message = reason
            return

        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

        async def run(asset: DocumentAsset) -> None:
            async with semaphore:
                result = await self.extractor.extract(
                    raw.get(asset.index, b""),
                    hint=asset.anchor,
                    filename=asset.filename,
                )
            apply_result(asset, result)

        await asyncio.gather(*(run(asset) for asset in candidates))

        # 重复图复用首次识别的结果：「跳过识别」不等于「没有内容」。
        by_index = {asset.index: asset for asset in assets}
        for asset in assets:
            if asset.status != STATUS_SKIPPED or not asset.reused_from:
                continue
            original = by_index.get(asset.reused_from)
            if original is None or original is asset:
                continue
            asset.text = original.text
            asset.extractor = original.extractor
            asset.kind = original.kind
            asset.confidence = original.confidence

    # ------------------------------------------------------------------ #
    def _compose(self, text: str, assets: list[DocumentAsset]) -> tuple[str, list[str]]:
        """把识别结果回填到占位位置，并把模型推断收进文末描述段。"""
        body = text or ""
        descriptions: list[str] = []
        inline_count = 0
        reused_count = 0

        for asset in assets:
            if not asset.text.strip():
                continue
            header = f"{asset.placeholder}（{asset.anchor or '图片'} · 来源：{asset.extractor}）"
            if asset.kind in DERIVED_KINDS:
                descriptions.append(f"{header}\n{asset.text.strip()}")
                continue
            block = f"{header}\n{asset.text.strip()}"
            if asset.placeholder and asset.placeholder in body:
                body = body.replace(asset.placeholder, block)
            else:
                body = f"{body}\n\n{block}" if body else block
            inline_count += 1
            if asset.status == STATUS_SKIPPED:
                reused_count += 1

        warnings: list[str] = []
        if inline_count:
            warnings.append(f"已把 {inline_count} 张图片的识别文字回填到正文对应位置。")
        if reused_count:
            warnings.append(f"其中 {reused_count} 张为文档内重复图片，直接复用了首次识别结果。")
        if descriptions:
            body = (
                f"{body}\n\n{IMAGE_DESC_SECTION}\n"
                "以下内容由模型读图生成，可能不准确，仅供理解图片；不参与字段约束抽取。\n\n"
                + "\n\n".join(descriptions)
            )
            warnings.append(
                f"有 {len(descriptions)} 张图片以「视觉描述」形式写入文末，需人工复核。"
            )
        return body.strip(), warnings


def persist_assets(
    settings: Settings, doc_id: str, assets: list[ParsedAsset]
) -> list[DocumentAsset]:
    """把图片落盘并生成资产记录（落盘失败不影响识别，因为字节还在内存里）。"""
    directory = settings.asset_dir / doc_id
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - 磁盘异常
        logger.warning("图片目录创建失败：%s", exc)

    records: list[DocumentAsset] = []
    for asset in assets:
        filename = f"img-{asset.index:03d}.{asset.extension or 'bin'}"
        stored = ""
        try:
            (directory / filename).write_bytes(asset.data)
            stored = filename
        except OSError as exc:  # pragma: no cover - 磁盘异常
            logger.warning("图片落盘失败：%s", exc)
        records.append(
            DocumentAsset(
                index=asset.index,
                filename=stored or filename,
                mime=asset.mime,
                size_bytes=len(asset.data),
                source=asset.source,
                anchor=asset.anchor,
                placeholder=asset.placeholder,
                width=asset.width,
                height=asset.height,
                checksum=asset.checksum,
                stored=bool(stored),
            )
        )
    return records


def apply_result(asset: DocumentAsset, result: ImageTextResult) -> None:
    """把识别结果写进资产记录，并判定状态（识别成功 / 无内容 / 通道不可用）。"""
    asset.text = result.text.strip()[:MAX_CHARS_PER_IMAGE]
    asset.extractor = result.extractor
    asset.kind = result.kind
    asset.confidence = result.confidence
    if result.usable:
        asset.status = STATUS_RECOGNIZED
        asset.message = "；".join(result.warnings)
    elif result.kind == "none":
        asset.status = STATUS_UNAVAILABLE
        asset.message = "；".join(result.warnings) or "图片识别通道不可用。"
    else:
        asset.status = STATUS_EMPTY
        asset.message = "；".join(result.warnings) or "识别完成，但图中没有可提取的文字。"


__all__ = [
    "EnrichmentOutcome",
    "ImageEnrichmentService",
    "MAX_CHARS_PER_IMAGE",
    "STATUS_EMPTY",
    "STATUS_RECOGNIZED",
    "STATUS_SKIPPED",
    "STATUS_UNAVAILABLE",
    "apply_result",
    "persist_assets",
]
