CREATE SCHEMA IF NOT EXISTS sistema_web;

CREATE TABLE IF NOT EXISTS sistema_web.usuarios (
    email text PRIMARY KEY CHECK (email = lower(email)),
    nombre text NOT NULL DEFAULT '',
    rol text NOT NULL DEFAULT 'Sin Rol Asignado'
        CHECK (rol IN (
            'Sin Rol Asignado',
            'Visualizador',
            'Modificador',
            'Administrador',
            'Super Administrador'
        )),
    estado text NOT NULL DEFAULT 'Pendiente'
        CHECK (estado IN ('Pendiente', 'Activo', 'Inactivo')),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    ultimo_ingreso_en timestamptz
);

CREATE TABLE IF NOT EXISTS sistema_web.expedientes (
    radicado_padre text PRIMARY KEY,
    contenido jsonb NOT NULL CHECK (jsonb_typeof(contenido) = 'object'),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    actualizado_por text NOT NULL REFERENCES sistema_web.usuarios(email),
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS expedientes_placa_idx
    ON sistema_web.expedientes ((upper(contenido ->> 'placa')));

CREATE INDEX IF NOT EXISTS expedientes_fecha_idx
    ON sistema_web.expedientes ((contenido ->> 'fecha_solicitud'));

CREATE TABLE IF NOT EXISTS sistema_web.auditoria (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_email text NOT NULL REFERENCES sistema_web.usuarios(email),
    accion text NOT NULL,
    radicado_padre text,
    detalle jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(detalle) = 'object'),
    ocurrido_en timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS auditoria_radicado_idx
    ON sistema_web.auditoria (radicado_padre, ocurrido_en DESC);
