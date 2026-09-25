import re
import datetime


def normalizar_texto_documento(texto):
    return " ".join(str(texto or "").replace("\xa0", " ").split())


def normalizar_errores_ocr(texto):
    """Corrige errores frecuentes del OCR antes de aplicar reglas documentales."""
    texto = normalizar_texto_documento(texto)
    texto = texto.replace("\ufffd", "o").replace("?", "o")
    reemplazos = (
        (r"\bempr[_\s]*a\b", "empresa"),
        (r"notificaci.n", "notificación"),
        (r"resoluci.n", "resolución"),
        (r"radicaci.n", "radicación"),
        (r"matr.cula", "matrícula"),
        (r"c.dula", "cédula"),
        (r"direcci.n", "dirección"),
        (r"\bveh[ií]cul[o0]\b", "vehículo"),
        (r"resoluci[oó6]n", "resolución"),
        (r"notificaci[oó6]n", "notificación"),
        (r"ejecutori[aá6]|ejecutor[ií]a", "ejecutoria"),
        (r"radicad[oó6]\s*no\b|radicadono\b", "radicado no"),
        (r"direcci[oó6]n", "dirección"),
        (r"matr[ií1]cula", "matrícula"),
        (r"c[eé3]dula", "cédula"),
    )
    for patron, reemplazo in reemplazos:
        texto = re.sub(patron, reemplazo, texto, flags=re.IGNORECASE)
    return texto


def componentes_ubicacion(ubicacion):
    """Convierte la ubicación administrativa en niveles físicos del almacenamiento."""
    texto = str(ubicacion or "").strip()
    if not texto:
        return "", "", ""
    texto = texto.replace("/", " ").replace("|", " ")
    coincidencias = re.findall(
        r"(caja|folder|carpeta)\s*[-:_ ]*\s*([A-Za-z0-9]+)",
        texto,
        flags=re.IGNORECASE,
    )
    valores = {"caja": "", "folder": "", "carpeta": ""}
    for clave, valor in coincidencias:
        nombre_clave = clave.lower()
        if nombre_clave in valores and not valores[nombre_clave]:
            valores[nombre_clave] = valor.strip()

    if sum(bool(v) for v in valores.values()) == 0:
        texto = texto.replace(" ", "-")
        partes = [p for p in texto.split("-") if p]
        if len(partes) >= 3:
            valores["caja"] = partes[0]
            valores["folder"] = partes[1]
            valores["carpeta"] = partes[2]

    return (
        f"CAJA-{valores['caja']}" if valores["caja"] else "",
        f"FOLDER-{valores['folder']}" if valores["folder"] else "",
        f"CARPETA-{valores['carpeta']}" if valores["carpeta"] else "",
    )


def _normalizar_parte_ubicacion(valor, prefijo):
    texto = str(valor or "").strip()
    if not texto:
        return ""
    texto = texto.replace("/", " ").replace("|", " ")
    texto = re.sub(rf"^{re.escape(prefijo)}\s*[-_: ]*", "", texto, flags=re.IGNORECASE)
    texto = texto.strip("-_/ ")
    return f"{prefijo}-{texto}" if texto else ""


def _token_nombre_documento(valor):
    texto = str(valor or "").strip()
    if not texto:
        return ""
    texto = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚáéíóúÑñÜü]+", "-", texto)
    texto = re.sub(r"-+", "-", texto).strip("-")
    return texto


def fecha_para_nombre_carpeta(fecha):
    try:
        return datetime.date.fromisoformat(str(fecha or "").strip()).isoformat()
    except (TypeError, ValueError):
        return "FECHA_PENDIENTE"


def nombre_carpeta_expediente(radicado, placa, fecha, ubicacion):
    fecha_formateada = fecha_para_nombre_carpeta(fecha)
    caja, folder, carpeta = componentes_ubicacion(ubicacion)
    partes = [radicado, placa, fecha_formateada]
    for token in (caja, folder, carpeta):
        if token:
            partes.append(token)
    nombre = "_".join(
        token for token in (_token_nombre_documento(parte) for parte in partes)
        if token
    )
    return nombre or "RADICADO_PENDIENTE"


