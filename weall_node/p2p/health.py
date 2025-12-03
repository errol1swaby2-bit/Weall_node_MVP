import json, subprocess


def get_peer_count() -> int:
    """
    Return the current number of peers connected to the IPFS swarm.
    Uses `ipfs swarm peers --enc json`.
    """
    try:
        out = subprocess.check_output(
            ["ipfs", "swarm", "peers", "--enc", "json"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        peers = json.loads(out)
        return len(peers) if isinstance(peers, list) else 0
    except Exception:
        return 0
