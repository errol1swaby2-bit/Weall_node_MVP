// Normalize an email to @handle
function normalizeUserId(emailOrId) {
  if (!emailOrId) return "unknown";
  let v = emailOrId.trim().toLowerCase();
  if (v.startsWith("@")) return v;
  if (v.includes("@")) return "@" + v.split("@")[0];
  return v;
}

// Global helper to get current user
function CurrentUser() {
  // From Session cookie if available
  if (window.Session && Session.get) {
    let s = Session.get();
    if (s && s.account) return normalizeUserId(s.account);
  }

  // Fallback from localStorage
  let ls = localStorage.getItem("weall.account") ||
           localStorage.getItem("weall_user") ||
           "";
  return normalizeUserId(ls);
}