def nombre_pdf_expediente(
    radicado,
    placa,
    fecha,
    tipo_caso=None,
    caja="",
    folder="",
    carpeta="",
    extension=".pdf",
):
    fecha_formateada = fecha_para_nombre_carpeta(fecha)
    partes = [
        _token_nombre_documento(radicado),
        _token_nombre_documento(placa),
        fecha_formateada,
    ]
    for valor, prefijo in ((caja, "CAJA"), (folder, "FOLDER"), (carpeta, "CARPETA")):
        parte = _normalizar_parte_ubicacion(valor, prefijo)
        if parte:
            partes.append(parte)
    nombre = "_".join(token for token in partes if token)
    return f"{nombre or 'EXPEDIENTE'}{extension.lower()}"


def clasificar_tipo_caso(texto="", nombre=""):
    evidencia = normalizar_errores_ocr(f"{nombre} {texto}").lower()
    if re.search(r"desistim|desestimiento|desistimiento|desiste", evidencia):
        return "Desistimiento"
    if re.search(
        r"\bsin\s+recurso\b|no\s+interpuso\s+(?:un\s+)?recurso\b|"
        r"no\s+se\s+interpuso\s+(?:un\s+)?recurso\b|"
        r"no\s+present[oó]\s+(?:el\s+|un\s+)?recurso\b|"
        r"sin\s+interponer\s+(?:el\s+)?recurso|"
        r"\bno\s+se\s+present[oó]\s+recurso\b|"
        r"\bconstancia\s+de\s+ejecutoria\b",
        evidencia,
    ):
        return "Sin recurso"
    if re.search(
        r"\bcon\s+recurso\b|\brecurso\s+de\s+reposici[oó]n\b|"
        r"\bpresent[oó]\s+(?:un\s+)?recurso\b|\binterpuso\s+(?:un\s+)?recurso\b|"
        r"\bse\s+resuelve\s+el\s+recurso\b|\bresoluci[oó]n\s+del\s+recurso\b",
        evidencia,
    ):
        return "Con recurso"
    return None


def normalizar_tipo_documental(valor):
    texto = normalizar_errores_ocr(valor).lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    if not texto:
        return ""
    if re.search(r"desistim|desiste", texto):
        return "Desistimiento"
    if re.search(r"consulta.*(?:qx|propiedad)|verificaci[oó]n.*(?:qx|propiedad)|\bqx\b", texto):
        return "Consulta QX"
    if re.search(r"resoluci[oó]n.*recurso|recurso.*resuelto", texto):
        return "Resolución del recurso"
    if re.search(r"citaci[oó]n.*recurso", texto):
        return "Citación del recurso"
    if re.search(r"notificaci[oó]n.*recurso", texto):
        return "Notificación del recurso"
    if re.search(r"remisi[oó]n.*registro|registro automotor|remitir.*registro", texto):
        return "Remisión a registro"
    if re.search(r"constancia.*ejecutoria|constancia.*firmeza|\bejecutoria\b|\bfirmeza\b", texto):
        return "Constancia de ejecutoria"
    if re.search(r"notificaci[oó]n.*personal|personalmente notificado", texto):
        return "Notificación personal"
    if re.search(r"notificaci[oó]n.*aviso|aviso de notificaci[oó]n", texto):
        return "Notificación por aviso"
    if re.search(r"notificaci[oó]n.*(?:publicaci[oó]n|web)|publicaci[oó]n.*web|edicto", texto):
        return "Notificación por publicación web"
    if re.search(r"\bnotificaci[oó]n\b|\bnotificacion\b", texto):
        return "Notificación"
    if re.search(r"oficio.*citaci[oó]n|citaci[oó]n.*(?:empresa|propietario)|citado", texto):
        return "Oficio de citación"
    if re.search(r"requerimient|requerido para|requerir", texto):
        return "Requerimiento"
    if re.search(r"\bresoluci[oó]n\b|acto administrativo|resuelve", texto):
        return "Resolución"
    if re.search(r"\brecurso\b|interpone\s+recurso|recurre|apelaci[oó]n", texto):
        return "Recurso"
    if re.search(r"\bpetici[oó]n\b|\bpeticion\b|\bsolicitud\b|\bsolicito\b", texto):
        return "Solicitud"
    return "Otro"


