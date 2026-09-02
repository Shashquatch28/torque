"""`python -m torque` — run the ingestion API under uvicorn.

Convenience entrypoint for local dev and the preview environment. Production
process management is out of scope for Milestone 7a.
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "torque.api.app:create_app",
        factory=True,
        host=os.environ.get("TORQUE_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("TORQUE_API_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
