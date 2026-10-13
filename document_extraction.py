"""Shared text-based administrative field extraction for desktop and mobile."""

from __future__ import annotations

import re

from document_rules import normalizar_errores_ocr


def normalizar_texto_documento(texto):
    return " ".join(str(texto or "").replace("\xa0", " ").split())


def radicado_padre_valido(valor):
    texto = normalizar_texto_documento(valor).strip().upper()
    if not texto or texto in {"ICADOPADRE", "RADICADOPADRE", "RADICADO PADRE"}:
        return False
    return len(re.sub(r"\D", "", texto)) >= 8


def valor_ocr_sospechoso(valor):
    texto = normalizar_texto_documento(valor).lower()
    if not texto:
        return False
    patrones = (
        r"\bde\s*:\s*mi\s+preferencia\b",
        r"\b(?:identificacion|identificaci?n)\s+doc\b",
        r"\b(?:nombres?|apellidos?)\s*/?\s*(?:emp|pan)\b",
        r"\bobligaciones\b",
        r"\bseleccione\b|\bseleccionar\b",
    )
    return any(re.search(patron, texto) for patron in patrones)


def extraer_datos_desde_texto(texto):
    """Apply the same field rules used by the desktop program to OCR text."""
    texto = normalizar_errores_ocr(texto)
    if not texto:
        return {}
    patrones = {
        "radicado_padre": [
            r"\b(?:rad|radicado|radicaci[oó]n|orfeo)\s*(?:padre|principal)?\s*(?:no\.?)?\s*[:.#\-]?\s*([A-Z0-9][A-Z0-9./\-]{7,})\b",
            r"\b(20\d{16})\b",
        ],
        "placa": [
            r"(?:placa|placas|matr[ií]cula|matricula|veh[ií]culo)\s*[:#\-]?\s*([A-Z]{3}\s*[-]?\s*\d{3})\b",
            r"\b([A-Z]{3}-?\d{3})\b",
        ],
        "fecha_solicitud": [
            r"(?:fecha\s*(?:de\s*)?(?:creaci[oó]n|radicaci[oó]n|solicitud|recibido))\s*[:#\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"\b(\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+20\d{2})\b",
            r"\b(\d{1,2}\s+(?:de\s+)?(?:ene(?:ro)?|feb(?:rero)?|mar(?:zo)?|"
            r"abr(?:il)?|may(?:o)?|jun(?:io)?|jul(?:io)?|ago(?:sto)?|"
            r"sep(?:tiembre)?|set(?:iembre)?|oct(?:ubre)?|nov(?:iembre)?|"
            r"dic(?:iembre)?)\s+(?:de\s+)?20\d{2})\b",
            r"\b((?:0[1-9]|[12][0-9]|3[01])[-/](?:0[1-9]|1[012])[-/](?:20\d{2}))\b",
        ],
        "fecha_radicacion": [
            r"(?:fecha\s+de\s+)?radicaci[oó]n\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"(?:fecha\s+de\s+)?radicaci[oó]n\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}\s+(?:de\s+)?[A-Za-záéíóú]+(?:\s+de)?\s+20\d{2})",
        ],
        "fecha_recurso": [
            r"fecha\s+(?:de\s+)?recurso\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"fecha\s+(?:de\s+)?recurso\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}\s+(?:de\s+)?[A-Za-záéíóú]+(?:\s+de)?\s+20\d{2})",
        ],
        "fecha_resolucion": [
            r"(?:fecha\s+(?:de\s+)?resoluci[oó]n|resoluci[oó]n[^.]{0,80}?\b(?:del|de fecha))\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"fecha\s+(?:de\s+)?resoluci[oó]n\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}\s+(?:de\s+)?[A-Za-záéíóú]+(?:\s+de)?\s+20\d{2})",
        ],
        "fecha_notificacion": [
            r"(?:fecha\s+(?:de\s+)?notificaci[oó]n|notificaci[oó]n[^.]{0,80}?\b(?:del|de fecha))\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"fecha\s+(?:de\s+)?notificaci[oó]n\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}\s+(?:de\s+)?[A-Za-záéíóú]+(?:\s+de)?\s+20\d{2})",
        ],
        "fecha_ejecutoria": [
            r"fecha\s+(?:de\s+)?(?:constancia\s+de\s+)?ejecutoria\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"fecha\s+(?:de\s+)?(?:constancia\s+de\s+)?ejecutoria\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}\s+(?:de\s+)?[A-Za-záéíóú]+(?:\s+de)?\s+20\d{2})",
        ],
        "correo": [
            r"\b([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})\b",
        ],
        "nit": [
            r"\b(?:NIT|NIT\.?|n\.i\.t\.?)\s*[:#.\-]?\s*([0-9][0-9.\s]{5,14}(?:\s*[\-–]\s*[0-9])?)\b",
        ],
        "cedula": [
            r"\b(?:c[eé]dula|c\.c\.|identificaci[oó]n)\s*[:#\-]?\s*([0-9][0-9.\s]{5,14})\b",
        ],
        "empresa": [
            r"\bempresa\s*[:#\-]?\s*([^|]{3,100}?)(?=\s+(?:NIT|propietario|placa|radicado|resoluci[oó]n|correo)\b|$)",
            r"\bempresa\s+de\s+transportes?\s+([^|]{3,100}?)(?=\s+(?:NIT|contrato|resoluci[oó]n|placa)\b|$)",
            r"\b(EMPRESA\s+DE\s+TRANSPORTES?\s+[A-Z0-9ÁÉÍÓÚÑ .,&-]{4,100}?)(?=\s+(?:NIT|RESOLUCI|CONTRATO|PLACA)\b|$)",
        ],
        "propietario": [
            r"\bpropietario(?:\s+del\s+veh[ií]culo)?\s*[:#\-]?\s*([^|]{3,100}?)(?=\s+(?:c[eé]dula|CC|placa|direcci[oó]n|resoluci[oó]n|correo|NIT)\b|$)",
            r"\b(?:representante\s+legal|gerente)\s*[:#\-]?\s*([A-ZÁÉÍÓÚÑ][^|]{3,100}?)(?=\s+(?:identificado|con\s+c[eé]dula|NIT|solicito)\b)",
        ],
        "direccion_empresa": [
            r"\bdirecci[oó]n\s+(?:de\s+)?empresa\s*[:#\-]?\s*([^|]{5,150}?)(?=\s+(?:direcci[oó]n|propietario|NIT|radicado|nueva\s+empresa)\b|$)",
        ],
        "direccion_propietario": [
            r"\bdirecci[oó]n\s+(?:del\s+)?propietario\s*[:#\-]?\s*([^|]{5,150}?)(?=\s+(?:propietario|c[eé]dula|placa|radicado|nueva\s+empresa)\b|$)",
        ],
        "nueva_empresa": [
            r"\bnueva\s+empresa\s*[:#\-]?\s*([^|]{3,120}?)(?=\s+(?:NIT|radicado|placa|fecha)\b|$)",
        ],
        "tipo_notificacion": [
            r"\bnotificaci[oó]n\s+(?:por\s+)?(personal|citación|citaci[oó]n|aviso|publicaci[oó]n|electrónica|electronica|correo)\b",
        ],
        "funcionario": [
            r"\bfuncionario\s+(?:que\s+)?desvincula\s*[:#\-]\s*([^|]{3,100}?)(?=\s+(?:fecha|observaci[oó]n|estado)\b|$)",
        ],
        "recurso": [
            r"\b(recurso(?:\s+de\s+(?:reposici[oó]n|apelaci[oó]n))?)\b",
        ],
        "resolucion": [
            r"\b(?:resoluci[oó]n|acto\s+administrativo)\s*(?:No\.?|N[°ºo]\.?)?\s*[:#\-]?\s*([A-Z0-9./\-]{4,40})\b",
        ],
    }
    meses = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
        "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
        "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
        "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
        "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11,
        "dic": 12,
    }
    datos = {}
    for campo, opciones in patrones.items():
        for patron in opciones:
            coincidencia = re.search(patron, texto, flags=re.IGNORECASE)
            if coincidencia:
                valor = coincidencia.group(1).strip(" .,:;")
                if campo == "radicado_padre":
                    valor = re.sub(r"\s+", "", valor).upper()
                if campo == "placa":
                    valor = re.sub(r"[\s-]", "", valor).upper()
                elif campo.startswith("fecha_"):
                    fecha_texto = valor.lower()
                    fecha_larga = re.fullmatch(
                        r"(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)\s+(?:de\s+)?(20\d{2})",
                        fecha_texto,
                    )
                    if fecha_larga:
                        dia, mes, anio = fecha_larga.groups()
                        valor = f"{anio}-{meses.get(mes, 0):02d}-{int(dia):02d}"
                    else:
                        partes = re.split(r"[/-]", valor)
                        if len(partes) == 3:
                            if len(partes[0]) == 4:
                                valor = "-".join(partes)
                            else:
                                dia, mes, anio = partes
                                if len(anio) == 2:
                                    anio = "20" + anio
                                valor = f"{anio}-{mes.zfill(2)}-{dia.zfill(2)}"
                elif campo == "nit":
                    valor = re.sub(r"\D", "", valor)
                elif campo == "cedula":
                    valor = re.sub(r"\D", "", valor)
                elif campo in {
                    "correo", "nit", "cedula", "empresa", "propietario",
                    "direccion_empresa", "direccion_propietario", "nueva_empresa",
                    "tipo_notificacion", "funcionario", "resolucion",
                }:
                    valor = re.sub(r"\s+", " ", valor).strip()
                datos[campo] = valor
                break
    if not datos.get("fecha_radicacion"):
        coincidencia_fecha_radicacion = re.search(
            r"radicaci[oó?]n[^0-9]{0,30}"
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            texto,
            flags=re.IGNORECASE,
        )
        if coincidencia_fecha_radicacion:
            dia_mes_anio = coincidencia_fecha_radicacion.group(1).split("/")
            if len(dia_mes_anio) == 1:
                dia_mes_anio = coincidencia_fecha_radicacion.group(1).split("-")
            if len(dia_mes_anio) == 3:
                if len(dia_mes_anio[0]) == 4:
                    datos["fecha_radicacion"] = "-".join(dia_mes_anio)
                else:
                    dia, mes, anio = dia_mes_anio
                    datos["fecha_radicacion"] = (
                        f"{'20' + anio if len(anio) == 2 else anio}-"
                        f"{mes.zfill(2)}-{dia.zfill(2)}"
                    )
    coincidencia_empresa = re.search(
        r"\bEMPRESA\s+DE\s+TRANSPORTES?\s+"
        r"[A-Z0-9ÁÉÍÓÚÑ .,&-]{4,100}",
        texto,
        flags=re.IGNORECASE,
    )
    if coincidencia_empresa:
        empresa_detectada = re.split(
            r"\s+(?:NIT|RESOLUCI\w*|NOTIFICACI\w*|CONTRATO|PLACA)\b",
            coincidencia_empresa.group(0),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" .,:;-")
        if len(empresa_detectada) >= len(str(datos.get("empresa", ""))):
            datos["empresa"] = empresa_detectada
    if datos.get("empresa"):
        datos["empresa"] = re.split(
            r"\s+(?:NIT|RESOLUCI\w*|NOTIFICACI\w*|CONTRATO|PLACA)\b",
            str(datos["empresa"]),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" .,:;-")
    radicado_extraido = str(datos.get("radicado_padre", "")).strip()
    if radicado_extraido and not radicado_padre_valido(radicado_extraido):
        datos.pop("radicado_padre", None)
        datos.pop("radicado_revision", None)
        radicado_extraido = ""
    if radicado_extraido and not re.fullmatch(r"20\d{16}", radicado_extraido):
        datos["radicado_revision"] = (
            f"Revisar radicado detectado: {radicado_extraido}. "
            "Confirma el número completo en el formulario."
        )
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", str(datos.get("resolucion", ""))):
        coincidencia_resolucion = re.search(
            r"\bresoluci[oó]n\s+(?:No\.?|N[°ºo]\.?)\s*[:#\-]?\s*([A-Z0-9-]{3,40})\b",
            texto,
            flags=re.IGNORECASE,
        )
        if coincidencia_resolucion:
            datos["resolucion"] = coincidencia_resolucion.group(1).strip()

    def fecha_en_contexto(etiquetas):
        etiqueta = "|".join(etiquetas)
        coincidencia = re.search(
            rf"(?:{etiqueta}).{{0,100}}?"
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            texto,
            flags=re.IGNORECASE,
        )
        if not coincidencia:
            return ""
        valor = coincidencia.group(1)
        partes = re.split(r"[/-]", valor)
        if len(partes) != 3:
            return ""
        if len(partes[0]) == 4:
            return "-".join(partes)
        dia, mes, anio = partes
        return f"{'20' + anio if len(anio) == 2 else anio}-{mes.zfill(2)}-{dia.zfill(2)}"

    for campo, etiquetas in {
        "fecha_resolucion": (r"resoluci[oó]n",),
        "fecha_notificacion": (r"notificaci[oó]n",),
        "fecha_ejecutoria": (r"ejecutoria",),
        "fecha_recurso": (r"recurso",),
    }.items():
        if not datos.get(campo):
            fecha_contexto = fecha_en_contexto(etiquetas)
            if fecha_contexto:
                datos[campo] = fecha_contexto
    if not datos.get("fecha_solicitud"):
        fecha_solicitud = re.search(
            r"\b(\d{1,2}[/-]\d{1,2}[/-]20\d{2}|20\d{2}[/-]\d{1,2}[/-]\d{1,2})\b",
            texto,
        )
        if fecha_solicitud:
            valor = fecha_solicitud.group(1)
            partes = re.split(r"[/-]", valor)
            if len(partes) == 3:
                if len(partes[0]) == 4:
                    datos["fecha_solicitud"] = "-".join(partes)
                else:
                    dia, mes, anio = partes
                    datos["fecha_solicitud"] = f"{anio}-{mes.zfill(2)}-{dia.zfill(2)}"
    for campo in (
        "empresa",
        "propietario",
        "direccion_empresa",
        "direccion_propietario",
        "nueva_empresa",
    ):
        if datos.get(campo) and valor_ocr_sospechoso(datos[campo]):
            datos.pop(campo, None)
    return datos
