import socket
from ultimate_pipeline.config.settings import SETTINGS

def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def main() -> int:
    host = SETTINGS.CARLA_HOST
    rpc = int(SETTINGS.CARLA_PORT)
    stream = int(getattr(SETTINGS, "CARLA_STREAMING_PORT", rpc + 1))
    print(f"CARLA host: {host}")
    print(f"RPC port {rpc}: open={_port_open(host, rpc)}")
    print(f"Streaming port {stream}: open={_port_open(host, stream)}")

    try:
        import carla
        c = carla.Client(host, rpc)
        c.set_timeout(float(getattr(SETTINGS, "CARLA_POLL_TIMEOUT", 2.0)))
        w = c.get_world()
        print("RPC get_world(): OK")
        try:
            w.wait_for_tick(seconds=2.0)
            print("Streaming wait_for_tick(): OK")
        except Exception as e:
            print(f"Streaming wait_for_tick(): FAILED: {type(e).__name__}: {e}")
            return 3
    except Exception as e:
        print(f"CARLA API connect failed: {type(e).__name__}: {e}")
        return 2

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
