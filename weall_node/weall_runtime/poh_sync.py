# weall_runtime/poh_sync.py
from .poh import apply_tier2, apply_tier3, juror_submit_vote
from .sync import Node


class PoHNode(Node):
    """
    Extends Node to directly handle PoH application flows.
    """

    def submit_tier2_application(self, user_pub: str, video_cid: str, meta: dict):
        """
        Tier2 application flow:
        - deterministically choose jurors
        - persist application
        - return juror list for front-end notifications
        """
        return apply_tier2(user_pub, video_cid, meta, self)

    def submit_tier3_application(self, user_pub: str, requested_window: dict):
        """
        Tier3 live verification flow:
        - deterministically choose jurors
        - persist scheduling request
        """
        return apply_tier3(user_pub, requested_window, self)

    def process_juror_vote(
        self, app_id: str, juror_pub: str, vote: str, signature_b64: str
    ):
        """
        Process a juror vote:
        - verify signature
        - store vote
        - finalize PoH if threshold reached
        """
        return juror_submit_vote(app_id, juror_pub, vote, signature_b64)
