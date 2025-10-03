const API_BASE = "http://localhost:8000";

// -------------------- Onboarding --------------------
async function signUp() {
    const userId = document.getElementById("user-id").value;
    const pohLevel = parseInt(document.getElementById("poh-level").value);

    const res = await fetch(`${API_BASE}/users`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({user_id: userId, poh_level: pohLevel})
    });

    const data = await res.json();
    const resultEl = document.getElementById("signup-result");

    if (res.ok) {
        resultEl.innerHTML = `<p>Sign-up successful! Welcome, ${userId}.</p>`;
    } else {
        resultEl.innerHTML = `<p>Error: ${data.detail}</p>`;
    }
}

// -------------------- Feed --------------------
async function loadFeed() {
    const res = await fetch(`${API_BASE}/posts`);
    const posts = await res.json();
    const feedEl = document.getElementById("feed");
    feedEl.innerHTML = "";

    posts.forEach(post => {
        const card = document.createElement("div");
        card.className = "post-card";
        card.innerHTML = `
            <h3>${post.user}</h3>
            <p>${post.content}</p>
            <div>Tags: ${post.tags.join(", ")}</div>
            <button onclick="commentPost(${post.id})">Comment</button>
        `;
        feedEl.appendChild(card);
    });
}

// -------------------- Profile --------------------
async function loadProfile() {
    const userId = document.getElementById("user-id").value;
    const res = await fetch(`${API_BASE}/users/${userId}`);
    const data = await res.json();
    const profileEl = document.getElementById("profile-data");

    if (data.error) {
        profileEl.innerHTML = `<p>${data.error}</p>`;
        return;
    }

    profileEl.innerHTML = `
        <h3>${data.user}</h3>
        <p>PoH Level: ${data.poh_level}</p>
        <p>Balance: ${data.balance}</p>
        <p>Posts: ${data.posts.length}</p>
        <button onclick="newPost('${data.user}')">New Post</button>
    `;
}

// -------------------- Posting --------------------
async function newPost(userId) {
    const content = prompt("Enter post content:");
    const tagsInput = prompt("Enter tags (comma separated):");
    const tags = tagsInput ? tagsInput.split(",") : [];

    const res = await fetch(`${API_BASE}/posts`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({user_id: userId, content, tags})
    });

    const data = await res.json();
    if (res.ok) {
        alert(`Post created! ID: ${data.post_id}`);
        loadFeed();
    } else {
        alert(`Error: ${data.detail}`);
    }
}

// -------------------- Commenting --------------------
async function commentPost(postId) {
    const userId = prompt("Your User ID:");
    const content = prompt("Enter your comment:");

    const res = await fetch(`${API_BASE}/comments`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({user_id: userId, post_id: postId, content})
    });

    const data = await res.json();
    if (res.ok) {
        alert(`Comment created! ID: ${data.comment_id}`);
        loadFeed();
    } else {
        alert(`Error: ${data.detail}`);
    }
}

// -------------------- Governance / Proposals --------------------
async function loadProposals() {
    const res = await fetch(`${API_BASE}/proposals`);
    const proposals = await res.json();
    const listEl = document.getElementById("proposal-list");
    listEl.innerHTML = "";

    proposals.forEach(p => {
        const card = document.createElement("div");
        card.className = "proposal-card";
        card.innerHTML = `
            <h3>${p.title}</h3>
            <p>${p.description}</p>
            <small>By: ${p.user}</small>
            <button onclick="voteProposal(${p.id})">Vote</button>
        `;
        listEl.appendChild(card);
    });
}

async function voteProposal(proposalId) {
    const userId = prompt("Your User ID:");
    const vote = prompt("Enter vote (yes/no):");

    const res = await fetch(`${API_BASE}/vote`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({user_id: userId, proposal_id: proposalId, vote_option: vote})
    });

    const data = await res.json();
    if (res.ok) {
        alert("Vote recorded!");
        loadProposals();
    } else {
        alert(`Error: ${data.detail}`);
    }
}

// -------------------- Auto-load feed --------------------
if (document.getElementById("feed")) {
    loadFeed();
}
if (document.getElementById("proposal-list")) {
    loadProposals();
}
