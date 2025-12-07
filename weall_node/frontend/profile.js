// weall_node/frontend/profile.js
// ----------------------------------------------------
// Profile page wiring for WeAll Node MVP.
//
// - Shows "Signed in as @handle"
// - Fetches wallet + rewards + PoH info
// - Degrades gracefully if some APIs are not configured yet
// ----------------------------------------------------

// ---------------------------------------------------------------------
// Tiny DOM helpers (no-op if elements are missing)
// ---------------------------------------------------------------------
window.$ =
  window.$ ||
  function (id) {
    return document.getElementById(id);
  };

window.setText =
  window.setText ||
  function (id, text) {
    const el = $(id);
    if (el) el.textContent = text;
  };

// ---------------------------------------------------------------------
// Generic API helper
// ---------------------------------------------------------------------
async function apiFetch(path, opts = {}, { allow404 = false } = {}) {
  const url = path.startsWith("http") ? path : path.startsWith("/") ? path : "/" + path;

  // If the app already defined apiFetch, prefer that.
  if (window.weallApiFetch) {
    return window.weallApiFetch(url, opts, { allow404 });
  }

  const res = await fetch(url, {
    credentials: "include",
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  });

  if (res.status === 404 && allow404) {
    return null;
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${url} failed: ${res.status} ${res.statusText} ${text}`);
  }

  return res.json();
}

// ---------------------------------------------------------------------
// Core profile loader
// ---------------------------------------------------------------------
async function loadProfile() {
  try {
    // Ensure we have a session + user
    const sess = typeof requireSessionAndUser === "function"
      ? await requireSessionAndUser()
      : (window.currentSession || { user_id: null });

    if (!sess || !sess.user_id) {
      setText("profileError", "Not signed in.");
      console.warn("[profile] No session / user_id found");
      return;
    }

    const rawHandle = String(sess.user_id);
    const handle = rawHandle.startsWith("@") ? rawHandle : "@" + rawHandle;

    // Basic header
    setText("profileSubtitle", `Signed in as ${handle}`);

    // Kick off all the backend calls in parallel
    const [
      walletMeta,
      walletInfo,
      rewardsMeta,
      rewardsInfo,
      pohInfo,
    ] = await Promise.all([
      apiFetch("/wallets/meta").catch((err) => {
        console.warn("[profile] wallets/meta failed", err);
        return null;
      }),
      apiFetch(`/wallets/${encodeURIComponent(handle)}`).catch((err) => {
        console.warn("[profile] wallets/@handle failed", err);
        return null;
      }),
      apiFetch("/rewards/meta").catch((err) => {
        console.warn("[profile] rewards/meta failed", err);
        return null;
      }),
      apiFetch(`/rewards/pending/${encodeURIComponent(handle)}`).catch((err) => {
        console.warn("[profile] rewards/pending/@handle failed", err);
        return null;
      }),
      // PoH is optional right now – allow 404 without blowing up the page
      apiFetch(`/poh/${encodeURIComponent(handle)}`, {}, { allow404: true }).catch(
        (err) => {
          console.warn("[profile] poh/@handle failed", err);
          return null;
        }
      ),
    ]);

    // --------------------------------------------------
    // Wallet summary
    // --------------------------------------------------
    let walletSummary = "Wallet info unavailable.";

    if (walletInfo && walletInfo.user) {
      const symbol =
        (walletMeta && walletMeta.token_symbol) ||
        (walletInfo.balances && Object.keys(walletInfo.balances)[0]) ||
        "WEC";

      const balance =
        (walletInfo.balances && walletInfo.balances[symbol]) !== undefined
          ? walletInfo.balances[symbol]
          : 0.0;

      const nfts = Array.isArray(walletInfo.nfts) ? walletInfo.nfts.length : 0;

      const note =
        (walletMeta && walletMeta.notes) ||
        "MVP wallets; balances not yet wired to on-chain rewards.";

      walletSummary = `Balance: ${balance} ${symbol} · NFTs: ${nfts} · ${note}`;
    } else if (walletMeta) {
      walletSummary =
        walletMeta.notes ||
        "Wallet meta available but no wallet record yet for this user.";
    }

    setText("walletSummary", walletSummary);

    // --------------------------------------------------
    // Rewards summary
    // --------------------------------------------------
    let rewardsSummary = "Rewards info unavailable.";

    if (rewardsInfo && rewardsInfo.user) {
      const total = rewardsInfo.total_pending ?? 0.0;
      const note =
        (rewardsMeta && rewardsMeta.notes) ||
        "MVP stub – amounts are not yet wired to chain rewards.";

      rewardsSummary = `Pending rewards: ${total} WEC · ${note}`;
    } else if (rewardsMeta) {
      rewardsSummary =
        rewardsMeta.notes || "Rewards meta available but no user record yet.";
    }

    setText("rewardsSummary", rewardsSummary);

    // --------------------------------------------------
    // PoH summary
    // --------------------------------------------------
    let pohSummary = "Proof-of-Humanity: not yet registered.";

    if (pohInfo && pohInfo.user) {
      const tier = pohInfo.tier ?? pohInfo.current_tier ?? 0;
      const status = pohInfo.status || "pending";

      pohSummary = `Proof-of-Humanity: Tier ${tier} (${status})`;
    }

    setText("pohSummary", pohSummary);

    // Clear any stale error message
    setText("profileError", "");
  } catch (err) {
    console.error("[profile] Failed to load profile", err);
    setText(
      "profileError",
      "Failed to load profile data. Please refresh or try again later."
    );
  }
}

// ---------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  loadProfile();
});
