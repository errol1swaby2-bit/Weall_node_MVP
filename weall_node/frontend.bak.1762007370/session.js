// session.js — simple session management using /auth/apply and /auth/check
(function () {
  const KEY = 'wa.session';
  const ACC = 'wa.account';

  function get() {
    try {
      const s = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (!s) return null;
      return s;
    } catch { return null; }
  }

  function set(sess) {
    localStorage.setItem(KEY, JSON.stringify(sess));
    if (sess?.account) localStorage.setItem(ACC, sess.account);
  }

  function clear() {
    localStorage.removeItem(KEY); localStorage.removeItem(ACC);
  }

  function nowSec() { return Date.now() / 1000; }

  async function validate(sess) {
    if (!sess?.token) return false;
    if (!sess?.expires || sess.expires < nowSec()) return false;
    try {
      const r = await fetch('/auth/check', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ token: sess.token, scope: "session" })
      });
      const j = await r.json();
      return !!j?.ok;
    } catch { return false; }
  }

  function ensure(redirect = true) {
    const sess = get();
    const okLocal = !!(sess && sess.token && sess.expires > nowSec());
    if (!okLocal && redirect) {
      const next = encodeURIComponent(location.pathname + location.search);
      location.replace(`/login.html?next=${next}`);
    }
    return sess || null;
  }

  async function requireValid() {
    const sess = ensure(true);
    if (!sess) return null;
    const ok = await validate(sess);
    if (!ok) {
      clear();
      const next = encodeURIComponent(location.pathname + location.search);
      location.replace(`/login.html?next=${next}`);
      return null;
    }
    return sess;
  }

  async function login(account) {
    const r = await fetch('/auth/apply', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ account_id: String(account||'').trim(), scope: "session" })
    });
    const j = await r.json();
    if (!r.ok || !j?.token) {
      throw new Error(j?.error || 'Login failed');
    }
    const sess = { account: String(account||'').trim(), token: j.token, expires: j.expires };
    set(sess);
    return sess;
  }

  function logout() {
    clear();
    const next = encodeURIComponent('/'); // go to app after re-login
    location.replace(`/login.html?next=${next}`);
  }

  async function authFetch(url, opts={}) {
    const sess = ensure(true);
    if (!sess) return Promise.reject(new Error('No session'));
    const headers = new Headers(opts.headers || {});
    headers.set('Authorization', `Bearer ${sess.token}`);
    headers.set('X-Account', sess.account || '');
    return fetch(url, { ...opts, headers });
  }

  window.Session = { get, set, clear, ensure, requireValid, login, logout, authFetch };
})();