def clasificar_tipo_documento(texto, tipo_fallback):
    evidencia = normalizar_errores_ocr(texto).lower()
    if re.search(r"\bdesistim\w*\b|\bdeclara(?:r)?\s+el\s+desistimiento\b", evidencia):
        return "Desistimiento"
    puntuaciones = {
        "Desistimiento": [
            (9, r"\bdesistimiento\b|declara(?:r)?\s+el\s+desistimiento"),
            (3, r"\bdesistim\w*"),
        ],
        "Resolución del recurso": [(14, r"resoluci[oó]n\s+del\s+recurso|resolucion\s+del\s+recurso|recurso\s+resuelto")],
        "Citación del recurso": [(14, r"citaci[oó]n\s+del\s+recurso|citacion\s+del\s+recurso")],
        "Notificación del recurso": [(14, r"notificaci[oó]n\s+(?:del|de la)\s+recurso|notificacion\s+(?:del|de la)\s+recurso")],
        "Resolución": [(10, r"\bresoluci[oó]n\b|\bresolucion\b\s*(?:no|n[°ºo])?\s*[:#\-.]?\s*\w+"), (9, r"\bpor\s+la\s+cual\b.*\bdesvincul"), (3, r"\bresoluci[oó]n\b|\bresolucion\b|acto\s+administrativo|resuelve")],
        "Requerimiento": [(8, r"\brequerimient[oó]\b|\brequerimiento\b|requerido\s+para|requerir")],
        "Notificación personal": [(12, r"notificaci[oó]n\s+personal|notificacion\s+personal|personalmente\s+notificado")],
        "Notificación por aviso": [(10, r"notificaci[oó]n\s+por\s+aviso|notificacion\s+por\s+aviso|aviso\s+de\s+notificaci")],
        "Notificación por publicación web": [(10, r"notificaci[oó]n\s+por\s+publicaci[oó]n\s+web|notificacion\s+por\s+publicacion\s+web|publicaci[oó]n\s+web")],
        "Oficio de citación": [(8, r"oficio\s+de\s+citaci[oó]n|citacion\s+de\s+la\s+empresa|citacion\s+al\s+propietario|oficio\s+de\s+citado")],
        "Constancia de ejecutoria": [(10, r"constancia\s+de\s+ejecutoria"), (7, r"\bejecutoria\b|\bfirmeza\b|\bconstancia\b")],
        "Remisión a registro": [(12, r"remisi[oó]n\s+(?:a|al)\s+registro|remision\s+(?:a|al)\s+registro"), (8, r"registro\s+automotor|remitir\s+al\s+registro")],
        "Recurso": [(10, r"recurso\s+de\s+(?:reposici[oó]n|apelaci[oó]n)"), (8, r"interpuso\s+(?:un\s+)?recurso|present[oó]\s+(?:un\s+)?recurso"), (3, r"\brecurso\b|impugn")],
        "Consulta QX": [(12, r"consulta\s+de\s+verificaci[oó]n\s+de\s+propiedad|consulta\s+de\s+propiedad|verificaci[oó]n\s+de\s+propiedad|consulta\s+qx|verificaci[oó]n\s+qx")],
        "Solicitud": [(10, r"derecho\s+de\s+petici[oó]n|derecho\s+de\s+peticion|solicitud\s+de\s+desvinculaci[oó]n"), (8, r"\bsolicito\b.*\bdesvincul"), (3, r"\bsolicitud\b|\bpetici[oó]n\b|\bpeticion\b")],
    }
    mejor_tipo = None
    mejor_puntaje = 0
    for tipo, reglas in puntuaciones.items():
        puntaje = sum(
            puntos for puntos, patron in reglas
            if re.search(patron, evidencia, flags=re.IGNORECASE | re.DOTALL)
        )
        if puntaje > mejor_puntaje:
            mejor_tipo = tipo
            mejor_puntaje = puntaje
    return mejor_tipo or tipo_fallback


