#!/usr/bin/env python3
"""
Shared runtime bootstrap — keeps periodic persistence and allows graceful stop
"""
import time, threading
from .executor import WeAllExecutor

class SharedRuntime:
    def __init__(self, poh_requirements=None):
        self.executor = WeAllExecutor("weall_dsl_v0.5.yaml", poh_requirements=poh_requirements or {})
        self._run = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self):
        while self._run:
            time.sleep(180)
            self.executor.save_state()

    def stop(self):
        self._run = False
        try: self._t.join(timeout=2.0)
        except Exception: pass
        self.executor.stop()  # also saves state
