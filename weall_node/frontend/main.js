// ===========================================================
// WeAll Frontend — Unified Controller
// Auto-refresh (30s), visual pulses on new data,
// clears badges when user visits that tab
// ===========================================================

const API_BASE = location.origin;
const snapshots = { feedIds: new Set(), govIds: new Set(), balance: null, reputation: null };
let refreshIntervals = { feed: null, gov: null, profile: null };

// ===========================================================
// LOGIN / SESSION
// ===========================================================
document.addEventListener("DOMContentLoaded", () => {
  const userId = localStorage.getItem("user_id");
  const page = window.location.pathname.split("/").pop();

  if ((page === "" || page === "index.html") && !userId) {
    window.location.href = "login.html"; return;
  }
  if (page === "login.html" && userId) {
    window.location.href = "index.html"; return;
  }

  const welcome = document.getElementById("welcome-user");
  if (welcome && userId) welcome.textContent = `Welcome, ${userId}`;

  if (document.getElementById("feed")) initFeedRefresh();
  if (document.getElementById("proposal-list")) initGovRefresh();
  if (document.getElementById("profile-data")) initProfileRefresh();
});

// ===========================================================
// HELPERS
// ===========================================================
async function api(path, { method="GET", body, headers }={}) {
  const opts = { method, headers:{ "Content-Type":"application/json", ...(headers||{}) } };
  if (body!==undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`${API_BASE}${path}`, opts);
  let data; try { data = await res.json(); } catch { data = {}; }
  if (!res.ok) throw new Error(data.error || data.detail || res.statusText);
  return data;
}

function addPulse(el){
  if(!el)return;
  el.classList.remove("pulse"); el.offsetWidth; // reset animation
  el.classList.add("pulse");
  setTimeout(()=>el.classList.remove("pulse"),1200);
}
function setUpdatedStamp(el){ if(el) el.textContent="Last updated: "+new Date().toLocaleTimeString(); }
function setBadgeVisible(id,visible){ const b=document.getElementById(id); if(b) b.style.opacity=visible?"1":"0"; }

// ===========================================================
// FEED
// ===========================================================
async function loadFeed(){
  const feed=document.getElementById("feed");
  const stamp=document.getElementById("feed-last-updated");
  const panel=document.getElementById("feed-panel");
  if(!feed)return;
  try{
    const posts=await api("/show_posts");
    const ids=new Set(Object.keys(posts));
    let hasNew=false;
    for(const id of ids) if(!snapshots.feedIds.has(id)){hasNew=true;break;}
    snapshots.feedIds=ids;
    feed.innerHTML="";
    for(const [pid,p] of Object.entries(posts)){
      const d=document.createElement("div");
      d.className="post-card";
      d.innerHTML=`<h3>${p.user}</h3><p>${p.content}</p><small>Tags: ${(p.tags||[]).join(", ")}</small><br><button onclick="commentPost(${pid})">Comment</button>`;
      feed.appendChild(d);
    }
    setUpdatedStamp(stamp);
    setBadgeVisible("badge-feed",hasNew);
    if(hasNew)addPulse(panel);
  }catch(e){feed.innerHTML=`<p>Error: ${e}</p>`;}
}
function initFeedRefresh(){loadFeed();clearInterval(refreshIntervals.feed);refreshIntervals.feed=setInterval(loadFeed,30000);}

// ===========================================================
// GOVERNANCE
// ===========================================================
async function loadProposals(){
  const list=document.getElementById("proposal-list");
  const stamp=document.getElementById("gov-last-updated");
  const panel=document.getElementById("gov-panel");
  if(!list)return;
  try{
    const props=await api("/governance/proposals");
    const ids=new Set(Object.keys(props));
    let hasNew=false;
    for(const id of ids) if(!snapshots.govIds.has(id)){hasNew=true;break;}
    snapshots.govIds=ids;
    list.innerHTML="";
    for(const [pid,p] of Object.entries(props)){
      const c=document.createElement("div");
      c.className="proposal-card";
      c.innerHTML=`<h3>${p.title||p.module}</h3><small>Status: ${p.status||"open"}</small><br><button onclick="voteProposal('${pid}')">Vote</button>`;
      list.appendChild(c);
    }
    setUpdatedStamp(stamp);
    setBadgeVisible("badge-gov",hasNew);
    if(hasNew)addPulse(panel);
  }catch(e){list.innerHTML=`<p>Error: ${e}</p>`;}
}
function initGovRefresh(){loadProposals();clearInterval(refreshIntervals.gov);refreshIntervals.gov=setInterval(loadProposals,30000);}

// ===========================================================
// PROFILE
// ===========================================================
async function loadProfile(){
  const userId=localStorage.getItem("user_id");
  const profile=document.getElementById("profile-data");
  const panel=document.getElementById("profile-panel");
  const stamp=document.getElementById("profile-last-updated");
  if(!userId||!profile)return;
  try{
    const bal=await api(`/ledger/balance/${userId}`);
    let rep={score:"N/A"};try{rep=await api(`/reputation/${userId}`);}catch{}
    const balChanged=snapshots.balance!==null&&snapshots.balance!==bal.balance;
    const repChanged=snapshots.reputation!==null&&snapshots.reputation!==rep.score;
    snapshots.balance=bal.balance;snapshots.reputation=rep.score;
    profile.innerHTML=`<h3>${userId}</h3><p>Balance: <span id="balance-value">${bal.balance}</span></p><p>Reputation: <span id="reputation-value">${rep.score??"N/A"}</span></p><button onclick="newPost('${userId}')">New Post</button>`;
    setUpdatedStamp(stamp);
    setBadgeVisible("badge-profile",balChanged||repChanged);
    if(balChanged||repChanged)addPulse(panel);
  }catch(e){profile.innerHTML=`<p>Error: ${e}</p>`;}
}
function initProfileRefresh(){loadProfile();clearInterval(refreshIntervals.profile);refreshIntervals.profile=setInterval(loadProfile,30000);}

// ===========================================================
// POSTS / COMMENTS / VOTING
// ===========================================================
async function newPost(uid){const c=prompt("Post content:");if(!c)return;const t=prompt("Tags (comma-separated):");const tags=t?t.split(","):[];const r=await api("/post",{method:"POST",body:{user_id:uid,content:c,tags}});alert(`Post created: ${JSON.stringify(r)}`);loadFeed();}
async function commentPost(pid){const u=prompt("Your User ID:");if(!u)return;const c=prompt("Comment:");if(!c)return;const r=await api("/comment",{method:"POST",body:{user_id:u,post_id:pid,content:c}});alert(r.ok?"Comment added!":JSON.stringify(r));loadFeed();}
async function voteProposal(pid){const u=prompt("User ID:");if(!u)return;const v=prompt("Vote (yes/no):");if(!v)return;const r=await api("/governance/vote",{method:"POST",body:{user:u,proposal_id:pid,vote:v}});alert(`Vote result: ${JSON.stringify(r)}`);loadProposals();}

// ===========================================================
// LOGOUT
// ===========================================================
function logout(){Object.values(refreshIntervals).forEach(clearInterval);localStorage.removeItem("user_id");location.href="login.html";}
