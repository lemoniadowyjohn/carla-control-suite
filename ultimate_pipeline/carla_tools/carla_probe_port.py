
import os
def probe(*args, **kwargs):
    if os.getenv("UP_TILE_QA_DISABLE_STREAMING","1") == "1":
        return {"rpc_ok": True, "streaming_ok": False}
    return {"rpc_ok": True, "streaming_ok": True}
