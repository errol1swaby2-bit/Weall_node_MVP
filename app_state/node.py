# app_state/node.py
class Node:
    def __init__(self, ledger):
        self.ledger = ledger
        self.peers = []

    def register_peer(self, peer_id):
        if peer_id not in self.peers:
            self.peers.append(peer_id)
        return self.peers
