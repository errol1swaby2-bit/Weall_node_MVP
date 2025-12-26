// weall_node/websdk.js
// Lightweight browser/Capacitor SDK for WeAll Node.
// Includes:
// - WeAllAPI: simple fetch wrapper
// - WeAllRotatingClient: decentralized, self-healing peer rotation (purpose-aware)
// - WeAllWebRTC: WebRTC signaling helper for panel/rooms
//
// Purpose-aware routing:
//   client.setPurpose("feed" | "upload" | "governance" | "webrtc")
//   -> refresh uses /p2p/peers/pick_for?purpose=... when available
//
// No dependencies. Works with <script type="module"> in a static frontend.

/* ------------------------- Basic single-endpoint API ------------------------- */

export class WeAllAPI {
  constructor(baseURL = '') {
    this.baseURL = String(baseURL || '').replace(/\/+$/, '');
  }

  // ----------- HTTP helpers -----------
  async _get(path) {
    const r = await fetch(this.baseURL + path, { method: 'GET', credentials: 'include' });
    if (!r.ok) throw new Error(`GET ${path} -> ${r.status}`);
    return r.json();
  }

  async _post(path, body) {
    const r = await fetch(this.baseURL + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body || {}),
    });
    const txt = await r.text();
    let json = {};
    try { json = txt ? JSON.parse(txt) : {}; } catch { json = { raw: txt }; }
    if (!r.ok) throw new Error(json.error || `${r.status}`);
    return json;
  }

  // ----------- System / Config -----------
  health() { return this._get('/health'); }
  ping() { return this._get('/p2p/ping'); }
  p2pClientConfig() { return this._get('/p2p/client_config'); }
  p2pPickPeers(k = 10) { return this._get(`/p2p/peers/pick?k=${encodeURIComponent(k)}`); }
  p2pPickPeersFor(purpose = 'governance', k = 10) {
    const p = encodeURIComponent(String(purpose || 'governance'));
    const kk = encodeURIComponent(String(k || 10));
    return this._get(`/p2p/peers/pick_for?purpose=${p}&k=${kk}`);
  }

  getIceServers() { return this._get('/webrtc/config').then(x => x.iceServers || []); }

  // ----------- Auth tokens (Apply Mode) -----------
  authIssueApply(accountId) { return this._post('/auth/apply', { account_id: String(accountId) }); }
  authCheck(token, scope) { return this._post('/auth/check', { token, scope }); }

  // ----------- Tier-2 Async Verification -----------
  t2Submit({ accountId, videos, title = '', desc = '' }) {
    return this._post('/poh/t2/submit', { account_id: String(accountId), videos: videos || [], title, desc });
  }
  t2List({ status = undefined, limit = 50, offset = 0 } = {}) {
    return this._post('/poh/t2/list', { status, limit, offset });
  }
  t2Item(accountId) { return this._post('/poh/t2/item', { account_id: String(accountId) }); }
  t2Vote({ candidateId, jurorId, approve }) {
    return this._post('/poh/t2/vote', { candidate_id: String(candidateId), juror_id: String(jurorId), approve: !!approve });
  }
  t2ConfigGet() { return this._post('/poh/t2/config', {}); }
  t2ConfigSet({ required_yes, max_pending } = {}) { return this._post('/poh/t2/config', { required_yes, max_pending }); }

  // ----------- PoH status -----------
  pohStatus(accountId) { return this._post('/poh/status', { account_id: String(accountId) }); }

  // ----------- Tier-3 Onboarding (Panel) -----------
  onboardingStart({ accountId, tier }) { return this._post('/weall/onboarding/start', { account_id: String(accountId), tier: Number(tier) }); }
  onboardingEvidence({ accountId, cids }) { return this._post('/weall/onboarding/evidence', { account_id: String(accountId), cids: cids || [] }); }
  onboardingLiveness({ accountId, provider, score = 0, passed = false }) {
    return this._post('/weall/onboarding/liveness', { account_id: String(accountId), provider, score: Number(score), passed: !!passed });
  }
  onboardingSchedulePanel({ accountId, required = 10 }) {
    return this._post('/weall/onboarding/panel/schedule', { account_id: String(accountId), required: Number(required) });
  }
  onboardingPanelVote({ panelId, jurorId, approve }) {
    return this._post('/weall/onboarding/panel/vote', { panel_id: String(panelId), juror_id: String(jurorId), approve: !!approve });
  }
  onboardingPanelForRoom(roomId) { return this._post('/weall/onboarding/panel/for_room', { room_id: String(roomId) }); }
  onboardingFinalize(accountId) { return this._post('/weall/onboarding/finalize', { account_id: String(accountId) }); }

  // ----------- WebRTC signaling -----------
  roomCreate({ policy = undefined, owner = undefined, panelId = undefined } = {}) {
    return this._post('/webrtc/room', { policy, owner, panel_id: panelId });
  }
  roomJoin({ roomId, clientId, accountId, role, publisher }) {
    return this._post('/webrtc/join', {
      room_id: String(roomId),
      client_id: String(clientId),
      account_id: accountId == null ? null : String(accountId),
      role,
      publisher: publisher === undefined ? undefined : !!publisher,
    });
  }
  roomState(roomId) { return this._post('/webrtc/state', { room_id: String(roomId) }); }
  roomPublish({ roomId, clientId, enable = true, role }) {
    return this._post('/webrtc/publish', { room_id: String(roomId), client_id: String(clientId), enable: !!enable, role });
  }
  signal({ roomId, from, to = null, type, data = {} }) {
    return this._post('/webrtc/signal', { room_id: String(roomId), from: String(from), to, type, data });
  }
  poll({ roomId, clientId, sinceMid = 0 }) {
    return this._post('/webrtc/poll', { room_id: String(roomId), client_id: String(clientId), since_mid: Number(sinceMid) });
  }
  leave({ roomId, clientId }) { return this._post('/webrtc/leave', { room_id: String(roomId), client_id: String(clientId) }); }
}

