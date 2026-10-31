from __future__ import annotations

from .settings import WebConfigurationError, WebSettings, normalizar_identidad_oidc


def validar_correo_propietario(email: str | None, correo_propietario: str) -> str:
    correo = str(email or "").strip().casefold()
    propietario = str(correo_propietario or "").strip().casefold()
    if not propietario or correo != propietario:
        raise WebConfigurationError(
            "Esta instalación web está reservada para la cuenta Google "
            "configurada por el propietario."
        )
    return correo


def _leer_configuracion_auth(st) -> tuple[str, dict]:
    try:
        web_config = st.secrets.get("web", {})
        auth_config = st.secrets.get("auth", {})
        google_config = auth_config.get("google", {})
    except Exception as error:
        raise WebConfigurationError(
            "No está configurado el inicio de sesión web. Crea "
            ".streamlit/secrets.toml siguiendo web-secrets.example.toml."
        ) from error

    propietario = str(
        web_config.get("owner_email", "")
    ).strip().casefold()
    if not propietario or "@" not in propietario:
        raise WebConfigurationError(
            "Configura web.owner_email en .streamlit/secrets.toml."
        )
    for key in ("redirect_uri", "cookie_secret"):
        if not auth_config.get(key):
            raise WebConfigurationError(
                f"Falta auth.{key} en .streamlit/secrets.toml."
            )
    for key in ("client_id", "client_secret", "server_metadata_url"):
        if not google_config.get(key):
            raise WebConfigurationError(
                f"Falta auth.google.{key} en .streamlit/secrets.toml."
            )
    return propietario, google_config


def autenticar_propietario_google(st) -> dict:
    try:
        propietario, _google_config = _leer_configuracion_auth(st)
    except WebConfigurationError as error:
        st.error(str(error))
        st.stop()

    usuario_oidc = st.user
    if not usuario_oidc.is_logged_in:
        st.title("Sistema de Desvinculaciones")
        st.info("Inicia sesión con la cuenta Google autorizada para esta instalación.")
        if st.button(
            "Continuar con Google",
            type="primary",
            icon=":material/login:",
        ):
            st.login("google")
        st.stop()

    try:
        correo = validar_correo_propietario(
            getattr(usuario_oidc, "email", None),
            propietario,
        )
        if getattr(usuario_oidc, "email_verified", False) is not True:
            raise WebConfigurationError(
                "Google no confirmó que el correo de la sesión esté verificado."
            )
    except WebConfigurationError as error:
        st.error(str(error))
        if st.button("Cerrar sesión de Google", icon=":material/logout:"):
            st.logout()
        st.stop()

    return {
        "email": correo,
        "nombre": str(getattr(usuario_oidc, "name", None) or correo).strip(),
    }


def autenticar_usuario_workspace(st, settings: WebSettings) -> dict:
    usuario_oidc = st.user
    if not usuario_oidc.is_logged_in:
        st.title("Sistema de Desvinculaciones")
        st.info("Inicia sesión con tu cuenta institucional de Google Workspace.")
        if st.button("Iniciar sesión institucional", type="primary"):
            st.login("google")
        st.stop()

    identidad = usuario_oidc.to_dict()
    email = normalizar_identidad_oidc(
        identidad.get("email"),
        identidad.get("email_verified") is True,
        settings.allowed_email_domains,
    )
    return {
        "email": email,
        "nombre": str(identidad.get("name") or email).strip(),
    }
