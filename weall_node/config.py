import os
import yaml
import pathlib

_DEFAULT = {
    "persistence": {"driver": "json", "sqlite_path": "weall.db"},
    "ipfs": {"require_ipfs": False},
    "governance": {"tier3_quorum_fraction": 0.6, "tier3_yes_fraction": 0.5},
    "chain": {"block_max_txs": 1000},
    "security": {"require_signed_votes": True, "require_signed_tx": False},
    "logging": {"level": "INFO", "json": True},
    "runtime": {
        "editable_roots": ["weall_node", "frontend", "pallets", "runtime"],
        "backup_dir": ".weall_backups",
    },
}


def load_config(repo_root: str) -> dict:
    """
    Loads the YAML config from repo_root/weall_config.yaml.
    Returns defaults if the file doesn't exist or can't be parsed.
    """
    path = os.path.join(repo_root, "weall_config.yaml")
    if not os.path.exists(path):
        return _DEFAULT

    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        cfg = _DEFAULT.copy()
        for k, v in data.items():
            if isinstance(v, dict) and k in cfg:
                tmp = cfg[k].copy()
                tmp.update(v)
                cfg[k] = tmp
            else:
                cfg[k] = v
        return cfg
    except Exception:
        return _DEFAULT
