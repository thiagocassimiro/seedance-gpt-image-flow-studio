from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from studio.project import Project, write_json_new
from studio.security import redact_data
from studio.seedance import ArkClient, download_task, recover_task

FAILURE_STATES = {"failed", "cancelled", "canceled", "expired"}
SUCCESS_STATES = {"succeeded", "success", "completed"}


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python scripts/wait-and-download.py <project> <task-id>")
        return 2
    project = Project.open(Path.cwd(), sys.argv[1])
    task_id = sys.argv[2]
    client = ArkClient(project.models_config(), timeout=60)
    deadline = time.monotonic() + 30 * 60
    previous = None
    network_failures = 0
    while time.monotonic() < deadline:
        try:
            result = recover_task(project, task_id, client)
            network_failures = 0
        except Exception as exc:
            network_failures += 1
            print(f"TASK_QUERY_ERROR={type(exc).__name__} attempt={network_failures}", flush=True)
            if network_failures >= 3:
                print("TASK_QUERY_STOPPED_NO_NEW_TASK", flush=True)
                return 1
            time.sleep(15)
            continue
        status = result["status"]
        if status != previous:
            print(f"TASK_STATUS={status}", flush=True)
            previous = status
        if status in FAILURE_STATES:
            print(json.dumps(redact_data(result["response"]), ensure_ascii=False), flush=True)
            return 1
        if status in SUCCESS_STATES:
            downloaded = download_task(project, task_id, client)
            print(json.dumps(redact_data(downloaded), ensure_ascii=False, indent=2), flush=True)
            write_json_new(project.root / "reports" / f"download-{task_id}.json", redact_data(downloaded))
            return 0
        time.sleep(15)
    print("TASK_WAIT_TIMEOUT_NO_NEW_TASK", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