def tipos_documentales_detectados(texto, tipo_fallback):
    evidencia = normalizar_errores_ocr(texto).lower()
    reglas = [
        ("Desistimiento", r"desistim|desiste"),
        ("Recurso", r"\brecurso\b|reposici[oó]n|reposicion|apelaci[oó]n|apelacion|impugn|interpone\s+recurso|recurre"),
        ("Resolución del recurso", r"resoluci[oó]n\s+del\s+recurso|resolucion\s+del\s+recurso|recurso\s+resuelto"),
        ("Citación del recurso", r"citaci[oó]n\s+(?:del|de la)\s+recurso|citacion\s+(?:del|de la)\s+recurso"),
        ("Notificación del recurso", r"notificaci[oó]n\s+(?:del|de la)\s+recurso|notificacion\s+(?:del|de la)\s+recurso"),
        ("Resolución", r"\bresoluci[oó]n\b|\bresolucion\b|acto\s+administrativo|resuelve"),
        ("Requerimiento", r"requerimient[oó]|requerimiento"),
        ("Oficio de citación", r"oficio\s+de\s+citaci[oó]n|citaci[oó]n\s+al\s+propietario|citaci[oó]n\s+de\s+la\s+empresa|citacion\s+al\s+propietario"),
        ("Notificación personal", r"notificaci[oó]n\s+personal|notificacion\s+personal|personalmente\s+notificado"),
        ("Notificación por aviso", r"notificaci[oó]n\s+por\s+aviso|notificacion\s+por\s+aviso|aviso\s+de\s+notificaci"),
        ("Notificación por publicación web", r"notificaci[oó]n\s+por\s+publicaci[oó]n\s+web|notificacion\s+por\s+publicacion\s+web|publicaci[oó]n\s+web"),
        ("Notificación", r"\bnotificaci[oó]n\b|\bnotificacion\b"),
        ("Constancia de ejecutoria", r"ejecutoria|firmeza|constancia.*firme"),
        ("Remisión a registro", r"remisi[oó]n\s+(?:a|al)\s+registro|registro\s+automotor|remitir\s+al\s+registro"),
        ("Consulta QX", r"consulta\s+de\s+verificaci[oó]n\s+de\s+propiedad|consulta\s+de\s+propiedad|verificaci[oó]n\s+de\s+propiedad|consulta\s+qx|verificaci[oó]n\s+qx"),
        ("Solicitud", r"derecho de petici[oó]n|derecho de peticion|solicito|solicitud|petici[oó]n|peticion"),
    ]
    detectados = {
        tipo for tipo, patron in reglas
        if re.search(patron, evidencia)
        and not (
            tipo == "Recurso"
            and re.search(r"\bsin\s+recurso\b|no\s+interpuso|no\s+present[oó]|sin\s+interponer", evidencia)
        )
    }
    tipos_especificos = {"Notificación personal", "Notificación por aviso", "Notificación por publicación web"}
    if detectados & tipos_especificos:
        detectados.discard("Notificación")
    return detectados or {tipo_fallback}


def documentos_faltantes(registro):
    esperados = set(registro.get("documentos_esperados", []))
    anexados = {
        normalizar_tipo_documental(documento.get("tipo_documento"))
        for documento in registro.get("canvas_paginas", [])
        if documento.get("tipo_documento")
    }
    if registro.get("tipo_caso") == "Con recurso":
        anexados.add("Recurso")
    faltantes = []
    notificaciones = {
        "Notificación",
        "Notificación personal",
        "Notificación por aviso",
        "Notificación por publicación web",
    }
    for esperado in esperados:
        canonico = normalizar_tipo_documental(esperado)
        if canonico in anexados:
            continue
        if canonico == "Notificación" and anexados & notificaciones:
            continue
        if canonico == "Resolución" and "Requerimiento" in anexados:
            continue
        faltantes.append(esperado)
    return sorted(faltantes)
