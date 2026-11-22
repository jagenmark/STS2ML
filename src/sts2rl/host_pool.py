"""Opt-in worker-local NativeSession pooling with strict per-episode trace isolation.

Kept separate from ``native.py`` so legacy ``mc_provenance`` source hashes stay invariant.
Each leased episode still receives its own exclusively created ``rpc.jsonl`` whose first
record is that episode's ``training_restore`` command. Any error, timeout, or divergence
evicts and terminates the pooled host process.
"""

from __future__ import annotations

import atexit
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile

from .native import NativeSession

_POOL: dict[tuple, tuple[NativeSession, Path]] = {}


def close_pooled_hosts() -> None:
    """Terminate all process-local pooled native hosts and remove temporary sandboxes."""
    for key in list(_POOL):
        session, sandbox = _POOL.pop(key)
        try:
            session.close()
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)


atexit.register(close_pooled_hosts)


def _preserve_engine_log(sandbox: Path, episode_dir: Path) -> None:
    src = sandbox / "host" / "engine.log"
    dst = episode_dir / "engine.log"
    if src.is_file() and not dst.exists():
        try:
            shutil.copy2(src, dst)
        except OSError:
            pass


@contextmanager
def lease_native_session(
    root: Path,
    folder: Path,
    *,
    ascension: int = 10,
    host_path=None,
    timeout: float = 45,
    act_list: str = "default",
    reuse_host: bool = False,
):
    """Yield an exclusive NativeSession; when ``reuse_host=True``, reuse an idle worker-local host."""
    if not reuse_host:
        with NativeSession(
            Path(root),
            Path(folder),
            ascension=ascension,
            host_path=host_path,
            timeout=timeout,
            act_list=act_list,
        ) as session:
            yield session
        return

    resolved_root = Path(root).resolve()
    resolved_host = str(Path(host_path).resolve()) if host_path else None
    key = (os.getpid(), str(resolved_root), resolved_host, ascension, act_list)
    # Pop while leased so overlapping same-key leases can never share one live NativeSession.
    entry = _POOL.pop(key, None)
    if entry is None or entry[0].closed:
        if entry is not None:
            shutil.rmtree(entry[1], ignore_errors=True)
        sandbox = Path(tempfile.mkdtemp(prefix="sts2-host-pool-"))
        session = NativeSession(
            resolved_root,
            sandbox / "host",
            ascension=ascension,
            host_path=host_path,
            timeout=timeout,
            act_list=act_list,
        )
    else:
        session, sandbox = entry
        session.timeout = timeout

    episode_dir = Path(folder)
    episode_dir.mkdir(parents=True, exist_ok=False)
    episode_trace = (episode_dir / "rpc.jsonl").open("x", encoding="utf-8")
    original_trace = session.trace
    session.trace = episode_trace
    # Clear Python-side episode metadata before the caller's first reset/restore.
    session.state, session.history, session.specification, session.sampled = {}, [], {}, False
    try:
        yield session
    except BaseException:
        try:
            session.trace = original_trace
            session.close()
        finally:
            episode_trace.close()
            _preserve_engine_log(sandbox, episode_dir)
            shutil.rmtree(sandbox, ignore_errors=True)
        raise
    else:
        session.trace = original_trace
        episode_trace.flush()
        episode_trace.close()
        if session.closed:
            _preserve_engine_log(sandbox, episode_dir)
            shutil.rmtree(sandbox, ignore_errors=True)
        elif key not in _POOL:
            _POOL[key] = (session, sandbox)
        else:
            try:
                session.close()
            finally:
                shutil.rmtree(sandbox, ignore_errors=True)
