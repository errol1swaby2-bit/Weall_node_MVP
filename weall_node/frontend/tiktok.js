// weall_node/frontend/tiktok.js
// Vertical home feed + composer + basic nav

(function () {
  "use strict";

  // ---------- Helpers ----------

  function $(id) {
    return document.getElementById(id);
  }

  function apiFetch(path, opts) {
    opts = opts || {};
    if (!opts.headers) opts.headers = {};
    // default JSON for non-FormData POSTs
    if (opts.body && !(opts.body instanceof FormData)) {
      opts.headers["Content-Type"] =
        opts.headers["Content-Type"] || "application/json";
    }
    opts.credentials = opts.credentials || "include";
    var url = path;
    if (path[0] === "/") {
      url = path;
    }
    return fetch(url, opts);
  }

  function getCurrentUser() {
    // 1) Prefer Session helper from session.js
    try {
      if (window.Session && typeof Session.get === "function") {
        var sess = Session.get();
        if (sess && sess.account) {
          return { id: sess.account, email: sess.account };
        }
      }
    } catch (e) {
      console.warn("Session.get failed in getCurrentUser:", e);
    }

    // 2) Fallback to various localStorage keys from older builds
    try {
      var acct =
        (window.localStorage &&
          (localStorage.getItem("wa.account") ||
            localStorage.getItem("weall.account") ||
            localStorage.getItem("weall_user") ||
            localStorage.getItem("weall_acct"))) ||
        null;

      if (acct) {
        acct = String(acct).trim();
        if (acct) return { id: acct, email: acct };
      }
    } catch (e2) {
      console.warn("localStorage fallback failed in getCurrentUser:", e2);
    }

    // 3) No session detected
    return null;
  }

  function timeAgo(ts) {
    if (!ts) return "";
    var now = Math.floor(Date.now() / 1000);
    if (ts > 1e12) {
      // ms → s
      ts = Math.floor(ts / 1000);
    }
    var diff = now - ts;
    if (diff < 5) return "now";
    if (diff < 60) return diff + "s";
    var m = Math.floor(diff / 60);
    if (m < 60) return m + "m";
    var h = Math.floor(m / 60);
    if (h < 48) return h + "h";
    var d = Math.floor(h / 24);
    if (d < 365) return d + "d";
    var y = Math.floor(d / 365);
    return y + "y";
  }

  function ipfsToHttp(url) {
    if (!url) return null;
    if (url.indexOf("ipfs://") === 0) {
      var cid = url.slice("ipfs://".length);
      return "/ipfs/" + cid;
    }
    return url;
  }

  // ---------- Toast ----------

  var toastTimer = null;

  function showToast(msg, kind) {
    var el = $("toast");
    if (!el) return;
    el.textContent = msg || "";
    el.className = "";
    el.classList.add("show");
    if (kind === "ok") el.classList.add("ok");
    else if (kind === "warn") el.classList.add("warn");
    else if (kind === "err") el.classList.add("err");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      el.classList.remove("show", "ok", "warn", "err");
    }, 2600);
  }

  // ---------- Sheet (composer) ----------

  function openSheet() {
    var b = $("waSheetBackdrop");
    if (!b) return;
    b.classList.add("open");
    hideSheetError();
  }

  function closeSheet() {
    var b = $("waSheetBackdrop");
    if (!b) return;
    b.classList.remove("open");
    hideSheetError();
  }

  function showSheetError(msg) {
    var el = $("waSheetError");
    if (!el) return;
    el.textContent = msg || "Something went wrong.";
    el.style.display = "block";
  }

  function hideSheetError() {
    var el = $("waSheetError");
    if (!el) return;
    el.textContent = "";
    el.style.display = "none";
  }

  // ---------- Feed rendering ----------

  function renderFeed(items) {
    var feed = $("waFeed");
    if (!feed) return;
    feed.innerHTML = "";

    if (!items || !items.length) {
      var empty = document.createElement("div");
      empty.className = "wa-slide";
      empty.innerHTML =
        '<div class="wa-text">No posts yet. Tap the + button to share something.</div>';
      feed.appendChild(empty);
      return;
    }

    items.forEach(function (p) {
      feed.appendChild(renderSlide(p));
    });
  }

  function renderSlide(post) {
    var el = document.createElement("article");
    el.className = "wa-slide";

    var author = post.author || "someone";
    var handle = (post.handle || author || "").toString();
    var text = (post.text || "").toString();
    var ts = post.time || post.created_at || post.ts;
    var ago = timeAgo(ts);

    var pohTier = post.poh_tier || post.pohTier || null;

    // header
    var header = document.createElement("div");
    header.className = "wa-slide-header";

    var left = document.createElement("div");
    left.className = "wa-slide-author";
    var avatar = document.createElement("div");
    avatar.className = "wa-avatar";
    left.appendChild(avatar);

    var at = document.createElement("div");
    at.className = "wa-author-text";

    var name = document.createElement("div");
    name.className = "wa-author-name";
    name.textContent = handle;
    at.appendChild(name);

    var meta = document.createElement("div");
    meta.className = "wa-author-meta";
    var tspan = document.createElement("span");
    tspan.textContent = ago || "";
    meta.appendChild(tspan);

    if (pohTier) {
      var badge = document.createElement("span");
      badge.className = "wa-poh tier" + pohTier;
      badge.textContent = "PoH " + pohTier;
      meta.appendChild(badge);
    }

    at.appendChild(meta);
    left.appendChild(at);

    var right = document.createElement("div");
    right.className = "wa-slide-menu";
    var dotBadge = document.createElement("div");
    dotBadge.className = "wa-badge-small";
    dotBadge.textContent = (post.group || "Public").toString();
    right.appendChild(dotBadge);

    var dots = document.createElement("button");
    dots.className = "wa-dots";
    dots.innerHTML = "⋯";
    dots.onclick = function (e) {
      e.stopPropagation();
      showToast("Post menu coming soon.", "warn");
    };
    right.appendChild(dots);

    header.appendChild(left);
    header.appendChild(right);

    // body
    var body = document.createElement("div");
    body.className = "wa-slide-body";

    if (
      post.media_url &&
      (post.content_type === "video" ||
        (post.tags || []).indexOf("video") >= 0)
    ) {
      var shell = document.createElement("div");
      shell.className = "wa-video-shell";
      var v = document.createElement("video");
      v.setAttribute("playsinline", "playsinline");
      v.setAttribute("controls", "controls");
      v.src = ipfsToHttp(post.media_url);
      shell.appendChild(v);

      var label = document.createElement("div");
      label.className = "wa-video-label";
      label.textContent = "Short video";
      shell.appendChild(label);

      body.appendChild(shell);
    }

    if (text) {
      var t = document.createElement("div");
      t.className = "wa-text";
      t.textContent = text;
      if (text.length > 180) t.classList.add("more");
      body.appendChild(t);
    }

    // footer
    var footer = document.createElement("div");
    footer.className = "wa-slide-footer";

    var leftF = document.createElement("div");
    leftF.className = "wa-footer-left";

    var likes = document.createElement("div");
    likes.className = "wa-footer-stat";
    likes.innerHTML = "<span>♡</span>" + (post.likes || 0);
    leftF.appendChild(likes);

    var comments = document.createElement("div");
    comments.className = "wa-footer-stat";
    comments.innerHTML = "<span>💬</span>" + (post.comments || 0);
    leftF.appendChild(comments);

    var rightF = document.createElement("div");
    rightF.className = "wa-footer-right";

    var btnOpenComments = document.createElement("button");
    btnOpenComments.className = "wa-footer-button";
    btnOpenComments.innerHTML = "<span>💬</span><span>Discuss</span>";
    btnOpenComments.onclick = function () {
      showToast("Comments not wired yet.", "warn");
    };

    rightF.appendChild(btnOpenComments);

    footer.appendChild(leftF);
    footer.appendChild(rightF);

    el.appendChild(header);
    el.appendChild(body);
    el.appendChild(footer);

    return el;
  }

  function loadFeed() {
    apiFetch("/content/feed", {
      method: "GET",
    })
      .then(function (res) {
        if (!res.ok) throw new Error("feed " + res.status);
        return res.json();
      })
      .then(function (data) {
        var items = data.items || data.posts || data.feed || [];
        renderFeed(items);
      })
      .catch(function (err) {
        console.warn("failed to load feed:", err);
        showToast("Couldn't load feed.", "err");
      });
  }

  // ---------- Post composer ----------

  function promptTextPost() {
    var text = window.prompt("Share something with WeAll:");
    if (!text) return;
    text = String(text || "").trim();
    if (!text) return;

    var user = getCurrentUser();
    if (!user || (!user.id && !user.email)) {
      showSheetError("Please sign in before posting.");
      return;
    }
    var author = user.id || user.email;

    apiFetch("/content/post", {
      method: "POST",
      body: JSON.stringify({
        author: author,
        text: text,
        tags: [],
      }),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("post " + res.status);
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function () {
        closeSheet();
        return loadFeed();
      })
      .catch(function (err) {
        console.warn("text post failed:", err);
        showSheetError(
          "We couldn't publish your text post. Please try again."
        );
      });
  }

  function startVideoFlow() {
    var input = $("waVideoInput");
    if (!input) return;
    input.value = "";
    input.click();
  }

  function handleVideoSelected(file) {
    if (!file) return;

    // Guard for low-memory devices
    var maxBytes = 16 * 1024 * 1024; // 16MB
    if (file.size && file.size > maxBytes) {
      showToast("Video is too large for this device. Try a shorter clip.", "warn");
      return;
    }

    var user = getCurrentUser();
    if (!user || (!user.id && !user.email)) {
      showSheetError("Please sign in before uploading.");
      return;
    }
    var author = user.id || user.email;

    var fd = new FormData();
    fd.append("file", file);
    fd.append("visibility", "private");

    apiFetch("/content/upload", {
      method: "POST",
      body: fd,
    })
      .then(function (res) {
        if (!res.ok) throw new Error("upload " + res.status);
        return res.json();
      })
      .then(function (body) {
        var cid = body.cid || body.Hash || null;
        var url = body.url || (cid ? "ipfs://" + cid : null);
        if (!url) {
          throw new Error("No media URL returned from upload.");
        }
        return apiFetch("/content/post", {
          method: "POST",
          body: JSON.stringify({
            author: author,
            text: "Shared a short video",
            tags: ["video"],
            media_url: url,
            content_type: "video",
          }),
        });
      })
      .then(function (res) {
        if (!res.ok) throw new Error("post-with-video " + res.status);
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function () {
        closeSheet();
        return loadFeed();
      })
      .catch(function (err) {
        console.warn("video upload flow failed:", err);
        showSheetError(
          "We couldn't upload this video. Try a smaller one or use text for now."
        );
      });
  }

  // ---------- Nav wiring ----------

  function wireNav() {
    var fab = $("waFab");
    if (fab) fab.onclick = openSheet;

    var sb = $("waSheetBackdrop");
    var closeBtn = $("waSheetClose");
    if (closeBtn) closeBtn.onclick = closeSheet;
    if (sb) {
      sb.addEventListener("click", function (ev) {
        if (ev.target === sb) closeSheet();
      });
    }

    var optText = $("waOptText");
    if (optText) optText.onclick = promptTextPost;

    var optVideo = $("waOptVideo");
    if (optVideo) optVideo.onclick = startVideoFlow;

    var vidInput = $("waVideoInput");
    if (vidInput) {
      vidInput.addEventListener("change", function () {
        var f = vidInput.files && vidInput.files[0];
        handleVideoSelected(f);
      });
    }

    // Bottom nav tabs
    var tabHome = $("waTabHome");
    if (tabHome) {
      tabHome.onclick = function () {
        window.location.href = "/frontend/index.html";
      };
    }

    var tabGov = $("waTabGov");
    var btnGov = $("waBtnGov");
    function goGov() {
      window.location.href = "/frontend/governance.html";
    }
    if (tabGov) tabGov.onclick = goGov;
    if (btnGov) btnGov.onclick = goGov;

    var tabInbox = $("waTabInbox");
    var btnInbox = $("waBtnInbox");
    function goInbox() {
      window.location.href = "/frontend/messaging.html";
    }
    if (tabInbox) tabInbox.onclick = goInbox;
    if (btnInbox) btnInbox.onclick = goInbox;

    var tabProfile = $("waTabProfile");
    if (tabProfile) {
      tabProfile.onclick = function () {
        window.location.href = "/frontend/profile.html";
      };
    }

    // Right-rail buttons – stubbed with toasts for now
    var likeBtn = $("waLike");
    var commentBtn = $("waComment");
    var shareBtn = $("waShare");
    if (likeBtn) {
      likeBtn.onclick = function () {
        showToast("Reactions are coming soon.", "warn");
      };
    }
    if (commentBtn) {
      commentBtn.onclick = function () {
        showToast("Comments are coming soon.", "warn");
      };
    }
    if (shareBtn) {
      shareBtn.onclick = function () {
        showToast("Sharing is coming soon.", "warn");
      };
    }
  }

  // ---------- Init ----------

  function init() {
    wireNav();
    loadFeed();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
