"""Thin entry point for the build pipeline.

Re-exports run_build, BUILD_STATUS, and _status_lock so existing callers
(e.g. app.py) keep working via `import build as build_mod`.
"""
from pipeline import run_build, BUILD_STATUS, _status_lock  # noqa: F401


def main():
    run_build()


if __name__ == "__main__":
    main()
