"""Shared archive status calculations for desktop and mobile clients."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any


def _normalize_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    unaccented = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    return unaccented.upper().replace("_", " ").strip()


def _field(record: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_normalize_key(key): value for key, value in record.items()}
    for alias in aliases:
        value = normalized.get(_normalize_key(alias))
        if value is not None and str(value).strip():
            return value
    return ""


def _is_confirmed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _normalize_key(value) in {"SI", "TRUE", "1", "YES"}


def expediente_completo(record: Mapping[str, Any]) -> bool:
    """Use the desktop archive's required-field rule for every client."""
    return bool(
        _field(record, "radicado_padre", "RAD PADRE", "RADICADO PADRE")
        and _field(record, "fecha_solicitud", "FECHA", "FECHA SOLICITUD")
        and _is_confirmed(_field(record, "qx_verificado", "QX VERIFICADO"))
        and _field(record, "resolucion", "RESOLUCION", "RESOLUCION DESVINCULACION")
        and _field(record, "fecha_resolucion", "FECHA DESVINCULACION", "FECHA RESOLUCION")
        and _field(record, "tipo_notificacion", "TIPO NOTIFICACION")
        and _field(record, "fecha_notificacion", "FECHA NOTIFICACION")
        and _field(record, "fecha_ejecutoria", "FECHA EJECUTORIA")
        and _is_confirmed(_field(record, "remitido", "REMITIDO"))
        and _field(record, "fecha_remision_registro", "FECHA REMISION REGISTRO")
    )


def _document_count(record: Mapping[str, Any]) -> int:
    value = _field(
        record,
        "contenido_documental",
        "CONTENIDO DOCUMENTAL",
        "documentos_drive",
        "DOCUMENTOS DRIVE",
    )
    if isinstance(value, (list, tuple, set)):
        return sum(bool(str(item).strip()) for item in value)
    entries = [part.strip() for part in str(value or "").split("|")]
    if any(entries):
        return sum(bool(part) for part in entries)
    return int(bool(_field(record, "pdf_unificado", "PDF UNIFICADO")))


def resumir_estado_archivo(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Summarize unique parent cases using data stored in the operational sheet."""
    unique_records: dict[str, Mapping[str, Any]] = {}
    for record in records:
        radicado = str(
            _field(record, "radicado_padre", "RAD PADRE", "RADICADO PADRE") or ""
        ).strip()
        if radicado:
            unique_records[radicado.casefold()] = record

    values = list(unique_records.values())
    complete_count = sum(expediente_completo(record) for record in values)
    missing_count = sum(
        bool(
            _field(
                record,
                "documentos_faltantes_drive",
                "DOCUMENTOS FALTANTES",
                "documentos_faltantes",
            )
        )
        for record in values
    )
    document_count = sum(_document_count(record) for record in values)
    return {
        "total_expedientes": len(values),
        "completos": complete_count,
        "con_faltantes": missing_count,
        "documentos_registrados": document_count,
    }
