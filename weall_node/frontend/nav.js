async function weallRenderNav() {
  const nav = document.getElementById("weall_nav");
  if (!nav) return;

  let sess = null;
  try {
    sess = await weallGetSession();
  } catch {
    sess = null;
  }

  const isAuthed = !!sess;
  const who = isAuthed ? sess.user_id : "Guest";
  const tier = isAuthed ? "Tier 1 · local" : "Tier 0 · guest";

  nav.innerHTML = `
    <div class="nav-wrap">
      <div class="nav-left">
        <a class="nav-brand" href="/frontend/">
          <span class="nav-title">WEALL NODE</span>
        </a>
      </div>
      <div class="nav-right">
        <span class="nav-user">${who}</span>
        <span class="nav-tier">${tier}</span>
        ${
          isAuthed
            ? `<button id="weall_logout_btn" class="nav-btn">Log out</button>`
            : `<a class="nav-btn" href="/frontend/login.html">Log in</a>`
        }
      </div>
    </div>
  `;

  const btn = document.getElementById("weall_logout_btn");
  if (btn) {
    btn.onclick = async () => {
      try { await weallJsonFetch("/auth/logout", { method: "POST" }); } catch {}
      weallClearClientAuth();
      window.location.href = "/frontend/login.html";
    };
  }
}

document.addEventListener("DOMContentLoaded", weallRenderNav);
