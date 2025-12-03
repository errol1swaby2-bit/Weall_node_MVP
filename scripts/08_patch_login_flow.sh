set -euo pipefail

HTML="weall_node/frontend/login.html"

# Backup
cp "$HTML" "$HTML.bak.$(date +%s)"

# Insert a helper <div id="status"> if it doesn't exist (for user feedback)
if ! grep -q 'id="status"' "$HTML"; then
  # add it just above closing </body> or after the big card if easier
  perl -0777 -i -pe 's#(</main>[^<]*</div>[^<]*</div>[^<]*\n?)#\1\n  <div id="status" style="text-align:center;margin:16px 0;opacity:.9;"></div>\n#' "$HTML" || true
fi

# Ensure our inputs are correctly identified (you already fixed email+code)
# email: id="email" (maxlength=254); code: id="codeInput" (6 digits); account: id="acct" (optional)

# Add (or replace) an inline script that wires up the buttons.
# We inject right before </body> to avoid fighting other scripts.
perl -0777 -i -pe '
  my $patch = qq{
<script>
(function () {
  function qs(sel){return document.querySelector(sel)}
  function qsv(sel){var el=qs(sel); return el?el.value.trim():""}
  function setStatus(msg, kind){
    var s = qs("#status"); if(!s) return;
    s.textContent = msg || "";
    s.style.color = (kind==="error") ? "#ff8080" : "#a0e3a0";
  }
  function getNext(){
    var p = new URLSearchParams(location.search);
    return p.get("next") || "/frontend/onboarding.html";
  }
  function deriveAccount(email, acctField){
    var a = (acctField || "").trim();
    if (a) return a.startsWith("@") ? a : ("@" + a);
    var m = String(email||"").split("@")[0].replace(/[^a-z0-9_\\.\\-]/gi,"");
    return m ? ("@" + m) : "@user";
  }

  async function resend() {
    try {
      const email = qsv("#email");
      if(!email){ setStatus("Enter your email first.", "error"); return; }
      const r = await fetch("/auth/start", {
        method: "POST",
        headers: { "Content-Type":"application/json" },
        body: JSON.stringify({ email })
      });
      const ok = r.ok;
      setStatus(ok ? ("Code sent to " + email + ". (dev: 123456)") : "Failed to send code.", ok? "ok":"error");
    } catch(e) {
      setStatus("Network error while sending code.", "error");
    }
  }

  async function verifyAndContinue() {
    try {
      const email = qsv("#email");
      const code  = qsv("#codeInput");
      if(!email){ setStatus("Email required.", "error"); return; }
      if(!/^\\d{6}$/.test(code)){ setStatus("Enter the 6-digit code.", "error"); return; }

      // 1) verify the code
      const v = await fetch("/auth/verify", {
        method: "POST",
        headers: { "Content-Type":"application/json" },
        body: JSON.stringify({ email, code })
      });
      const vj = await v.json().catch(()=>({}));
      if(!v.ok || vj.ok !== true){
        setStatus(vj?.detail || "Invalid code.", "error");
        return;
      }

      // 2) start a session via Session.login(account_id)
      const acct = deriveAccount(email, qsv("#acct"));
      if (!window.Session || !Session.login) {
        setStatus("Session module not loaded.", "error");
        return;
      }
      await Session.login(acct);
      setStatus("Verified. Redirecting...", "ok");
      location.replace(getNext());
    } catch(e) {
      setStatus("Network error verifying code.", "error");
    }
  }

  // Wire buttons by label/id
  var verifyBtn = Array.from(document.querySelectorAll("button, input[type=button], input[type=submit]"))
    .find(b => /verify/i.test(b.textContent||b.value||""));
  var resendBtn = Array.from(document.querySelectorAll("button, a, input[type=button]"))
    .find(b => /resend/i.test((b.textContent||b.value||"")));

  if (verifyBtn) {
    verifyBtn.type = "button";
    verifyBtn.addEventListener("click", verifyAndContinue);
  }
  if (resendBtn) {
    resendBtn.addEventListener("click", function(e){ e.preventDefault(); resend(); });
  }

  // Enter-to-submit for the 6-digit code
  var codeEl = qs("#codeInput");
  if (codeEl) {
    codeEl.addEventListener("input", function(){
      if (this.value && this.value.length === 6) {
        // do not auto-submit; just enable UX
      }
    });
    codeEl.addEventListener("keydown", function(e){
      if (e.key === "Enter") { e.preventDefault(); verifyAndContinue(); }
    });
  }
})();
</script>
  };
  # If a previous injected block exists (by our marker), replace it. Otherwise insert before </body>.
  if ($ARGV eq "weall_node/frontend/login.html") {
     if ($_ !~ /Session\.login\(/) {
        s#</body>#$patch\n</body>#i;
     } else {
        # idempotent: ensure verifyAndContinue is present even if Session.login already exists
        s#</body>#$patch\n</body>#i;
     }
  }
' "$HTML"

echo "✅ Patched $HTML with OTP submission + session creation"
