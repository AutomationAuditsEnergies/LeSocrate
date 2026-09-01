"""Entrypoint for the isolated audio worker process."""

from __future__ import annotations

import sys

from .pipeline_worker import main


if __name__ == "__main__":
    raise SystemExit(main(["--worker-kind", "audio", *sys.argv[1:]]))
