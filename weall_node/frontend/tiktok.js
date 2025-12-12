/* weall_node/frontend/tiktok.js
 *
 * Spec-aligned PoH gates:
 * - Tier 1: view only
 * - Tier 2: like + comment
 * - Tier 3: post content + media uploads
 *
 * Backend endpoints (content.py):
 * - GET    /content/feed?scope=global|group&group_id=...&limit=...
 * - POST   /content/posts
 * - POST   /content/upload   (multipart)
 * - POST   /content/posts/{id}/like
 * - DELETE /content/posts/{id}/like
 * - GET    /content/posts/{id}/comments
 * - POST   /content/posts/{id}/comments
 */

(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // ---------- DOM mapping (defensive) ----------
  function dom() {
    const feed =
      $("#feedList") || $("#feed") || $("#posts") || $(".feed") || $(".tiktok-feed");

    const postText =
      $("#postText") || $("#text") || $("#newPostText") || $("textarea[name='text']") || $("textarea");

    const postBtn =
      $("#btnPost") || $("#postBtn") || $("#submitPost") || $("button[data-action='post']");

    const postStatus =
      $("#postStatus") || $("#status") || $(".post-status") || null;

    const feedStatus =
      $("#feedStatus") || $("#feedMsg") || $(".feed-status") || null;

    const feedMeta =
      $("#feedMeta") || $(".feed-meta") || null;

    const scope =
      $("#postScope") || $("#scope") || $("select[name='scope']") || null;

    const groupId =
      $("#postGroupId") || $("#groupId") || $("input[name='group_id']") || null;

    const file =
      $("#postFile") || $("#file") || $("input[type='file']") || null;

    const refresh =
      $("#btnRefresh") || $("#refreshBtn") || $("button[data-action='refresh']") || null;

    return { feed, postText, postBtn, postStatus, feedStatus, feedMeta, scope, groupId, file, refresh };
  }

  function setElText(el, text) {
    if (!el) return;
    el.textContent = text || "";
  }

  function setStatus(el, msg, kind = "") {
    if (!el) return;
    el.textContent = msg || "";
    el.classList.remove("ok", "err", "warn");
    if (kind) el.classList.add(kind);
  }

  function apiBase() {
    return (window.ENV && (window.ENV.VITE_API_BASE || window.ENV.API_BASE)) || "";
  }

  // ---------- session / tier ----------
  async function getSessionSafe() {
    try {
      if (window.weallAuth && typeof window.weallAuth.getSession === "function") {
        return await window.weallAuth.getSession();
      }
    } catch {}
    try {
      if (typeof window.weallGetSession === "function") {
        return await window.weallGetSession();
      }
    } catch {}
    return null;
  }

  async function getTierSafe() {
    // Prefer weallAuth.getPohMe() if present
    try {
      if (window.weallAuth && typeof window.weallAuth.getPohMe === "function") {
        const me = await window.weallAuth.getPohMe();
        return Number(me && me.tier) || 0;
      }
    } catch {}

    // Fallback: request /poh/me if your backend exposes it
    try {
      const sess = await getSessionSafe();
      if (!sess || !sess.user_id) return 0;
      const res = await fetch(apiBase() + "/poh/me", {
        method: "GET",
        credentials: "include",
        headers: { "Accept": "application/json", "X-WeAll-User": sess.user_id },
      });
      if (!res.ok) return 0;
      const data = await res.json();
      return Number(data && data.tier) || 0;
    } catch {}

    return 0;
  }

  async function jsonFetch(path, opts = {}) {
    const sess = await getSessionSafe();
    const headers = Object.assign({ Accept: "application/json" }, opts.headers || {});
    if (sess && sess.user_id) headers["X-WeAll-User"] = sess.user_id;

    const init = Object.assign({ credentials: "include" }, opts, { headers });
    if (init.body && typeof init.body !== "string") {
      init.headers["Content-Type"] = init.headers["Content-Type"] || "application/json";
      init.body = JSON.stringify(init.body);
    }

    const res = await fetch(apiBase() + path, init);
    let data = null;
    try { data = await res.json(); } catch { data = null; }

    if (!res.ok) {
      const msg = (data && (data.detail || data.error || data.message)) || `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return data;
  }

  async function uploadFile(file) {
    const sess = await getSessionSafe();
    const headers = {};
    if (sess && sess.user_id) headers["X-WeAll-User"] = sess.user_id;

    const form = new FormData();
    form.append("file", file);

    const res = await fetch(apiBase() + "/content/upload", {
      method: "POST",
      credentials: "include",
      headers,
      body: form,
    });

    let data = null;
    try { data = await res.json(); } catch { data = null; }
    if (!res.ok) {
      const msg = (data && (data.detail || data.error || data.message)) || `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return data;
  }

  // ---------- scope helpers ----------
  function normalizeScope(v) {
    const s = String(v || "").trim().toLowerCase();
    if (s === "public") return "global";
    if (s === "global") return "global";
    if (s === "group") return "group";
    return "global";
  }

  function currentScopeAndGroup() {
    const d = dom();
    const scope = normalizeScope(d.scope ? d.scope.value : "global");
    const group_id = d.groupId ? String(d.groupId.value || "").trim() : "";
    return { scope, group_id: group_id || null };
  }

  // ---------- rendering ----------
  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  function ensureCommentUI(postEl) {
    let box = postEl.querySelector(".weall-comments");
    if (box) return box;

    box = document.createElement("div");
    box.className = "weall-comments";
    box.style.marginTop = "10px";
    box.style.paddingTop = "10px";
    box.style.borderTop = "1px solid rgba(34,40,54,.7)";

    box.innerHTML = `
      <div class="muted" style="font-size:12px;margin-bottom:6px;">Comments</div>
      <div class="weall-comment-list" style="font-size:13px;"></div>
      <div class="weall-comment-compose" style="display:flex;gap:8px;margin-top:8px;">
        <input class="weall-comment-input" type="text" placeholder="Write a comment…" style="flex:1;min-width:0;">
        <button class="weall-comment-send">Send</button>
      </div>
      <div class="weall-comment-status muted" style="font-size:12px;margin-top:6px;"></div>
    `;

    postEl.appendChild(box);
    return box;
  }

  function renderMedia(media) {
    if (!Array.isArray(media) || media.length === 0) return "";
    const parts = [];

    for (const m of media) {
      const cid = m && m.cid;
      if (!cid) continue;
      const mime = String(m.mime || "");
      const url = `${apiBase()}/content/media/${encodeURIComponent(cid)}`;

      if (mime.startsWith("image/")) {
        parts.push(`<img src="${url}" alt="media" style="max-width:100%;border-radius:12px;margin-top:8px;border:1px solid rgba(34,40,54,.7);" />`);
      } else if (mime.startsWith("video/")) {
        parts.push(`<video controls src="${url}" style="max-width:100%;border-radius:12px;margin-top:8px;border:1px solid rgba(34,40,54,.7);"></video>`);
      } else {
        parts.push(`<a href="${url}" class="muted" style="display:inline-block;margin-top:8px;">Download attachment (${esc(mime || "file")})</a>`);
      }
    }

    return parts.join("");
  }

  function renderPostCard(post, tier) {
    const id = post.id;
    const author = post.author || "@unknown";
    const text = post.text || "";
    const scope = post.scope || "global";
    const gid = post.group_id || null;

    const likeCount = Number(post.like_count || 0);
    const commentCount = Number(post.comment_count || 0);
    const meLiked = !!post.me_liked;

    const canLikeComment = tier >= 2;
    const likeLabel = meLiked ? "♥ Liked" : "♡ Like";

    const card = document.createElement("article");
    card.className = "card";
    card.style.marginBottom = "10px";
    card.dataset.postId = id;

    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;">
        <div style="font-size:13px;">
          <span style="color:var(--accent);font-weight:700;">${esc(author)}</span>
          <span class="muted"> · ${esc(scope)}${gid ? " · group:" + esc(String(gid).slice(0, 8)) : ""}</span>
        </div>
        <div class="muted" style="font-size:12px;">id:${esc(String(id).slice(0, 8))}</div>
      </div>

      <div style="white-space:pre-wrap;font-size:14px;margin-top:8px;">${esc(text)}</div>
      ${renderMedia(post.media)}

      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:10px;">
        <button class="weall-like-btn" ${canLikeComment ? "" : "disabled"}>${likeLabel} (${likeCount})</button>
        <button class="weall-comment-btn" ${canLikeComment ? "" : "disabled"}>💬 Comments (${commentCount})</button>
        <span class="muted" style="font-size:12px;">${canLikeComment ? "" : "Tier 2 required to like/comment."}</span>
      </div>
    `;

    return card;
  }

  // ---------- feed ----------
  async function loadFeed() {
    const d = dom();
    if (!d.feed) {
      setStatus(d.feedStatus, "tiktok.js: feed container not found.", "warn");
      return;
    }

    const sess = await getSessionSafe();
    const tier = await getTierSafe();

    const { scope, group_id } = currentScopeAndGroup();

    // Tier 1 is view-only, but global viewing can be anonymous; group viewing requires auth tier>=1.
    if (scope === "group") {
      if (!sess || !sess.user_id) {
        d.feed.innerHTML = `<div class="muted">Sign in to view group feeds.</div>`;
        setStatus(d.feedStatus, "Group feed requires sign-in (Tier 1+).", "warn");
        setElText(d.feedMeta, "");
        return;
      }
      if (tier < 1) {
        d.feed.innerHTML = `<div class="muted">Tier 1 required to view group feeds.</div>`;
        setStatus(d.feedStatus, "Tier 1 required for group feeds.", "warn");
        setElText(d.feedMeta, "");
        return;
      }
      if (!group_id) {
        d.feed.innerHTML = `<div class="muted">Enter a group_id to view group feed.</div>`;
        setStatus(d.feedStatus, "group_id required when scope=group.", "warn");
        setElText(d.feedMeta, "");
        return;
      }
    }

    setStatus(d.feedStatus, "Loading feed…");
    d.feed.innerHTML = `<div class="muted">Loading…</div>`;

    let url = `/content/feed?scope=${encodeURIComponent(scope)}&limit=50`;
    if (scope === "group") url += `&group_id=${encodeURIComponent(group_id)}`;

    try {
      const data = await jsonFetch(url, { method: "GET" });
      const posts = (data && data.posts) || [];

      d.feed.innerHTML = "";
      if (!posts.length) {
        d.feed.innerHTML = `<div class="muted">No posts yet.</div>`;
        setElText(d.feedMeta, "0 posts");
        setStatus(d.feedStatus, "Feed loaded.", "ok");
        return;
      }

      for (const p of posts) d.feed.appendChild(renderPostCard(p, tier));

      wirePostActions(tier);

      setElText(d.feedMeta, `${posts.length} posts`);
      setStatus(d.feedStatus, "Feed loaded.", "ok");
    } catch (e) {
      console.error("loadFeed error:", e);
      d.feed.innerHTML = `<div class="muted">Failed to load feed.</div>`;
      setStatus(d.feedStatus, e.message || "Failed to load feed.", "err");
      setElText(d.feedMeta, "");
    }
  }

  // ---------- like/comment actions ----------
  function wirePostActions(tier) {
    const canLikeComment = tier >= 2;

    $$(".weall-like-btn").forEach((btn) => {
      btn.onclick = async () => {
        if (!canLikeComment) return;
        const card = btn.closest("article[data-post-id]");
        const postId = card && card.dataset.postId;
        if (!postId) return;

        try {
          const likedNow = btn.textContent.startsWith("♥");
          // Toggle
          let res;
          if (likedNow) {
            res = await jsonFetch(`/content/posts/${encodeURIComponent(postId)}/like`, { method: "DELETE" });
          } else {
            res = await jsonFetch(`/content/posts/${encodeURIComponent(postId)}/like`, { method: "POST" });
          }

          // Update label in-place
          const count = Number(res.like_count || 0);
          const meLiked = !!res.me_liked;
          btn.textContent = `${meLiked ? "♥ Liked" : "♡ Like"} (${count})`;
        } catch (e) {
          console.error("like toggle error:", e);
          alert(`Like failed: ${e.message}`);
        }
      };
    });

    $$(".weall-comment-btn").forEach((btn) => {
      btn.onclick = async () => {
        if (!canLikeComment) return;
        const card = btn.closest("article[data-post-id]");
        const postId = card && card.dataset.postId;
        if (!postId) return;

        const ui = ensureCommentUI(card);
        const list = ui.querySelector(".weall-comment-list");
        const input = ui.querySelector(".weall-comment-input");
        const send = ui.querySelector(".weall-comment-send");
        const status = ui.querySelector(".weall-comment-status");

        // Toggle show/hide
        const isHidden = ui.style.display === "none";
        ui.style.display = isHidden ? "" : "none";
        if (!isHidden) return;

        // Load comments
        try {
          status.textContent = "Loading comments…";
          const data = await jsonFetch(`/content/posts/${encodeURIComponent(postId)}/comments`, { method: "GET" });
          const comments = (data && data.comments) || [];
          list.innerHTML = comments.length
            ? comments.map(c => `<div style="margin:6px 0;"><span style="color:var(--accent)">${esc(c.author || "@unknown")}</span>: ${esc(c.text || "")}</div>`).join("")
            : `<div class="muted">No comments yet.</div>`;
          status.textContent = "";
        } catch (e) {
          console.error("load comments error:", e);
          status.textContent = `Failed: ${e.message}`;
        }

        // Send comment
        send.onclick = async () => {
          const text = String(input.value || "").trim();
          if (!text) return;

          try {
            send.disabled = true;
            status.textContent = "Sending…";
            const res = await jsonFetch(`/content/posts/${encodeURIComponent(postId)}/comments`, {
              method: "POST",
              body: { text },
            });
            const c = res.comment;
            input.value = "";

            // Append to list
            if (list.innerHTML.includes("No comments yet")) list.innerHTML = "";
            const line = document.createElement("div");
            line.style.margin = "6px 0";
            line.innerHTML = `<span style="color:var(--accent)">${esc(c.author || "@unknown")}</span>: ${esc(c.text || "")}`;
            list.appendChild(line);

            status.textContent = "";
          } catch (e) {
            console.error("send comment error:", e);
            status.textContent = `Failed: ${e.message}`;
          } finally {
            send.disabled = false;
          }
        };
      };
    });
  }

  // ---------- composer gating + post ----------
  async function applyComposerGates() {
    const d = dom();
    const tier = await getTierSafe();

    // Post: Tier 3+
    if (d.postBtn) d.postBtn.disabled = tier < 3;
    if (d.postText) d.postText.disabled = tier < 3;
    if (d.file) d.file.disabled = tier < 3;
    if (d.scope) d.scope.disabled = tier < 1; // scope change ok; but group view still requires auth
    if (d.groupId) d.groupId.disabled = tier < 1;

    if (d.postStatus) {
      if (tier < 3) {
        setStatus(d.postStatus, "Tier 3 required to post.", "warn");
      } else {
        setStatus(d.postStatus, "", "");
      }
    }
  }

  async function createPost() {
    const d = dom();
    const tier = await getTierSafe();
    if (tier < 3) {
      setStatus(d.postStatus, "Tier 3 required to post.", "warn");
      return;
    }

    // Use your existing auth helper if present (keeps UX consistent)
    if (window.weallAuth && typeof window.weallAuth.require === "function") {
      const ok = await window.weallAuth.require({ minTier: 3, redirectToLogin: "/frontend/login.html" });
      if (!ok) return;
    }

    const sess = await getSessionSafe();
    if (!sess || !sess.user_id) {
      window.location.href = "/frontend/login.html";
      return;
    }

    const text = String(d.postText && d.postText.value || "").trim();
    if (!text) {
      alert("Write something first.");
      return;
    }

    const { scope, group_id } = currentScopeAndGroup();
    if (scope === "group" && !group_id) {
      alert("group_id required when scope=group.");
      return;
    }

    try {
      if (d.postBtn) d.postBtn.disabled = true;
      setStatus(d.postStatus, "Posting…");

      const media = [];

      // Optional media upload (Tier 3)
      if (d.file && d.file.files && d.file.files[0]) {
        setStatus(d.postStatus, "Uploading media…");
        const up = await uploadFile(d.file.files[0]);
        media.push({ cid: up.cid, mime: up.mime || null });
      }

      await jsonFetch("/content/posts", {
        method: "POST",
        body: {
          author: sess.user_id,
          text,
          scope,
          group_id: scope === "group" ? group_id : null,
          media: media.length ? media : null,
        },
      });

      if (d.postText) d.postText.value = "";
      if (d.file) d.file.value = "";

      setStatus(d.postStatus, "Posted!", "ok");
      await loadFeed();
    } catch (e) {
      console.error("createPost error:", e);
      setStatus(d.postStatus, `Failed: ${e.message}`, "err");
    } finally {
      if (d.postBtn) d.postBtn.disabled = false;
    }
  }

  // ---------- wire + boot ----------
  function wire() {
    const d = dom();

    if (d.refresh) d.refresh.addEventListener("click", loadFeed);
    if (d.postBtn) d.postBtn.addEventListener("click", (ev) => { ev.preventDefault(); createPost(); });

    if (d.postText) {
      d.postText.addEventListener("keydown", (ev) => {
        if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
          ev.preventDefault();
          createPost();
        }
      });
    }

    if (d.scope) d.scope.addEventListener("change", loadFeed);
    if (d.groupId) d.groupId.addEventListener("change", loadFeed);
  }

  async function boot() {
    wire();
    await applyComposerGates();
    await loadFeed();
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
