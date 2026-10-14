"""S7 回归：Excel 需求清单、直接上传的图片、内嵌图提取与接口行为。"""
from __future__ import annotations

import io

import pytest

from app.parsers.registry import get_parser_for, parse_document, supported_extensions
from app.vision.base import KIND_TEXT, ImageTextExtractor, ImageTextResult
from tests.pdf_factory import make_minimal_pdf
from tests.test_vision import PNG_1X1, PNG_ICON, PNG_SHOT


def make_xlsx(rows_by_sheet: dict[str, list[list[object]]]) -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    first = True
    for name, rows in rows_by_sheet.items():
        sheet = workbook.active if first else workbook.create_sheet()
        sheet.title = name
        first = False
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class FakeExtractor(ImageTextExtractor):
    name = "scripted"
    label = "脚本化识别"
    kind = KIND_TEXT

    async def extract(self, image: bytes, *, hint: str = "", filename: str = "") -> ImageTextResult:
        return ImageTextResult(text="识别出的图片文字", extractor=self.name, kind=self.kind)


class TestExcelParser:
    def test_field_table_becomes_markdown_table(self) -> None:
        data = make_xlsx(
            {
                "字段说明": [
                    ["字段名", "类型", "必填", "取值范围"],
                    ["手机号", "字符串", "是", "11位数字"],
                    ["年龄", "整数", "否", "18~120"],
                ]
            }
        )
        parsed = parse_document(data, "需求.xlsx")
        assert parsed.parser == "excel"
        assert "# 字段说明" in parsed.text
        assert "| 字段名 | 类型 | 必填 | 取值范围 |" in parsed.text
        assert "| 手机号 | 字符串 | 是 | 11位数字 |" in parsed.text
        assert parsed.table_count == 1

    def test_requirement_list_becomes_sections(self) -> None:
        """每行一条需求的清单必须还原成章节，而不是渲染成表格。"""
        data = make_xlsx(
            {
                "需求清单": [
                    ["需求编号", "需求标题", "模块", "需求描述", "优先级"],
                    ["REQ-001", "用户注册", "用户中心", "手机号唯一", "P1"],
                    ["REQ-002", "订单退款", "订单", "支持部分退款", "P2"],
                ]
            }
        )
        parsed = parse_document(data, "需求清单.xlsx")
        assert "## 用户注册" in parsed.text
        assert "## 订单退款" in parsed.text
        assert "模块：用户中心" in parsed.text
        assert "优先级：P1" in parsed.text
        assert parsed.table_count == 0

    def test_rule_parser_understands_excel_output(self) -> None:
        """端到端：Excel 需求清单经规则解析器要能变成需求条目。"""
        from app.services import rule_parser

        data = make_xlsx(
            {
                "需求清单": [
                    ["需求编号", "需求标题", "需求描述"],
                    ["REQ-001", "用户注册", "手机号必须唯一，年龄 18~120"],
                ]
            }
        )
        parsed = parse_document(data, "需求清单.xlsx")
        _, _, items, _ = rule_parser.parse_requirements(parsed.text)
        assert any(item.title == "用户注册" for item in items)

    def test_corrupted_excel_raises_parse_error(self) -> None:
        from app.core.exceptions import DocumentParseError

        with pytest.raises(DocumentParseError):
            parse_document(b"not a real xlsx", "需求.xlsx")


class TestImageParser:
    @pytest.mark.parametrize("filename", ["shot.png", "shot.JPG", "shot.jpeg", "shot.webp", "shot.bmp", "shot.tif"])
    def test_dispatch(self, filename: str) -> None:
        assert get_parser_for(filename).name == "image"

    def test_image_upload_yields_asset_instead_of_error(self) -> None:
        parsed = parse_document(PNG_1X1, "截图.png")
        assert parsed.parser == "image"
        assert len(parsed.assets) == 1
        assert parsed.assets[0].mime == "image/png"
        assert parsed.assets[0].placeholder == "[图片 1]"

    def test_extension_is_registered(self) -> None:
        extensions = supported_extensions()
        for expected in ("png", "jpg", "jpeg", "webp", "xlsx"):
            assert expected in extensions

    def test_uploaded_image_carries_pixel_size(self) -> None:
        parsed = parse_document(PNG_SHOT, "截图.png")
        assert (parsed.assets[0].width, parsed.assets[0].height) == (300, 180)


