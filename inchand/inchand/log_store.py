import json
from datetime import datetime, timezone
from pathlib import Path


def append_jsonl(path, payload):
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **payload}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
