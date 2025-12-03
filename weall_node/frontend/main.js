// ===========================================================
// WeAll Frontend — Unified Controller (v2.1)
// -----------------------------------------------------------
// Handles session logic, refresh intervals, API helpers,
// content feed, governance, profile, wallet, and voting.
// Integrates with new modules: Treasury, Rewards, Messaging.
// ===========================================================

const API_BASE = location.origin;
const snapshots = { feedIds: new Set(), govIds: new Set(), balance: null, reputation: null };
let refreshIntervals = { feed: null, gov: null, profile: null };

// ===========================================================
// SESSION + BOOTSTRAP
// ===========================================================
document.addEventListener("DOMContentLoaded", () => {
  const keys = JSON.parse(localStorage.getItem("weall_keys") || "{}");
  const userId = keys.public || localStorage.getItem("user");
  const segments = window.location.pathname.split("/").filter(Boolean);
  const page = segments.length ? segments[segments.length - 1] : "index.html";

  // If NOT logged in, force them onto login for any protected page
  if (!userId && !["login.html", "signup.html", "recover.html"].includes(page)) {
    window.location.href = "/frontend/login.html";
    return;
  }

  // If already logged in and they open login/signup, push them to feed
  if (userId && ["", "login.html", "signup.html"].includes(page)) {
    window.location.href = "/frontend/index.html";
    return;
  }
  const welcome = document.getElementById("welcome-user");
  if (welcome && userId) welcome.textContent = `Welcome, ${userId}`;

  if (document.getElementById("feed")) initFeedRefresh();
  if (document.getElementById("proposal-list")) initGovRefresh();
  if (document.getElementById("profile-data")) initProfileRefresh();
});

// ===========================================================
// HELPERS
// ===========================================================
async function api(path, { method = "GET", body, headers } = {}) {
  const opts = { method, headers: { "Content-Type": "application/json", ...(headers || {}) } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`${API_BASE}${path}`, opts);
  let data; try { data = await res.json(); } catch { data = {}; }
  if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
  return data;
}

function addPulse(el) {
  if (!el) return;
  el.classList.remove("pulse"); el.offsetWidth;
  el.classList.add("pulse");
  setTimeout(() => el.classList.remove("pulse"), 1200);
}
function setUpdatedStamp(el) {
  if (el) el.textContent = "Last updated: " + new Date().toLocaleTimeString();
}
function setBadgeVisible(id, visible) {
  const b = document.getElementById(id);
  if (b) b.style.opacity = visible ? "1" : "0";
}

// ===========================================================
// FEED
// ===========================================================
async function loadFeed() {
  const feed = document.getElementById("feed");
  const stamp = document.getElementById("feed-last-updated");
  const panel = document.getElementById("feed-panel");
  if (!feed) return;

  try {
    const posts = await api("/content/list");
    const ids = new Set(posts.map(p => p.id || p.cid));
    let hasNew = false;
    for (const id of ids) if (!snapshots.feedIds.has(id)) { hasNew = true; break; }
    snapshots.feedIds = ids;
    feed.innerHTML = "";
    posts.forEach(p => {
      const d = document.createElement("div");
      d.className = "post-card";
      d.innerHTML = `
        <h3>${p.user || p.author}</h3>
        <p>${p.content || p.text}</p>
        <small>Tags: ${(p.tags || []).join(", ")}</small><br>
        <button onclick="commentPost('${p.id}')">Comment</button>
        <button onclick="reportPost('${p.id}')">Report</button>
      `;
      feed.appendChild(d);
    });
    setUpdatedStamp(stamp);
    setBadgeVisible("badge-feed", hasNew);
    if (hasNew) addPulse(panel);
  } catch (e) {
    feed.innerHTML = `<p>Error loading feed: ${e.message}</p>`;
  }
}
function initFeedRefresh() {
  loadFeed();
  clearInterval(refreshIntervals.feed);
  refreshIntervals.feed = setInterval(loadFeed, 30000);
}

