"""Convenience entry-point for the SoakSIM web dashboard."""

from __future__ import annotations

import argparse


def main() -> None:
    """Launch the SoakSIM web dashboard with Uvicorn."""
    parser = argparse.ArgumentParser(description="SoakSIM web dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    try:
        import uvicorn  # noqa: WPS433
    except ImportError:
        raise SystemExit(
            "uvicorn is required. Install it with:\n"
            "  pip install soakhydro[web]"
        )

    uvicorn.run(
        "soakhydro.web.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
