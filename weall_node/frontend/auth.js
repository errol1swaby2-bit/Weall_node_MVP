export async function authApply({ identifier, handle, email, password }) {
  const payload = { password };

  // identifier can be "@handle" or "email"
  if (identifier) payload.user_id = identifier;

  // signup path (explicit)
  if (handle) payload.handle = handle;
  if (email) payload.email = email;

  const r = await fetch("/auth/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  });

  const text = await r.text();
  let data = null;
  try { data = JSON.parse(text); } catch { /* ignore */ }

  if (!r.ok) {
    const msg = (data && (data.detail || data.error)) || text || `HTTP ${r.status}`;
    throw new Error(msg);
  }

  return data;
}

export async function authLogout() {
  await fetch("/auth/logout", {
    method: "POST",
    credentials: "include",
  });
}
