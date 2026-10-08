"""下载响应构造：导出与原文下载共用，避免中文文件名在浏览器里变成乱码。"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import Response


def build_download_response(content: bytes, filename: str, media_type: str) -> Response:
    """构造带中文文件名的下载响应（RFC 5987 filename*）。

    同时回一个 ``X-Export-Filename`` 头，前端在拿不到
    ``Content-Disposition`` 时也能还原出正确文件名。
    """
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "X-Export-Filename": quote(filename),
        },
    )
