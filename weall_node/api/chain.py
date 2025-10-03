from fastapi import APIRouter
from weall_node.app_state import chain
from weall_node.weall_api import executor_instance  # ✅ shared singleton
from weall_node.weall_runtime.ledger import INITIAL_EPOCH_REWARD, HALVING_INTERVAL
import time

router = APIRouter(prefix="/chain", tags=["chain"])

@router.get("/blocks")
def get_blocks():
    return chain.all_blocks()

@router.get("/latest")
def get_latest():
    return chain.latest()

@router.get("/tokenomics")
def tokenomics_status():
    """Return current tokenomics status (epoch reward, halving, bootstrap, pools)."""
    now = int(time.time())
    elapsed = now - executor_instance.ledger.wecoin.genesis_time
    halvings = elapsed // HALVING_INTERVAL
    current_reward = executor_instance.ledger.wecoin.current_epoch_reward()
    next_halving_eta = HALVING_INTERVAL - (elapsed % HALVING_INTERVAL)

    return {
        "epoch": executor_instance.current_epoch,
        "bootstrap_mode": executor_instance.bootstrap_mode,
        "min_validators": executor_instance.min_validators,
        "total_epoch_reward": current_reward,
        "initial_epoch_reward": INITIAL_EPOCH_REWARD,
        "halvings_so_far": int(halvings),
        "next_halving_in_seconds": int(next_halving_eta),
        "pools": {
            name: {
                "members": meta["members"],
                "count": len(meta["members"])
            }
            for name, meta in executor_instance.ledger.wecoin.pools.items()
        }
    }