/* ------------------------- Rotating peer client (purpose-aware) ------------------------- */

function _nowSec() { return Math.floor(Date.now() / 1000); }

function _safeParseJSON(s, fallback) {
  try { return JSON.parse(s); } catch { return fallback; }
}

function _shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function _uniqAddrs(addrs) {
  const out = [];
  const seen = new Set();
  for (const a of addrs || []) {
    const x = String(a || '').replace(/\/+$/, '');
    if (!x) continue;
    if (seen.has(x)) continue;
    seen.add(x);
    out.push(x);
  }
  return out;
}

function _clamp(n, lo, hi) {
  n = Number(n);
  if (!Number.isFinite(n)) return lo;
  return Math.max(lo, Math.min(hi, n));
}

/**
 * WeAllRotatingClient
 * - Maintains a local pool of peer base URLs
 * - Uses /p2p/client_config and /p2p/peers/pick_for?purpose=... to learn the mesh
 * - Automatically fails over on request errors
 *
 * Purpose-aware:
 * - "feed" routes to video-capable operators when available
 * - "upload" routes to operator/pinning/bandwidth-friendly peers when available
 * - "governance" routes to reliable peers
 * - "webrtc" routes to signaling-friendly peers
 */
export class WeAllRotatingClient {
  constructor(opts = {}) {
    this.storageKey = opts.storageKey || 'weall_peer_pool_v1';

    // Bootstrap seeds you ship in the APK/web config.
    this.seeds = _uniqAddrs(opts.seeds || []);

    // Default purpose (can be changed at runtime)
    this.purpose = String(opts.purpose || 'governance').toLowerCase();

    // Client rules (can be refreshed from network)
    this.rules = {
      pick_k: 10,
      refresh_interval_sec: 180,
      timeout_ms: 2500,
      fail_cooldown_sec: 60,
      max_pool: 64,
      mix: { top_frac: 0.6, random_frac: 0.4 },
      ...(opts.rules || {}),
    };

    // Pool entries: { base, score, lastOk, lastFail, cooldownUntil, lastSeen }
    this.pool = [];
    this.lastRefreshSec = 0;

    this._load();

    // Ensure seeds are present
    for (const s of this.seeds) this._upsertBase(s, { score: 0 });

    // Optional: start background refresh loop
    if (opts.autoRefresh !== false) {
      this._startBackgroundRefresh();
    }
  }

  /* ------------------------- Public controls ------------------------- */

  setPurpose(purpose) {
    const p = String(purpose || '').toLowerCase().trim();
    if (!p) return;
    // Accept only known purposes; ignore junk
    if (!['feed', 'upload', 'governance', 'webrtc'].includes(p)) return;
    this.purpose = p;
    // Encourage quicker adaptation after a purpose switch
    this.lastRefreshSec = 0;
    this._save();
  }

  getPurpose() {
    return this.purpose;
  }

