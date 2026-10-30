"""Resumable complete replay collection with pacing and auditable coverage.

Page totals can be lower bounds. Discover through an empty page, then reconcile
from page one until a full pass finds no new IDs before the fixed collection
cutoff. Download journals, not the unrelated bulk run-summary export.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
from urllib.error import HTTPError, URLError

from .adapters.spire_codex import RateLimitedError, download_replay, list_replays
from .target import ASCENSION, CHARACTER, GAME_VERSION


class CollectionStopped(RuntimeError):
    pass


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def collection_lock(folder: Path):
    """OS-released lock: a terminated download cannot leave a stale PID lock."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".collector.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        import os
        if os.name == "nt":
            import msvcrt
            def lock():
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

            def unlock():
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def lock():
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def unlock():
                fcntl.flock(stream, fcntl.LOCK_UN)
        try:
            lock()
        except OSError as exc:
            raise RuntimeError(f"Another collector is using {folder}") from exc
        try:
            yield
        finally:
            stream.seek(0)
            unlock()


def retry_delay(error: Exception, attempt: int, now: float) -> float | None:
    """None means non-transient; Retry-After is never shortened by a cap."""
    delay = min(300.0, 15.0 * 2 ** attempt)
    if isinstance(error, RateLimitedError):
        header = error.retry_after
        if header:
            try:
                requested = float(header)
            except ValueError:
                try:
                    requested = parsedate_to_datetime(header).timestamp() - now
                except (ValueError, TypeError, OverflowError):
                    requested = 60.0
            return max(delay, requested, 0.0)
        return max(delay, 60.0)
    if isinstance(error, HTTPError):
        return delay if error.code in {408, 425, 500, 502, 503, 504} else None
    if isinstance(error, (TimeoutError, ConnectionError, URLError)):
        return delay
    return None


class PacedRequests:
    def __init__(self, progress, stopped, *, interval=4.1, attempts=12,
                 clock=time.monotonic, sleep=time.sleep, wall_clock=time.time):
        if interval < 4.1 or attempts < 1:
            raise ValueError("Use at least 4.1 seconds pacing and one attempt")
        self.progress, self.stopped = progress, stopped
        self.interval, self.attempts = interval, attempts
        self.clock, self.sleep, self.wall_clock = clock, sleep, wall_clock
        self.next_request = clock()

    def wait(self, seconds):
        until = self.clock() + max(0, seconds)
        while self.clock() < until:
            if self.stopped():
                raise CollectionStopped("STOP requested during collection")
            self.sleep(min(1.0, until - self.clock()))

    def call(self, label, operation):
        for attempt in range(self.attempts):
            if self.stopped():
                raise CollectionStopped("STOP requested during collection")
            self.wait(self.next_request - self.clock())
            self.next_request = self.clock() + self.interval
            try:
                return operation()
            except Exception as error:
                delay = retry_delay(error, attempt, self.wall_clock())
                if delay is None or attempt + 1 == self.attempts:
                    raise
                self.progress("retrying", request=label, attempt=attempt + 1,
                              wait_seconds=delay, error=f"{type(error).__name__}: {error}")
                self.wait(delay)
        raise AssertionError("Unreachable retry state")


