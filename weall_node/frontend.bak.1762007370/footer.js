/*
weall_node/frontendtendtend/footer.js
--------------------------------------------------
Shared footer navigation bar for all WeAll frontend pages.
Provides quick navigation across core dashboards and utilities.
Automatically highlights the current active page.
*/

document.addEventListener("DOMContentLoaded", () => {
  const footer = document.createElement("footer");
  const current = window.location.pathname.split("/").pop();

  // List of main navigation buttons
  const navItems = [
    { name: "Feed", icon: "🏠", file: "index.html" },
    { name: "Governance", icon: "⚖️", file: "governance.html" },
    { name: "Juror", icon: "⚔️", file: "juror.html" },
    { name: "Operator", icon: "🛰️", file: "operator.html" },
    { name: "Treasury", icon: "💰", file: "treasury.html" },
    { name: "Rewards", icon: "🏆", file: "rewards.html" },
    { name: "Messages", icon: "💬", file: "messaging.html" },
    { name: "Profile", icon: "👤", file: "profile.html" }
  ];

  // Render navigation
  footer.innerHTML = `
    <nav class="footer-nav">
      ${navItems.map(item => `
        <button
          onclick="window.location.href='${item.file}'"
          class="${current === item.file ? 'active' : ''}"
        >
          ${item.icon}<span class="label">${item.name}</span>
        </button>
      `).join("")}
    </nav>
  `;

  // Inject styling
  const style = document.createElement("style");
  style.textContent = `
    footer {
      position: fixed;
      bottom: 0;
      width: 100%;
      background: #111;
      border-top: 1px solid #222;
      z-index: 100;
    }
    .footer-nav {
      display: flex;
      justify-content: space-around;
      align-items: center;
      max-width: 900px;
      margin: auto;
      padding: 6px 0;
    }
    .footer-nav button {
      background: none;
      border: none;
      color: #fff;
      font-size: 18px;
      cursor: pointer;
      transition: color 0.2s, transform 0.2s;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }
    .footer-nav button .label {
      font-size: 0.7em;
      color: #aaa;
      margin-top: 2px;
    }
    .footer-nav button:hover {
      color: #2ecc71;
      transform: translateY(-1px);
    }
    .footer-nav button.active {
      color: #2ecc71;
    }
    @media (max-width: 600px) {
      .footer-nav {
        flex-wrap: wrap;
        padding-bottom: 4px;
      }
      .footer-nav button {
        font-size: 16px;
        padding: 4px;
        width: 25%;
      }
      .footer-nav button .label {
        display: none;
      }
    }
  `;

  document.body.appendChild(footer);
  document.head.appendChild(style);
});
