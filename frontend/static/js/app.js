/* SGCM frontend client - login, JWT storage, fetch wrapper. */
const SGCM = (() => {
  const API = "/api/v1";
  const TOKEN_KEY = "sgcm_token";

  /* ---- Masks ---- */
  function formatCedula(v) {
    const d = (v || "").replace(/\D/g, "").slice(0, 11);
    if (d.length <= 3) return d;
    if (d.length <= 10) return d.slice(0, 3) + "-" + d.slice(3);
    return d.slice(0, 3) + "-" + d.slice(3, 10) + "-" + d.slice(10);
  }

  function formatTelefono(v) {
    const d = (v || "").replace(/\D/g, "").slice(0, 10);
    if (!d.length) return "";
    if (d.length <= 3) return "(" + d;
    if (d.length <= 6) return "(" + d.slice(0, 3) + ") " + d.slice(3);
    return "(" + d.slice(0, 3) + ") " + d.slice(3, 6) + "-" + d.slice(6);
  }

  function stripDigits(v) {
    return (v || "").replace(/\D/g, "");
  }

  function applyMaskCedula(el) {
    if (!el) return;
    el.placeholder = "000-0000000-0";
    el.setAttribute("maxlength", "13");
    el.addEventListener("input", function () {
      const pos = this.selectionStart;
      const oldLen = this.value.length;
      this.value = formatCedula(this.value);
      const newLen = this.value.length;
      this.setSelectionRange(pos + (newLen - oldLen), pos + (newLen - oldLen));
    });
  }

  function applyMaskTelefono(el) {
    if (!el) return;
    el.placeholder = "(000) 000-0000";
    el.setAttribute("maxlength", "14");
    el.addEventListener("input", function () {
      const pos = this.selectionStart;
      const oldLen = this.value.length;
      this.value = formatTelefono(this.value);
      const newLen = this.value.length;
      this.setSelectionRange(pos + (newLen - oldLen), pos + (newLen - oldLen));
    });
  }

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function setToken(t) {
    localStorage.setItem(TOKEN_KEY, t);
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
  }

  function requireAuth() {
    if (!getToken()) {
      window.location.href = "/login.html";
    }
  }

  async function login(email, password) {
    const body = new URLSearchParams();
    body.set("username", email);
    body.set("password", password);

    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al iniciar sesión");
    }
    const data = await res.json();
    setToken(data.access_token);
    return data;
  }

  async function api(path, options = {}) {
    const headers = options.headers || {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    if (options.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(`${API}${path}`, { ...options, headers });
    if (res.status === 401) {
      logout();
      window.location.href = "/login.html";
      throw new Error("Sesión expirada");
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  async function me() {
    return api("/auth/me");
  }

  function applyNavPermissions(rol) {
    const isAdmin = rol === "admin";
    const isStaff = rol === "admin" || rol === "secretaria";
    document.querySelectorAll("[data-role]").forEach((el) => {
      const required = el.dataset.role;
      let visible = false;
      if (required === "admin") visible = isAdmin;
      else if (required === "staff") visible = isStaff;
      else if (required === "medico") visible = rol === "medico";
      else if (required === "secretaria") visible = rol === "secretaria";
      el.style.display = visible ? "" : "none";
    });
  }

  function formatMedicoNombre(nombre) {
    if (!nombre) return '';
    return 'Dr. ' + nombre;
  }

  /* Formatea un timestamp ISO devuelto por el backend a hora local de RD.
     Si el backend lo envía con offset (TIMESTAMPTZ → ISO con -04:00), Date()
     lo entiende correctamente. timeZone fuerza la presentación a RD aun si
     el navegador del usuario está en otra zona. */
  function formatFechaHora(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleString('es-DO', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'America/Santo_Domingo',
    });
  }

  return {
    login, logout, requireAuth, api, me, getToken, applyNavPermissions,
    applyMaskCedula, applyMaskTelefono, formatCedula, formatTelefono, stripDigits,
    formatMedicoNombre, formatFechaHora,
  };
})();
