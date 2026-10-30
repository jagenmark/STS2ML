"""Exercise benchmark classification and cleanup through a fake JSON process."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def benchmark():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark-headless.py"
    spec = importlib.util.spec_from_file_location("headless_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mode,expected", [
    ("normal", "terminal"), ("wrong_identity", "error"), ("engine_error", "error"),
    ("stall", "error"), ("never_terminal", "truncated"),
])
def test_episode_checks_identity_and_keeps_failures_separate_from_deaths(
    tmp_path, monkeypatch, benchmark, mode, expected,
):
    host = tmp_path / "fake_host.py"
    host.write_text(f"MODE = {mode!r}\n" + '''
import json, sys, time
def emit(data):
    print(json.dumps(data), flush=True)
emit({'type': 'ready'})
identity = {'character': 'SILENT', 'ascension': 10,
            'assembly_version': '0.1.0+41cef1ea4657c524aa50e870df009e56337e8c32'}
for line in sys.stdin:
    command = json.loads(line)
    if command['cmd'] == 'quit':
        emit({'type': 'quit_result'})
        break
    if MODE == 'stall':
        time.sleep(10)
    if MODE == 'wrong_identity':
        identity['ascension'] = 0
    if MODE == 'engine_error':
        emit({'type': 'error', 'message': 'native action failed'})
        continue
    if command['cmd'] == 'start_run' or MODE == 'never_terminal':
        emit({'type': 'decision', 'decision': 'event_choice', 'runtime_identity': identity,
              'options': [{'index': 0, 'is_locked': False}]})
    else:
        emit({'type': 'decision', 'decision': 'game_over', 'runtime_identity': identity,
              'victory': False, 'act': 1, 'floor': 5, 'player': {'hp': 0}})
''', encoding="utf-8")
    monkeypatch.setattr(benchmark, "DOTNET", Path(sys.executable))
    monkeypatch.setattr(benchmark, "HOST", host)
    monitor = benchmark.MemoryMonitor()
    monitor.thread.start()
    try:
        result = benchmark.episode("test", tmp_path / "episode", monitor,
                                   0.5 if mode == "stall" else 5, 10, 2)
    finally:
        monitor.stop.set()
        monitor.thread.join()
    assert result["status"] == expected
    assert not monitor.processes
    assert json.loads((tmp_path / "episode/result.json").read_text()) == result
    if expected == "terminal":
        assert result["victory"] is False
        assert result["actions"] == 1
    else:
        assert "victory" not in result
    if mode == "stall":
        assert result["wall_seconds"] < 3
