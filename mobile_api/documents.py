"""PDF validation, page OCR, and document-block separation for mobile uploads."""

from __future__ import annotations

import io
import hashlib
import re
import threading
from collections import OrderedDict
from functools import lru_cache
from typing import Callable

import fitz
import onnxruntime
from PIL import Image, ImageOps, UnidentifiedImageError
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.errors import PdfReadError
from rapidocr_onnxruntime import RapidOCR

from document_extraction import extraer_datos_desde_texto
from document_rules import (
    clasificar_tipo_caso,
    clasificar_tipo_documento,
    normalizar_errores_ocr,
)


MAX_PDF_PAGES = 300
MAX_IMAGE_PIXELS = 25_000_000
OCR_RENDER_SCALE = 1.2
OCR_CACHE_MAX_PAGES = 4096
BLANK_PAGE_DARK_PIXEL_RATIO = 0.005
DOCUMENT_TYPES = {
    "Expediente completo",
    "Solicitud",
    "Consulta QX",
    "Documento de identidad",
    "Tarjeta de propiedad",
    "Certificado o soporte",
    "Resolución",
    "Requerimiento",
    "Oficio de citación",
    "Citación del recurso",
    "Notificación",
    "Notificación personal",
    "Notificación por aviso",
    "Notificación por publicación web",
    "Notificación del recurso",
    "Constancia de ejecutoria",
    "Recurso",
    "Resolución del recurso",
    "Remisión a registro",
    "Desistimiento",
    "Otro",
}
_OCR_CACHE: OrderedDict[tuple[str, int, float], str] = OrderedDict()
_OCR_CACHE_LOCK = threading.Lock()
_OCR_ENGINE_LOCK = threading.Lock()


def convertir_imagen_a_pdf(image_bytes: bytes) -> bytes:
    if not image_bytes:
        raise ValueError("La imagen está vacía.")

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image_format = image.format
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError(
                    f"La imagen supera el máximo de {MAX_IMAGE_PIXELS:,} píxeles."
                )
            image.verify()
        if image_format not in {"PNG", "JPEG"}:
            raise ValueError("Solo se aceptan imágenes PNG o JPG.")

        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
            oriented = ImageOps.exif_transpose(image)
            try:
                rgba = oriented.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                output = io.BytesIO()
                background.save(output, format="PDF", resolution=150.0)
                background.close()
                rgba.close()
                return output.getvalue()
            finally:
                if oriented is not image:
                    oriented.close()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
    ) as error:
        raise ValueError(f"No se pudo leer la imagen PNG o JPG: {error}") from error


def validar_pdf(pdf_bytes: bytes) -> tuple[bool, str]:
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        return False, "El archivo está vacío o no es un PDF válido."
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes), strict=True)
        if reader.is_encrypted:
            return False, "El PDF está protegido y no se puede procesar."
        if not reader.pages:
            return False, "El PDF no contiene páginas."
        if len(reader.pages) > MAX_PDF_PAGES:
            return False, f"El PDF supera el máximo de {MAX_PDF_PAGES} páginas."
    except (OSError, PdfReadError, ValueError, TypeError) as error:
        raise ValueError(f"No se pudo abrir el PDF: {error}") from error
    return True, "OK"


def obtener_tamano_pdf(pdf_bytes: bytes | None) -> int:
    return len(pdf_bytes) if pdf_bytes else 0


@lru_cache(maxsize=1)
def _ocr_engine() -> RapidOCR:
    providers = onnxruntime.get_available_providers()
    configuration = {
        "use_cuda": "CUDAExecutionProvider" in providers,
        "use_dml": "DmlExecutionProvider" in providers,
    }
    try:
        return RapidOCR(**configuration)
    except (TypeError, RuntimeError, ValueError):
        if configuration["use_cuda"] or configuration["use_dml"]:
            return RapidOCR(use_cuda=False, use_dml=False)
        raise