def collect_all_replays(
    folder: Path, *, game_version: str | None = GAME_VERSION,
    cache_folders=(), progress=lambda stage, **kw: None, stopped=lambda: False,
    requests: PacedRequests | None = None,
) -> dict:
    """Collect all accessible solo standard Silent A10 journals at a fixed cutoff.

    All-patch discovery is allowed only as collection; callers must filter actual
    journal headers before training. A 404/410 is retained as unavailable, not a
    downloaded or training example. Other exhausted request errors stop the job.
    """
    folder = Path(folder).resolve()
    requests = requests or PacedRequests(progress, stopped)
    manifest_path = folder / "collection.json"
    target = {"character": CHARACTER, "ascension": ASCENSION, "game_version": game_version}
    with collection_lock(folder):
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest["target"] != target:
                raise ValueError("Collection target differs from retained manifest")
        else:
            manifest = {"schema_version": 1, "target": target,
                        "cutoff_utc": datetime.now(timezone.utc).isoformat(), "records": {}}
        cutoff = datetime.fromisoformat(manifest["cutoff_utc"])
        records = manifest["records"]
        manifest.update(status="collecting", discovery_complete=False)

        def save(stage, **details):
            counts = Counter(r.get("status", "pending") for r in records.values())
            manifest.update(details, status=stage, discovered=len(records), counts=dict(counts),
                            updated_at=datetime.now(timezone.utc).isoformat())
            _write(manifest_path, manifest)
            progress(stage, discovered=len(records), counts=dict(counts), **details)

        def obtain(run_id):
            record = records[run_id]
            destination = folder / f"{run_id}.jsonl.gz"
            if not destination.exists():
                for cache in cache_folders:
                    source = Path(cache) / destination.name
                    if source.is_file() and source.resolve() != destination:
                        temporary = destination.with_suffix(".cache.tmp")
                        shutil.copyfile(source, temporary)
                        temporary.replace(destination)
                        record.update(status="reused", cache_source=str(source))
                        break
            if destination.exists():
                with destination.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if record.get("sha256") and record["sha256"] != digest:
                    raise ValueError(f"Retained replay checksum changed: {run_id}")
                record.update(status="downloaded" if record.get("status") == "downloaded" else "reused",
                              sha256=digest, bytes=destination.stat().st_size, path=str(destination))
            else:
                try:
                    result = requests.call(f"replay {run_id}", lambda: download_replay(
                        run_id, destination, timeout=90,
                    ))
                    record.update(result, status="downloaded")
                except HTTPError as error:
                    if error.code not in {404, 410}:
                        raise
                    record.update(status="unavailable", http_status=error.code)

        try:
            # Finish retained work first; a previous timeout never drops a hash.
            for run_id in list(records):
                obtain(run_id)
                save("resuming", last_run_id=run_id)
            discovery_pass = 0
            while True:
                discovery_pass += 1
                new_ids, page, page_hashes = 0, 1, set()
                while True:
                    save("listing", discovery_pass=discovery_pass, page=page)
                    listing = requests.call(f"listing page {page}", lambda: list_replays(
                        game_version=game_version, page=page, limit=100, timeout=90,
                    ))
                    _write(folder / "listings" / f"pass-{discovery_pass}-page-{page}.json", listing)
                    rows = listing.get("runs")
                    if not isinstance(rows, list):
                        raise ValueError("Missing replay listing rows")
                    manifest.update(reported_total=listing.get("total"),
                                    total_is_lower_bound=listing.get("total_is_lower_bound", True))
                    if not rows:
                        break  # Never stop at total_pages, a short page or a lower-bound total.
                    ids = tuple(row.get("run_hash") for row in rows)
                    if ids in page_hashes:
                        raise ValueError("Server repeated a listing page; cannot certify full coverage")
                    page_hashes.add(ids)
                    pending = []
                    for row in rows:
                        run_id = row.get("run_hash")
                        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
                            raise ValueError("Invalid replay hash")
                        if row.get("character") != CHARACTER or row.get("ascension") != ASCENSION:
                            raise ValueError("Replay listing returned another character/ascension")
                        if game_version is not None and row.get("build_id") != game_version:
                            raise ValueError("Replay listing returned another game version")
                        submitted = datetime.fromisoformat(row["submitted_at"])
                        if submitted.tzinfo is None:
                            submitted = submitted.replace(tzinfo=timezone.utc)
                        if submitted > cutoff:
                            continue  # Fixed snapshot, not an unbounded live feed.
                        if run_id not in records:
                            records[run_id] = {"listing": row, "status": "pending"}
                            new_ids += 1
                            pending.append(run_id)
                    save("downloading", discovery_pass=discovery_pass, page=page)
                    for run_id in pending:
                        obtain(run_id)
                        save("downloading", discovery_pass=discovery_pass, page=page,
                             last_run_id=run_id)
                    page += 1
                save("reconciling", discovery_pass=discovery_pass, page=page, new_ids=new_ids)
                if new_ids == 0:
                    break
            save("collected", discovery_complete=True)
            return manifest
        except CollectionStopped:
            save("stopped")
            raise
        except Exception as error:
            save("collection_failed", error=f"{type(error).__name__}: {error}")
            raise
