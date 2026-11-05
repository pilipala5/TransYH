"""One full engine run, using existing config on stdin and existing caches.

Writes only numerical diagnostics. Generated PDFs stay in the local output
directory. Never install into a user's Zotero attachment or change their prefs.
The exclusive marker prevents an accidental repeat in the same output directory.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import worker
from performance import Performance


def main():
    config = json.loads(sys.stdin.readline())
    output = Path(config["outputDir"]).resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    # An existing completed/failed attempt must be reviewed, never auto-retried.
    descriptor = os.open(output / "benchmark-started", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    performance = Performance(output)
    performance.settings.update(engine_pipeline=True, zotero_ui_included=False)
    status = "failed"
    logging.disable(logging.CRITICAL)
    original_protocol = worker.PROTOCOL
    try:
        performance.start_checkpoints()
        # Third-party stdout and protocol events can include private file paths.
        # Only the explicit numerical recorder is retained by this runner.
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            worker.PROTOCOL = sink
            translated = asyncio.run(worker.translate({**config, "outputDir": str(output / "translation")}, performance))
            highlighted = worker.highlight_action("highlight", {
                **config, "input": translated["path"], "protectedOriginal": config["input"],
                "outputDir": str(output / "highlight")}, performance)
            if not highlighted.get("unchanged"):
                performance.phase("highlight_install")
                worker.highlight_action("installHighlights", {
                    "input": translated["path"], "protectedOriginal": config["input"],
                    "candidatePath": highlighted["path"], "sourceFingerprint": highlighted["sourceFingerprint"],
                    "installDir": str(output / "installation")})
            performance.phase("cleanup")
        status = "completed"
    except KeyboardInterrupt:
        status = "cancelled"
    except Exception:
        # SDK exception text is deliberately excluded.
        performance.count("pipeline_errors")
    finally:
        worker.PROTOCOL = original_protocol
        performance.finish(status)
    print(json.dumps({"status": status, "elapsed_s": performance.finished_s}))
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
