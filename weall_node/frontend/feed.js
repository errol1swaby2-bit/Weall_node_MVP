// frontend/feed.js
// -----------------------------------------------------------------------------
// WeAll Home Feed controller
// - Loads feed from /content/feed
// - Renders posts with basic metadata
// - Handles loading / empty / error states
// - Supports simple filters: All | Mine
// - Optionally wires to a composer: #feedComposer + #feedSubmit
// -----------------------------------------------------------------------------
//
// Expected minimal HTML on index.html:
//
// <div id="feed-root"></div>
//
// Optional (for posting support):
//
// <div id="feed-composer">
//   <textarea id="feedComposer" placeholder="Share something with WeAll..."></textarea>
//   <button id="feedSubmit">Post</button>
// </div>
//
// This file is safe to include even if those elements are missing.
//

(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------------

  function $(id) {
    return document.getElementById(id);
  }

  function timeAgo(tsSeconds) {
    if (!tsSeconds) return "";
    // server gives unix seconds; convert to ms
    var now = Date.now();
    var t = typeof tsSeconds === "number" ? tsSeconds * 1000 : Date.parse(tsSeconds);
    if (!t || isNaN(t)) return "";
    var diff = Math.max(0, now - t);

    var sec = Math.floor(diff / 1000);
    if (sec < 10) return "just now";
    if (sec < 60) return sec + "s ago";

    var min = Math.floor(sec / 60);
    if (min < 60) return min + "m ago";

    var hr = Math.floor(min / 60);
    if (hr < 24) return hr + "h ago";

    var d = Math.floor(hr / 24);
    if (d < 7) return d + "d ago";

    var w = Math.floor(d / 7);
    if (w < 4) return w + "w ago";

    var M = Math.floor(d / 30);
    if (M < 12) return M + "mo ago";

    var y = Math.floor(d / 365);
    return y + "y ago";
  }

  function escapeHtml(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function shortAuthor(author) {
    if (!author) return "Unknown";
    // if it's an email, show the part before @
    var at = author.indexOf("@");
    if (at > 0) return author.slice(0, at);
    return author;
  }

  function pohBadge(tier) {
    // Only show "Unverified" when we explicitly know tier is 0.
    // If tier is null/undefined, we simply omit the badge.
    if (tier === 0) {
      return '<span class="poh-badge poh-tier-0">Unverified</span>';
    }
    if (!tier) {
      return "";
    }
    if (tier === 1) {
      return '<span class="poh-badge poh-tier-1">Tier 1</span>';
    }
    if (tier === 2) {
      return '<span class="poh-badge poh-tier-2">Tier 2</span>';
    }
    return '<span class="poh-badge poh-tier-3">Tier 3</span>';
  }

  // Try to integrate with Session.authFetch if available
  function hasSessionAuthFetch() {
    return typeof window.Session === "object" &&
      window.Session !== null &&
      typeof window.Session.authFetch === "function";
  }

  function apiFetch(path, options) {
    options = options || {};
    // Prefer Session.authFetch if it exists (it attaches auth token)
    if (hasSessionAuthFetch()) {
      return window.Session.authFetch(path, options);
    }
    return fetch(path, options);
  }

  function getCurrentUserId() {
    // Try Session / localStorage; fall back gracefully
    try {
      if (typeof window.Session === "object" && window.Session && typeof Session.getCurrentUser === "function") {
        var u = Session.getCurrentUser();
        if (u && u.id) return u.id;
        if (u && u.email) return u.email;
      }
    } catch (e) {}

    try {
      var stored = localStorage.getItem("weall.account") ||
                   localStorage.getItem("weall_user") ||
                   localStorage.getItem("weall_acct");
      if (stored) return stored;
    } catch (e2) {}

    return null;
  }

  // ---------------------------------------------------------------------------
  // Feed state
  // ---------------------------------------------------------------------------

  var Feed = {
    state: {
      posts: [],
      filter: "all", // "all" | "mine"
      loading: false,
      error: null
    },

    rootEl: null,
    tabsEl: null,
    listEl: null,
    statusEl: null,

    init: function () {
      this.rootEl = $("feed-root");
      if (!this.rootEl) {
        // No feed container; nothing to do.
        return;
      }

      this.buildSkeleton();
      this.attachTabHandlers();
      this.attachComposerHandlers();
      this.load();
    },

    buildSkeleton: function () {
      this.rootEl.innerHTML = [
        '<div id="feed-header" class="feed-header">',
        '  <div class="feed-tabs" id="feed-tabs">',
        '    <button data-filter="all" class="feed-tab feed-tab-active">All</button>',
        '    <button data-filter="mine" class="feed-tab">Mine</button>',
        '  </div>',
        '</div>',
        '<div id="feed-status" class="feed-status"></div>',
        '<div id="feed-list" class="feed-list"></div>'
      ].join("");

      this.tabsEl = $("feed-tabs");
      this.listEl = $("feed-list");
      this.statusEl = $("feed-status");
    },

    setLoading: function (isLoading) {
      this.state.loading = isLoading;
      if (!this.statusEl) return;

      if (isLoading) {
        this.statusEl.innerHTML = '<div class="feed-loading">Loading feed…</div>';
      } else if (!this.state.error) {
        this.statusEl.innerHTML = "";
      }
    },

    setError: function (msg) {
      this.state.error = msg;
      if (!this.statusEl) return;

      if (!msg) {
        this.statusEl.innerHTML = "";
        return;
      }

      this.statusEl.innerHTML = [
        '<div class="feed-error">',
        '  <span>' + escapeHtml(msg) + '</span>',
        '  <button id="feedRetry" class="feed-retry">Retry</button>',
        '</div>'
      ].join("");

      var retryBtn = $("feedRetry");
      if (retryBtn) {
        var self = this;
        retryBtn.onclick = function () {
          self.load();
        };
      }
    },

    attachTabHandlers: function () {
      if (!this.tabsEl) return;
      var self = this;
      this.tabsEl.addEventListener("click", function (ev) {
        var btn = ev.target;
        if (!btn || !btn.dataset || !btn.dataset.filter) return;
        var filter = btn.dataset.filter;
        if (filter !== "all" && filter !== "mine") return;

        self.state.filter = filter;
        self.updateTabStyles();
        self.render();
      });
    },

    updateTabStyles: function () {
      if (!this.tabsEl) return;
      var buttons = this.tabsEl.querySelectorAll(".feed-tab");
      for (var i = 0; i < buttons.length; i++) {
        var b = buttons[i];
        if (b.dataset.filter === this.state.filter) {
          b.classList.add("feed-tab-active");
        } else {
          b.classList.remove("feed-tab-active");
        }
      }
    },

    attachComposerHandlers: function () {
      var textarea = $("feedComposer");
      var button = $("feedSubmit");
      if (!textarea || !button) {
        // No composer on this page; posting will be ignored.
        return;
      }

      var self = this;

      button.addEventListener("click", function () {
        var text = textarea.value.trim();
        if (!text) return;
        button.disabled = true;

        self.submitPost(text)
          .then(function (ok) {
            if (ok) {
              textarea.value = "";
            }
          })
          .finally(function () {
            button.disabled = false;
          });
      });
    },

    submitPost: function (text) {
      var self = this;

      // Optimistic insert
      var author = getCurrentUserId() || "me";
      var optimisticPost = {
        id: "local-" + Date.now(),
        author: author,
        content: text,
        created_at: Math.floor(Date.now() / 1000),
        poh_tier: null,
        _optimistic: true
      };
      this.state.posts.unshift(optimisticPost);
      this.render();

      return apiFetch("/content/post", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ content: text })
      })
        .then(function (res) {
          if (!res.ok) {
            throw new Error("Post failed with status " + res.status);
          }
          return res.json().catch(function () { return {}; });
        })
        .then(function (body) {
          // If server returns the full post, replace optimistic post
          // Otherwise, just mark it as non-optimistic.
          var id = body && (body.id || body.post_id || body.postId);
          if (id) {
            optimisticPost.id = id;
          }
          optimisticPost._optimistic = false;
          // Optionally refresh from server for full accuracy
          self.load(/*silent*/ true);
          return true;
        })
        .catch(function (err) {
          console.warn("feed: post failed:", err);
          // Remove optimistic post on failure
          self.state.posts = self.state.posts.filter(function (p) {
            return p !== optimisticPost;
          });
          self.render();
          self.setError("We couldn't publish your post. Please try again.");
          return false;
        });
    },

    load: function (silent) {
      var self = this;
      if (!silent) {
        this.setError(null);
        this.setLoading(true);
      }

      return apiFetch("/content/feed")
        .then(function (res) {
          if (!res.ok) {
            throw new Error("Feed request failed with status " + res.status);
          }
          return res.json();
        })
        .then(function (body) {
          // Body might be { ok, posts } or just [posts]
          var posts = [];
          if (Array.isArray(body)) {
            posts = body;
          } else if (body && Array.isArray(body.posts)) {
            posts = body.posts;
          }

          // Sort newest first by created_at if available
          posts.sort(function (a, b) {
            var ta = a.created_at || a.time || 0;
            var tb = b.created_at || b.time || 0;
            return tb - ta;
          });

          self.state.posts = posts;
          self.setLoading(false);
          self.render();
        })
        .catch(function (err) {
          console.warn("feed: load failed:", err);
          self.setLoading(false);
          self.setError("We couldn't load the feed.");
        });
    },

    getFilteredPosts: function () {
      var posts = this.state.posts.slice();
      if (this.state.filter === "mine") {
        var me = getCurrentUserId();
        if (!me) return [];
        posts = posts.filter(function (p) {
          return p.author === me || p.user_id === me || p.account === me;
        });
      }
      return posts;
    },

    render: function () {
      if (!this.listEl) return;

      var posts = this.getFilteredPosts();
      if (posts.length === 0) {
        this.listEl.innerHTML = [
          '<div class="feed-empty">',
          '  <h3>No posts yet.</h3>',
          '  <p>Be the first to plant a thought in WeAll.</p>',
          "</div>"
        ].join("");
        return;
      }

      var html = [];
      for (var i = 0; i < posts.length; i++) {
        html.push(this.renderPost(posts[i]));
      }
      this.listEl.innerHTML = html.join("");
    },

    renderPost: function (post) {
      var author = post.author || post.user_id || post.account || "Unknown";
      var tier = post.poh_tier || post.poh_level || null;
      var createdAt = post.created_at || post.time || null;
      var reputation = typeof post.reputation === "number" ? post.reputation : null;
      var optimistic = !!post._optimistic;

      var repLabel = "";
      if (reputation !== null) {
        if (reputation > 0.5) repLabel = "Good standing";
        else if (reputation < -0.2) repLabel = "Low reputation";
        else repLabel = "Mixed";
      }

      var footerBits = [];
      if (createdAt) footerBits.push(timeAgo(createdAt));
      if (repLabel) footerBits.push(repLabel);
      if (optimistic) footerBits.push("syncing…");

      return [
        '<article class="feed-card">',
        '  <header class="feed-card-header">',
        '    <div class="feed-card-author">',
        '      <span class="feed-card-author-name">' + escapeHtml(shortAuthor(author)) + "</span>",
        '      ' + pohBadge(tier),
        "    </div>",
        "  </header>",
        '  <div class="feed-card-body">',
        '    <p class="feed-card-text">' + escapeHtml(post.content || post.text || "") + "</p>",
        "  </div>",
        '  <footer class="feed-card-footer">',
        '    <span class="feed-card-meta">' + escapeHtml(footerBits.join(" · ")) + "</span>",
        "  </footer>",
        "</article>"
      ].join("");
    }
  };

  // ---------------------------------------------------------------------------
  // Basic styles injection (minimal, non-intrusive)
  // ---------------------------------------------------------------------------

  (function injectStyles() {
    var css = [
      "#home-feed-section { display: none !important; }",
      
      "#feed-root { max-width: 700px; margin: 0 auto; }",
      ".feed-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }",
      ".feed-tabs { display: inline-flex; gap: 0.25rem; }",
      ".feed-tab { border: none; padding: 0.3rem 0.8rem; border-radius: 999px; font-size: 0.85rem; cursor: pointer; background: rgba(255,255,255,0.02); }",
      ".feed-tab-active { background: rgba(255,255,255,0.1); font-weight: 600; }",
      ".feed-status { margin-bottom: 0.5rem; font-size: 0.9rem; }",
      ".feed-loading { opacity: 0.8; }",
      ".feed-error { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; padding: 0.4rem 0.6rem; border-radius: 0.5rem; background: rgba(255,0,0,0.06); font-size: 0.85rem; }",
      ".feed-retry { border: none; padding: 0.2rem 0.6rem; border-radius: 999px; cursor: pointer; font-size: 0.8rem; }",
      ".feed-list { display: flex; flex-direction: column; gap: 0.6rem; }",
      ".feed-empty { text-align: center; padding: 1.5rem 0.5rem; opacity: 0.85; }",
      ".feed-empty h3 { margin: 0 0 0.25rem 0; font-size: 1.1rem; }",
      ".feed-card { padding: 0.6rem 0.7rem; border-radius: 0.8rem; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04); }",
      ".feed-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.2rem; }",
      ".feed-card-author { display: flex; align-items: center; gap: 0.4rem; }",
      ".feed-card-author-name { font-weight: 600; font-size: 0.9rem; }",
      ".poh-badge { padding: 0.05rem 0.4rem; border-radius: 999px; font-size: 0.7rem; opacity: 0.9; }",
      ".poh-tier-0 { background: rgba(128,128,128,0.18); }",
      ".poh-tier-1 { background: rgba(150,150,255,0.2); }",
      ".poh-tier-2 { background: rgba(120,190,255,0.2); }",
      ".poh-tier-3 { background: rgba(255,215,0,0.2); }",
      ".feed-card-body { margin: 0.1rem 0 0.3rem 0; }",
      ".feed-card-text { margin: 0; white-space: pre-wrap; word-wrap: break-word; font-size: 0.9rem; }",
      ".feed-card-footer { font-size: 0.75rem; opacity: 0.8; }",
      ".feed-card-meta { }"
    ].join("\n");

    var style = document.createElement("style");
    style.type = "text/css";
    style.appendChild(document.createTextNode(css));
    document.head.appendChild(style);
  })();

  // ---------------------------------------------------------------------------
  // Auto-init
  // ---------------------------------------------------------------------------

  function isFeedPage() {
    // Heuristic: look for a heading whose text starts with "Feed"
    var hs = document.querySelectorAll("h1, h2, h3");
    for (var i = 0; i < hs.length; i++) {
      var t = (hs[i].textContent || "").trim();
      if (/^Feed\b/i.test(t)) {
        return true;
      }
    }
    return false;
  }

  function initIfFeedPage() {
    var section = document.getElementById("home-feed-section");
    if (!section) return;

    if (!isFeedPage()) {
      // We are on Profile / Governance / something else; hide the mini-feed.
      section.style.display = "none";
      return;
    }

    Feed.init();
    window.WeAllFeed = Feed; // optional for debugging
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initIfFeedPage);
  } else {
    initIfFeedPage();
  }
})();