def _pagina_en_blanco(pixmap: fitz.Pixmap) -> bool:
    samples = pixmap.samples
    if not samples:
        return True
    channels = pixmap.n
    total_pixels = len(samples) // channels
    stride = max(channels * 4, 1)
    dark_pixels = sum(
        1
        for offset in range(0, len(samples), stride)
        if min(samples[offset:offset + 3]) < 245
    )
    return total_pixels == 0 or (
        dark_pixels / max(total_pixels // 4, 1)
    ) < BLANK_PAGE_DARK_PIXEL_RATIO


def _ocr_page(
    ocr_engine: RapidOCR,
    pixmap: fitz.Pixmap,
    cache_key: tuple[str, int, float],
) -> str:
    with _OCR_CACHE_LOCK:
        cached = _OCR_CACHE.get(cache_key)
        if cached is not None:
            _OCR_CACHE.move_to_end(cache_key)
            return cached

    with _OCR_ENGINE_LOCK:
        with _OCR_CACHE_LOCK:
            cached = _OCR_CACHE.get(cache_key)
            if cached is not None:
                _OCR_CACHE.move_to_end(cache_key)
                return cached
        result, _ = ocr_engine(pixmap.tobytes("png"))
    if not result:
        text = ""
    else:
        text = " ".join(
            str(item[1]).strip()
            for item in result
            if len(item) > 1 and str(item[1]).strip()
        )
    with _OCR_CACHE_LOCK:
        _OCR_CACHE[cache_key] = text
        _OCR_CACHE.move_to_end(cache_key)
        while len(_OCR_CACHE) > OCR_CACHE_MAX_PAGES:
            _OCR_CACHE.popitem(last=False)
    return text


def _clasificar_caso_por_bloques(groups: list[dict]) -> str:
    documents = [
        (
            group["tipo_documento"],
            normalizar_errores_ocr(" ".join(group["texts"])).lower(),
        )
        for group in groups
    ]
    if any(
        re.search(r"\b(?:resoluci[oó]n|acto administrativo|resuelve)\b", text)
        and re.search(r"desistim|desiste", text)
        for _, text in documents
    ):
        return "Desistimiento"
    if any(
        kind
        in {
            "Recurso",
            "Resolución del recurso",
            "Citación del recurso",
            "Notificación del recurso",
        }
        for kind, _ in documents
    ):
        return "Con recurso"

    classification_text = re.sub(
        r"desistim\w*|desiste",
        "",
        "\n".join(text for _, text in documents),
    )
    text_classification = clasificar_tipo_caso(classification_text)
    if text_classification == "Con recurso":
        return text_classification
    if any(
        kind in {"Constancia de ejecutoria", "Resolución"}
        for kind, _ in documents
    ):
        return "Sin recurso"
    if text_classification == "Sin recurso":
        return text_classification
    return ""


def separar_pdf(
    pdf_bytes: bytes,
    tipo_fallback: str = "Otro",
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict:
    """Classify each page from embedded text/OCR and return contiguous PDF blocks."""
    valid, detail = validar_pdf(pdf_bytes)
    if not valid:
        raise ValueError(detail)
    fallback = tipo_fallback if tipo_fallback in DOCUMENT_TYPES else "Otro"
    reader = PdfReader(io.BytesIO(pdf_bytes), strict=True)
    visual_document = fitz.open(stream=pdf_bytes, filetype="pdf")
    groups: list[dict] = []
    current_type = "Otro" if fallback == "Expediente completo" else fallback
    ocr_pages = 0
    pdf_digest = hashlib.sha256(pdf_bytes).hexdigest()
    all_texts = []
    try:
        for page_index, source_page in enumerate(reader.pages):
            text = " ".join((source_page.extract_text() or "").split())
            page = visual_document.load_page(page_index)
            preview = page.get_pixmap(
                matrix=fitz.Matrix(0.35, 0.35),
                alpha=False,
            )
            if not _pagina_en_blanco(preview):
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(OCR_RENDER_SCALE, OCR_RENDER_SCALE),
                    alpha=False,
                )
                ocr_text = _ocr_page(
                    _ocr_engine(),
                    pixmap,
                    (pdf_digest, page_index, OCR_RENDER_SCALE),
                )
                text = " ".join(part for part in (text, ocr_text) if part)
                ocr_pages += 1
            all_texts.append(text)

            detected = clasificar_tipo_documento(text, "")
            if detected and detected != "Expediente completo":
                current_type = detected
            elif current_type == "Expediente completo":
                current_type = "Otro"

            if not groups or groups[-1]["tipo_documento"] != current_type:
                groups.append(
                    {
                        "tipo_documento": current_type,
                        "pages": [],
                        "source_pages": [],
                        "texts": [],
                    }
                )
            groups[-1]["pages"].append(source_page)
            groups[-1]["source_pages"].append(page_index + 1)
            groups[-1]["texts"].append(text)
            if progress_callback:
                progress_callback(page_index + 1, len(reader.pages))
    finally:
        visual_document.close()

    blocks = []
    for group in groups:
        writer = PdfWriter()
        for page in group["pages"]:
            writer.add_page(page)
        output = io.BytesIO()
        writer.write(output)
        blocks.append(
            {
                "tipo_documento": group["tipo_documento"],
                "contenido": output.getvalue(),
                "paginas": group["source_pages"],
            }
        )
    classification = _clasificar_caso_por_bloques(groups)
    return {
        "bloques": blocks,
        "paginas": len(reader.pages),
        "paginas_ocr": ocr_pages,
        "clasificacion_final": classification or "",
        "datos_extraidos": extraer_datos_desde_texto(" ".join(all_texts)),
    }
