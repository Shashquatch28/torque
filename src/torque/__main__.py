"""`python -m torque` — run the FastAPI API (and the static UI it serves) under
uvicorn, one process, one port.

The host dev command. Bind address comes from `torque.config.Settings`
(`TORQUE_API_HOST` / `TORQUE_API_PORT`, defaults `127.0.0.1:8000`). The
docker-compose `api` service runs this same command with `TORQUE_API_HOST=
0.0.0.0`. Container process management (worker / beat / migrate) is in
docker-compose.yml, not here.
"""

from __future__ import annotations


def main() -> None:
    import uvicorn

    from torque.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "torque.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
    )


if __name__ == "__main__":
    main()
