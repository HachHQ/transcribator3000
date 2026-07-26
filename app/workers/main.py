from __future__ import annotations

import logging

from arq import run_worker

from app.workers.jobs import WorkerSettings


def run() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.INFO,
    )
    run_worker(WorkerSettings)


if __name__ == "__main__":
    run()
