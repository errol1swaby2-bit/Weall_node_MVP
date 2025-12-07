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

  function showToast(msg, kind) {
    kind = kind || "info";
    var toast = $("toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "toast";
      document.body.appendChild(toast);
    }
    toast.textContent = msg || "";
    toast.className = "toast " + kind;
    toast.style.opacity = "1";
    setTimeout(function () {
      toast.style.opacity = "0";
    }, 2600);
  }

  function closeSheet() {
    var sheet = $("waSheet");
    if (sheet) sheet.style.display = "none";
    var overlay = $("waOverlay");
    if (overlay) overlay.style.display = "none";
  }

  function openSheet() {
    var sheet = $("waSheet");
    if (sheet) sheet.style.display = "block";
    var overlay = $("waOverlay");
    if (overlay) overlay.style.display = "block";
  }

  function setSheetMode(mode) {
    var textMode = $("waSheetTextMode");
    var videoMode = $("waSheetVideoMode");
    if (textMode) textMode.style.display = mode === "text" ? "block" : "none";
    if (videoMode) videoMode.style.display = mode === "video" ? "block" : "none";
  }

  // ---------- DOM builders ----------

  function renderEmptyState() {
    var root = $("waFeed");
    if (!root) return;
    root.innerHTML = "";
    var div = document.createElement("div");
    div.className = "wa-empty";
    div.textContent = "No posts yet. Be the first to share something.";
    root.appendChild(div);
  }

  function renderFeed(items) {
    var root = $("waFeed");
    if (!root) return;
    root.innerHTML = "";
    if (!items || items.length === 0) {
      renderEmptyState();
      return;
    }

    items.forEach(function (post) {
      var slide = renderPost(post);
      root.appendChild(slide);
    });
  }

  function renderPost(post) {
    var el = document.createElement("article");
    el.className = "wa-slide";

    var body = document.createElement("div");
    body.className = "wa-slide-body";

    var header = document.createElement("header");
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
    var handle = post.author || post.user_id || "anon";
    if (handle && handle.indexOf("@") !== 0) handle = "@" + handle;
    name.textContent = handle;

    var meta = document.createElement("div");
    meta.className = "wa-author-meta";

    var tspan = document.createElement("span");
    tspan.className = "wa-time";
    tspan.textContent = timeAgo(post.created_at || post.timestamp || post.ts);
    meta.appendChild(tspan);

    var pohTier = post.poh_tier || post.tier || null;
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
    dotBadge.textContent = (post.group || "Public").slice(0, 6);
    right.appendChild(dotBadge);

    header.appendChild(left);
    header.appendChild(right);

    var content = document.createElement("div");
    content.className = "wa-slide-content";

    var text = (post.text || post.caption || "").trim();
    if (text) {
      var p = document.createElement("p");
      p.className = "wa-slide-text";
      p.textContent = text;
      content.appendChild(p);
    }

    var mediaUrl = post.media_url || post.image_url || post.video_url || null;
    var contentType = post.content_type || post.type || "";

    if (mediaUrl) {
      var resolved = ipfsToHttp(mediaUrl);
      if (contentType === "video" || /\.mp4($|\?)/.test(resolved || "")) {
        var videoWrap = document.createElement("div");
        videoWrap.className = "wa-slide-video-wrap";
        var video = document.createElement("video");
        video.className = "wa-slide-video";
        video.src = resolved;
        video.controls = true;
        video.playsInline = true;
        videoWrap.appendChild(video);
        content.appendChild(videoWrap);
      } else {
        var imgWrap = document.createElement("div");
        imgWrap.className = "wa-slide-media-wrap";
        var img = document.createElement("img");
        img.className = "wa-slide-image";
        img.src = resolved;
        img.alt = "Post media";
        imgWrap.appendChild(img);
        content.appendChild(imgWrap);
      }
    }

    body.appendChild(header);
    body.appendChild(content);

    var footer = document.createElement("footer");
    footer.className = "wa-slide-footer";

    var stats = document.createElement("div");
    stats.className = "wa-stats";
    var likes = document.createElement("span");
    likes.textContent = (post.likes || 0) + " likes";
    var comments = document.createElement("span");
    comments.textContent = (post.comments || 0) + " comments";
    stats.appendChild(likes);
    stats.appendChild(comments);

    var actions = document.createElement("div");
    actions.className = "wa-actions";
    var likeBtn = document.createElement("button");
    likeBtn.className = "wa-action";
    likeBtn.textContent = "♡";
    likeBtn.onclick = function () {
      showToast("Likes are coming soon.", "info");
    };
    var commentBtn = document.createElement("button");
    commentBtn.className = "wa-action";
    commentBtn.textContent = "💬";
    commentBtn.onclick = function () {
      showToast("Comments are coming soon.", "info");
    };
    actions.appendChild(likeBtn);
    actions.appendChild(commentBtn);

    footer.appendChild(stats);
    footer.appendChild(actions);

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


  // ---------- Top bar (user + PoH) ----------

  function hydrateTopBar() {
    var topUserEl = $("waTopUser");
    var topPohEl = $("waTopPoh");

    var user = getCurrentUser();
    if (topUserEl) {
      if (user && (user.id || user.email)) {
        topUserEl.textContent = user.id || user.email;
      } else {
        topUserEl.textContent = "Guest";
      }
    }

    if (!topPohEl) return;

    apiFetch("/poh/me", { method: "GET" })
      .then(function (res) {
        if (!res.ok) throw new Error("poh " + res.status);
        return res.json();
      })
      .then(function (poh) {
        var tier = typeof poh.tier === "number" ? poh.tier : 0;
        var status = (poh.status || "ok").toLowerCase();
        var txt = "PoH: " + tier;
        if (status !== "ok") {
          txt += " · " + status;
        }
        topPohEl.textContent = txt;
        topPohEl.dataset.status = status;
      })
      .catch(function () {
        topPohEl.textContent = "PoH: –";
      });
  }

  // ---------- Post composer ----------

  function promptTextPost() {
    var text = window.prompt("Share something with WeAll:");
    if (!text) return;

    var user = getCurrentUser();
    if (!user || (!user.id && !user.email)) {
      alert("Please sign in before posting.");
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
          "We couldn't publish your post. This is a beta node; please try again."
        );
      });
  }

  function showSheetError(msg) {
    var err = $("waSheetError");
    if (!err) return;
    err.textContent = msg || "";
    err.style.display = msg ? "block" : "none";
  }

  function handleVideoFile(file) {
    if (!file) return;
    if (!file.type || file.type.indexOf("video/") !== 0) {
      showSheetError("Please choose a video file.");
      return;
    }

    var maxSizeBytes = 50 * 1024 * 1024; // 50 MB-ish for now
    if (file.size > maxSizeBytes) {
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
        console.warn("video upload/post failed:", err);
        showSheetError(
          "We couldn't upload your video yet. This is a beta node; please try again."
        );
      });
  }

  function wireComposer() {
    var fab = $("waFab");
    var overlay = $("waOverlay");
    var closeBtn = $("waSheetClose");
    var textBtn = $("waSheetText");
    var videoBtn = $("waSheetVideo");
    var textSubmit = $("waSheetTextSubmit");
    var videoSubmit = $("waSheetVideoSubmit");
    var videoInput = $("waVideoInput");

    if (fab) {
      fab.onclick = function () {
        setSheetMode("text");
        openSheet();
      };
    }
    if (overlay) {
      overlay.onclick = closeSheet;
    }
    if (closeBtn) {
      closeBtn.onclick = closeSheet;
    }
    if (textBtn) {
      textBtn.onclick = function () {
        setSheetMode("text");
      };
    }
    if (videoBtn) {
      videoBtn.onclick = function () {
        setSheetMode("video");
      };
    }
    if (textSubmit) {
      textSubmit.onclick = function () {
        promptTextPost();
      };
    }
    if (videoSubmit) {
      videoSubmit.onclick = function () {
        if (videoInput) {
          videoInput.click();
        }
      };
    }
    if (videoInput) {
      videoInput.onchange = function (ev) {
        var file = ev.target && ev.target.files && ev.target.files[0];
        handleVideoFile(file);
        // reset so selecting the same file again still fires change
        ev.target.value = "";
      };
    }
  }

  function wireNav() {
    var profileBtn = $("waProfileBtn");
    var homeBtn = $("waHomeBtn");
    var tabGov = $("waTabGov");
    var btnGov = $("waBtnGov");
    var tabInbox = $("waTabInbox");
    var btnInbox = $("waBtnInbox");
    var tabProfile = $("waTabProfile");

    if (profileBtn) {
      profileBtn.onclick = function () {
        window.location.href = "/frontend/profile.html";
      };
    }
    if (homeBtn) {
      homeBtn.onclick = function () {
        window.location.href = "/frontend/tiktok.html";
      };
    }

    function goGov() {
      window.location.href = "/frontend/governance.html";
    }
    if (tabGov) tabGov.onclick = goGov;
    if (btnGov) btnGov.onclick = goGov;

    function goInbox() {
      window.location.href = "/frontend/messaging.html";
    }
    if (tabInbox) tabInbox.onclick = goInbox;
    if (btnInbox) btnInbox.onclick = goInbox;

    if (tabProfile) {
      tabProfile.onclick = function () {
        window.location.href = "/frontend/profile.html";
      };
    }

    wireComposer();

    var shareBtn = $("waShareBtn");
    if (shareBtn) {
      shareBtn.onclick = function () {
        showToast("Sharing is coming soon.", "warn");
      };
    }
  }

  // ---------- Init ----------

  function init() {
    wireNav();
    hydrateTopBar();
    loadFeed();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