// ===========================================================
// GOVERNANCE
// ===========================================================
async function loadProposals() {
  const list = document.getElementById("proposal-list");
  const stamp = document.getElementById("gov-last-updated");
  const panel = document.getElementById("gov-panel");
  if (!list) return;
  try {
    const props = await api("/governance/proposals");
    const ids = new Set(props.map(p => p.id));
    let hasNew = false;
    for (const id of ids) if (!snapshots.govIds.has(id)) { hasNew = true; break; }
    snapshots.govIds = ids;
    list.innerHTML = "";
    props.forEach(p => {
      const c = document.createElement("div");
      c.className = "proposal-card";
      c.innerHTML = `
        <h3>${p.title || p.module}</h3>
        <small>Status: ${p.status || "open"}</small><br>
        <button onclick="voteProposal('${p.id}')">Vote</button>
      `;
      list.appendChild(c);
    });
    setUpdatedStamp(stamp);
    setBadgeVisible("badge-gov", hasNew);
    if (hasNew) addPulse(panel);
  } catch (e) {
    list.innerHTML = `<p>Error loading proposals: ${e.message}</p>`;
  }
}
function initGovRefresh() {
  loadProposals();
  clearInterval(refreshIntervals.gov);
  refreshIntervals.gov = setInterval(loadProposals, 30000);
}

// ===========================================================
// PROFILE (Balance / Reputation)
// ===========================================================
async function loadProfile() {
  const keys = JSON.parse(localStorage.getItem("weall_keys") || "{}");
  const userId = keys.public || localStorage.getItem("user");
  const profile = document.getElementById("profile-data");
  const panel = document.getElementById("profile-panel");
  const stamp = document.getElementById("profile-last-updated");
  if (!userId || !profile) return;

  try {
    const bal = await api(`/ledger/balance/${userId}`);
    let rep = { score: "N/A" };
    try { rep = await api(`/reputation/${userId}`); } catch {}
    const balChanged = snapshots.balance !== null && snapshots.balance !== bal.balance;
    const repChanged = snapshots.reputation !== null && snapshots.reputation !== rep.score;
    snapshots.balance = bal.balance; snapshots.reputation = rep.score;

    profile.innerHTML = `
      <h3>${userId}</h3>
      <p>Balance: <span id="balance-value">${bal.balance} WEC</span></p>
      <p>Reputation: <span id="reputation-value">${rep.score ?? "N/A"}</span></p>
      <button onclick="newPost('${userId}')">New Post</button>
      <button onclick="window.location.href='profile.html'">Open Profile</button>
    `;
    setUpdatedStamp(stamp);
    setBadgeVisible("badge-profile", balChanged || repChanged);
    if (balChanged || repChanged) addPulse(panel);
  } catch (e) {
    profile.innerHTML = `<p>Error: ${e.message}</p>`;
  }
}
function initProfileRefresh() {
  loadProfile();
  clearInterval(refreshIntervals.profile);
  refreshIntervals.profile = setInterval(loadProfile, 30000);
}

// ===========================================================
// CONTENT ACTIONS
// ===========================================================
async function newPost(uid) {
  const content = prompt("Post content:");
  if (!content) return;
  const t = prompt("Tags (comma-separated):");
  const tags = t ? t.split(",") : [];
  try {
    const r = await api("/content/upload", { method: "POST", body: { user: uid, content, tags } });
    alert("✅ Post created and pinned: " + JSON.stringify(r));
    loadFeed();
  } catch (e) { alert("⚠️ " + e.message); }
}

async function commentPost(pid) {
  const content = prompt("Comment:");
  if (!content) return;
  try {
    const r = await api("/content/comment", { method: "POST", body: { post_id: pid, content } });
    alert("✅ Comment added.");
    loadFeed();
  } catch (e) { alert("⚠️ " + e.message); }
}

async function reportPost(pid) {
  const reason = prompt("Reason for report:");
  if (!reason) return;
  try {
    const r = await api("/disputes/create", { method: "POST", body: { post_id: pid, reason } });
    alert("📝 Dispute opened: " + JSON.stringify(r));
  } catch (e) { alert("⚠️ " + e.message); }
}

async function voteProposal(pid) {
  const v = prompt("Vote (yes/no):");
  if (!v) return;
  try {
    const r = await api("/governance/vote", { method: "POST", body: { proposal_id: pid, vote: v } });
    alert("✅ Vote submitted: " + JSON.stringify(r));
    loadProposals();
  } catch (e) { alert("⚠️ " + e.message); }
}

// ===========================================================
// LOGOUT
// ===========================================================
function logout() {
  Object.values(refreshIntervals).forEach(clearInterval);
  localStorage.removeItem("user");
  localStorage.removeItem("weall_keys");
  location.href = "/frontend/login.html";
}
