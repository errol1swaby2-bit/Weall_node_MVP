// weall_node/frontend/wallet.js
// ---------------------------------
// Wallet + NFT UI glue.
//
// Flow:
//   1) Fetch /auth/session to resolve a user id.
//   2) Store that in window.WEALL_USER_ID.
//   3) All wallet calls send X-WeAll-User so backend can resolve the account.

(function () {
  function $(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = value;
  }

  function setStatus(message, level) {
    const el = $("walletStatus");
    if (!el) return;
    el.textContent = message;
    el.dataset.level = level || "info";
  }

  const API_BASE = window.API_BASE || "";
  let gUserId = null; // what we send in X-WeAll-User

  async function fetchJson(path, opts) {
    const baseOpts = opts || {};
    const existingHeaders = (baseOpts && baseOpts.headers) || {};

    const headers = {
      "Content-Type": "application/json",
      ...existingHeaders,
    };

    if (gUserId) {
      headers["X-WeAll-User"] = gUserId;
    }

    const res = await fetch(API_BASE + path, {
      credentials: "include",
      ...baseOpts,
      headers,
    });

    let data;
    try {
      data = await res.json();
    } catch (e) {
      throw new Error("Wallet API: invalid JSON (" + res.status + ")");
    }

    if (!res.ok || data.ok === false) {
      const detail = data && (data.detail || data.error || JSON.stringify(data));
      throw new Error(detail || "HTTP " + res.status);
    }

    return data;
  }

  async function resolveUserFromSession() {
    setStatus("Resolving wallet session…", "info");
    try {
      const data = await fetchJson("/auth/session", {
        // no X-WeAll-User yet; fetchJson will only add it if gUserId is set
        headers: {},
      });

      const sess = data.session || data;
      const emailFromSession = sess.email || sess.email_for_login || null;

      const pohIdFromSession =
        sess.poh_id ||
        emailFromSession ||
        sess.user_id ||
        sess.account_id ||
        sess.handle ||
        null;

      if (!pohIdFromSession) {
        setStatus(
          "Wallet not available: session is missing a user id. Please re-login.",
          "error"
        );
        return null;
      }

      gUserId = pohIdFromSession;
      window.WEALL_USER_ID = pohIdFromSession;
      setStatus("Session resolved.", "ok");
      return gUserId;
    } catch (err) {
      console.error("resolveUserFromSession failed", err);
      setStatus("Failed to resolve session: " + err.message, "error");
      return null;
    }
  }

  async function loadWallet() {
    if (!gUserId) {
      const resolved = await resolveUserFromSession();
      if (!resolved) return;
    }

    setStatus("Loading wallet…", "info");
    try {
      const data = await fetchJson("/wallet/me");
      const wallet = data.wallet || data;

      const balance = wallet.balance != null ? wallet.balance : 0;
      setText("walletBalance", balance.toString() + " WeCoin");

      const nftCount = wallet.nft_count != null ? wallet.nft_count : 0;
      setText("walletNftCount", nftCount.toString());

      setStatus("Wallet loaded.", "ok");
    } catch (err) {
      console.error("wallet/me failed", err);
      setStatus("Failed to load wallet: " + err.message, "error");
    }
  }

  function renderNftList(nfts) {
    const container = $("nftList");
    if (!container) return;

    if (!Array.isArray(nfts) || nfts.length === 0) {
      container.innerHTML = '<li class="nft-empty">No NFTs minted yet.</li>';
      return;
    }

    const items = nfts
      .map((nft) => {
        const created = nft.created_at
          ? new Date(nft.created_at * 1000).toLocaleString()
          : "";
        const title = nft.title || nft.content_cid || nft.id;
        const kind = nft.kind || "post";

        return (
          '<li class="nft-item">' +
          '  <div class="nft-main">' +
          '    <div class="nft-title">' +
          title +
          "</div>" +
          '    <div class="nft-meta">' +
          '      <span class="nft-kind">' +
          kind +
          "</span>" +
          '      <span class="nft-created">' +
          created +
          "</span>" +
          "    </div>" +
          "  </div>" +
          '  <div class="nft-cid" title="' +
          (nft.content_cid || "") +
          '">' +
          (nft.content_cid || "") +
          "</div>" +
          "</li>"
        );
      })
      .join("");

    container.innerHTML = items;
  }

  async function loadNfts() {
    if (!gUserId) {
      const resolved = await resolveUserFromSession();
      if (!resolved) return;
    }

    try {
      const data = await fetchJson("/wallet/nfts");
      const nfts = data.nfts || [];
      renderNftList(nfts);
    } catch (err) {
      console.error("wallet/nfts failed", err);
      setStatus("Failed to load NFTs: " + err.message, "error");
    }
  }

  async function mintDemoNft() {
    if (!gUserId) {
      const resolved = await resolveUserFromSession();
      if (!resolved) return;
    }

    setStatus("Minting demo NFT…", "info");
    try {
      const now = Date.now();
      const payload = {
        content_cid: "demo:" + now,
        title: "Demo creator NFT " + now,
        kind: "demo",
        preview_url: null,
      };

      await fetchJson("/wallet/mint", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      setStatus("Demo NFT minted.", "ok");
      await loadWallet();
      await loadNfts();
    } catch (err) {
      console.error("wallet/mint failed", err);
      setStatus("Mint failed: " + err.message, "error");
    }
  }

  function attachHandlers() {
    const btn = $("mintDemoBtn");
    if (btn) {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        mintDemoNft();
      });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    attachHandlers();
    // Resolve session first, then load wallet + NFTs
    resolveUserFromSession().then((uid) => {
      if (!uid) return;
      loadWallet();
      loadNfts();
    });
  });
})();