  /**
   * call(fn)
   * - Picks a peer
   * - Runs fn(api)
   * - If it fails, rotates to another peer and retries
   */
  async call(fn, { retries = 2 } = {}) {
    const attempts = Math.max(0, Number(retries) || 0) + 1;

    for (let i = 0; i < attempts; i++) {
      await this._maybeRefresh();

      const base = this._pickBase();
      if (!base) throw new Error('No peers available');

      const api = new WeAllAPI(base);

      try {
        const res = await this._withTimeout(() => fn(api), this.rules.timeout_ms);
        this._markOk(base);
        this._save();
        return res;
      } catch (e) {
        this._markFail(base);
        this._save();
        if (i === attempts - 1) throw e;
      }
    }

    throw new Error('call failed');
  }

  getPeers() {
    return this.pool.map(p => ({ ...p }));
  }

  /* ------------------------- Internal: refresh + learning ------------------------- */

  async _maybeRefresh() {
    const now = _nowSec();
    const interval = _clamp(this.rules.refresh_interval_sec, 30, 3600);
    if (now - this.lastRefreshSec < interval) return;
    await this._refreshFromNetwork();
  }

  async _refreshFromNetwork() {
    const now = _nowSec();
    this.lastRefreshSec = now;

    const candidates = _shuffle(_uniqAddrs([
      ...this.seeds,
      ...this.pool.map(p => p.base),
    ])).slice(0, 6);

    const timeoutMs = _clamp(this.rules.timeout_ms, 500, 15000);
    const pickK = _clamp(this.rules.pick_k, 3, 30);

    for (const base of candidates) {
      const api = new WeAllAPI(base);
      try {
        // 1) Pull client rules (optional)
        const cfg = await this._withTimeout(() => api.p2pClientConfig(), timeoutMs);
        if (cfg && cfg.rules && typeof cfg.rules === 'object') {
          // merge conservatively
          this.rules = { ...this.rules, ...cfg.rules };
        }
        if (cfg && Array.isArray(cfg.seeds)) {
          for (const s of _uniqAddrs(cfg.seeds)) this._upsertBase(s, { score: 0 });
        }

        // 2) Pull purpose-aware peer pick (preferred)
        let pick = null;
        try {
          pick = await this._withTimeout(() => api.p2pPickPeersFor(this.purpose, pickK), timeoutMs);
        } catch {
          // fallback to generic pick if node doesn't support pick_for yet
          pick = await this._withTimeout(() => api.p2pPickPeers(pickK), timeoutMs);
        }

        const peers = (pick && pick.peers) || [];
        for (const p of peers) {
          const addr = String(p.addr || '').replace(/\/+$/, '');
          if (!addr) continue;
          const score = Number(p.score || 0);
          this._upsertBase(addr, { score });
        }

        this._capPool();
        this._save();
        return;
      } catch {
        // try next candidate
      }
    }

    // If refresh failed everywhere, still enforce cap
    this._capPool();
    this._save();
  }

  _startBackgroundRefresh() {
    const tick = async () => {
      try { await this._maybeRefresh(); } catch {}
      setTimeout(tick, 5000);
    };
    setTimeout(tick, 1000);
  }

  /* ------------------------- Internal: pool management ------------------------- */

  _capPool() {
    const max = _clamp(this.rules.max_pool, 8, 256);
    if (this.pool.length <= max) return;

    const now = _nowSec();
    const ranked = this.pool
      .map(p => {
        const okAge = p.lastOk ? (now - p.lastOk) : 10000;
        const okBoost = 1.0 / (1.0 + okAge / 300.0);
        const eff = (Number(p.score || 0)) + (2.0 * okBoost);
        return { p, eff };
      })
      .sort((a, b) => b.eff - a.eff);

    this.pool = ranked.slice(0, max).map(x => x.p);
  }

  _upsertBase(base, { score = 0 } = {}) {
    base = String(base || '').replace(/\/+$/, '');
    if (!base) return;

    let rec = this.pool.find(p => p.base === base);
    if (!rec) {
      rec = { base, score: Number(score || 0), lastOk: 0, lastFail: 0, cooldownUntil: 0, lastSeen: _nowSec() };
      this.pool.push(rec);
      return;
    }
    rec.lastSeen = _nowSec();
    const s = Number(score || 0);
    if (Number.isFinite(s)) rec.score = Math.max(rec.score, s);
  }

  _markOk(base) {
    const now = _nowSec();
    const rec = this.pool.find(p => p.base === base);
    if (!rec) return;
    rec.lastOk = now;
    rec.cooldownUntil = 0;
    rec.score = Math.min(50, (rec.score || 0) + 0.25);
  }

  _markFail(base) {
    const now = _nowSec();
    const rec = this.pool.find(p => p.base === base);
    if (!rec) return;
    rec.lastFail = now;
    rec.cooldownUntil = now + _clamp(this.rules.fail_cooldown_sec, 5, 3600);
    rec.score = Math.max(-50, (rec.score || 0) - 0.75);
  }

