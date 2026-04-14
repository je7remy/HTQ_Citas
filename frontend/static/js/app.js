/* SGCM frontend client - login, JWT storage, fetch wrapper. */
const SGCM = (() => {
  const API = "/api/v1";
  const TOKEN_KEY = "sgcm_token";

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

  return { login, logout, requireAuth, api, me, getToken };
})();
