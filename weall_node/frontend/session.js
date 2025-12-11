/**
 * weall_node/frontend/session.js
 * ----------------------------------------------------------
 * Frontend session + roles helper.
 *
 * Responsibilities:
 *  - Track signed-in user in localStorage ("weall_user_id").
 *  - Call `/roles/effective/me` with X-WeAll-User.
 *  - Expose helpers:
 *      - WeAllSession.loadSession()
 *      - WeAllSession.getSession()
 *      - WeAllSession.renderSignedInBanner(elementId)
 *      - WeAllSession.hasCapability(capability)
 *      - WeAllSession.requireCapability(capability, onFail)
 *
 * NOTE: This file assumes:
 *  - Backend implements GET /roles/effective/me
 *  - That endpoint uses X-WeAll-User header
 */

(function () {
  const STORAGE_KEY_USER = "weall_user_id";
  const STORAGE_KEY_SESSION = "weall_session_cache";

  // If you ever change your API base path, set this on window before loading:
  //   window.WEALL_API_BASE = "http://127.0.0.1:8000";
  const API_BASE = window.WEALL_API_BASE || "";

  let _session = null;
  let _loadingPromise = null;

  // --------------------------------------------------------
  // Signed-in user ID helpers
  // --------------------------------------------------------

  function setSignedInUser(userId) {
    if (!userId) return;
    localStorage.setItem(STORAGE_KEY_USER, userId);
  }

  function getSignedInUser() {
    return localStorage.getItem(STORAGE_KEY_USER) || "";
  }

  // --------------------------------------------------------
  // Fetch effective role profile
  // --------------------------------------------------------

  async function fetchEffectiveProfile() {
    const userId = getSignedInUser();
    if (!userId) {
      throw new Error("No signed-in user found in localStorage");
    }

    const resp = await fetch(API_BASE + "/roles/effective/me", {
      method: "GET",
      headers: {
        "X-WeAll-User": userId,
        "Accept": "application/json",
      },
      credentials: "include",
    });

    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(
        "Failed to load effective role profile: " + resp.status + " " + text
      );
    }

    const data = await resp.json();
    // Normalize capabilities as a Set for easy checks
    const caps = Array.isArray(data.capabilities) ? data.capabilities : [];
    const session = {
      user_id: data.user_id || userId,
      poh_tier: data.poh_tier || 0,
      flags: data.flags || {},
      capabilities: new Set(caps),
      raw: data,
    };

    _session = session;
    try {
      localStorage.setItem(
        STORAGE_KEY_SESSION,
        JSON.stringify({
          user_id: session.user_id,
          poh_tier: session.poh_tier,
          flags: session.flags,
          capabilities: caps,
          cached_at: Date.now(),
        })
      );
    } catch (e) {
      // non-fatal
      console.warn("Failed to cache session:", e);
    }

    return session;
  }

  function restoreCachedSession() {
    if (_session) return _session;
    const raw = localStorage.getItem(STORAGE_KEY_SESSION);
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      const caps = Array.isArray(parsed.capabilities)
        ? parsed.capabilities
        : [];
      _session = {
        user_id: parsed.user_id,
        poh_tier: parsed.poh_tier,
        flags: parsed.flags || {},
        capabilities: new Set(caps),
        raw: parsed,
      };
      return _session;
    } catch (e) {
      console.warn("Failed to parse cached session:", e);
      return null;
    }
  }

  // --------------------------------------------------------
  // Public API
  // --------------------------------------------------------

  async function loadSession(options) {
    options = options || {};
    const { forceRefresh = false } = options;

    if (!forceRefresh) {
      const cached = restoreCachedSession();
      if (cached) return cached;
    }

    if (_loadingPromise) return _loadingPromise;

    _loadingPromise = fetchEffectiveProfile()
      .catch((err) => {
        console.error("loadSession failed:", err);
        _session = null;
        throw err;
      })
      .finally(() => {
        _loadingPromise = null;
      });

    return _loadingPromise;
  }

  function getSession() {
    if (_session) return _session;
    return restoreCachedSession();
  }

  function hasCapability(capability) {
    const sess = getSession();
    if (!sess) return false;
    return sess.capabilities.has(capability);
  }

  function requireCapability(capability, onFail) {
    if (!hasCapability(capability)) {
      if (typeof onFail === "function") {
        try {
          onFail();
        } catch (e) {
          console.error("onFail callback threw:", e);
        }
      } else {
        alert("You do not have permission to perform this action.");
      }
      return false;
    }
    return true;
  }

  function renderSignedInBanner(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const sess = getSession();
    if (!sess) {
      el.innerText = "Not signed in";
      return;
    }

    const tier = sess.poh_tier;
    const flags = sess.flags || {};
    const roles = [];

    if (flags.wants_juror) roles.push("juror");
    if (flags.wants_validator) roles.push("validator");
    if (flags.wants_operator) roles.push("operator");
    if (flags.wants_emissary) roles.push("emissary");
    if (flags.wants_creator !== false) roles.push("creator");

    const rolesText = roles.length ? " · " + roles.join(", ") : "";
    el.innerText =
      "Signed in as " +
      sess.user_id +
      " · PoH Tier " +
      tier +
      rolesText;
  }

  // Expose on window
  window.WeAllSession = {
    setSignedInUser,
    getSignedInUser,
    loadSession,
    getSession,
    hasCapability,
    requireCapability,
    renderSignedInBanner,
  };

  // Optional: auto-load session on pages that care.
  // Call WeAllSession.loadSession() in page-specific init scripts.
})();
