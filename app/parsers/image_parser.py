"""直接上传的图片解析器（png / jpg / webp / bmp / tif）。

它做的事情只有一件：把图片包成一个 :class:`ParsedAsset` 交给上层识别通道。
因此「识别不了」这件事不会在这里变成解析失败 —— 使用者至少还能看到文档入库、
图片留档与明确告警，而不是一个 422。
"""
from __future__ import annotations

from app.parsers.base import ASSET_UPLOAD, DocumentParser, ParsedAsset, ParsedDocument
from app.vision.imaging import extension_for, read_size, sniff_mime


class ImageParser(DocumentParser):
    name = "image"
    label = "图片解析器"
    extensions = ("png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff")

    def parse(self, data: bytes, *, filename: str = "") -> ParsedDocument:
        mime = sniff_mime(data)
        width, height = read_size(data)
        asset = ParsedAsset(
            index=1,
            data=data,
            mime=mime,
            extension=extension_for(mime),
            source=ASSET_UPLOAD,
            placeholder="[图片 1]",
            anchor=filename or "上传的图片",
            width=width,
            height=height,
        )
        warnings: list[str] = []
        if mime == "application/octet-stream":
            warnings.append(
                "这张图片的格式无法识别（既不是 png/jpeg，也不是 gif/bmp/tiff/webp），"
                "很可能不是图片文件或文件已损坏。"
            )
        return self._finalize(
            "",
            extension=self._extension(filename),
            metadata={"filename": filename, "image_mime": mime},
            warnings=warnings,
            assets=[asset],
        )

    @staticmethod
    def _extension(filename: str) -> str:
        if "." in filename:
            return filename.rsplit(".", 1)[1].lower()
        return "png"


__all__ = ["ImageParser"]
