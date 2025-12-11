"""
weall_node/api/node_meta.py
--------------------------------------------------
Node metadata API: expose node_kind and topology profile.
"""

from fastapi import APIRouter

from ..weall_executor import executor

router = APIRouter(prefix="/node", tags=["node"])


@router.get("/meta")
def node_meta():
  """
  Returns the node's configured kind/topology.
  """
  return {
      "ok": True,
      "node_kind": executor.node_kind.value,
      "topology": executor.node_topology_profile(),
  }
