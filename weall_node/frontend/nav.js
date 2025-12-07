// weall_node/frontend/nav.js
// -----------------------------------------------------------------------------
// Lightweight shared navbar for WeAll frontends.
//
// - Injects a small top nav bar into any page that includes this script.
// - Uses weallAuth.pohStatus() if available to detect PoH tier.
// - Hides juror / disputes / treasury links unless user is high tier.
// - Never touches secrets; only reads public-ish session hints.
//
// Usage in any HTML page (near the end of <body>, AFTER auth.js/session.js):
//   <script src="/frontend/auth.js"></script>
//   <script src="/frontend/session.js"></script>
//   <script src="/frontend/nav.js"></script>
// -----------------------------------------------------------------------------

(function () {
  const NAV_ID = "wa-nav";
  const NAV_STYLE_ID = NAV_ID + "-style";

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------

  function ensureStyles() {
    if (document.getElementById(NAV_STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = NAV_STYLE_ID;
    style.textContent = `
      :root {
        --wa-nav-bg: rgba(2, 6, 23, 0.96);
        --wa-nav-border: rgba(15, 23, 42, 0.85);
        --wa-nav-fg: #e5e7eb;
        --wa-nav-muted: #9ca3af;
        --wa-nav-accent: #22c55e;
      }

      #${NAV_ID} {
        position: sticky;
        top: 0;
        z-index: 50;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        background: linear-gradient(to bottom,
          rgba(15, 23, 42, 0.98),
          rgba(15, 23, 42, 0.92),
          rgba(15, 23, 42, 0.88)
        );
        border-bottom: 1px solid var(--wa-nav-border);
      }

      .wa-nav-inner {
        max-width: 1040px;
        margin: 0 auto;
        padding: 8px 12px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        font-family: system-ui, -apple-system, BlinkMacSystemFont,
                     "Segoe UI", sans-serif;
        color: var(--wa-nav-fg);
        font-size: 13px;
      }

      .wa-nav-left,
      .wa-nav-right {
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
      }

      .wa-nav-logo {
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        font-size: 12px;
        opacity: 0.9;
      }

      .wa-nav-links {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }

      .wa-nav-link {
        padding: 4px 9px;
        border-radius: 999px;
        border: 1px solid transparent;
        color: var(--wa-nav-muted);
        text-decoration: none;
        line-height: 1.3;
      }

      .wa-nav-link:hover {
        border-color: rgba(148, 163, 184, 0.6);
        color: var(--wa-nav-fg);
        background: rgba(15, 23, 42, 0.95);
      }

      .wa-nav-link.active {
        border-color: rgba(34, 197, 94, 0.9);
        color: var(--wa-nav-accent);
        background: rgba(22, 163, 74, 0.1);
      }

      .wa-nav-user {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        color: var(--wa-nav-muted);
      }

      .wa-nav-user-id {
        color: var(--wa-nav-fg);
        font-weight: 500;
      }

      .wa-nav-pill {
        border-radius: 999px;
        padding: 3px 8px;
        border: 1px solid rgba(148, 163, 184, 0.7);
        background: rgba(15, 23, 42, 0.96);
        font-size: 11px;
        display: inline-flex;
        align-items: center;
        gap: 5px;
      }

      .wa-nav-dot {
        width: 7px;
        height: 7px;
        border-radius: 999px;
        background: #64748b;
      }

      .wa-nav-dot.tier1 { background: #22c55e; }
      .wa-nav-dot.tier2 { background: #22c55e; box-shadow: 0 0 0 2px rgba(34,197,94,0.6); }
      .wa-nav-dot.tier3 { background: #facc15; box-shadow: 0 0 0 2px rgba(234,179,8,0.6); }

      .wa-nav-btn {
        border-radius: 999px;
        padding: 4px 9px;
        border: 1px solid rgba(148, 163, 184, 0.7);
        background: rgba(15, 23, 42, 0.96);
        color: var(--wa-nav-fg);
        font-size: 11px;
        cursor: pointer;
      }

      .wa-nav-btn:hover {
        background: rgba(15, 23, 42, 1);
      }

      @media (max-width: 640px) {
        .wa-nav-inner {
          padding: 6px 8px;
        }
        .wa-nav-links {
          display: none;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function normalizeUserId(raw) {
    if (!raw) return null;
    let v = String(raw).trim();
    if (!v) return null;
    if (v.startsWith("@")) return v;
    if (v.includes("@")) return "@" + v.split("@", 1)[0];
    return v;
  }

  function currentPathKey() {
    const p = window.location.pathname || "";
    if (p.includes("tiktok")) return "feed";
    if (p.includes("governance")) return "gov";
    if (p.includes("profile")) return "profile";
    if (p.includes("onboarding")) return "onboarding";
    if (p.includes("juror")) return "juror";
    if (p.includes("disputes")) return "disputes";
    if (p.includes("treasury")) return "treasury";
    return "";
  }

  async function detectSessionAndTier() {
    // 1) Try weallAuth if available
    let acct = null;
    let tier = 0;
    let status = "guest";

    try {
      if (window.weallAuth) {
        if (typeof weallAuth.getAccount === "function") {
          acct = weallAuth.getAccount();
        }
        if (typeof weallAuth.pohStatus === "function" && acct) {
          const s = await weallAuth.pohStatus(acct);
          tier = Number(s.tier || 0);
          status = s.status || "ok";
        }
      }
    } catch (e) {
      // ignore and fall through
    }

    // 2) Try CurrentUser helper (session.js)
    if (!acct && typeof window.CurrentUser === "function") {
      try {
        acct = CurrentUser();
      } catch (e) {}
    }

    // 3) Fallback: localStorage heuristics
    if (!acct) {
      try {
        acct = localStorage.getItem("weall.account") ||
               localStorage.getItem("weall_user") ||
               localStorage.getItem("weall_acct") ||
               "";
      } catch (e) {}
    }

    return {
      accountId: normalizeUserId(acct),
      tier,
      status
    };
  }

  function createLink(href, label, key, activeKey) {
    const a = document.createElement("a");
    a.href = href;
    a.textContent = label;
    a.className = "wa-nav-link";
    if (key && activeKey === key) {
      a.classList.add("active");
    }
    return a;
  }

  function renderUserPill(container, sessionInfo) {
    const { accountId, tier, status } = sessionInfo;

    const userBox = document.createElement("div");
    userBox.className = "wa-nav-user";

    if (accountId) {
      const spanId = document.createElement("span");
      spanId.className = "wa-nav-user-id";
      spanId.textContent = accountId;
      userBox.appendChild(spanId);
    } else {
      const spanAnon = document.createElement("span");
      spanAnon.className = "wa-nav-user-id";
      spanAnon.textContent = "Guest";
      userBox.appendChild(spanAnon);
    }

    const pill = document.createElement("span");
    pill.className = "wa-nav-pill";
    const dot = document.createElement("span");
    dot.className = "wa-nav-dot";

    if (tier >= 3) dot.classList.add("tier3");
    else if (tier >= 2) dot.classList.add("tier2");
    else if (tier >= 1) dot.classList.add("tier1");

    const label = document.createElement("span");
    if (!accountId) {
      label.textContent = "Tier 0 · " + (status || "guest");
    } else {
      label.textContent = "Tier " + (tier || 0) + " · " + (status || "ok");
    }

    pill.appendChild(dot);
    pill.appendChild(label);
    userBox.appendChild(pill);

    container.appendChild(userBox);
  }

  function renderAuthButton(container, sessionInfo) {
    const { accountId } = sessionInfo;
    const btn = document.createElement("button");
    btn.className = "wa-nav-btn";

    if (!accountId) {
      btn.textContent = "Log in";
      btn.onclick = () => {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = "/frontend/login.html?next=" + next;
      };
    } else {
      btn.textContent = "Log out";
      btn.onclick = async () => {
        try {
          // Prefer explicit logout endpoint if wired later
          if (window.weallAuth && typeof weallAuth.logout === "function") {
            await weallAuth.logout();
          } else if (window.Session && typeof Session.logout === "function") {
            await Session.logout();
          } else {
            // Fallback: clear local hints
            try {
              localStorage.removeItem("weall.account");
              localStorage.removeItem("weall_user");
              localStorage.removeItem("weall_acct");
            } catch (e) {}
          }
        } catch (e) {
          console.warn("Logout failed", e);
        } finally {
          window.location.href = "/frontend/login.html";
        }
      };
    }

    container.appendChild(btn);
  }

  async function renderNav() {
    if (document.getElementById(NAV_ID)) return; // already present
    ensureStyles();

    const body = document.body || document.documentElement;
    if (!body) return;

    const activeKey = currentPathKey();
    const nav = document.createElement("nav");
    nav.id = NAV_ID;

    const inner = document.createElement("div");
    inner.className = "wa-nav-inner";

    const left = document.createElement("div");
    left.className = "wa-nav-left";

    const logo = document.createElement("div");
    logo.className = "wa-nav-logo";
    logo.textContent = "WEALL NODE";
    left.appendChild(logo);

    const links = document.createElement("div");
    links.className = "wa-nav-links";

    links.appendChild(createLink("/frontend/tiktok.html", "Feed", "feed", activeKey));
    links.appendChild(createLink("/frontend/governance.html", "Governance", "gov", activeKey));
    links.appendChild(createLink("/frontend/profile.html", "Profile", "profile", activeKey));
    links.appendChild(createLink("/frontend/onboarding.html", "Onboarding", "onboarding", activeKey));

    // Right side will decide whether to show juror/treasury links
    const right = document.createElement("div");
    right.className = "wa-nav-right";

    inner.appendChild(left);
    inner.appendChild(links);
    inner.appendChild(right);
    nav.appendChild(inner);

    // Insert at top of body
    if (body.firstChild) {
      body.insertBefore(nav, body.firstChild);
    } else {
      body.appendChild(nav);
    }

    // After mount, detect session & tier, conditionally add higher-tier links
    try {
      const sess = await detectSessionAndTier();

      // High-tier links:
      if (sess.accountId && sess.tier >= 2) {
        links.appendChild(createLink("/frontend/treasury.html", "Treasury", "treasury", activeKey));
      }
      if (sess.accountId && sess.tier >= 3) {
        links.appendChild(createLink("/frontend/disputes_overview.html", "Disputes", "disputes", activeKey));
        links.appendChild(createLink("/frontend/juror.html", "Juror", "juror", activeKey));
      }

      renderUserPill(right, sess);
      renderAuthButton(right, sess);
    } catch (e) {
      console.warn("nav.js: failed to detect session/tier", e);
      // Fallback: anonymous
      renderUserPill(right, { accountId: null, tier: 0, status: "guest" });
      renderAuthButton(right, { accountId: null, tier: 0, status: "guest" });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderNav);
  } else {
    renderNav();
  }
})();
