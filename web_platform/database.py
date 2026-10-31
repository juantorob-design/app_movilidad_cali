from __future__ import annotations

import json
from pathlib import Path

from .settings import WebSettings


class CaseConcurrencyError(RuntimeError):
    """El expediente cambió desde que el usuario lo abrió."""


def conectar_postgres(settings: WebSettings):
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError(
            "Falta psycopg. Instala las dependencias de requirements-web.txt."
        ) from error

    return psycopg.connect(
        settings.database_url,
        connect_timeout=10,
        application_name="sistema_desvinculaciones_web",
    )


def aplicar_migraciones(connection) -> None:
    migration = (
        Path(__file__).resolve().parent
        / "migrations"
        / "001_web_foundation.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    with connection.cursor() as cursor:
        cursor.execute(sql)


def registrar_usuario_oidc(
    connection,
    email: str,
    nombre: str,
    super_admin_email: str,
) -> dict:
    correo = email.strip().casefold()
    es_super_admin = correo == super_admin_email.strip().casefold()
    rol_inicial = "Super Administrador" if es_super_admin else "Sin Rol Asignado"
    estado_inicial = "Activo" if es_super_admin else "Pendiente"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO sistema_web.usuarios
                (email, nombre, rol, estado)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (email) DO NOTHING
            """,
            (correo, nombre.strip() or correo, rol_inicial, estado_inicial),
        )
        cursor.execute(
            """
            SELECT email, nombre, rol, estado
            FROM sistema_web.usuarios
            WHERE email = %s
            """,
            (correo,),
        )
        fila = cursor.fetchone()
    if not fila:
        raise RuntimeError("No fue posible crear o leer el perfil institucional.")
    return {
        "email": fila[0],
        "nombre": fila[1],
        "rol": fila[2],
        "estado": fila[3],
    }


def cargar_expedientes(connection) -> dict[str, dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT radicado_padre, contenido
            FROM sistema_web.expedientes
            ORDER BY (contenido ->> 'fecha_solicitud') NULLS LAST,
                     radicado_padre
            """
        )
        return {
            radicado: contenido
            for radicado, contenido in cursor.fetchall()
        }


def guardar_expediente(
    connection,
    radicado_padre: str,
    contenido: dict,
    usuario_email: str,
    version_esperada: int | None,
) -> int:
    radicado = str(radicado_padre or "").strip()
    actor = str(usuario_email or "").strip().casefold()
    if not radicado or not actor:
        raise ValueError("El radicado y el usuario son obligatorios.")
    if not isinstance(contenido, dict):
        raise TypeError("El contenido del expediente debe ser un objeto.")

    try:
        json_contenido = json.dumps(
            contenido,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "El expediente contiene datos no serializables; no se guardó."
        ) from error

    with connection.transaction():
        with connection.cursor() as cursor:
            if version_esperada is None:
                cursor.execute(
                    """
                    INSERT INTO sistema_web.expedientes
                        (radicado_padre, contenido, version, actualizado_por)
                    VALUES (%s, %s::jsonb, 1, %s)
                    ON CONFLICT (radicado_padre) DO NOTHING
                    RETURNING version
                    """,
                    (radicado, json_contenido, actor),
                )
            else:
                cursor.execute(
                    """
                    UPDATE sistema_web.expedientes
                    SET contenido = %s::jsonb,
                        version = version + 1,
                        actualizado_por = %s,
                        actualizado_en = now()
                    WHERE radicado_padre = %s
                      AND version = %s
                    RETURNING version
                    """,
                    (json_contenido, actor, radicado, version_esperada),
                )
            fila = cursor.fetchone()
            if not fila:
                raise CaseConcurrencyError(
                    "El expediente fue creado o actualizado por otro usuario. "
                    "Vuelve a cargarlo antes de guardar tus cambios."
                )
            version_nueva = int(fila[0])
            cursor.execute(
                """
                INSERT INTO sistema_web.auditoria
                    (actor_email, accion, radicado_padre, detalle)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (
                    actor,
                    "expediente_creado" if version_esperada is None else "expediente_actualizado",
                    radicado,
                    json.dumps(
                        {"version": version_nueva},
                        separators=(",", ":"),
                    ),
                ),
            )
    return version_nueva
