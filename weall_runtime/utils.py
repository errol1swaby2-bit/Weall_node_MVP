# weall_runtime/utils.py
import hashlib, random
import json

def deterministic_shuffle(items, seed_bytes):
    """
    Deterministic shuffle: use SHA256(seed_bytes) as integer seed.
    items: list of items (e.g., pubkeys)
    seed_bytes: bytes
    """
    if isinstance(seed_bytes, str):
        seed_bytes = seed_bytes.encode("utf-8")
    seed_int = int(hashlib.sha256(seed_bytes).hexdigest(), 16)
    rng = random.Random(seed_int)
    items_copy = list(items)
    rng.shuffle(items_copy)
    return items_copy

def choose_jurors_for_application(node, count=10):
    """
    node.get_registered_jurors() should return list of dicts: {'pub':..., 'tier':(1|2|3), 'last_active':...}
    Prefer Tier 3 jurors. Deterministic seeded by latest block hash.
    """
    pool = node.get_registered_jurors()  # implement this on Node
    if not pool:
        return []
    tier3 = [p["pub"] for p in pool if p.get("tier") == 3]
    others = [p["pub"] for p in pool if p.get("tier") != 3]
    pool_order = tier3 + others
    seed = node.get_last_block_hashes(1)
    seed_bytes = seed[0].encode("utf-8") if seed else b"default-seed"
    shuffled = deterministic_shuffle(pool_order, seed_bytes)
    return shuffled[:count]

def simple_threshold_check(votes, threshold=7):
    """
    votes: iterable of 'approve'/'reject' strings
    returns True if approvals >= threshold
    """
    approvals = sum(1 for v in votes if v == "approve")
    return approvals >= threshold
