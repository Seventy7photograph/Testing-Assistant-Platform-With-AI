"""V2.0 多模态 OCR 回归：识别通道选择、结果回填、描述与原文分流。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.config import Settings
from app.parsers.base import ParsedAsset, ParsedDocument
from app.services.image_enrichment_service import (
    STATUS_RECOGNIZED,
    STATUS_SKIPPED,
    STATUS_UNAVAILABLE,
    ImageEnrichmentService,
)
from app.services.rule_parser import strip_derived_blocks
from app.vision.base import IMAGE_DESC_SECTION, KIND_DESCRIPTION, KIND_TEXT, ImageTextExtractor, ImageTextResult
from app.vision.imaging import prepare_image, sniff_mime
from app.vision.local_ocr import LocalOcrExtractor
from app.vision.null import NullExtractor
from app.vision.registry import build_vision_extractor, vision_capabilities
from app.vision.vlm import MODE_BOTH, MODE_DESCRIBE, MODE_TEXT, VisionLlmExtractor, clean_vision_text

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)
JPEG_MINIMAL = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")


def make_png(width: int, height: int) -> bytes:
    """手写一个纯色 PNG（不依赖 Pillow），用于精确控制图片尺寸。"""
    import struct
    import zlib

    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


#: 一张尺寸正常的截图（300×180 = 54000 像素，高于默认的 4096 像素阈值）。
PNG_SHOT = make_png(300, 180)
#: 一张图标尺寸的小图，用于验证「跳过小图标」。
PNG_ICON = make_png(24, 24)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    settings = Settings(storage_dir=tmp_path, **overrides)
    settings.ensure_dirs()
    return settings


def asset(index: int = 1, *, data: bytes = PNG_1X1, width: int = 0, height: int = 0) -> ParsedAsset:
    return ParsedAsset(
        index=index,
        data=data,
        mime="image/png",
        extension="png",
        source="docx",
        placeholder=f"[图片 {index}]",
        anchor="用户注册",
        width=width,
        height=height,
    )


class FakeExtractor(ImageTextExtractor):
    """脚本化识别通道：记录调用次数，便于断言去重与上限行为。"""

    name = "scripted"
    label = "脚本化识别"
    kind = KIND_TEXT

    def __init__(self, text: str = "手机号：11位数字，必填", kind: str = KIND_TEXT, available: bool = True) -> None:
        self.text = text
        self.kind = kind
        self._available = available
        self.calls = 0

    @property
    def available(self) -> bool:
        return self._available

    @property
    def degraded_reason(self) -> str:
        return "" if self._available else "测试用：通道不可用"

    async def extract(self, image: bytes, *, hint: str = "", filename: str = "") -> ImageTextResult:
        self.calls += 1
        return ImageTextResult(text=self.text, extractor="scripted", kind=self.kind, confidence=0.9)


# --------------------------------------------------------------------------- #
# 图片预处理
# --------------------------------------------------------------------------- #


class TestImaging:
    def test_sniff_mime_by_magic(self) -> None:
        assert sniff_mime(PNG_1X1) == "image/png"
        assert sniff_mime(JPEG_MINIMAL) == "image/jpeg"
        assert sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
        assert sniff_mime(b"not an image") == "application/octet-stream"

    def test_prepare_downscales_large_image(self) -> None:
        pytest.importorskip("PIL")
        from PIL import Image
        import io

        buffer = io.BytesIO()
        Image.new("RGB", (3000, 1500), "white").save(buffer, format="PNG")
        data, mime, warnings = prepare_image(buffer.getvalue(), max_side=800)
        assert mime == "image/png"
        assert warnings == []
        with Image.open(io.BytesIO(data)) as result:
            assert max(result.size) == 800

    def test_prepare_passes_through_unknown_format(self) -> None:
        data, mime, warnings = prepare_image(b"garbage-bytes")
        assert data == b"garbage-bytes"
        assert mime == "application/octet-stream"
        assert warnings and "无法识别图片格式" in warnings[0]


# --------------------------------------------------------------------------- #
# 识别通道
# --------------------------------------------------------------------------- #


class TestExtractorSelection:
    def test_auto_falls_back_to_null_with_reason(self, tmp_path: Path, monkeypatch) -> None:
        # 必须把**本地 OCR 真正使用的那个**探测函数打掉：
        # LocalOcrExtractor.backend 走的是 app.vision.local_ocr.detect_backend。
        # 只打 registry 里那一个，本机装了 RapidOCR 时这条断言就会假失败 ——
        # 之前的"通过"其实只是因为机器上没装引擎。
        monkeypatch.setattr("app.vision.local_ocr.detect_backend", lambda: None)
        monkeypatch.setattr("app.vision.registry.detect_backend", lambda: None)
        settings = make_settings(tmp_path, vision_provider="auto", vision_cloud_url="")
        extractor = build_vision_extractor(settings)
        assert extractor.name == "none"
        assert extractor.available is False
        # 降级原因必须说清「为什么不可用」，否则界面只能显示一句没用的「不可用」。
        assert "本地 OCR" in extractor.degraded_reason or "多模态" in extractor.degraded_reason

    def test_explicit_none_disables(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, vision_provider="none")
        extractor = build_vision_extractor(settings)
        assert isinstance(extractor, NullExtractor)

    def test_unknown_provider_falls_back_to_auto(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("app.vision.registry.detect_backend", lambda: None)
        settings = make_settings(tmp_path, vision_provider="magic-ocr")
        assert build_vision_extractor(settings).name in {"vlm", "local-ocr", "cloud-ocr", "none"}

    def test_fake_provider_is_selectable(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, vision_provider="fake")
        extractor = build_vision_extractor(settings)
        assert extractor.available
        result = asyncio.run(extractor.extract(PNG_1X1, filename="a.png"))
        assert "模拟识别" in result.text

    def test_capabilities_report_reason(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("app.vision.local_ocr.detect_backend", lambda: None)
        monkeypatch.setattr("app.vision.registry.detect_backend", lambda: None)
        capabilities = vision_capabilities(make_settings(tmp_path))
        assert capabilities["available"] is False
        assert capabilities["degraded_reason"]
        assert capabilities["supported"] == ["cloud-ocr", "fake", "local-ocr", "none", "vlm"]


class TestLocalOcr:
    def test_reports_install_hint_when_no_backend(self, monkeypatch) -> None:
        monkeypatch.setattr("app.vision.local_ocr.detect_backend", lambda: None)
        extractor = LocalOcrExtractor()
        assert extractor.available is False
        result = asyncio.run(extractor.extract(PNG_1X1))
        assert result.usable is False
        assert any("pip install" in warning for warning in result.warnings)

    def test_runs_detected_backend(self, monkeypatch) -> None:
        from app.vision import local_ocr

        monkeypatch.setattr(local_ocr, "detect_backend", lambda: local_ocr.TESSERACT_CLI)
        extractor = LocalOcrExtractor()
        monkeypatch.setattr(
            LocalOcrExtractor, "_run_tesseract_cli", lambda self, image: ("识别到的文字", 0.91)
        )
        result = asyncio.run(extractor.extract(PNG_1X1))
        assert result.text == "识别到的文字"
        assert result.confidence == 0.91
        assert result.extractor == "local-ocr:tesseract-cli"

    def test_low_confidence_is_flagged(self, monkeypatch) -> None:
        from app.vision import local_ocr

        monkeypatch.setattr(local_ocr, "detect_backend", lambda: local_ocr.TESSERACT_CLI)
        monkeypatch.setattr(
            LocalOcrExtractor, "_run_tesseract_cli", lambda self, image: ("模糊文字", 0.31)
        )
        result = asyncio.run(LocalOcrExtractor().extract(PNG_1X1))
        assert any("置信度偏低" in warning for warning in result.warnings)


class TestVisionLlm:
    def test_sends_image_content_part(self, tmp_path: Path, monkeypatch) -> None:
        captured: dict = {}

        async def fake_complete(self, messages, **kwargs):  # noqa: ANN001
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            from app.llm.base import LLMResponse

            return LLMResponse(content="```\n识别出的表格\n```", model="qwen-vl-max")

        monkeypatch.setattr("app.llm.openai_compatible.OpenAICompatibleProvider.complete", fake_complete)
        settings = make_settings(tmp_path, vision_provider="vlm", llm_api_key="k", vision_model="qwen-vl-max")
        extractor = VisionLlmExtractor(settings, mode=MODE_TEXT)
        result = asyncio.run(extractor.extract(PNG_1X1, hint="第 3 页"))

        content = captured["messages"][0].content
        assert isinstance(content, list)
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "第 3 页" in content[0]["text"]
        # 代码围栏必须被清掉，否则识别文本会带着 ``` 进入正文。
        assert result.text == "识别出的表格"
        assert result.kind == KIND_TEXT

    def test_describe_mode_returns_description(self, tmp_path: Path, monkeypatch) -> None:
        async def fake_complete(self, messages, **kwargs):  # noqa: ANN001
            from app.llm.base import LLMResponse

            return LLMResponse(content="这是一个登录页，含手机号与验证码输入框。", model="qwen-vl-max")

        monkeypatch.setattr("app.llm.openai_compatible.OpenAICompatibleProvider.complete", fake_complete)
        settings = make_settings(tmp_path, llm_api_key="k")
        extractor = VisionLlmExtractor(settings, mode=MODE_DESCRIBE)
        result = asyncio.run(extractor.extract(PNG_1X1))
        assert result.is_description
        assert result.kind == KIND_DESCRIPTION

    def test_unavailable_without_key(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, llm_api_key="", vision_api_key="")
        extractor = VisionLlmExtractor(settings)
        assert extractor.available is False
        result = asyncio.run(extractor.extract(PNG_1X1))
        assert result.usable is False

    def test_mode_fallback_and_cleanup(self) -> None:
        assert VisionLlmExtractor.__name__
        assert clean_vision_text("```json\n{}\n```") == "{}"
        assert clean_vision_text("（无文字）") == ""
        assert clean_vision_text("  正常文字 ") == "正常文字"
        assert MODE_BOTH in {MODE_TEXT, MODE_DESCRIBE, MODE_BOTH}


# --------------------------------------------------------------------------- #
# 回填与分流
# --------------------------------------------------------------------------- #


class TestEnrichment:
    def test_inline_backfill_keeps_position(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, vision_provider="fake")
        parsed = ParsedDocument(
            text="## 用户注册\n[图片 1]\n提交按钮校验",
            parser="docx",
            extension="docx",
            assets=[asset()],
        )
        outcome = asyncio.run(
            ImageEnrichmentService(settings, FakeExtractor()).enrich(doc_id="DOC-1", parsed=parsed)
        )
        assert outcome.recognized == 1
        assert "手机号：11位数字，必填" in outcome.text
        # 识别文本必须落在占位符原来的位置：在「## 用户注册」之后、「提交按钮校验」之前。
        assert outcome.text.index("用户注册") < outcome.text.index("手机号") < outcome.text.index("提交按钮校验")
        # 占位符本身保留，但升级成「带来源的图注」：便于回溯这段文字是第几张图、谁识别的。
        assert "[图片 1]（用户注册 · 来源：scripted）" in outcome.text

    def test_description_goes_to_tail_section(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, vision_provider="fake")
        parsed = ParsedDocument(
            text="正文",
            parser="docx",
            extension="docx",
            assets=[asset()],
        )
        outcome = asyncio.run(
            ImageEnrichmentService(settings, FakeExtractor("这是登录页原型", KIND_DESCRIPTION)).enrich(
                doc_id="DOC-1", parsed=parsed
            )
        )
        assert IMAGE_DESC_SECTION in outcome.text
        assert outcome.text.index("正文") < outcome.text.index(IMAGE_DESC_SECTION)
        assert any("视觉描述" in warning for warning in outcome.warnings)

    def test_derived_section_is_stripped_for_rule_parsing(self) -> None:
        text = "## 下单\n数量：1~99\n\n[图片描述 · 模型推断，非原文]\n这里说金额上限 500"
        stripped = strip_derived_blocks(text)
        assert "数量：1~99" in stripped
        assert "金额上限 500" not in stripped

    def test_duplicate_images_recognized_once(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, vision_provider="fake")
        document = ParsedDocument(
            text="[图片 1]\n[图片 2]",
            parser="docx",
            extension="docx",
            assets=[asset(1), asset(2)],
        )
        extractor = FakeExtractor()
        outcome = asyncio.run(
            ImageEnrichmentService(settings, extractor).enrich(doc_id="DOC-1", parsed=document)
        )
        assert extractor.calls == 1
        second = next(item for item in outcome.assets if item.index == 2)
        assert second.status == STATUS_SKIPPED
        assert second.reused_from == 1
        # 复用不等于没内容：正文里两处都要有文字。
        assert outcome.text.count("手机号：11位数字，必填") == 2

    def test_max_images_cap_skips_rest(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, vision_provider="fake", vision_max_images=1)
        assets = [asset(1, data=b"a" * 100), asset(2, data=b"b" * 100), asset(3, data=b"c" * 100)]
        document = ParsedDocument(text="[图片 1]\n[图片 2]\n[图片 3]", parser="docx", extension="docx", assets=assets)
        outcome = asyncio.run(
            ImageEnrichmentService(settings, FakeExtractor()).enrich(doc_id="DOC-1", parsed=document)
        )
        assert outcome.recognized == 1
        assert outcome.skipped == 2
        assert any("单文档识别上限" in item.message for item in outcome.assets)

    def test_tiny_images_are_skipped(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, vision_provider="fake", vision_min_pixels=4096)
        document = ParsedDocument(
            text="[图片 1]",
            parser="pdf",
            extension="pdf",
            assets=[asset(1, width=16, height=16)],
        )
        extractor = FakeExtractor()
        outcome = asyncio.run(
            ImageEnrichmentService(settings, extractor).enrich(doc_id="DOC-1", parsed=document)
        )
        assert extractor.calls == 0
        assert outcome.assets[0].status == STATUS_SKIPPED
        assert "过小" in outcome.assets[0].message

    def test_uploaded_image_bypasses_size_filter(self, tmp_path: Path) -> None:
        """使用者主动上传的那一张不做尺寸过滤：他既然单独传了，就是想让平台看一眼。"""
        settings = make_settings(tmp_path, vision_provider="fake", vision_min_pixels=4096)
        uploaded = asset(1, width=16, height=16)
        uploaded.source = "upload"
        document = ParsedDocument(text="", parser="image", extension="png", assets=[uploaded])
        extractor = FakeExtractor()
        outcome = asyncio.run(
            ImageEnrichmentService(settings, extractor).enrich(doc_id="DOC-1", parsed=document)
        )
        assert extractor.calls == 1
        assert outcome.assets[0].status == STATUS_RECOGNIZED

    def test_unavailable_channel_is_reported_not_silent(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, vision_provider="fake")
        document = ParsedDocument(text="[图片 1]", parser="docx", extension="docx", assets=[asset()])
        outcome = asyncio.run(
            ImageEnrichmentService(settings, FakeExtractor(available=False)).enrich(
                doc_id="DOC-1", parsed=document
            )
        )
        assert outcome.assets[0].status == STATUS_UNAVAILABLE
        assert outcome.assets[0].message
        # 占位符保留：至少让人知道这里原本有张图。
        assert "[图片 1]" in outcome.text

    def test_assets_are_persisted_next_to_document(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, vision_provider="fake")
        document = ParsedDocument(text="[图片 1]", parser="docx", extension="docx", assets=[asset()])
        outcome = asyncio.run(
            ImageEnrichmentService(settings, FakeExtractor()).enrich(doc_id="DOC-9", parsed=document)
        )
        stored = settings.asset_dir / "DOC-9" / outcome.assets[0].filename
        assert stored.is_file()
        assert stored.read_bytes() == PNG_1X1
        assert outcome.assets[0].status == STATUS_RECOGNIZED


# --------------------------------------------------------------------------- #
# 配置接口
# --------------------------------------------------------------------------- #

API = "/api/v1"


class TestVisionConfigApi:
    def test_read_config_exposes_options_and_status(self, client) -> None:
        data = client.get(f"{API}/vision/config").json()["data"]
        assert {item["name"] for item in data["providers"]} >= {"auto", "vlm", "local-ocr", "cloud-ocr", "none"}
        assert {item["value"] for item in data["modes"]} == {"text", "describe", "both"}
        assert data["extractor"]
        assert data["available"] in (True, False)

    def test_roundtrip_and_reset(self, client) -> None:
        try:
            saved = client.put(
                f"{API}/vision/config", json={"provider": "fake", "mode": "text", "max_images": 5}
            ).json()["data"]
            assert saved["provider"] == "fake"
            assert saved["source"] == "runtime"
            assert saved["available"] is True
            assert saved["extractor"] == "fake"
            assert saved["max_images"] == 5

            tested = client.post(f"{API}/vision/config/test").json()["data"]
            assert tested["ok"] is True
            assert "模拟识别" in tested["sample"]

            reset = client.delete(f"{API}/vision/config").json()["data"]
            assert reset["source"] == "env"
            assert reset["provider"] == "auto"
        finally:
            client.delete(f"{API}/vision/config")

    def test_vision_reset_keeps_llm_overrides(self, client) -> None:
        """清图片识别配置不该顺手把大模型那头的界面配置也清掉。"""
        try:
            client.put(f"{API}/llm/config", json={"provider": "fake", "model": "fake-model"})
            client.put(f"{API}/vision/config", json={"provider": "fake"})
            client.delete(f"{API}/vision/config")
            llm = client.get(f"{API}/llm/config").json()["data"]
            assert llm["provider"] == "fake"
            assert llm["source"] == "runtime"
        finally:
            client.delete(f"{API}/llm/config")

    def test_llm_reset_clears_everything(self, client) -> None:
        """大模型页的「恢复基线」是全局动作：图片识别的覆盖也一并清掉（同为一份覆盖文件）。"""
        try:
            client.put(f"{API}/vision/config", json={"provider": "fake"})
            client.delete(f"{API}/llm/config")
            vision = client.get(f"{API}/vision/config").json()["data"]
            assert vision["source"] == "env"
        finally:
            client.delete(f"{API}/llm/config")
