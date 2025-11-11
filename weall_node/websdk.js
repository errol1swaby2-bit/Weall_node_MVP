// weall_node/websdk.js
// Lightweight browser SDK for WeAll Node v3.1 (HTTPS + PoH + WebRTC signaling)
// Usage (ES module):
//   import { WeAllAPI, WeAllWebRTC } from './websdk.js';
//   const api = new WeAllAPI('https://node.host:8443');
//   const rtc = new WeAllWebRTC(api, { onLog: console.log });
//
// No dependencies. Works with <script type="module"> in a static frontend.

export class WeAllAPI {
  constructor(baseURL = '') {
    this.baseURL = baseURL.replace(/\/+$/, '');
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

// ---------------- WeAllWebRTC: browser-side helper for panel/rooms ----------------
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
    // Attach to already-open PCs if publishing
    if (this.isPublisher) {
      for (const pc of this.pcMap.values()) {
        this.localStream.getTracks().forEach(t => pc.addTrack(t, this.localStream));
      }
    } else {
      // Mute tracks if not publishing (watch-only)
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

    // Derive isPublisher & role as enforced by server
    const selfMeta = (res.participants || []).find(p => p.client_id === this.clientId);
    this.isPublisher = !!(selfMeta && selfMeta.publisher);
    this.role = (selfMeta && selfMeta.role) || this.role;

    // Start media if publishing
    if (this.isPublisher) {
      await this.startMedia();
    }

    // Setup initial offers to existing peers (server may push presence soon too)
    await this._refreshRoster();
    for (const p of res.participants || []) {
      if (p.client_id !== this.clientId && this.isPublisher) {
        await this._makeOffer(p.client_id);
      }
    }

    // Start polling
    this._pollAbort = false;
    this._pollLoop().catch(e => this.log(`poll error: ${e.message}`));
    return res;
  }

  async leaveRoom() {
    if (!this.roomId || !this.clientId) return;
    this._pollAbort = true;
    try { await this.api.leave({ roomId: this.roomId, clientId: this.clientId }); } catch {}
    for (const pc of this.pcMap.values()) { try { pc.close(); } catch {} }
    this.pcMap.clear();
    this.stopMedia();
    this.opts.onDisconnected();
    this.log('Left room');
  }

  async publish(enable = true, roleOverride = undefined) {
    if (!this.roomId || !this.clientId) throw new Error('join the room first');
    const role = roleOverride || this.role;
    const out = await this.api.roomPublish({ roomId: this.roomId, clientId: this.clientId, enable, role });
    this.isPublisher = enable;
    if (enable && this.localStream == null) {
      await this.startMedia();
    }
    // Offer to everyone if just enabled publish
    if (enable) {
      for (const p of (out.participants || [])) {
        if (p.client_id !== this.clientId) await this._makeOffer(p.client_id);
      }
    }
    return out;
  }

  // ---- Internal helpers
  _randClientId() {
    if (crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, '').slice(0, 12);
    return Math.random().toString(16).slice(2, 14);
  }

  async _refreshRoster() {
    if (!this.roomId) return;
    try {
      const s = await this.api.roomState(this.roomId);
      this.opts.onRoster(s.participants || []);
    } catch {}
  }

  async _pollLoop() {
    while (!this._pollAbort) {
      try {
        const r = await this.api.poll({ roomId: this.roomId, clientId: this.clientId, sinceMid: this.lastMid });
        this.lastMid = r.last_mid || this.lastMid;
        for (const m of r.messages || []) {
          this.lastMid = Math.max(this.lastMid, m.mid);
          if ((m.from || '') === this.clientId) continue;
          await this._handleSignal(m);
        }
      } catch (e) {
        this.log(`poll error: ${e.message}`);
        await new Promise(r => setTimeout(r, 800));
      }
    }
  }

  async _handleSignal(m) {
    const { from, type, data } = m;
    if (type === 'offer') {
      await this._handleOffer(from, data.sdp);
    } else if (type === 'answer') {
      await this._handleAnswer(from, data.sdp);
    } else if (type === 'candidate') {
      await this._handleCandidate(from, data.candidate);
    } else if (type === 'bye') {
      const id = (data && (data.client_id || from)) || from;
      const pc = this.pcMap.get(id);
      if (pc) try { pc.close(); } catch {}
      this.pcMap.delete(id);
      this.opts.onRoster(await this.api.roomState(this.roomId).then(r => r.participants || []));
    } else if (type === 'presence') {
      // join/publish/unpublish notifications
      await this._refreshRoster();
      if (this.isPublisher && data && data.client_id && data.client_id !== this.clientId && data.event !== 'unpublish') {
        await this._makeOffer(data.client_id);
      }
    } else {
      this.opts.onMessage(m);
    }
  }

  async _pcFor(peerId) {
    let pc = this.pcMap.get(peerId);
    if (pc) return pc;

    pc = new RTCPeerConnection({ iceServers: await this.loadIce() });
    this.pcMap.set(peerId, pc);

    pc.onicecandidate = ev => {
      if (ev.candidate) {
        this.api.signal({ roomId: this.roomId, from: this.clientId, to: peerId, type: 'candidate', data: { candidate: ev.candidate } })
          .catch(e => this.log('candidate send failed: ' + e.message));
      }
    };
    pc.ontrack = ev => {
      const stream = ev.streams[0];
      this.opts.onRemoteTrack(peerId, stream);
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === 'failed' || pc.connectionState === 'closed' || pc.connectionState === 'disconnected') {
        // keep map but app may decide to remove
      }
    };

    if (this.isPublisher && this.localStream) {
      this.localStream.getTracks().forEach(t => pc.addTrack(t, this.localStream));
    }

    return pc;
  }

  async _makeOffer(peerId) {
    const pc = await this._pcFor(peerId);
    const offer = await pc.createOffer({ offerToReceiveAudio: true, offerToReceiveVideo: true });
    await pc.setLocalDescription(offer);
    await this.api.signal({
      roomId: this.roomId,
      from: this.clientId,
      to: peerId,
      type: 'offer',
      data: { sdp: pc.localDescription }
    });
  }

  async _handleOffer(from, sdp) {
    const pc = await this._pcFor(from);
    await pc.setRemoteDescription(sdp);
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    await this.api.signal({
      roomId: this.roomId,
      from: this.clientId,
      to: from,
      type: 'answer',
      data: { sdp: pc.localDescription }
    });
  }

  async _handleAnswer(from, sdp) {
    const pc = this.pcMap.get(from);
    if (!pc) return;
    await pc.setRemoteDescription(sdp);
  }

  async _handleCandidate(from, candidate) {
    const pc = await this._pcFor(from);
    try { await pc.addIceCandidate(candidate); } catch {}
  }
}
