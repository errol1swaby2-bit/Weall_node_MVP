"""
NodeState – height, last hash, epochs, simple finality flag
"""

from typing import List, Optional

DEFAULT_EPOCH_LEN = 128

class NodeState:
    def __init__(self, epoch_len: int = DEFAULT_EPOCH_LEN):
        self.height: int = 0
        self.last_hash: Optional[str] = None
        self.epoch_len: int = int(epoch_len)
        self.current_epoch: int = 0
        self.validators: List[str] = []  # future: staking set
        self.finalized_height: int = -1

    def note_new_block(self, block_hash: str) -> None:
        self.height += 1
        self.last_hash = block_hash
        if (self.height % self.epoch_len) == 0:
            self.current_epoch += 1

    def finalize(self, height: int) -> None:
        # MVP finality: strictly monotonic
        if height > self.finalized_height:
            self.finalized_height = height
