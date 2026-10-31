(() => {
  "use strict";

  const config = window.SISTEMA_CONFIG || {};
  const storageKey = "sistema-desvinculaciones-auth-v1";
  const workspaceRoles = new Set([
    "Visualizador",
    "Modificador",
    "Administrador",
    "Super Administrador",
  ]);
  const elements = Object.fromEntries(
    [
      "notice",
      "loading-panel",
      "sign-in-panel",
      "sign-in-button",
      "sign-out-button",
      "refresh-button",
      "user-label",
      "access-panel",
      "access-title",
      "access-description",
      "workspace",
      "welcome-title",
      "profile-summary",
      "role-badge",
      "download-request-panel",
      "download-request-button",
      "message-form",
      "message-subject",
      "message-body",
      "messages-list",
      "admin-panel",
      "profiles-list",
    ].map((id) => [id.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()), document.getElementById(id)]),
  );

  let session = null;
  let profile = null;

  function showNotice(message, kind = "info") {
    elements.notice.textContent = message;
    elements.notice.dataset.kind = kind;
    elements.notice.hidden = false;
  }

  function clearNotice() {
    elements.notice.textContent = "";
    elements.notice.hidden = true;
    delete elements.notice.dataset.kind;
  }

  function setBusy(value) {
    elements.signInButton.disabled = value;
    elements.signOutButton.disabled = value;
    elements.refreshButton.disabled = value;
  }

  function readSession() {
    const value = sessionStorage.getItem(storageKey);
    if (!value) return null;
    try {
      return JSON.parse(value);
    } catch (error) {
      sessionStorage.removeItem(storageKey);
      throw new Error("La sesión local está dañada. Inicia sesión nuevamente.", { cause: error });
    }
  }

  function storeSession(value) {
    session = {
      ...value,
      expires_at: value.expires_at || Math.floor(Date.now() / 1000) + Number(value.expires_in || 0),
    };
    sessionStorage.setItem(storageKey, JSON.stringify(session));
  }

  function clearSession() {
    session = null;
    profile = null;
    sessionStorage.removeItem(storageKey);
    elements.messagesList.replaceChildren();
    elements.profilesList.replaceChildren();
  }

  function supabaseUrl(path) {
    return `${config.supabaseUrl.replace(/\/+$/, "")}${path}`;
  }

  function publicHeaders(extra = {}) {
    return { apikey: config.supabaseAnonKey, ...extra };
  }

  async function responseBody(response) {
    const text = await response.text();
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }

  function errorMessage(body, status) {
    if (body && typeof body === "object") {
      return body.msg || body.message || body.error_description || body.error || `Error HTTP ${status}`;
    }
    return typeof body === "string" ? body : `Error HTTP ${status}`;
  }

  async function refreshSession() {
    if (!session?.refresh_token) {
      clearSession();
      setScreen("sign-in");
      throw new Error("La sesión venció. Inicia sesión nuevamente.");
    }
    const response = await fetch(supabaseUrl("/auth/v1/token?grant_type=refresh_token"), {
      method: "POST",
      headers: publicHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ refresh_token: session.refresh_token }),
      cache: "no-store",
    });
    const body = await responseBody(response);
    if (!response.ok) {
      if (response.status === 400 || response.status === 401) {
        clearSession();
        setScreen("sign-in");
      }
      throw new Error(errorMessage(body, response.status));
    }
    storeSession(body);
  }

  async function apiRequest(path, options = {}, retry = true) {
    if (!session?.access_token) throw new Error("Inicia sesión para continuar.");
    if (session.expires_at <= Math.floor(Date.now() / 1000) + 45) {
      await refreshSession();
    }
    const headers = publicHeaders({
      Authorization: `Bearer ${session.access_token}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    });
    const response = await fetch(supabaseUrl(path), {
      ...options,
      headers,
      cache: "no-store",
    });
    if (response.status === 401 && retry) {
      await refreshSession();
      return apiRequest(path, options, false);
    }
    const body = await responseBody(response);
    if (!response.ok) {
      if (response.status === 401) {
        clearSession();
        setScreen("sign-in");
      }
      throw new Error(errorMessage(body, response.status));
    }
    return body;
  }

  function bytesToBase64Url(bytes) {
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  async function beginGoogleSignIn() {
    if (!window.isSecureContext || !crypto.subtle) {
      throw new Error("El inicio seguro requiere HTTPS.");
    }
    const random = crypto.getRandomValues(new Uint8Array(48));
    const verifier = bytesToBase64Url(random);
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
    const challenge = bytesToBase64Url(new Uint8Array(digest));
    sessionStorage.setItem("sistema-desvinculaciones-pkce", verifier);
    const redirectTo = new URL("./", window.location.href).toString();
    const authorize = new URL(supabaseUrl("/auth/v1/authorize"));
    authorize.searchParams.set("provider", "google");
    authorize.searchParams.set("redirect_to", redirectTo);
    authorize.searchParams.set("code_challenge", challenge);
    authorize.searchParams.set("code_challenge_method", "s256");
    window.location.assign(authorize.toString());
  }

  async function completeGoogleSignIn() {
    const currentUrl = new URL(window.location.href);
    const code = currentUrl.searchParams.get("code");
    const error = currentUrl.searchParams.get("error_description") || currentUrl.searchParams.get("error");
    if (error) {
      window.history.replaceState({}, document.title, currentUrl.pathname);
      throw new Error(error);
    }
    if (!code) return false;
    const verifier = sessionStorage.getItem("sistema-desvinculaciones-pkce");
    sessionStorage.removeItem("sistema-desvinculaciones-pkce");
    window.history.replaceState({}, document.title, currentUrl.pathname);
    if (!verifier) throw new Error("No se encontró la verificación de inicio. Vuelve a intentarlo.");
    const response = await fetch(supabaseUrl("/auth/v1/token?grant_type=pkce"), {
      method: "POST",
      headers: publicHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ auth_code: code, code_verifier: verifier }),
      cache: "no-store",
    });
    const body = await responseBody(response);
    if (!response.ok) throw new Error(errorMessage(body, response.status));
    storeSession(body);
    return true;
  }

  function setScreen(screen) {
    elements.loadingPanel.hidden = screen !== "loading";
    elements.signInPanel.hidden = screen !== "sign-in";
    elements.accessPanel.hidden = screen !== "access";
    elements.workspace.hidden = screen !== "workspace";
    elements.signOutButton.hidden = !session;
    elements.refreshButton.hidden = !session || screen !== "workspace";
    elements.userLabel.hidden = !session;
    elements.userLabel.textContent = session?.user?.email || "";
  }

  function create(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function showAccess(title, description) {
    elements.accessTitle.textContent = title;
    elements.accessDescription.textContent = description;
    setScreen("access");
  }

  async function loadProfile() {
    const email = String(session?.user?.email || "").trim().toLowerCase();
    if (!email) throw new Error("La cuenta autenticada no tiene un correo verificado.");
    const query = new URLSearchParams({
      select: "email,full_name,role,status,download_allowed,download_requested",
      email: `eq.${email}`,
      limit: "1",
    });
    const rows = await apiRequest(`/rest/v1/profiles?${query.toString()}`);
    if (!Array.isArray(rows)) throw new Error("Supabase devolvió un perfil con formato inválido.");
    return rows[0] || null;
  }

  function allowedToUseWorkspace(value) {
    return value.status === "Activo" && workspaceRoles.has(value.role);
  }

  async function showWorkspace() {
    profile = await loadProfile();
    if (!profile) {
      showAccess(
        "Perfil pendiente de registro",
        "No encontramos tu perfil en el sistema. El propietario debe verificar que el registro de tu cuenta esté habilitado.",
      );
      return;
    }
    if (!allowedToUseWorkspace(profile)) {
      showAccess(
        profile.status === "Pendiente" ? "Acceso pendiente de aprobación" : "Acceso no disponible",
        `Tu cuenta tiene estado "${profile.status}" y rol "${profile.role}". Contacta al administrador del sistema.`,
      );
      return;
    }

    elements.welcomeTitle.textContent = `Hola${profile.full_name ? `, ${profile.full_name}` : ""}`;
    elements.profileSummary.textContent = `${profile.email} · Estado: ${profile.status}`;
    elements.roleBadge.textContent = profile.role;
    elements.downloadRequestPanel.hidden =
      profile.role !== "Visualizador" || profile.download_allowed;
    elements.downloadRequestButton.textContent = profile.download_requested
      ? "Solicitud enviada"
      : "Solicitar permiso";
    elements.downloadRequestButton.disabled = profile.download_requested;
    elements.adminPanel.hidden = !["Administrador", "Super Administrador"].includes(profile.role);
    setScreen("workspace");
    const results = await Promise.allSettled([
      loadMessages(),
      elements.adminPanel.hidden ? Promise.resolve() : loadProfiles(),
    ]);
    const failed = results.find((result) => result.status === "rejected");
    if (failed) {
      if (results[0].status === "rejected") {
        elements.messagesList.replaceChildren(create("p", "muted", "No se pudieron cargar los mensajes."));
      }
      if (results[1].status === "rejected") {
        elements.profilesList.replaceChildren(create("p", "muted", "No se pudieron cargar los perfiles."));
      }
      showNotice(`No se pudo cargar toda la información compartida: ${failed.reason.message}`, "error");
    }
  }

  async function loadMessages() {
    elements.messagesList.replaceChildren(create("p", "muted", "Cargando mensajes..."));
    const query = new URLSearchParams({
      select: "id,sender_email,subject,message,created_at,read_at",
      order: "created_at.desc",
      limit: "200",
    });
    const messages = await apiRequest(`/rest/v1/support_messages?${query.toString()}`);
    if (!Array.isArray(messages)) throw new Error("Supabase devolvió mensajes con formato inválido.");
    elements.messagesList.replaceChildren();
    if (messages.length === 0) {
      elements.messagesList.append(create("p", "muted", "Todavía no hay mensajes."));
      return;
    }
    for (const message of messages) {
      const card = create("article", "message-card");
      const title = create("h3", "", message.subject || "Soporte");
      const date = new Date(message.created_at);
      const sender = message.sender_email === profile.email ? "Enviado por ti" : `De ${message.sender_email}`;
      const meta = create(
        "p",
        "message-meta",
        `${sender} · ${Number.isNaN(date.valueOf()) ? "Fecha no disponible" : date.toLocaleString("es-CO")}${message.read_at ? " · Leído" : " · Sin leer"}`,
      );
      const body = create("p", "message-body", message.message);
      card.append(title, meta, body);
      if (!message.read_at && ["Administrador", "Super Administrador"].includes(profile.role)) {
        const markRead = create("button", "button button-secondary", "Marcar como leído");
        markRead.type = "button";
        markRead.addEventListener("click", () => markMessageRead(message.id, markRead));
        card.append(markRead);
      }
      elements.messagesList.append(card);
    }
  }

  async function markMessageRead(id, button) {
    button.disabled = true;
    try {
      const query = new URLSearchParams({ id: `eq.${id}`, read_at: "is.null" });
      const rows = await apiRequest(`/rest/v1/support_messages?${query.toString()}`, {
        method: "PATCH",
        headers: { Prefer: "return=representation" },
        body: JSON.stringify({ read_at: new Date().toISOString() }),
      });
      if (!Array.isArray(rows) || rows.length === 0) {
        throw new Error("No se confirmó el cambio. Puede que el mensaje ya esté leído.");
      }
    } catch (error) {
      button.disabled = false;
      showNotice(`No se pudo actualizar el mensaje: ${error.message}`, "error");
      return;
    }
    try {
      await loadMessages();
      showNotice("Mensaje marcado como leído.", "success");
    } catch (error) {
      showNotice(`El mensaje se marcó como leído, pero no se pudo actualizar la lista: ${error.message}`, "error");
    }
  }

  async function loadProfiles() {
    elements.profilesList.replaceChildren(create("p", "muted", "Cargando perfiles..."));
    const query = new URLSearchParams({
      select: "email,full_name,role,status,download_allowed,download_requested",
      order: "email.asc",
    });
    const rows = await apiRequest(`/rest/v1/profiles?${query.toString()}`);
    if (!Array.isArray(rows)) throw new Error("Supabase devolvió perfiles con formato inválido.");
    elements.profilesList.replaceChildren();
    for (const row of rows) {
      const item = create("article", "profile-row");
      const identity = create("div", "profile-identity");
      identity.append(
        create("strong", "", row.full_name || row.email),
        create("span", "", `${row.email} · Descargas: ${row.download_allowed ? "permitidas" : "no permitidas"}${row.download_requested ? " · solicita permiso" : ""}`),
      );
      item.append(identity, create("span", "badge", `${row.role} · ${row.status}`));
      elements.profilesList.append(item);
    }
    if (rows.length === 0) elements.profilesList.append(create("p", "muted", "No hay perfiles registrados."));
  }

  async function requestDownloadPermission(button) {
    button.disabled = true;
    try {
      await apiRequest("/rest/v1/rpc/request_document_download", {
        method: "POST",
        body: "{}",
      });
      profile.download_requested = true;
      button.textContent = "Solicitud enviada";
      showNotice("La solicitud de descarga fue enviada al administrador.", "success");
    } catch (error) {
      button.disabled = false;
      showNotice(`No se pudo solicitar el permiso: ${error.message}`, "error");
    }
  }

  async function sendMessage(event) {
    event.preventDefault();
    const subject = elements.messageSubject.value.trim() || "Soporte";
    const message = elements.messageBody.value.trim();
    if (!message) {
      showNotice("Escribe un mensaje antes de enviarlo.", "error");
      return;
    }
    const submit = elements.messageForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const rows = await apiRequest(
        "/rest/v1/support_messages?select=id,sender_email,subject,message,created_at,read_at",
        {
          method: "POST",
          headers: { Prefer: "return=representation" },
          body: JSON.stringify({ sender_email: profile.email, subject, message }),
        },
      );
      if (!Array.isArray(rows) || rows.length === 0) {
        throw new Error("No se confirmó el registro del mensaje.");
      }
      elements.messageBody.value = "";
      showNotice("Mensaje enviado.", "success");
    } catch (error) {
      showNotice(`No se pudo enviar el mensaje: ${error.message}`, "error");
      submit.disabled = false;
      return;
    }
    try {
      await loadMessages();
    } catch (error) {
      showNotice(`El mensaje fue enviado, pero no se pudo actualizar la lista: ${error.message}`, "error");
    } finally {
      submit.disabled = false;
    }
  }

  async function signOut() {
    const active = session;
    clearSession();
    setScreen("sign-in");
    if (active?.access_token) {
      const response = await fetch(supabaseUrl("/auth/v1/logout"), {
        method: "POST",
        headers: publicHeaders({ Authorization: `Bearer ${active.access_token}` }),
        cache: "no-store",
      });
      if (!response.ok) {
        const body = await responseBody(response);
        showNotice(`La sesión se cerró en este dispositivo, pero el servidor no confirmó su revocación: ${errorMessage(body, response.status)}`, "error");
      } else {
        showNotice("Sesión cerrada.", "success");
      }
    }
  }

  async function initialize() {
    elements.signInButton.addEventListener("click", async () => {
      clearNotice();
      try {
        await beginGoogleSignIn();
      } catch (error) {
        showNotice(error.message, "error");
      }
    });
    elements.signOutButton.addEventListener("click", async () => {
      setBusy(true);
      try {
        await signOut();
      } catch (error) {
        showNotice(`No fue posible cerrar la sesión: ${error.message}`, "error");
      } finally {
        setBusy(false);
      }
    });
    elements.refreshButton.addEventListener("click", async () => {
      clearNotice();
      setBusy(true);
      try {
        await showWorkspace();
      } catch (error) {
        showNotice(`No fue posible actualizar el espacio: ${error.message}`, "error");
      } finally {
        setBusy(false);
      }
    });
    elements.messageForm.addEventListener("submit", sendMessage);
    elements.downloadRequestButton.addEventListener("click", () =>
      requestDownloadPermission(elements.downloadRequestButton),
    );

    if (!config.supabaseUrl || !config.supabaseAnonKey || config.supabaseAnonKey.includes("YOUR_")) {
      setScreen("sign-in");
      elements.signInButton.disabled = true;
      showNotice("Falta configurar la URL pública y la clave anon de Supabase para este despliegue.", "error");
      return;
    }

    setBusy(true);
    try {
      await completeGoogleSignIn();
      session = readSession();
      if (!session) {
        setScreen("sign-in");
        return;
      }
      setScreen("workspace");
      await showWorkspace();
    } catch (error) {
      setScreen(session ? "access" : "sign-in");
      if (session) {
        showAccess("No se pudo validar el acceso", error.message);
      } else {
        showNotice(`No fue posible iniciar sesión: ${error.message}`, "error");
      }
    } finally {
      setBusy(false);
    }
  }

  initialize();
})();
