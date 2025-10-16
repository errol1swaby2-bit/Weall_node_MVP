(function(){
  const API_BASE=location.origin;
  if(!document.getElementById("sessionFooter")){
    const f=document.createElement("footer");
    f.id="sessionFooter";
    f.style.cssText=`
      position:fixed;bottom:0;left:0;right:0;
      background:#111;color:#ccc;
      display:flex;justify-content:space-between;align-items:center;
      padding:6px 12px;font-size:13px;
      border-top:1px solid #222;z-index:9999;
    `;
    f.innerHTML=`
      <span id="sessionUser">User: —</span>
      <span id="sessionStatus">Tier: — | Epoch: — | Node: …</span>
      <button id="logoutBtn" style="background:#222;border:none;color:#fff;padding:4px 10px;border-radius:4px;cursor:pointer;">Logout</button>
    `;
    document.body.appendChild(f);
  }

  async function updateFooter(){
    const u=localStorage.getItem('weall_user_id');
    const userEl=document.getElementById('sessionUser');
    const statEl=document.getElementById('sessionStatus');
    if(!u){
      userEl.textContent="User: —";
      statEl.textContent="Tier: — | Epoch: — | Node: offline";
      return;
    }
    userEl.textContent=`User: ${u}`;
    try{
      const [statusRes,healthRes]=await Promise.all([
        fetch(`${API_BASE}/poh/status/${u}`),
        fetch(`${API_BASE}/healthz`)
      ]);
      let tier="—",epoch="—",node="🔴 Offline";
      if(statusRes.ok){
        const d=await statusRes.json();
        tier=d.poh_level??"—";
        epoch=d.epoch??"—";
      }
      if(healthRes.ok){
        const h=await healthRes.json();
        node=h.ok?"✅ Online":"🔴 Offline";
      }
      statEl.textContent=`Tier: ${tier} | Epoch: ${epoch} | Node: ${node}`;
    }catch{
      statEl.textContent="Tier: — | Epoch: — | Node: 🔴 Offline";
    }
  }

  function logout(){
    localStorage.removeItem('weall_user_id');
    localStorage.removeItem('weall_email');
    alert("Logged out.");
    window.location.href="login.html";
  }

  document.getElementById("logoutBtn").onclick=logout;
  updateFooter();
  setInterval(updateFooter,8000);
})();
