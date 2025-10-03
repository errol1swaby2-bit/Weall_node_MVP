from fastapi import APIRouter, Query
from weall_node.weall_api import executor_instance

router = APIRouter(prefix="/operators", tags=["operators"])

@router.post("/opt-in/{user_id}")
def opt_in_operator(user_id: str):
    return executor_instance.opt_in_operator(user_id)

@router.post("/opt-out/{user_id}")
def opt_out_operator(user_id: str):
    return executor_instance.opt_out_operator(user_id)

@router.get("/list")
def list_operators():
    return {"operators": executor_instance._current_operators()}

@router.post("/assign/{cid}")
def assign_replicas(cid: str, rf: int = Query(default=3)):
    return executor_instance.assign_replicas(cid, replication_factor=rf)

@router.post("/uptime/{user_id}")
def record_uptime(user_id: str, online: bool = Query(default=True)):
    return executor_instance.record_operator_uptime(user_id, online)

@router.post("/challenge/{user_id}/{cid}")
def challenge_storage(user_id: str, cid: str):
    return executor_instance.challenge_operator_storage(user_id, cid)
