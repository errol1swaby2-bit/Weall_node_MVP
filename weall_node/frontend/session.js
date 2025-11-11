
// === Root navigation sanitizer (auto-injected) ===
(function(){
  var LOGIN = "/frontend/login.html";
  function normalize(url){
    try{
      if(!url) return url;
      // Absolute root or origin-only
      if(url === "/" || url === window.location.origin || url === window.location.origin + "/") return LOGIN;
      // Pure relative "/" too
      if(typeof url === "string" && url.trim() === "/") return LOGIN;
    }catch(e){}
    return url;
  }

  // Patch Location methods
  try{
    var L = window.location;
    var proto = Location && Location.prototype ? Location.prototype : null;
    var rep = (proto && proto.replace) ? proto.replace : L.replace.bind(L);
    var asn = (proto && proto.assign) ? proto.assign : L.assign.bind(L);

    function safeReplace(u){ return rep.call(this, normalize(u)||u); }
    function safeAssign(u){ return asn.call(this, normalize(u)||u); }

    if(proto){
      if(proto.replace !== safeReplace) proto.replace = safeReplace;
      if(proto.assign  !== safeAssign ) proto.assign  = safeAssign;
    }else{
      // fallback
      window.location.replace = safeReplace;
      window.location.assign  = safeAssign;
    }

    // Intercept setting .href
    try{
      var hrefDesc = Object.getOwnPropertyDescriptor(Location.prototype, "href");
      if(hrefDesc && hrefDesc.set){
        var origSet = hrefDesc.set;
        Object.defineProperty(Location.prototype, "href", {
          configurable: true,
          enumerable: hrefDesc.enumerable,
          get: hrefDesc.get,
          set: function(v){ origSet.call(this, normalize(v)||v); }
        });
      }
    }catch(_){}
  }catch(_){}

  // Patch history state mutations
  try{
    var op = history.pushState;
    var or = history.replaceState;
    history.pushState = function(state, title, url){ return op.call(this, state, title, normalize(url)||url); }
    history.replaceState = function(state, title, url){ return or.call(this, state, title, normalize(url)||url); }
  }catch(_){}

  // Rewrite DOM attributes that try to hit "/"
  function rewriteDom(root){
    if(!root) root = document;
    root.querySelectorAll('[href="/"], [src="/"], [action="/"]').forEach(function(el){
      if(el.hasAttribute("href"))   el.setAttribute("href",   LOGIN);
      if(el.hasAttribute("src"))    el.setAttribute("src",    LOGIN);
      if(el.hasAttribute("action")) el.setAttribute("action", LOGIN);
    });
  }

  // On submit to "/", reroute to login without posting to root
  document.addEventListener("submit", function(e){
    try{
      var f = e.target;
      if(f && (f.getAttribute("action")==="/" || f.action === window.location.origin + "/")){
        e.preventDefault();
        window.location.assign(LOGIN);
      }
    }catch(_){}
  }, true);

  // Initial pass + observe new nodes
  if(document.readyState === "loading"){
    document.addEventListener("DOMContentLoaded", function(){ rewriteDom(); });
  } else { rewriteDom(); }

  try{
    var obs = new MutationObserver(function(muts){
      for (var m of muts){
        for (var n of (m.addedNodes||[])){
          if(n.nodeType === 1) rewriteDom(n);
        }
      }
    });
    obs.observe(document.documentElement, {subtree:true, childList:true});
  }catch(_){}

  // As a last resort, if pathname is ever "/" (some code did location.pathname="/"), bounce to login.
  try{
    setInterval(function(){
      if(location.pathname === "/"){ location.replace(LOGIN); }
    }, 300);
  }catch(_){}
})();


// --- patched next= handling ---
(function(){
  try{
    const u = new URL(location.href);
    const next = u.searchParams.get('next') || "";
    const adv  = (u.searchParams.get('advanced') === '1');
    const SAFE = new Set([
      "/frontend/index.html",
      "/frontend/profile.html",
      "/frontend/settings.html",
      "/frontend/tiers.html"
    ]);
    // If next was pointing to onboarding and not advanced, ignore it.
    if (next && (SAFE.has(next) || (adv && next === "/frontend/index.html"))) {
      window.__WEALL_SAFE_NEXT__ = next;
    } else {
      window.__WEALL_SAFE_NEXT__ = "/frontend/index.html";
    }
  }catch(e){ window.__WEALL_SAFE_NEXT__ = "/frontend/index.html"; }
})();

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
      location.replace(`/frontend/login.html?next=${next}`);
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
      location.replace(`/frontend/login.html?next=${next}`);
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
    location.replace(`/frontend/login.html?next=${next}`);
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
