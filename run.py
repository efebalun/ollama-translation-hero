#!/usr/bin/env python3
"""
TranslationHero — entry point.
Run:  python run.py           (hot-reload enabled by default)
      python run.py --no-reload
      python run.py --port 8080
"""

import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(ROOT, "src")

# Add src to path so all modules resolve
sys.path.insert(0, SRC)

import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="TranslationHero server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7979, help="Port (default: 7979)")
    parser.add_argument("--reload", action="store_true", default=True,
                        help="Hot-reload on Python changes (default: on)")
    parser.add_argument("--no-reload", dest="reload", action="store_false",
                        help="Disable hot-reload")
    args = parser.parse_args()

    reload_indicator = "on" if args.reload else "off"
    print(f"\n  TranslationHero")
    print(f"  ───────────────────────────────")
    print(f"  Web UI  → http://{args.host}:{args.port}")
    print(f"  API     → http://{args.host}:{args.port}/docs")
    print(f"  Reload  → {reload_indicator}")
    print(f"  ───────────────────────────────\n")

    uvicorn.run(
        "api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[SRC] if args.reload else None,
        reload_includes=["*.py"] if args.reload else None,
        app_dir=SRC,
        log_level="info",
    )


if __name__ == "__main__":
    main()
