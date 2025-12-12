async function weallJsonFetch(url, opts = {}) {
  const res = await fetch(url, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });

  let data = null;
  try { data = await res.json(); } catch {}

  if (!res.ok) {
    const msg = data?.detail || data?.error || `HTTP ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function weallClearClientAuth() {
  localStorage.removeItem("weall_user_id");
  localStorage.removeItem("weall_user_roles");
  localStorage.removeItem("weall_user_roles_ts");
}

function weallStripQueryIfSensitive() {
  const qs = new URLSearchParams(window.location.search);
  if (qs.has("password") || qs.has("userId") || qs.has("userid")) {
    // Remove it from the URL immediately (no reload)
    window.history.replaceState({}, document.title, window.location.pathname);
    return true;
  }
  return false;
}

async function weallGetSession() {
  try {
    const sess = await weallJsonFetch("/auth/session", { method: "GET" });
    if (sess?.user_id) localStorage.setItem("weall_user_id", sess.user_id);
    return sess;
  } catch (e) {
    if (e.status === 401) {
      weallClearClientAuth();
      return null;
    }
    throw e;
  }
}
