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

  /* Convierte una hora en formato 24h ("14:30:00", "14:30" o Date) a 12h
     con AM/PM en español: "2:30 PM". Devuelve "" si la entrada es nula
     o no se reconoce. Solo presentacional — el backend sigue en 24h. */
  function formatHora12(hora24) {
    if (hora24 === null || hora24 === undefined || hora24 === '') return '';
    let h, m;
    if (typeof hora24 === 'string') {
      const parts = hora24.split(':');
      if (parts.length < 2) return '';
      h = parseInt(parts[0], 10);
      m = parts[1].padStart(2, '0');
      if (Number.isNaN(h)) return '';
    } else if (hora24 instanceof Date) {
      if (isNaN(hora24.getTime())) return '';
      h = hora24.getHours();
      m = String(hora24.getMinutes()).padStart(2, '0');
    } else {
      return '';
    }
    const ampm = h >= 12 ? 'PM' : 'AM';
    const h12 = h % 12 === 0 ? 12 : h % 12;
    return `${h12}:${m} ${ampm}`;
  }

  function formatRangoHora12(inicio, fin) {
    return `${formatHora12(inicio)} - ${formatHora12(fin)}`;
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
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: 'America/Santo_Domingo',
    });
  }

  /* ─────────── Shell (sidebar + header) ───────────
     Monta el layout estándar (sidebar de navegación + header superior)
     en la pantalla actual. El template debe contener:
       <div id="app-shell" data-active="calendario"></div>
     y luego un <main id="page-main">…contenido…</main> que será movido
     dentro del shell.
  */

  const NAV_ITEMS = [
    { key: 'calendario', label: 'Calendario',  href: '/calendar.html',   icon: 'calendar-days', role: null },
    { key: 'pacientes',  label: 'Pacientes',   href: '/pacientes.html',  icon: 'users',         role: null },
    { key: 'medicos',    label: 'Médicos',     href: '/medicos.html',    icon: 'stethoscope',   role: null },
    { key: 'agenda',     label: 'Mi Agenda',   href: '/agenda.html',     icon: 'clipboard-list', role: 'medico' },
    { key: 'usuarios',   label: 'Usuarios',    href: '/usuarios.html',   icon: 'shield-check',  role: 'admin' },
    { key: 'auditoria',  label: 'Auditoría',   href: '/auditoria.html',  icon: 'file-search',   role: 'admin' },
  ];

  function _initials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/).filter(Boolean);
    const first = parts[0]?.[0] || '';
    const last  = parts.length > 1 ? parts[parts.length - 1][0] : '';
    return (first + last).toUpperCase();
  }

  function _renderSidebar(activeKey) {
    const items = NAV_ITEMS.map(it => {
      const cls = 'nav-link' + (it.key === activeKey ? ' is-active' : '');
      const roleAttr = it.role ? `data-role="${it.role}"` : '';
      const hidden = it.role ? 'style="display:none"' : '';
      return `
        <span ${roleAttr} ${hidden}>
          <a href="${it.href}" class="${cls}">
            <i data-lucide="${it.icon}"></i>
            <span>${it.label}</span>
          </a>
        </span>`;
    }).join('');

    return `
      <aside class="app-sidebar" id="app-sidebar">
        <div class="app-sidebar__brand">
          <div class="app-sidebar__brand-mark">
            <i data-lucide="activity"></i>
          </div>
          <div>
            <div class="app-sidebar__title">SGCM</div>
            <div class="app-sidebar__sub">HTQPJB · La Vega</div>
          </div>
        </div>
        <nav class="app-sidebar__nav">
          <div class="app-sidebar__section">Operación</div>
          ${items}
        </nav>
        <div class="app-sidebar__footer">© 2026 HTQPJB</div>
      </aside>`;
  }

  function _renderHeader(pageTitle) {
    return `
      <header class="app-header">
        <div class="app-header__title">${pageTitle || ''}</div>
        <div class="app-header__right">
          <div class="user-chip" id="user-chip" style="visibility:hidden">
            <div class="user-chip__avatar" id="user-avatar">??</div>
            <div class="user-chip__meta">
              <div class="user-chip__name" id="user-name">—</div>
              <div class="user-chip__role" id="user-role">—</div>
            </div>
          </div>
          <button id="logout" class="btn-logout" type="button">
            <i data-lucide="log-out"></i>
            <span>Salir</span>
          </button>
        </div>
      </header>`;
  }

  /* mountShell({ active, pageTitle }) — envuelve <main id="page-main">
     con el shell, hidrata datos del usuario, aplica RBAC y wire-up logout.
     Retorna el objeto `me` del usuario (Promise). */
  async function mountShell({ active, pageTitle }) {
    requireAuth();
    const main = document.getElementById('page-main');
    if (!main) {
      console.warn('SGCM.mountShell: no se encontró <main id="page-main">');
      return null;
    }
    // Construye contenedor shell
    const shell = document.createElement('div');
    shell.className = 'app-shell';
    shell.innerHTML = _renderSidebar(active) + _renderHeader(pageTitle || '');

    // Mueve el main dentro del shell
    main.classList.add('app-main');
    main.parentNode.insertBefore(shell, main);
    shell.appendChild(main);

    // Inicializa íconos lucide
    if (window.lucide) lucide.createIcons();

    // Wire logout
    document.getElementById('logout').addEventListener('click', () => {
      logout();
      window.location.href = '/login.html';
    });

    // Carga usuario y aplica RBAC
    try {
      const meData = await me();
      document.getElementById('user-name').textContent = meData.nombre;
      document.getElementById('user-role').textContent = meData.rol;
      document.getElementById('user-avatar').textContent = _initials(meData.nombre);
      document.getElementById('user-chip').style.visibility = 'visible';
      applyNavPermissions(meData.rol);
      return meData;
    } catch (err) {
      console.error('mountShell: error cargando /auth/me', err);
      return null;
    }
  }

  return {
    login, logout, requireAuth, api, me, getToken, applyNavPermissions,
    applyMaskCedula, applyMaskTelefono, formatCedula, formatTelefono, stripDigits,
    formatMedicoNombre, formatFechaHora, formatHora12, formatRangoHora12,
    mountShell,
  };
})();