class TestDocxImages:
    def _docx_with_image(self) -> bytes:
        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_heading("用户注册", level=1)
        document.add_paragraph("手机号必须唯一")
        # 用正常尺寸的位图：docx 内嵌图现在会读尺寸，1×1 会被「跳过小图标」拦下，
        # 那样测的就不是"识别链路"而是"过滤规则"了。
        document.add_picture(io.BytesIO(PNG_SHOT))
        document.add_paragraph("提交后跳转首页")
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    def test_extracts_asset_with_placeholder_in_place(self) -> None:
        parsed = parse_document(self._docx_with_image(), "需求.docx")
        assert len(parsed.assets) == 1
        assert parsed.assets[0].source == "docx"
        assert parsed.assets[0].mime == "image/png"
        lines = parsed.text.splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith("[图片 1]"))
        # 图片占位必须夹在「手机号必须唯一」与「提交后跳转首页」之间。
        assert any("手机号必须唯一" in line for line in lines[:index])
        assert any("提交后跳转首页" in line for line in lines[index:])
        assert any("内嵌图片" in warning for warning in parsed.warnings)

    def test_anchor_is_nearby_paragraph(self) -> None:
        parsed = parse_document(self._docx_with_image(), "需求.docx")
        assert parsed.assets[0].anchor

    def test_asset_carries_pixel_size(self) -> None:
        """内嵌图必须带上尺寸，否则「跳过小图标」这条规则对 Word 图完全失效。"""
        parsed = parse_document(self._docx_with_image(), "需求.docx")
        assert (parsed.assets[0].width, parsed.assets[0].height) == (300, 180)

    def test_tiny_embedded_icon_is_skipped(self, client, monkeypatch) -> None:
        """图标级内嵌图（24×24）不该浪费一次识别。"""
        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_paragraph("正文")
        document.add_picture(io.BytesIO(PNG_ICON))
        buffer = io.BytesIO()
        document.save(buffer)

        calls: list[int] = []

        class CountingExtractor(FakeExtractor):
            async def extract(self, image, *, hint="", filename=""):  # noqa: ANN001
                calls.append(len(image))
                return await super().extract(image, hint=hint, filename=filename)

        monkeypatch.setattr(
            "app.services.image_enrichment_service.build_vision_extractor",
            lambda settings: CountingExtractor(),
        )
        response = client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "图标.docx",
                    buffer.getvalue(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        image = response.json()["data"]["images"][0]
        assert image["status"] == "skipped", image
        assert "过小" in image["message"]
        assert calls == [], "小图标不应触发识别"


class TestPdfAssets:
    def test_scanned_pdf_pages_are_rendered_for_ocr(self) -> None:
        """文本层为空时，整页渲染成图片交给 OCR（pypdfium2 路径）。"""
        pytest.importorskip("pypdfium2")
        from app.parsers.pdf_parser import render_pages_as_assets

        warnings: list[str] = []
        assets = render_pages_as_assets(make_minimal_pdf(), 1, warnings)
        assert assets, warnings
        assert assets[0].source == "pdf-page"
        assert assets[0].mime == "image/png"
        assert assets[0].width > 0 and assets[0].height > 0

    def test_text_pdf_still_parses_without_assets(self) -> None:
        parsed = parse_document(make_minimal_pdf("Requirement: phone must be 11 digits"), "req.pdf")
        assert "Requirement" in parsed.text
        assert parsed.assets == []


class TestDocumentApiWithImages:
    def _upload_docx(self, client) -> dict:
        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_heading("用户注册", level=1)
        document.add_paragraph("手机号必须唯一")
        document.add_picture(io.BytesIO(PNG_SHOT))
        buffer = io.BytesIO()
        document.save(buffer)
        response = client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "需求.docx",
                    buffer.getvalue(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]

    def test_summary_reports_image_status(self, client) -> None:
        summary = self._upload_docx(client)
        assert summary["image_count"] == 1
        assert len(summary["images"]) == 1
        image = summary["images"][0]
        assert image["source"] == "docx"
        assert image["status"] in {"unavailable", "recognized", "empty", "skipped"}
        # 测试环境既没配多模态模型、也没装本地 OCR：必须给出明确原因，而不是静默留空。
        if image["status"] == "unavailable":
            assert image["message"]

    def test_image_can_be_fetched(self, client) -> None:
        summary = self._upload_docx(client)
        filename = summary["images"][0]["filename"]
        response = client.get(f"/api/v1/documents/{summary['doc_id']}/images/{filename}")
        assert response.status_code == 200
        assert response.content == PNG_SHOT

    def test_unknown_image_returns_404(self, client) -> None:
        summary = self._upload_docx(client)
        response = client.get(f"/api/v1/documents/{summary['doc_id']}/images/nope.png")
        assert response.status_code == 404

    def test_recognize_returns_501_without_channel(self, client, monkeypatch) -> None:
        from app.vision.null import NullExtractor

        monkeypatch.setattr(
            "app.services.document_service.build_vision_extractor",
            lambda settings: NullExtractor("测试用：没有任何识别通道"),
        )
        summary = self._upload_docx(client)
        response = client.post(f"/api/v1/documents/{summary['doc_id']}/images/recognize")
        assert response.status_code == 501
        assert response.json()["code"] == "VISION_UNAVAILABLE"

    def test_recognize_succeeds_with_channel(self, client, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.services.document_service.build_vision_extractor",
            lambda settings: FakeExtractor(),
        )
        summary = self._upload_docx(client)
        response = client.post(f"/api/v1/documents/{summary['doc_id']}/images/recognize")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["image_recognized"] == 1

        detail = client.get(f"/api/v1/documents/{summary['doc_id']}").json()["data"]
        assert detail["image_recognized"] == 1

    def test_health_exposes_vision_capabilities(self, client) -> None:
        data = client.get("/api/v1/health").json()["data"]
        assert "vision" in data
        assert data["vision"]["supported"]

    def test_delete_purges_image_files(self, client) -> None:
        summary = self._upload_docx(client)
        doc_id = summary["doc_id"]
        assert client.delete(f"/api/v1/documents/{doc_id}").status_code == 200
        assert client.get(f"/api/v1/documents/{doc_id}").status_code == 404
