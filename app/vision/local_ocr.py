"""本地 OCR：不联网、不依赖 API Key 的图片取字通道。

按可用性自动挑引擎（顺序即优先级）：

  1. ``rapidocr-onnxruntime`` —— 纯 pip 安装、CPU 推理、自带中英文模型，
     私有化场景最省事，因此列为默认；
  2. ``pytesseract`` —— 需要系统另装 tesseract 与中文语言包；
  3. ``tesseract`` 命令行 —— 机器上装了 tesseract 但没装 python 包时仍可用。

一个都没有时**不报错、不静默**：``available`` 为 False，调用方拿到的是带原因的
结果，界面据此提示「装哪个包 / 配哪个变量」。
"""
from __future__ import annotations

import asyncio
import io
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.core.utils import Timer
from app.vision.base import KIND_TEXT, ImageTextExtractor, ImageTextResult

logger = get_logger(__name__)

DEFAULT_LANGUAGES = "chi_sim+eng"

#: RapidOCR 的引擎构造（加载 ONNX 模型）有明显开销，进程内复用一份。
_rapidocr_engine = None


@dataclass(slots=True)
class BackendInfo:
    name: str
    label: str
    requires: str


RAPIDOCR = BackendInfo(
    "rapidocr", "RapidOCR（离线 ONNX）", "pip install rapidocr-onnxruntime"
)
PYTESSERACT = BackendInfo(
    "pytesseract",
    "pytesseract",
    "pip install pytesseract pillow，并安装 tesseract 本体与中文语言包",
)
TESSERACT_CLI = BackendInfo(
    "tesseract-cli", "tesseract 命令行", "安装 tesseract 并把 tesseract 加入 PATH"
)

BACKENDS: dict[str, BackendInfo] = {
    RAPIDOCR.name: RAPIDOCR,
    PYTESSERACT.name: PYTESSERACT,
    TESSERACT_CLI.name: TESSERACT_CLI,
}


def detect_backend() -> BackendInfo | None:
    """探测可用引擎；顺序即优先级。"""
    if rapidocr_importable():
        return RAPIDOCR
    if pytesseract_importable():
        return PYTESSERACT
    if shutil.which("tesseract"):
        return TESSERACT_CLI
    return None


def rapidocr_importable() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def pytesseract_importable() -> bool:
    """装了 pytesseract **且** tesseract 本体真的能找到，才算可用。

    pytesseract 的 ``tesseract_cmd`` 默认是裸名字 ``"tesseract"``，于是
    「这个字段非空」根本证明不了二进制存在 —— 只判断 import 成功的话，
    机器上装了 pytesseract 却没装 tesseract 时，能力清单会显示「本地 OCR 可用」，
    而每张图片实际都会识别失败。这正是本项目最忌讳的「假装可用」。
    """
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    try:
        import pytesseract as module

        command = str(getattr(module.pytesseract, "tesseract_cmd", "") or "").strip()
    except Exception:  # noqa: BLE001
        return False
    if not command:
        return False
    # 显式给了路径（绝对路径或含目录分隔符）就查文件；裸命令名查 PATH。
    if os.path.isabs(command) or "/" in command or "\\" in command:
        return Path(command).is_file()
    return shutil.which(command) is not None


class LocalOcrExtractor(ImageTextExtractor):
    name = "local-ocr"
    label = "本地 OCR"
    kind = KIND_TEXT

    def __init__(self, *, languages: str = DEFAULT_LANGUAGES, backend: str = "") -> None:
        self.languages = languages or DEFAULT_LANGUAGES
        self._forced = (backend or "").strip()

    # ------------------------------------------------------------------ #
    @property
    def backend(self) -> BackendInfo | None:
        if self._forced:
            return BACKENDS.get(self._forced)
        return detect_backend()

    @property
    def available(self) -> bool:
        return self.backend is not None

    @property
    def requires(self) -> str:
        return "安装本地 OCR 引擎：" + "；".join(
            f"{item.label} -> {item.requires}" for item in BACKENDS.values()
        )

    # ------------------------------------------------------------------ #
    async def extract(self, image: bytes, *, hint: str = "", filename: str = "") -> ImageTextResult:
        backend = self.backend
        if backend is None:
            return ImageTextResult(extractor=self.name, warnings=["本地 OCR 不可用：" + self.requires])
        with Timer() as timer:
            try:
                # OCR 是 CPU 密集的同步调用，放到线程池里跑，避免阻塞事件循环。
                text, confidence = await asyncio.to_thread(self._run_backend, backend, image)
            except Exception as exc:  # noqa: BLE001 - 第三方引擎异常类型不可控
                logger.warning("本地 OCR（%s）识别失败：%s", backend.name, exc)
                return ImageTextResult(
                    extractor=f"local-ocr:{backend.name}",
                    warnings=[f"本地 OCR（{backend.label}）识别失败：{exc}"],
                    elapsed_ms=timer.elapsed_ms,
                )
        warnings: list[str] = []
        if not text.strip():
            warnings.append(f"本地 OCR（{backend.label}）未从图片中识别出文字。")
        elif confidence is not None and confidence < 0.6:
            warnings.append(
                f"本地 OCR 平均置信度偏低（{confidence:.2f}），识别结果可能有误，建议人工复核。"
            )
        return ImageTextResult(
            text=text,
            extractor=f"local-ocr:{backend.name}",
            kind=KIND_TEXT,
            confidence=confidence,
            warnings=warnings,
            elapsed_ms=timer.elapsed_ms,
        )

    def _run_backend(self, backend: BackendInfo, image: bytes) -> tuple[str, float | None]:
        if backend is RAPIDOCR:
            return self._run_rapidocr(image)
        if backend is PYTESSERACT:
            return self._run_pytesseract(image)
        return self._run_tesseract_cli(image)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _run_rapidocr(image: bytes) -> tuple[str, float | None]:
        global _rapidocr_engine
        if _rapidocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-not-found]

            _rapidocr_engine = RapidOCR()
        result, _ = _rapidocr_engine(image)
        if not result:
            return "", None
        lines: list[str] = []
        scores: list[float] = []
        for item in result:
            # RapidOCR 每条结果为 [box, text, score]。
            text = str(item[1]) if len(item) > 1 else ""
            if text.strip():
                lines.append(text.strip())
            if len(item) > 2:
                try:
                    scores.append(float(item[2]))
                except (TypeError, ValueError):
                    continue
        average = round(sum(scores) / len(scores), 4) if scores else None
        return "\n".join(lines), average

    def _run_pytesseract(self, image: bytes) -> tuple[str, float | None]:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]

        with Image.open(io.BytesIO(image)) as handle:
            text = pytesseract.image_to_string(handle, lang=self.languages)
        return text.strip(), None

    def _run_tesseract_cli(self, image: bytes) -> tuple[str, float | None]:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(image)
            path = Path(handle.name)
        try:
            completed = subprocess.run(
                ["tesseract", str(path), "stdout", "-l", self.languages],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or "tesseract 退出码非 0").strip()[:200])
            return (completed.stdout or "").strip(), None
        finally:
            path.unlink(missing_ok=True)


__all__ = [
    "BACKENDS",
    "DEFAULT_LANGUAGES",
    "PYTESSERACT",
    "RAPIDOCR",
    "TESSERACT_CLI",
    "BackendInfo",
    "LocalOcrExtractor",
    "detect_backend",
    "pytesseract_importable",
    "rapidocr_importable",
]
