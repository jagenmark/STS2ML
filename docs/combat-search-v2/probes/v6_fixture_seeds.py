"""Keep historical native scenario fixtures in the fresh CSV4FIX namespace."""
from sts2rl.native import NativeSession

original = NativeSession.reset


def reset(self, seed, *args, **kwargs):
    if seed.startswith("CSV3FIX_"):
        seed = "CSV4FIX_REGRESSION_" + seed.removeprefix("CSV3FIX_")
    if seed == "CSV4FIX_REGRESSION_MOVES_RUBY_RAIDERS_NORMAL":
        seed = "CSV4FIX_REGRESSION_RUBY_3"
    if seed.startswith(("VAL256", "SEEDED128", "TRUE_SEEDED", "REP512", "CSV2DATA", "CSV3", "M4")):
        raise ValueError("Reserved lobby " + seed)
    return original(self, seed, *args, **kwargs)


NativeSession.reset = reset