  _pickBase() {
    const now = _nowSec();

    const live = this.pool.filter(p => !p.cooldownUntil || p.cooldownUntil <= now);
    const candidates = live.length ? live : this.pool;
    if (!candidates.length) return null;

    // Prefer reliable/high-score, but keep diversity.
    const sorted = candidates.slice().sort((a, b) => (b.score || 0) - (a.score || 0));
    const sliceN = Math.min(sorted.length, Math.max(3, Math.floor(sorted.length * 0.3)));
    const topSlice = sorted.slice(0, sliceN);

    // Weighted pick among top slice
    let total = 0;
    const weights = topSlice.map(p => {
      const w = Math.max(0.1, 1.0 + (p.score || 0));
      total += w;
      return w;
    });

    const r = Math.random() * total;
    let acc = 0;
    for (let i = 0; i < topSlice.length; i++) {
      acc += weights[i];
      if (r <= acc) return topSlice[i].base;
    }

    return topSlice[Math.floor(Math.random() * topSlice.length)].base;
  }

  /* ------------------------- Internal: persistence + timeout ------------------------- */

  _load() {
    try {
      const raw = localStorage.getItem(this.storageKey);
      if (!raw) return;
      const j = _safeParseJSON(raw, null);
      if (!j || !Array.isArray(j.pool)) return;

      this.lastRefreshSec = Number(j.lastRefreshSec || 0) || 0;
      if (j.rules && typeof j.rules === 'object') {
        this.rules = { ...this.rules, ...j.rules };
      }
      if (typeof j.purpose === 'string') {
        const p = j.purpose.toLowerCase();
        if (['feed', 'upload', 'governance', 'webrtc'].includes(p)) this.purpose = p;
      }

      this.pool = j.pool
        .filter(x => x && typeof x.base === 'string')
        .map(x => ({
          base: String(x.base).replace(/\/+$/, ''),
          score: Number(x.score || 0),
          lastOk: Number(x.lastOk || 0),
          lastFail: Number(x.lastFail || 0),
          cooldownUntil: Number(x.cooldownUntil || 0),
          lastSeen: Number(x.lastSeen || 0),
        }))
        .filter(x => x.base);
    } catch {
      // ignore
    }
  }

  _save() {
    try {
      localStorage.setItem(this.storageKey, JSON.stringify({
        lastRefreshSec: this.lastRefreshSec,
        purpose: this.purpose,
        rules: this.rules,
        pool: this.pool,
      }));
    } catch {
      // ignore (private mode)
    }
  }

