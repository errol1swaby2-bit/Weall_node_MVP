from fastapi import APIRouter
from weall_node.weall_api import executor_instance

router = APIRouter(prefix="/validators", tags=["validators"])

@router.post("/opt-in/{user_id}")
def opt_in_validator(user_id: str):
    return executor_instance.opt_in_validator(user_id)

@router.post("/opt-out/{user_id}")
def opt_out_validator(user_id: str):
    return executor_instance.opt_out_validator(user_id)

@router.get("/list")
def list_validators():
    return {
        "validators": executor_instance.get_validators(),
        "elected": executor_instance.elected_validator()
    }

@router.post("/run/{user_id}")
def run_validator(user_id: str):
    return executor_instance.run_validator(user_id)
