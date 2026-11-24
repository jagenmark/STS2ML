"""Run the locked CSV10DEV triples with rotating arm order and full native auditing."""

import hashlib
import json

from v64 import DOC, main

ARMS = ("v64_control", "trap_cleanup_v65", "unified_draft_v65")
LOCK_SHA = "6b30bfddc5f1a9883b3cfbd63351b8c55d3c23de6217d84e480cf46caf20164f"


def cohort():
    data = (DOC / "csv10dev-lock.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == LOCK_SHA
    rows = json.loads(data)
    assert rows == [
        [i, f"CSV10DEV_{m.upper()}_{i:04d}", m] for i in range(192) for m in ("default", "seeded")
    ]
    return rows


if __name__ == "__main__":
    main(ARMS, cohort, LOCK_SHA, __doc__, offer_context=True)