  async _withTimeout(fn, timeoutMs) {
    const ms = _clamp(timeoutMs, 500, 15000);
    let timer = null;

    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('timeout')), ms);
    });

    try {
      return await Promise.race([fn(), timeout]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}

/* ---------------- WeAllWebRTC: browser-side helper for panel/rooms ---------------- */

export class WeAllWebRTC {
  constructor(api, opts = {}) {
    this.api = api;
    this.opts = Object.assign({
      onLog: () => {},
      onRoster: () => {},
      onRemoteTrack: () => {}, // (peerId, MediaStream)
      onDisconnected: () => {},
      onMessage: () => {},
    }, opts);

    this.iceServers = null;
    this.roomId = null;
    this.clientId = null;
    this.accountId = null;
    this.role = 'observer';

    this.localStream = null;
    this.pcMap = new Map(); // peerId -> RTCPeerConnection
    this.lastMid = 0;
    this._pollAbort = false;
    this.isPublisher = false;
  }

  log(msg) { try { this.opts.onLog(msg); } catch {} }

  async loadIce() {
    if (!this.iceServers) {
      try {
        const list = await this.api.getIceServers();
        this.iceServers = list && list.length ? list : [{ urls: ['stun:stun.l.google.com:19302'] }];
      } catch {
        this.iceServers = [{ urls: ['stun:stun.l.google.com:19302'] }];
      }
      this.log(`ICE servers ready (${this.iceServers.length})`);
    }
    return this.iceServers;
  }

  // ---- Media
  async startMedia({ video = true, audio = true } = {}) {
    if (this.localStream) return this.localStream;
    this.localStream = await navigator.mediaDevices.getUserMedia({ video, audio });
    this.log('Local media started');
    if (this.isPublisher) {
      for (const pc of this.pcMap.values()) {
        this.localStream.getTracks().forEach(t => pc.addTrack(t, this.localStream));
      }
    } else {
      this.localStream.getTracks().forEach(t => t.enabled = false);
    }
    return this.localStream;
  }

  stopMedia() {
    if (!this.localStream) return;
    this.localStream.getTracks().forEach(t => t.stop());
    this.localStream = null;
    this.log('Local media stopped');
  }

  // ---- Room lifecycle
  async createRoom({ policy, owner, panelId } = {}) {
    const { room_id } = await this.api.roomCreate({ policy, owner, panelId });
    this.roomId = room_id;
    this.lastMid = 0;
    return room_id;
  }

  async joinRoom({ roomId, clientId, accountId, role, publisher } = {}) {
    this.roomId = roomId || this.roomId;
    if (!this.roomId) throw new Error('roomId required');
    this.clientId = clientId || this._randClientId();
    this.accountId = accountId || null;
    this.role = role || 'observer';

    const res = await this.api.roomJoin({
      roomId: this.roomId,
      clientId: this.clientId,
      accountId: this.accountId,
      role: this.role,
      publisher,
    });

    const selfMeta = (res.participants || []).find(p => p.client_id === this.clientId);
    this.isPublisher = !!(selfMeta && selfMeta.publisher);
    this.role = (selfMeta && selfMeta.role) || this.role;

    if (this.isPublisher) await this.startMedia();

    await this._refreshRoster();
    for (const p of res.participants || []) {
      if (p.client_id !== this.clientId) {
        await this._ensurePeer(p.client_id, p.publisher);
      }
    }

    this._pollAbort = false;
    this._pollLoop();
    return res;
  }

  async leaveRoom() {
    this._pollAbort = true;
    if (this.roomId && this.clientId) {
      try { await this.api.leave({ roomId: this.roomId, clientId: this.clientId }); } catch {}
    }
    for (const pc of this.pcMap.values()) {
      try { pc.close(); } catch {}
    }
    this.pcMap.clear();
    this.roomId = null;
    this.clientId = null;
    this.lastMid = 0;
    this.stopMedia();
    try { this.opts.onDisconnected(); } catch {}
  }

  _randClientId() {
    return 'c_' + Math.random().toString(16).slice(2) + Math.random().toString(16).slice(2);
  }

  async _refreshRoster() {
    const st = await this.api.roomState(this.roomId);
    try { this.opts.onRoster(st.participants || []); } catch {}
    return st.participants || [];
  }

  async _ensurePeer(peerId) {
    if (this.pcMap.has(peerId)) return this.pcMap.get(peerId);
    await this.loadIce();
    const pc = new RTCPeerConnection({ iceServers: this.iceServers });
    this.pcMap.set(peerId, pc);

    pc.onicecandidate = async (ev) => {
      if (ev.candidate) {
        try {
          await this.api.signal({
            roomId: this.roomId,
            from: this.clientId,
            to: peerId,
            type: 'ice',
            data: ev.candidate,
          });
        } catch {}
      }
    };

    pc.ontrack = (ev) => {
      const stream = ev.streams && ev.streams[0] ? ev.streams[0] : new MediaStream([ev.track]);
      try { this.opts.onRemoteTrack(peerId, stream); } catch {}
    };

    if (this.isPublisher && this.localStream) {
      this.localStream.getTracks().forEach(t => pc.addTrack(t, this.localStream));
    }

    if (String(this.clientId) < String(peerId)) {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await this.api.signal({
        roomId: this.roomId,
        from: this.clientId,
        to: peerId,
        type: 'offer',
        data: offer,
      });
    }

    return pc;
  }

  async _handleSignal(msg) {
    const { from, type, data } = msg || {};
    if (!from || from === this.clientId) return;

    const pc = await this._ensurePeer(from);

    if (type === 'offer') {
      await pc.setRemoteDescription(data);
      const ans = await pc.createAnswer();
      await pc.setLocalDescription(ans);
      await this.api.signal({
        roomId: this.roomId,
        from: this.clientId,
        to: from,
        type: 'answer',
        data: ans,
      });
    } else if (type === 'answer') {
      await pc.setRemoteDescription(data);
    } else if (type === 'ice') {
      try { await pc.addIceCandidate(data); } catch {}
    } else {
      try { this.opts.onMessage(msg); } catch {}
    }
  }

  async _pollLoop() {
    while (!this._pollAbort) {
      try {
        const res = await this.api.poll({ roomId: this.roomId, clientId: this.clientId, sinceMid: this.lastMid });
        this.lastMid = res.last_mid || this.lastMid;

        if (res.roster) {
          try { this.opts.onRoster(res.roster || []); } catch {}
        }

        for (const msg of res.messages || []) {
          await this._handleSignal(msg);
        }
      } catch {
        await new Promise(r => setTimeout(r, 600));
      }

      await new Promise(r => setTimeout(r, 150));
    }
  }
}
