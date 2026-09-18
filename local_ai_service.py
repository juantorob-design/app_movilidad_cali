"""Análisis documental local mediante Ollama.

El texto nunca sale del equipo: Ollama se consulta únicamente en localhost.
El servicio es opcional y el flujo OCR/reglas continúa funcionando si no está
instalado o si el modelo no está disponible.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests


OLLAMA_URL = os.environ.get("SISTEMA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("SISTEMA_OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = int(os.environ.get("SISTEMA_OLLAMA_TIMEOUT", "180"))
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"

SYSTEM_PROMPT = """Eres el analista documental local del Sistema de Desvinculaciones.
Analiza únicamente la evidencia recibida y no inventes datos. Respeta esta secuencia:
solicitud, consulta QX, resolución o requerimiento, citaciones, notificaciones,
recurso y sus actuaciones, constancia de ejecutoria y remisión a registro.
Los únicos desenlaces válidos son Con recurso, Sin recurso o Desistimiento.
Si falta evidencia, indícalo expresamente. Distingue Otro de los documentos
principales y conserva la trazabilidad de cada dato.

Devuelve exclusivamente JSON válido con estas claves:
{
  "radicado_padre": "",
  "placa": "",
  "fecha_solicitud": "YYYY-MM-DD",
  "fecha_notificacion": "YYYY-MM-DD",
  "tipo_caso": "Con recurso|Sin recurso|Desistimiento|Por confirmar",
  "solicitante": "",
  "empresa": "",
  "nit": "",
  "propietario": "",
  "cedula": "",
  "fecha_resolucion": "YYYY-MM-DD",
  "fecha_recurso": "YYYY-MM-DD",
  "resumen_ejecutivo": "string",
  "datos_identificados": [{"campo": "string", "valor": "string", "evidencia": "string"}],
  "trazabilidad_temporal": [{"fecha": "string", "hito": "string", "evidencia": "string"}],
  "analisis_fondo_decision": "string",
  "tipo_caso": "Con recurso|Sin recurso|Desistimiento|Por confirmar",
  "estado_carga": "Expediente completo|Complemento",
  "paginas_por_seccion": [{"tipo": "string", "paginas": [1, 2]}],
  "documentos_detectados": [{"tipo": "string", "paginas_o_evidencia": "string"}],
  "faltantes": ["string"]
}
"""

FORMULARIO_CAMPOS = (
    "radicado_padre",
    "placa",
    "fecha_solicitud",
    "fecha_notificacion",
    "tipo_caso",
    "solicitante",
    "empresa",
    "nit",
    "propietario",
    "cedula",
    "fecha_resolucion",
    "fecha_recurso",
)


def ollama_disponible() -> bool:
    """Comprueba el servicio local sin enviar contenido documental."""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return response.ok
    except requests.RequestException:
        return False


def _extraer_json(respuesta: str) -> dict[str, Any]:
    texto = str(respuesta or "").strip()
    if texto.startswith("```"):
        texto = texto.strip("`")
        if texto.startswith("json"):
            texto = texto[4:].lstrip()
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio < 0 or fin <= inicio:
        raise ValueError("La IA local no devolvió un objeto JSON.")
    resultado = json.loads(texto[inicio:fin + 1])
    if not isinstance(resultado, dict):
        raise ValueError("La respuesta de la IA local no tiene formato de objeto.")
    return resultado


def analizar_expediente_local(texto: str, *, modelo: str | None = None) -> dict[str, Any]:
    """Analiza OCR local con Ollama y devuelve un resultado estructurado."""
    contenido = str(texto or "").strip()
    if not contenido:
        raise ValueError("No hay texto OCR suficiente para analizar.")
    if not ollama_disponible():
        raise ConnectionError(
            "Ollama no está disponible en localhost. Instala Ollama y descarga "
            f"el modelo {modelo or OLLAMA_MODEL}."
        )

    prompt = (
        "Analiza el siguiente texto OCR por bloques documentales. Prioriza los "
        "campos administrativos y cita la evidencia textual breve.\n\n"
        f"TEXTO OCR:\n{contenido}"
    )
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": modelo or OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            },
            timeout=OLLAMA_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        return _extraer_json(payload.get("message", {}).get("content", ""))
    except requests.RequestException as error:
        raise ConnectionError(f"No fue posible consultar la IA local: {error}") from error
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"La IA local devolvió una respuesta inválida: {error}") from error


def analisis_a_markdown(resultado: dict[str, Any]) -> str:
    """Convierte la respuesta validada en el formato visible para el usuario."""
    datos = resultado.get("datos_identificados") or []
    fechas = resultado.get("trazabilidad_temporal") or []
    documentos = resultado.get("documentos_detectados") or []
    faltantes = resultado.get("faltantes") or []
    lineas = [
        "## Resumen Ejecutivo",
        str(resultado.get("resumen_ejecutivo") or "Sin resumen disponible."),
        "",
        "## Datos Identificados",
    ]
    lineas.extend(
        f"- **{item.get('campo', 'Campo')}:** {item.get('valor', '')} "
        f"_(evidencia: {item.get('evidencia', 'no indicada')})_"
        for item in datos if isinstance(item, dict)
    )
    lineas.extend(["", "## Trazabilidad Temporal"])
    lineas.extend(
        f"- **{item.get('fecha', 'Fecha no indicada')} — {item.get('hito', '')}:** "
        f"{item.get('evidencia', '')}"
        for item in fechas if isinstance(item, dict)
    )
    lineas.extend([
        "",
        "## Análisis de Fondo / Decisión",
        str(resultado.get("analisis_fondo_decision") or "Sin análisis disponible."),
        "",
        f"**Desenlace:** {resultado.get('tipo_caso') or 'Por confirmar'}",
        "",
        "## Documentos detectados",
    ])
    lineas.extend(
        f"- **{item.get('tipo', 'Otro')}:** {item.get('paginas_o_evidencia', '')}"
        for item in documentos if isinstance(item, dict)
    )
    if faltantes:
        lineas.extend(["", "## Faltantes", *[f"- {item}" for item in faltantes]])
    return "\n".join(lineas)


def campos_formulario_desde_ia(resultado: dict[str, Any]) -> dict[str, str]:
    """Extrae solo los campos del formulario con valores simples y trazables."""
    campos = {}
    for campo in FORMULARIO_CAMPOS:
        valor = resultado.get(campo)
        if isinstance(valor, (str, int, float)) and str(valor).strip():
            campos[campo] = str(valor).strip()
    return campos
