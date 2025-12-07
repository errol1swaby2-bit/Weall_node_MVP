// weall_node/weall_node/frontend/governance.js
(function () {
  "use strict";

  // -----------------------------
  // Helpers
  // -----------------------------

  function $(id) {
    return document.getElementById(id);
  }

  function apiBase() {
    return (window.ENV && window.ENV.VITE_API_BASE) || "";
  }

  async function jsonFetch(path, opts) {
    const url = apiBase() + path;
    const options = Object.assign(
      {
        headers: {
          Accept: "application/json",
        },
        credentials: "include",
      },
      opts || {}
    );
    if (options.body && typeof options.body !== "string") {
      options.headers["Content-Type"] =
        options.headers["Content-Type"] || "application/json";
      options.body = JSON.stringify(options.body);
    }

    const res = await fetch(url, options);
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    if (!res.ok) {
      const msg =
        (data && (data.detail || data.error || data.message)) ||
        "Request failed with status " + res.status;
      throw new Error(msg);
    }
    return data;
  }

  function formatDate(ts) {
    if (!ts) return "";
    if (ts > 1e12) ts = ts / 1000;
    const d = new Date(ts * 1000);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString();
  }

  function timeRemaining(proposal) {
    const now = Date.now() / 1000;
    const closes = proposal.closes_at || 0;
    const diff = closes - now;
    if (diff <= 0) return "closed";
    const minutes = Math.floor(diff / 60);
    if (minutes < 60) return minutes + " min left";
    const hours = Math.floor(minutes / 60);
    if (hours < 48) return hours + " h left";
    const days = Math.floor(hours / 24);
    return days + " d left";
  }

  function normalizeHandle(id) {
    if (!id) return "";
    const v = String(id).trim();
    if (!v) return "";
    return v.startsWith("@") ? v : "@" + v.toLowerCase();
  }

  async function ensureTier1OrRedirect(reason) {
    reason = reason || "This action requires PoH Tier-1.";
    let sess;
    try {
      sess = await weallAuth.getSession();
    } catch {
      const next = encodeURIComponent("/frontend/governance.html");
      window.location.replace("/frontend/login.html?next=" + next);
      return null;
    }
    if (!sess || !sess.user_id) {
      const next = encodeURIComponent("/frontend/governance.html");
      window.location.replace("/frontend/login.html?next=" + next);
      return null;
    }

    try {
      const poh = await weallAuth.getPohMe();
      const tier = typeof poh.tier === "number" ? poh.tier : 0;
      const status = (poh.status || "ok").toLowerCase();
      if (status === "banned") {
        alert("Your account is banned. You cannot participate in governance.");
        return null;
      }
      if (status === "suspended") {
        alert("Your account is suspended. You cannot participate in governance.");
        return null;
      }
      if (tier < 1) {
        alert(reason + " Your current PoH tier is " + tier + ".");
        return null;
      }
    } catch (e) {
      alert("Failed to load PoH status: " + e.message);
      return null;
    }

    return sess;
  }

  // -----------------------------
  // Rendering
  // -----------------------------

  function renderProposals(list, currentUserId) {
    const container = $("gov-proposals");
    if (!container) return;
    container.innerHTML = "";

    if (!list || list.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No proposals yet. Be the first to submit one.";
      container.appendChild(empty);
      return;
    }

    list
      .slice()
      .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
      .forEach((p) => {
        container.appendChild(renderProposalCard(p, currentUserId));
      });
  }

  function renderProposalCard(proposal, currentUserId) {
    const card = document.createElement("article");
    card.className = "proposal-card";

    const header = document.createElement("header");
    header.className = "proposal-header";

    const title = document.createElement("h3");
    title.textContent = proposal.title || "(no title)";
    header.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "proposal-meta";

    const createdBy = document.createElement("span");
    createdBy.textContent = "By " + normalizeHandle(proposal.created_by || "unknown");
    meta.appendChild(createdBy);

    const statusSpan = document.createElement("span");
    const isOpen = proposal.status === "open";
    const rem = timeRemaining(proposal);
    statusSpan.textContent = isOpen ? "Open · " + rem : "Closed";
    statusSpan.className = "proposal-status " + (isOpen ? "open" : "closed");
    meta.appendChild(statusSpan);

    header.appendChild(meta);

    const body = document.createElement("div");
    body.className = "proposal-body";
    const desc = document.createElement("p");
    desc.textContent = proposal.description || "";
    body.appendChild(desc);

    const optsWrap = document.createElement("div");
    optsWrap.className = "proposal-options";

    const options = proposal.options || [];
    const groupName = "gov-option-" + proposal.id;
    options.forEach((opt) => {
      const label = document.createElement("label");
      label.className = "option-pill";

      const input = document.createElement("input");
      input.type = "radio";
      input.name = groupName;
      input.value = opt;

      label.appendChild(input);
      const span = document.createElement("span");
      span.textContent = opt;
      label.appendChild(span);

      optsWrap.appendChild(label);
    });

    body.appendChild(optsWrap);

    const tallies = document.createElement("div");
    tallies.className = "proposal-tallies";
    const talliesObj = proposal.tallies || {};
    const totalVotes = Object.values(talliesObj).reduce(
      (acc, v) => acc + (typeof v === "number" ? v : 0),
      0
    );

    const tallyPieces = [];
    options.forEach((opt) => {
      const count = talliesObj[opt] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      tallyPieces.push(opt + ": " + count + (totalVotes ? " (" + pct + "%)" : ""));
    });

    tallies.textContent =
      totalVotes > 0
        ? "Votes: " + tallyPieces.join(" · ")
        : "No votes yet.";

    body.appendChild(tallies);

    const footer = document.createElement("footer");
    footer.className = "proposal-footer";

    const left = document.createElement("div");
    left.className = "proposal-id";
    left.textContent = "ID: " + proposal.id;

    const right = document.createElement("div");
    right.className = "proposal-actions";

    if (proposal.status === "open") {
      const btn = document.createElement("button");
      btn.className = "btn-secondary";
      btn.textContent = "Vote";
      btn.onclick = async () => {
        const chosen = document.querySelector(
          'input[name="' + groupName + '"]:checked'
        );
        if (!chosen) {
          alert("Please select an option before voting.");
          return;
        }
        const opt = chosen.value;
        try {
          await ensureTier1OrRedirect("Voting on proposals requires PoH Tier-1.");
          await jsonFetch("/governance/proposals/" + proposal.id + "/vote", {
            method: "POST",
            body: { option: opt },
          });
          await loadProposals(); // refresh
        } catch (e) {
          alert("Failed to cast vote: " + e.message);
        }
      };
      right.appendChild(btn);
    } else {
      const closed = document.createElement("span");
      closed.className = "badge-closed";
      closed.textContent = "Closed";
      right.appendChild(closed);
    }

    footer.appendChild(left);
    footer.appendChild(right);

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(footer);

    return card;
  }

  // -----------------------------
  // API + init
  // -----------------------------

  async function loadProposals() {
    const statusEl = $("gov-list-status");
    if (statusEl) {
      statusEl.textContent = "Loading…";
    }
    try {
      const data = await jsonFetch("/governance/proposals", { method: "GET" });
      const proposals = data.proposals || data.items || [];
      if (statusEl) {
        statusEl.textContent =
          proposals.length === 0
            ? "No proposals yet."
            : proposals.length + " proposals";
      }
      const sess = await weallAuth
        .getSession()
        .catch(() => ({ user_id: null }));
      const uid = sess && sess.user_id;
      renderProposals(proposals, uid);
    } catch (e) {
      if (statusEl) {
        statusEl.textContent = "Failed to load proposals: " + e.message;
      }
    }
  }

  async function handleCreateProposal() {
    const titleEl = $("gov-title");
    const descEl = $("gov-desc");
    const optEl = $("gov-options");
    const durEl = $("gov-duration");
    const statusEl = $("gov-create-status");

    if (!titleEl || !descEl || !statusEl) return;

    const title = titleEl.value.trim();
    const desc = descEl.value.trim();
    const optionsRaw = optEl ? optEl.value.trim() : "";
    const durationDays = durEl ? Number(durEl.value || "7") : 7;

    if (!title) {
      statusEl.textContent = "Please enter a title.";
      statusEl.className = "status err";
      return;
    }

    statusEl.textContent = "Submitting proposal…";
    statusEl.className = "status";

    let sess = await ensureTier1OrRedirect(
      "Creating proposals requires PoH Tier-1."
    );
    if (!sess) {
      // ensureTier1OrRedirect already redirected or alerted
      return;
    }

    let options = null;
    if (optionsRaw) {
      options = optionsRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      if (options.length === 0) {
        options = null;
      }
    }

    const payload = {
      title: title,
      description: desc,
      type: "signal",
      options: options || null,
      duration_sec: Math.max(1, durationDays) * 24 * 3600,
    };

    try {
      await jsonFetch("/governance/proposals", {
        method: "POST",
        body: payload,
      });
      statusEl.textContent = "Proposal created.";
      statusEl.className = "status ok";

      // Clear fields
      titleEl.value = "";
      descEl.value = "";
      if (optEl) optEl.value = "";
      if (durEl) durEl.value = "7";

      await loadProposals();
    } catch (e) {
      statusEl.textContent = "Failed to create proposal: " + e.message;
      statusEl.className = "status err";
    }
  }

  async function hydrateCurrentUser() {
    const el = $("gov-current-user");
    if (!el) return;

    try {
      const sess = await weallAuth.getSession();
      if (sess && sess.user_id) {
        el.textContent = "Current user: " + normalizeHandle(sess.user_id);
      } else {
        el.textContent =
          "Current user: guest (sign in to create and vote on proposals).";
      }
    } catch {
      el.textContent =
        "Current user: guest (sign in to create and vote on proposals).";
    }
  }

  function init() {
    const submitBtn = $("gov-submit");
    if (submitBtn) {
      submitBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        handleCreateProposal();
      });
    }

    hydrateCurrentUser();
    loadProposals();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
