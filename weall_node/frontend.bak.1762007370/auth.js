// Minimal login + PoH gate helper for WeAll Node frontends (hardened).
// Usage on protected pages (e.g., juror/panel/groups):
//   <script src="./auth.js"></script>
//   <script> weallAuth.require({ minTier: 3 }); </script>
//
// Public/low-tier pages can set minTier: 0 or 1 as needed.
// Relies on HTTPS and the node’s /poh/status and /auth/* endpoints.

(() => {
  const LS_ACCT  = 'weall_acct';
  const LS_TOKEN = 'weall_apply_token';

  // ---------- URL helpers ----------
  function urlParam(name) {
    const u = new URL(window.location.href);
    return u.searchParams.get(name);
  }
  function setParam(url, k, v) {
    const u = new URL(url, window.location.href);
    if (v == null) u.searchParams.delete(k);
    else u.searchParams.set(k, v);
    return u.toString();
  }
  function page(urlRel) { return new URL(urlRel, window.location.href).toString(); }
  function nowSec() { return Math.floor(Date.now()/1000); }

  // ---------- Transport helpers ----------
  async function postJSON(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include', // carry cookies if you add them later
      body: JSON.stringify(body || {})
    });
    const t = await r.text();
    let j = {};
    try { j = t ? JSON.parse(t) : {}; } catch { j = { raw: t }; }
    if (!r.ok) throw new Error(j.error || String(r.status));
    return j;
  }
  async function getJSON(path) {
    const r = await fetch(path, { credentials: 'include' });
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }

  // ---------- HTTPS enforcement ----------
  function isSecureContext() {
    return location.protocol === 'https:' ||
           location.hostname === 'localhost' ||
           location.hostname === '127.0.0.1' ||
           location.hostname === '::1';
  }
  function ensureHttps() {
    if (isSecureContext()) return true;
    // upgrade to https on same host/path
    const to = 'https://' + location.host + location.pathname + location.search + location.hash;
    try { location.replace(to); } catch { location.href = to; }
    return false;
  }

  // ---------- PoH ----------
  async function pohStatus(accountId) {
    if (!accountId) throw new Error('missing accountId');
    return postJSON('/poh/status', { account_id: String(accountId) });
  }
  function isExpired(nft) {
    if (!nft || !nft.expires_at) return false;
    return nowSec() > Number(nft.expires_at);
  }

  // ---------- Session (localStorage; no secrets) ----------
  function getAccount() { return localStorage.getItem(LS_ACCT) || null; }
  function setAccount(id) { if (id) localStorage.setItem(LS_ACCT, String(id)); }
  function logout() { localStorage.removeItem(LS_ACCT); localStorage.removeItem(LS_TOKEN); }

  function getToken() { return localStorage.getItem(LS_TOKEN) || null; }
  function setToken(tok) { if (tok) localStorage.setItem(LS_TOKEN, String(tok)); }

  // ---------- Guard ----------
  // opts: {
  //   minTier: number = 1,
  //   loginUrl: 'login.html',
  //   onboardingUrl: 'onboarding.html',
  //   fallback: 'index.html',          // used if node unreachable
  //   enforceHttps: true
  // }
  async function requireGuard(opts = {}) {
    const minTier       = Number(opts.minTier ?? 1);
    const loginUrl      = opts.loginUrl || 'login.html';
    const onboardingUrl = opts.onboardingUrl || 'onboarding.html';
    const fallback      = opts.fallback || 'index.html';
    const enforceHttps  = opts.enforceHttps !== false; // default true
    const next = urlParam('next') || window.location.pathname + window.location.search;

    if (enforceHttps) {
      if (!ensureHttps()) return false; // will redirect
    }

    const acct = getAccount();
    if (!acct) {
      const to = setParam(page(loginUrl), 'next', next);
      window.location.replace(to);
      return false;
    }

    let s;
    try {
      s = await pohStatus(acct);
    } catch (e) {
      // Node unreachable => send to fallback (dashboard/home) rather than loop on login
      const to = setParam(page(fallback), 'reason', 'node_unreachable');
      window.location.replace(setParam(to, 'next', next));
      return false;
    }

    let effectiveTier = s.tier || 0;
    if (isExpired(s.nft)) effectiveTier = 0;

    if (effectiveTier < minTier) {
      // Force redirect to onboarding to reapply or upgrade tier
      let to = setParam(page(onboardingUrl), 'next', next);
      to = setParam(to, 'reason', 'low_tier');
      window.location.replace(to);
      return false;
    }

    return true;
  }

  // ---------- Tokens (apply scope) ----------
  async function issueApplyToken() {
    const acct = getAccount();
    if (!acct) throw new Error('not logged in');
    const r = await postJSON('/auth/apply', { account_id: acct });
    setToken(r.token);
    return r;
  }
  async function checkApplyToken(tok = null) {
    const t = tok || getToken();
    if (!t) throw new Error('no token');
    return postJSON('/auth/check', { token: t, scope: 'apply' });
  }

  // ---------- Public API ----------
  window.weallAuth = {
    // session
    getAccount, setAccount, logout,
    getToken, setToken,

    // status
    pohStatus,

    // guard
    require: requireGuard,

    // tokens
    issueApplyToken, checkApplyToken,

    // optional
    ensureHttps, isExpired,
  };
})();
