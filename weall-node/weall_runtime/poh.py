# weall_runtime/poh.py
import uuid
import json
import hashlib
from datetime import datetime
from .ledger import (
    create_application_record,
    get_application,
    set_application_status,
    add_juror_vote,
    get_juror_votes,
    add_block,
    register_user,
)
from .utils import choose_jurors_for_application, simple_threshold_check
from .crypto_utils import verify_ed25519_sig

# Configurable thresholds
DEFAULT_JUROR_COUNT = 10
DEFAULT_APPROVAL_THRESHOLD = 7  # need >=7 approvals

# ---------------------------
# Tier 1: Basic onboarding
# ---------------------------
def apply_tier1(user_pub: str, email_hash: str):
    """
    Tier1 onboarding: minimal KYC (hashed email)
    """
    register_user(user_pub, poh_cid=None, tier=1)
    payload = {
        "type": "poh_tier1",
        "user_pub": user_pub,
        "email_hash": email_hash,
        "issued_at": datetime.utcnow().isoformat()
    }
    bh = hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()
    add_block(bh, "0", payload)
    return {"ok": True, "user_pub": user_pub, "tier": 1}

# ---------------------------
# Tier 2: Asynchronous video verification
# ---------------------------
def apply_tier2(user_pub: str, video_cid: str, meta: dict, node):
    """
    Create a Tier2 application: persist application and deterministically choose jurors.
    """
    app_id = str(uuid.uuid4())
    jurors = choose_jurors_for_application(node, count=DEFAULT_JUROR_COUNT)
    create_application_record(app_id, user_pub, tier_requested=2, video_cid=video_cid, meta=meta, jurors=jurors)

    payload = {
        "type": "poh_application_created",
        "app_id": app_id,
        "user_pub": user_pub,
        "tier": 2,
        "jurors": jurors,
        "video_cid": video_cid,
        "meta": meta
    }
    last_hash = node.get_last_block_hashes(1)[0] if node.get_last_block_hashes(1) else "0"
    add_block(hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest(), last_hash, payload)
    return {"app_id": app_id, "jurors": jurors}

def juror_submit_vote(app_id: str, juror_pub: str, vote: str, signature_b64: str):
    """
    Called when a juror submits a vote. Verify signature then persist.
    """
    msg = f"{app_id}:{vote}".encode("utf-8")
    if not verify_ed25519_sig(juror_pub, msg, signature_b64):
        return {"ok": False, "reason": "invalid_signature"}

    add_juror_vote(app_id, juror_pub, vote, signature_b64)
    votes_list = [v["vote"] for v in get_juror_votes(app_id)]

    if simple_threshold_check(votes_list, threshold=DEFAULT_APPROVAL_THRESHOLD):
        # Mint Tier2 PoH NFT
        app = get_application(app_id)
        cid = add_bytes(json.dumps({"user_pub": app.user_pub, "tier": 2, "app_id": app_id}).encode("utf-8"))
        set_application_status(app_id, "approved", mint_cid=cid)

        payload = {"type": "poh_minted", "app_id": app_id, "tier": 2, "cid": cid}
        add_block(hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest(), "0", payload)
        return {"ok": True, "finalized": True, "cid": cid}

    return {"ok": True, "finalized": False}

# ---------------------------
# Tier 3: Live video + governance
# ---------------------------
def apply_tier3(user_pub: str, requested_window: dict, node):
    """
    requested_window: {"from": iso_ts, "to": iso_ts}
    Returns scheduling token + jurors assigned
    """
    app_id = str(uuid.uuid4())
    jurors = choose_jurors_for_application(node, count=DEFAULT_JUROR_COUNT)
    create_application_record(app_id, user_pub, tier_requested=3, meta={"requested_window": requested_window}, jurors=jurors)

    payload = {"type": "poh_tier3_request", "app_id": app_id, "user_pub": user_pub, "jurors": jurors}
    last_hash = node.get_last_block_hashes(1)[0] if node.get_last_block_hashes(1) else "0"
    add_block(hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest(), last_hash, payload)

    # In production: notify jurors, schedule WebRTC live call
    return {"app_id": app_id, "jurors": jurors, "scheduled": False}

# ---------------------------
# Minimal IPFS storage fallback
# ---------------------------
def add_bytes(b: bytes):
    """
    Placeholder to add bytes to IPFS. Returns pseudo-CID if IPFS unavailable.
    """
    try:
        from .storage import NodeStorage
        node_storage = NodeStorage()
        return node_storage.add_bytes(b)
    except Exception:
        return f"cid-{hashlib.sha256(b).hexdigest()[:16]}"

class ProofOfHumanity:
    def __init__(self, ledger):
        self.ledger = ledger

    def apply_tier1(self, *args, **kwargs):
        return apply_tier1(*args, **kwargs)

    def apply_tier2(self, *args, **kwargs):
        return apply_tier2(*args, **kwargs)

    def apply_tier3(self, *args, **kwargs):
        return apply_tier3(*args, **kwargs)

    def juror_submit_vote(self, *args, **kwargs):
        return juror_submit_vote(*args, **kwargs)
