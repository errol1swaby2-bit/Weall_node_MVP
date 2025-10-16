#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Juror orchestration for WeAll PoH (Phases B/C/D)

Responsibilities
- Randomly select Tier-3 jurors for a candidate's panel
- Split selection into "live" (on-camera) and "watch" (spectator, vote-only)
- Expose helper utilities used by the API layer
"""

from __future__ import annotations
import random
import time
from typing import Dict, List, Any, Tuple, Set

from weall_node.executor import WeAllExecutor


class JurorOrchestrator:
    """
    Minimal, stateless-ish orchestrator. Selection is performed against the
    current executor state; invite persistence / session lifecycle is handled
    by the API module (weall_api.py) using PANEL_SESSIONS.
    """

    def __init__(self, exec_: WeAllExecutor):
        self.exec = exec_

    # -------- Selection --------
    def tier3_pool(self, exclude: Set[str] | None = None) -> List[str]:
        exclude = exclude or set()
        users = self.exec.state.get("users", {})
        pool = [u for u, meta in users.items() if int(meta.get("poh_level", 0)) >= 3 and u not in exclude]
        return pool

    def select_random_jurors(self, count: int, exclude: Set[str] | None = None) -> List[str]:
        pool = self.tier3_pool(exclude=exclude)
        random.shuffle(pool)
        return pool[:max(0, count)]

    def split_live_watch(self, required: int) -> Tuple[int, int]:
        live = min(3, required)  # at most 3 on camera
        watch = max(0, required - live)
        return live, watch

    def create_panel(self, target: str, required: int) -> Dict[str, Any]:
        """
        Returns a selection for the panel without mutating shared state.
        live jurors: up to 3; watch jurors: the remainder (up to 7 when required=10)
        """
        live_n, watch_n = self.split_live_watch(required)
        exclude = {target}
        all_needed = live_n + watch_n
        chosen = self.select_random_jurors(count=all_needed, exclude=exclude)
        live = chosen[:live_n]
        watch = chosen[live_n:live_n + watch_n]
        return {
            "target": target,
            "required": required,
            "jurors_live": live,
            "jurors_watch": watch,
            "created": time.time(),
        }
