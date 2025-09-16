# app_state/governance.py

proposals = {}
proposal_counter = 1
votes = {}

def propose(user_id: str, title: str, description: str):
    global proposal_counter
    pid = proposal_counter
    proposals[pid] = {
        "user": user_id,
        "title": title,
        "description": description,
        "votes": 0
    }
    proposal_counter += 1
    return {"ok": True, "proposal_id": pid}

def vote(user_id: str, proposal_id: int, approve: bool):
    if proposal_id not in proposals:
        return {"ok": False, "error": "proposal_not_found"}
    votes.setdefault(proposal_id, {})
    votes[proposal_id][user_id] = approve
    # Count votes
    total = sum(1 if v else -1 for v in votes[proposal_id].values())
    proposals[proposal_id]["votes"] = total
    return {"ok": True, "votes": total}
