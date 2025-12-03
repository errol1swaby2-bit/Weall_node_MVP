"""
weall_runtime.sync

Epoch/blocktime scheduler for WeAll runtime.
Automatically advances epochs every N seconds to enforce finality.
"""

import time
import threading


class BlockTimeScheduler:
    """
    Periodic epoch advancement tied to block time.
    Default = 600 seconds (10 minutes).
    """

    def __init__(self, executor, interval_seconds: int = 600):
        self.executor = executor
        self.interval = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        """Start the scheduler in a background thread."""
        if not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        """Stop the scheduler."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)

    def _run(self):
        """Internal loop that advances epochs on a fixed schedule."""
        while not self._stop.is_set():
            time.sleep(self.interval)
            try:
                winners = self.executor.advance_epoch()
                print(
                    f"[BlockTimeScheduler] Advanced epoch {self.executor.current_epoch}, winners={winners}"
                )
            except Exception as e:
                print(f"[BlockTimeScheduler] Error: {e}")
