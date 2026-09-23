"""Análisis documental local mediante Ollama.

El contenido nunca sale del equipo: Ollama se consulta únicamente en localhost.
La visión local es la ruta principal para escaneos; el análisis textual
alimentado por OCR queda como respaldo explícito.
"""

from __future__ import annotations

import json
import os
import re
import base64
from typing import Any

import requests


OLLAMA_URL = os.environ.get("SISTEMA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("SISTEMA_OLLAMA_MODEL", "qwen2.5vl:3b")
OLLAMA_TEXT_MODEL = os.environ.get("SISTEMA_OLLAMA_TEXT_MODEL", "qwen2.5:7b")
OLLAMA_VISION_MODEL = os.environ.get("SISTEMA_OLLAMA_VISION_MODEL", OLLAMA_MODEL)
OLLAMA_TIMEOUT = int(os.environ.get("SISTEMA_OLLAMA_TIMEOUT", "600"))
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"

DEFAULT_OLLAMA_OPTIONS = {
    "temperature": 0.1,
    "num_predict": 1536,
    "repeat_penalty": 1.05,
    "seed": 42,
}

SYSTEM_PROMPT = """Eres el analista documental local del Sistema de Desvinculaciones.
Tu misión es clasificar el expediente por bloques y no por menciones generales.

Reglas estrictas:
1) Usa únicamente la evidencia textual del bloque. No inventes ni reutilices texto de interfaz, menús, nombres de campos o etiquetas.
2) La secuencia administrativa obligatoria es:
   Solicitud o petición
   Consulta QX
   Resolución o Requerimiento
   Oficios de citación
   Comunicación: notificación personal, por aviso, publicación web
   Recurso
   Resolución del recurso
   Citación del recurso
   Notificación del recurso
   Constancia de ejecutoria
   Remisión a registro
3) Solo puedes marcar un documento cuando exista encabezado, fórmula administrativa, acto o evidencia propia del bloque. Si aparece solo mencionado dentro de otro documento, NO lo marques como documento principal.
4) Los únicos desenlaces válidos son: Con recurso, Sin recurso, Desistimiento.
5) Si una etapa no aparece, indícalo en faltantes y no la conviertas en un documento falso.
6) Mantén la prioridad correcta de los tipos documentales y de la secuencia del flujo administrativo.
7) No mezcles texto de labels, OCR contaminado, tablas de interfaz, nombres de pestañas o mensajes automáticos con datos reales del expediente.

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
  "direccion_empresa": "",
  "direccion_propietario": "",
  "nueva_empresa": "",
  "funcionario": "",
  "correo": "",
  "resolucion": "",
  "tipo_notificacion": "",
  "recurso": "",
  "fecha_resolucion": "YYYY-MM-DD",
  "fecha_recurso": "YYYY-MM-DD",
  "fecha_ejecutoria": "YYYY-MM-DD",
  "fecha_remision_registro": "YYYY-MM-DD",
  "ubicacion": "",
  "resumen_ejecutivo": "string",
  "datos_identificados": [{"campo": "string", "valor": "string", "evidencia": "string"}],
  "trazabilidad_temporal": [{"fecha": "string", "hito": "string", "evidencia": "string"}],
  "analisis_fondo_decision": "string",
  "estado_carga": "Expediente completo|Complemento",
  "paginas_por_seccion": [{"tipo": "string", "paginas": [1, 2]}],
  "documentos_detectados": [{
    "tipo": "Solicitud|Consulta QX|Resolución|Requerimiento|Oficio de citación|Notificación personal|Notificación por aviso|Notificación por publicación web|Recurso|Resolución del recurso|Citación del recurso|Notificación del recurso|Constancia de ejecutoria|Remisión a registro|Desistimiento|Otro",
    "paginas": [1, 2],
    "paginas_o_evidencia": "string"
  }],
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
    "direccion_empresa",
    "direccion_propietario",
    "nueva_empresa",
    "funcionario",
    "correo",
    "resolucion",
    "tipo_notificacion",
    "recurso",
    "fecha_resolucion",
    "fecha_recurso",
    "fecha_ejecutoria",
    "fecha_remision_registro",
    "ubicacion",
)


def _validar_resultado_ia(resultado: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(resultado, dict):
        raise ValueError("La IA local no devolvió un objeto JSON.")
    for clave in ("documentos_detectados", "paginas_por_seccion", "faltantes"):
        valor = resultado.get(clave)
        if valor is not None and not isinstance(valor, list):
            raise ValueError(f"La IA local devolvió `{clave}` con formato inválido.")
    return resultado


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
    if inicio < 0:
        raise ValueError("La IA local no devolvió un objeto JSON.")
    for fin in range(len(texto) - 1, inicio, -1):
        if texto[fin] != "}":
            continue
        try:
            resultado = json.loads(texto[inicio:fin + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(resultado, dict):
            return resultado
    raise ValueError("La IA local devolvió una respuesta JSON inválida o truncada.")


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
        "Analiza el siguiente texto OCR por bloques documentales, no como un único expediente. "
        "Haz primero una lectura dirigida al flujo administrativo obligatorio: "
        "solicitud/petición, consulta QX, resolución o requerimiento, citación, notificación, "
        "recurso, resolución del recurso, citación del recurso, notificación del recurso, "
        "constancia de ejecutoria y remisión a registro. "
        "Identifica radicado padre, placa, fechas, empresa, NIT, propietario, cédula y el desenlace. "
        "No marques un documento solo porque aparezca citado dentro de otro bloque. Requiere encabezado, "
        "acto administrativo o evidencia propia del documento. Ignora etiquetas de interfaz, nombres de campos, "
        "menús, texto de herramientas y residuos OCR tipo 'de: mi preferencia', 'Identificación Doc', 'Nombres ...', 'obligaciones'. "
        "Si no hay evidencia suficiente, deja el valor vacío y añade el nombre del documento ausente a faltantes. "
        "Usa la secuencia administrativa como prioridad; la clasificación no debe confundirse con un texto general del expediente.\n\n"
        "Formato esperado: JSON válido con los campos del esquema, incluyendo `paginas_por_seccion` y `documentos_detectados` con `paginas` y `paginas_o_evidencia`.\n\n"
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
                "options": DEFAULT_OLLAMA_OPTIONS.copy(),
            },
            timeout=OLLAMA_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        return _validar_resultado_ia(
            _extraer_json(payload.get("message", {}).get("content", ""))
        )
    except requests.RequestException as error:
        raise ConnectionError(f"No fue posible consultar la IA local: {error}") from error
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"La IA local devolvió una respuesta inválida: {error}") from error


def analizar_paginas_local(
    paginas: list[tuple[int, bytes]],
    *,
    modelo: str | None = None,
) -> dict[str, Any]:
    """Analiza páginas renderizadas con un modelo Ollama compatible con visión.

    Cada tupla conserva el número de página para que la IA deba justificar la
    clasificación y el formulario con evidencia verificable.
    """
    if not paginas:
        raise ValueError("No hay páginas renderizadas para analizar.")
    imagenes = []
    referencias = []
    for numero, contenido in paginas:
        if not isinstance(numero, int) or numero < 1 or not contenido:
            raise ValueError("Cada página visual debe tener número y contenido.")
        imagenes.append(base64.b64encode(contenido).decode("ascii"))
        referencias.append(str(numero))
    modelo_vision = modelo or OLLAMA_VISION_MODEL
    if not ollama_disponible():
        raise ConnectionError("Ollama no está disponible en localhost.")
    prompt = (
        "Analiza visualmente cada página adjunta de forma independiente. "
        "Las páginas están numeradas en el mismo orden de `PÁGINA` indicado en el mensaje. "
        "No clasifiques una etapa porque otra página la mencione: exige encabezado, firma, "
        "fórmula administrativa o evidencia propia. Devuelve únicamente el JSON del esquema "
        "del sistema. En `documentos_detectados` y `paginas_por_seccion` incluye siempre "
        "las páginas que sustentan cada hallazgo. Si una página no es legible, deja el campo "
        "vacío y añade una observación en `faltantes`. No uses etiquetas de interfaz como "
        "evidencia documental."
    )
    mensajes = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
            + "\nLa fuente prioritaria son las imágenes; el texto debe salir de la página visible.",
        },
        {
            "role": "user",
            "content": prompt
            + "\n\n"
            + "\n".join(f"PÁGINA {numero}" for numero in referencias),
            "images": imagenes,
        },
    ]
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": modelo_vision,
                "messages": mensajes,
                "stream": False,
                "format": "json",
                "options": DEFAULT_OLLAMA_OPTIONS.copy(),
            },
            timeout=OLLAMA_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        return _validar_resultado_ia(
            _extraer_json(payload.get("message", {}).get("content", ""))
        )
    except requests.RequestException as error:
        raise ConnectionError(
            f"No fue posible consultar la visión local de Ollama: {error}"
        ) from error
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"La visión local devolvió una respuesta inválida: {error}"
        ) from error


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


def _valor_ia_sospechoso(valor: Any) -> bool:
    """Elimina texto contaminado que suele aparecer por OCR o por etiquetas de interfaz."""
    texto = str(valor or "").strip().lower()
    if not texto:
        return False
    patrones = (
        r"de\s*:\s*mi\s+preferencia",
        r"identificaci[oó]n\s+doc",
        r"nombres?\s*(?:emp|pan|/|\|)?",
        r"obligaciones",
        r"preferencia",
        r"seleccione",
        r"guardar y sincronizar",
        r"documentos esperados",
    )
    return any(re.search(p, texto) for p in patrones)


def campos_formulario_desde_ia(resultado: dict[str, Any]) -> dict[str, str]:
    """Extrae solo los campos del formulario con valores simples, reales y no contaminados."""
    campos = {}
    for campo in FORMULARIO_CAMPOS:
        valor = resultado.get(campo)
        if not isinstance(valor, (str, int, float)):
            continue
        texto = str(valor).strip()
        if not texto:
            continue
        if campo in {"empresa", "propietario", "direccion_empresa", "direccion_propietario", "nueva_empresa"} and _valor_ia_sospechoso(texto):
            continue
        if campo in {"nit", "cedula", "radicado_padre"}:
            texto_limpio = re.sub(r"[^0-9A-Za-z]", "", texto)
            if len(texto_limpio) < 4:
                continue
            if campo == "radicado_padre" and (
                texto.upper() in {"ICADOPADRE", "RADICADOPADRE", "RADICADO PADRE"}
                or len(re.sub(r"\D", "", texto)) < 8
            ):
                continue
        campos[campo] = texto
    return campos
