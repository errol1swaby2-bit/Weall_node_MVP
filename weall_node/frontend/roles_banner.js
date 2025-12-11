// weall_node/frontend/roles_banner.js
//
// Shared helper for showing network roles + typography in the header.
//
// Usage on any page:
//
//   <script src="/frontend/roles_banner.js"></script>
//   <script>
//     document.addEventListener("DOMContentLoaded", () => {
//       hydrateRoleBanner("signedInBanner");
//     });
//   </script>
//
// And in HTML:
//
//   <span id="signedInBanner" class="signed-in-banner"></span>
//

async function weallFetchJson(url, opts) {
  const res = await fetch(url, opts || {});
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Request failed ${res.status}: ${text}`);
  }
  return res.json();
}

function weallGetAccountId() {
  // This assumes the login flow stored the handle here, e.g. "@errol1swaby2"
  const acct = window.localStorage.getItem("weall_account_id");
  if (!acct) {
    throw new Error("Not signed in: localStorage.weall_account_id is empty");
  }
  return acct;
}

async function weallFetchRolesAndNode() {
  const userId = weallGetAccountId();

  const headers = {
    "X-WeAll-User": userId,
  };

  const [roles, node] = await Promise.all([
    weallFetchJson("/roles/effective/me", { headers }),
    weallFetchJson("/node/meta"),
  ]);

  return { userId, roles, node };
}

function weallFormatBadges(roles, nodeMeta) {
  const parts = [];

  // PoH tier
  const tier = roles.poh_tier || 0;
  if (tier > 0) {
    parts.push(`PoH Tier ${tier}`);
  } else {
    parts.push("Unverified");
  }

  // High-level desires (creator / juror / validator / operator / emissary)
  const flags = roles.flags || {};
  const caps = roles.capabilities || [];

  const roleTags = [];

  if (flags.wants_creator || caps.includes("earn_creator_rewards")) {
    roleTags.push("Creator");
  }
  if (flags.wants_juror || caps.includes("serve_juror_panel")) {
    roleTags.push("Juror");
  }
  if (flags.wants_validator || caps.includes("validator_duties")) {
    roleTags.push("Validator");
  }
  if (flags.wants_operator || caps.includes("operator_duties")) {
    roleTags.push("Operator");
  }
  if (flags.wants_emissary || caps.includes("act_as_emissary")) {
    roleTags.push("Emissary");
  }

  if (roleTags.length > 0) {
    parts.push(roleTags.join(" · "));
  }

  // Node role (taken from /node/meta)
  const nodeKind = (nodeMeta && nodeMeta.node_kind) || "public_gateway";
  let nodeLabel = "Gateway node";

  if (nodeKind === "validator_node") {
    nodeLabel = "Validator node";
  } else if (nodeKind === "private_node") {
    nodeLabel = "Private node";
  }

  parts.push(nodeLabel);

  return parts.join(" · ");
}

function weallRenderBannerText(userId, roles, nodeMeta) {
  const badges = weallFormatBadges(roles, nodeMeta);
  return `Signed in as ${userId} · ${badges}`;
}

/**
 * Hydrate a span/div with id = elementId with the full banner text.
 *
 * Example:
 *   <span id="signedInBanner"></span>
 *   document.addEventListener("DOMContentLoaded", () => {
 *     hydrateRoleBanner("signedInBanner");
 *   });
 */
async function hydrateRoleBanner(elementId) {
  const el = document.getElementById(elementId);
  if (!el) {
    console.warn("[WeAll] hydrateRoleBanner: element not found:", elementId);
    return;
  }

  try {
    el.textContent = "Loading session…";

    const { userId, roles, node } = await weallFetchRolesAndNode();
    const text = weallRenderBannerText(userId, roles, node);
    el.textContent = text;
    el.classList.add("signed-in-banner--ready");
  } catch (err) {
    console.error("[WeAll] Failed to hydrate role banner:", err);
    el.textContent = "Not signed in";
    el.classList.add("signed-in-banner--error");
  }
}

// Optional: expose utilities globally for debugging
window.weallRolesBanner = {
  hydrateRoleBanner,
  weallFetchRolesAndNode,
  weallRenderBannerText,
};
