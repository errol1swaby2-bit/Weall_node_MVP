<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>WeAll • Verify (Phase A)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body{margin:0;background:#000;color:#fff;font-family:system-ui,Arial,sans-serif}
    header{padding:12px 16px;background:#111;border-bottom:1px solid #222}
    main{padding:16px}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    video{width:100%;background:#111;border:1px solid #333;border-radius:8px;aspect-ratio:16/9}
    .bar{display:flex;gap:8px;margin:12px 0}
    button{background:#1f2937;color:#fff;border:1px solid #374151;border-radius:8px;padding:8px 12px;cursor:pointer}
    .pill{display:inline-block;padding:4px 8px;border:1px solid #333;border-radius:999px;background:#0b0b0b;margin-right:8px}
    .status{font-size:14px;opacity:.9}
    .muted{opacity:.7}
    .row{display:flex;align-items:center;gap:10px}
  </style>
</head>
<body>
  <header>
    <div class="row">
      <strong>WeAll • Phase A Verification</strong>
      <span id="rolePill" class="pill"></span>
      <span id="uidPill" class="pill"></span>
      <span id="sessionPill" class="pill"></span>
    </div>
  </header>
  <main>
    <div class="bar">
      <button id="btnStart">Start Camera/Mic</button>
      <button id="btnMute" disabled>Mute</button>
      <button id="btnCamera" disabled>Camera Off</button>
      <span class="status" id="status">Idle</span>
    </div>
    <div class="grid">
      <div>
        <h4>Local</h4>
        <video id="localVideo" autoplay playsinline muted></video>
      </div>
      <div>
        <h4>Remote</h4>
        <video id="remoteVideo" autoplay playsinline></video>
      </div>
    </div>
  </main>

  <script>
  (function() {
    const qs = new URLSearchParams(location.search);
    const sessionId = qs.get('session_id');
    const role = qs.get('role'); // "founder" | "candidate"
    const uid = qs.get('uid') || role; // optional uid param (not strictly needed here)

    const statusEl = document.getElementById('status');
    const localVideo = document.getElementById('localVideo');
    const remoteVideo = document.getElementById('remoteVideo');
    const btnStart = document.getElementById('btnStart');
    const btnMute = document.getElementById('btnMute');
    const btnCamera = document.getElementById('btnCamera');

    document.getElementById('rolePill').textContent = `role=${role || '?'}`;
    document.getElementById('uidPill').textContent = `uid=${uid || '?'}`;
    document.getElementById('sessionPill').textContent = `session=${(sessionId||'').slice(0,8)}…`;

    if (!sessionId || !role) {
      statusEl.textContent = 'Missing session_id or role in URL.';
      btnStart.disabled = true;
      return;
    }

    let pc, ws, localStream;
    let audioOn = true, videoOn = true;

    const iceServers = [{ urls: "stun:stun.l.google.com:19302" }];

    function log(s){ console.log('[verify]', s); statusEl.textContent = s; }

    async function startLocal() {
      try {
        localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        localVideo.srcObject = localStream;
        btnMute.disabled = false;
        btnCamera.disabled = false;
        log('Camera/Mic ready. Waiting for room readiness…');
      } catch (e) {
        console.error(e);
        log('Could not access camera/microphone.');
      }
    }

    function toggleMute() {
      audioOn = !audioOn;
      localStream?.getAudioTracks().forEach(t => t.enabled = audioOn);
      btnMute.textContent = audioOn ? 'Mute' : 'Unmute';
    }

    function toggleCamera() {
      videoOn = !videoOn;
      localStream?.getVideoTracks().forEach(t => t.enabled = videoOn);
      btnCamera.textContent = videoOn ? 'Camera Off' : 'Camera On';
    }

    function createPeer() {
      pc = new RTCPeerConnection({ iceServers });
      pc.ontrack = ev => {
        if (ev.streams && ev.streams[0]) {
          remoteVideo.srcObject = ev.streams[0];
        } else {
          const inbound = new MediaStream([ev.track]);
          remoteVideo.srcObject = inbound;
        }
      };
      pc.onicecandidate = ev => {
        if (ev.candidate) {
          ws.send(JSON.stringify({ type: 'signal', data: { candidate: ev.candidate } }));
        }
      };
      if (localStream) {
        localStream.getTracks().forEach(t => pc.addTrack(t, localStream));
      }
    }

    async function makeOffer() {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      ws.send(JSON.stringify({ type: 'signal', data: { sdp: pc.localDescription } }));
      log('Sent SDP offer.');
    }

    async function handleSignal(msg) {
      const data = msg.data || msg;
      if (data.sdp) {
        await pc.setRemoteDescription(new RTCSessionDescription(data.sdp));
        if (data.sdp.type === 'offer') {
          const answer = await pc.createAnswer();
          await pc.setLocalDescription(answer);
          ws.send(JSON.stringify({ type: 'signal', data: { sdp: pc.localDescription } }));
          log('Received offer, sent answer.');
        } else {
          log('Answer set.');
        }
      } else if (data.candidate) {
        try { await pc.addIceCandidate(new RTCIceCandidate(data.candidate)); }
        catch (e) { console.warn('ICE add error', e); }
      }
    }

    function connectWS() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const base = `${proto}://${location.host}`;
      ws = new WebSocket(`${base}/ws/verify/${sessionId}?role=${encodeURIComponent(role)}`);
      ws.onopen = () => log('Signaling connected. Waiting for start…');
      ws.onmessage = async ev => {
        const msg = JSON.parse(ev.data);
        if (msg.action === 'start_webrtc') {
          if (!pc) createPeer();
          if (role === 'founder') await makeOffer();
          // candidate responds when receiving offer
        } else if (msg.type === 'signal') {
          await handleSignal(msg);
        } else if (msg.status) {
          log(`Room: ${msg.status}`);
        }
      };
      ws.onclose = () => log('Signaling closed.');
      ws.onerror = () => log('Signaling error.');
    }

    btnStart.addEventListener('click', async () => {
      await startLocal();
      connectWS();
    });
    btnMute.addEventListener('click', toggleMute);
    btnCamera.addEventListener('click', toggleCamera);
  })();
  </script>
</body>
</html>
