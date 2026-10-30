from copy import deepcopy
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from sts2rl.collection import (
    CollectionStopped, PacedRequests, collect_all_replays, collection_lock, retry_delay,
)
from sts2rl.adapters.spire_codex import RateLimitedError


class Clock:
    now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Direct:
    def call(self, label, operation):
        return operation()


def row(run_id, version="v0.111.0"):
    return {"run_hash": run_id, "character": "SILENT", "ascension": 10,
            "build_id": version, "submitted_at": "2026-01-01T00:00:00"}


def page(*rows):
    return {"runs": list(rows), "total": 1, "total_pages": 1, "total_is_lower_bound": True}


def download(run_id, destination, **kwargs):
    Path(destination).write_bytes(run_id.encode())
    import hashlib
    return {"sha256": hashlib.sha256(run_id.encode()).hexdigest(), "bytes": len(run_id)}


def test_all_pages_short_pages_dedup_cache_and_reconciliation(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "a.jsonl.gz").write_bytes(b"a")
    sequence = [page(row("a")), page(row("a"), row("b")), page(),
                page(row("a"), row("c")), page(row("b")), page(),
                page(row("a"), row("b"), row("c")), page()]
    with patch("sts2rl.collection.list_replays", side_effect=sequence) as listing, \
            patch("sts2rl.collection.download_replay", side_effect=download) as fetch:
        report = collect_all_replays(tmp_path / "raw", cache_folders=[cache], requests=Direct())
    assert listing.call_count == 8  # Ignores lower-bound total_pages=1 and short pages.
    assert [call.args[0] for call in fetch.call_args_list] == ["b", "c"]
    assert report["discovery_complete"]
    assert report["discovered"] == 3
    assert report["counts"] == {"reused": 1, "downloaded": 2}


def test_resume_download_failure_retains_pending_hashes(tmp_path):
    def first(run_id, dest, **kw):
        if run_id == "b":
            raise TimeoutError()
        return download(run_id, dest)
    with patch("sts2rl.collection.list_replays", return_value=page(row("a"), row("b"))), \
            patch("sts2rl.collection.download_replay", side_effect=first):
        with pytest.raises(TimeoutError):
            collect_all_replays(tmp_path / "raw", requests=Direct())
    with patch("sts2rl.collection.list_replays", side_effect=[page(row("a"), row("b")), page()]), \
            patch("sts2rl.collection.download_replay", side_effect=download) as fetch:
        report = collect_all_replays(tmp_path / "raw", requests=Direct())
    assert report["discovery_complete"]
    assert [call.args[0] for call in fetch.call_args_list] == ["b"]


def test_cross_patch_discovery_is_explicit_and_cutoff_is_fixed(tmp_path):
    future = row("future") | {"submitted_at": "2099-01-01T00:00:00Z"}
    rows = page(row("old", "v0.other"), future)
    with patch("sts2rl.collection.list_replays", side_effect=[rows, page(), rows, page()]), \
            patch("sts2rl.collection.download_replay", side_effect=download):
        report = collect_all_replays(tmp_path / "all", game_version=None, requests=Direct())
    assert set(report["records"]) == {"old"}
    with patch("sts2rl.collection.list_replays", return_value=rows):
        with pytest.raises(ValueError, match="another game version"):
            collect_all_replays(tmp_path / "target", requests=Direct())


def test_deleted_replay_remains_explicitly_unavailable(tmp_path):
    with patch("sts2rl.collection.list_replays", side_effect=[page(row("gone")), page(), page(row("gone")), page()]), \
            patch("sts2rl.collection.download_replay", side_effect=HTTPError("url", 404, "gone", {}, None)):
        report = collect_all_replays(tmp_path / "raw", requests=Direct())
    assert report["counts"] == {"unavailable": 1}
    assert not list((tmp_path / "raw").glob("*.jsonl.gz"))


def test_repeated_page_cannot_falsely_complete(tmp_path):
    with patch("sts2rl.collection.list_replays", return_value=page(row("a"))), \
            patch("sts2rl.collection.download_replay", side_effect=download):
        with pytest.raises(ValueError, match="repeated a listing page"):
            collect_all_replays(tmp_path / "raw", requests=Direct())


def test_pacing_transient_retry_and_long_retry_after():
    clock, calls, events = Clock(), [], []
    requests = PacedRequests(lambda *a, **kw: events.append(kw), lambda: False,
                             clock=clock.time, sleep=clock.sleep, wall_clock=clock.time)
    errors = iter([RateLimitedError("600"), TimeoutError(), None])

    def attempt():
        calls.append(clock.time())
        error = next(errors)
        if error:
            raise error
        return "done"
    assert requests.call("test", attempt) == "done"
    assert calls == [0, 600, 630]
    requests.call("next", lambda: calls.append(clock.time()))
    assert calls[-1] >= 634.1
    assert events[0]["wait_seconds"] == 600


def test_retry_after_http_date_and_permanent_failures():
    timestamp = 1_800_000_000
    date = format_datetime(datetime.fromtimestamp(timestamp + 900, timezone.utc), usegmt=True)
    assert retry_delay(RateLimitedError(date), 0, timestamp) == 900
    assert retry_delay(HTTPError("url", 503, "temporary", {}, None), 0, timestamp) == 15
    assert retry_delay(HTTPError("url", 401, "auth", {}, None), 0, timestamp) is None
    assert retry_delay(ValueError("invalid data"), 0, timestamp) is None


def test_stop_is_responsive_during_backoff():
    clock = Clock()
    requests = PacedRequests(lambda *a, **kw: None, lambda: clock.now >= 3,
                             clock=clock.time, sleep=clock.sleep)
    with pytest.raises(CollectionStopped):
        requests.call("test", lambda: (_ for _ in ()).throw(RateLimitedError("600")))
    assert clock.now == 3


def test_lock_releases_and_refuses_concurrent_writer(tmp_path):
    with collection_lock(tmp_path):
        with pytest.raises(RuntimeError, match="Another collector"):
            with collection_lock(tmp_path):
                pytest.fail("Lock admitted a second writer")
    with collection_lock(tmp_path):
        pass


def test_modified_cache_fails_checksum_validation(tmp_path):
    rows = page(row("a"))
    with patch("sts2rl.collection.list_replays", side_effect=[rows, page(), deepcopy(rows), page()]), \
            patch("sts2rl.collection.download_replay", side_effect=download):
        collect_all_replays(tmp_path / "raw", requests=Direct())
    (tmp_path / "raw/a.jsonl.gz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum changed"):
        collect_all_replays(tmp_path / "raw", requests=Direct())
