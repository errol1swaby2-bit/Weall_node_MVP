// weall_node/weall_node/frontend/auth.js
// Unified auth + PoH guard helper for WeAll Node frontends.
//
// Usage on protected pages (e.g. juror/panel/groups):
//   <script src="/frontend/auth.js"></script>
//   <script>
//     document.addEventListener("DOMContentLoaded", () => {
//       weallAuth.require({ minTier: 1 }); // or 2/3
//     });
//   </script>
//
// Relies on:
//   POST /auth/apply
//   GET  /auth/session
//   POST /auth/logout
//   GET  /poh/me
//
// NOTE: All auth is cookie-based via `weall_session`.

(() => {
  const LS_ACCT = "weall_acct";

  const API_BASE = window.ENV && window.ENV.VITE_API_BASE
    ? window.ENV.VITE_API_BASE
    : "";

  // --------------------------
  // HTTP helpers
  // --------------------------

  async function jsonFetch(path, opts) {
    const url = API_BASE + path;
    const options = Object.assign(
      {
        headers: {
          "Accept": "application/json",
        },
        credentials: "include",
      },
      opts || {}
    );

    if (options.body && typeof options.body !== "string") {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }

    const res = await fetch(url, options);
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }

    if (!res.ok) {
      const msg =
        (data && (data.detail || data.error || data.message)) ||
        ("Request failed with status " + res.status);
      throw new Error(msg);
    }
    return data;
  }

  // --------------------------
  // Session / account helpers
  // --------------------------

  function normalizeUserId(id) {
    if (!id) return "";
    let v = String(id).trim();
    // Allow @handle or plain
    if (v.startsWith("@")) return v;
    return v.toLowerCase();
  }

  function getAccount() {
    // Prefer local cache first
    try {
      const v = localStorage.getItem(LS_ACCT);
      if (v) return normalizeUserId(v);
    } catch {}
    return "";
  }

  function setAccount(userId) {
    try {
      localStorage.setItem(LS_ACCT, normalizeUserId(userId));
    } catch {}
  }

  function clearAccount() {
    try {
      localStorage.removeItem(LS_ACCT);
    } catch {}
  }

  // --------------------------
  // Public API wrappers
  // --------------------------

  async function login(userId, password) {
    const payload = {
      user_id: normalizeUserId(userId),
      password: String(password || ""),
    };
    const data = await jsonFetch("/auth/apply", {
      method: "POST",
      body: payload,
    });
    if (data && data.user_id) {
      setAccount(data.user_id);
    }
    return data;
  }

  async function logout() {
    try {
      await jsonFetch("/auth/logout", { method: "POST" });
    } catch {
      // ignore
    }
    clearAccount();
  }

  async function getSession() {
    const data = await jsonFetch("/auth/session", { method: "GET" });
    if (data && data.user_id) {
      setAccount(data.user_id);
    }
    return data;
  }

  async function getPohMe() {
    return jsonFetch("/poh/me", { method: "GET" });
  }

  // --------------------------
  // PoH guard
  // --------------------------

  async function requireGuard(opts) {
    const minTier = (opts && typeof opts.minTier === "number")
      ? opts.minTier
      : 0;
    const redirectToLogin = (opts && opts.redirectToLogin) || "/frontend/login.html";

    // 1) Ensure we have a session
    let sess;
    try {
      sess = await getSession();
    } catch (e) {
      // Not authenticated → go to login with ?next=
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.replace(redirectToLogin + "?next=" + next);
      return false;
    }

    if (!sess || !sess.user_id) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.replace(redirectToLogin + "?next=" + next);
      return false;
    }

    // 2) Check PoH tier
    if (minTier > 0) {
      let poh;
      try {
        poh = await getPohMe();
      } catch (e) {
        alert("Failed to load PoH status: " + e.message);
        return false;
      }
      const tier = typeof poh.tier === "number" ? poh.tier : 0;
      const status = poh.status || "ok";

      if (status === "banned") {
        alert("Your account is banned and cannot access this page.");
        return false;
      }
      if (status === "suspended") {
        alert("Your account is suspended and cannot access this page.");
        return false;
      }
      if (tier < minTier) {
        alert(
          "This page requires PoH Tier " +
            minTier +
            ". Your current tier is " +
            tier +
            "."
        );
        return false;
      }
    }

    return true;
  }

  // Expose global
  window.weallAuth = {
    // account
    getAccount,
    setAccount,
    clearAccount,

    // low-level
    login,
    logout,
    getSession,
    getPohMe,

    // guard
    require: requireGuard,
  };
})();
