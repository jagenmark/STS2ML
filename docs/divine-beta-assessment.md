# divine-sts2 assessment for Silent A10 on v0.111.0

Assessment date: 2026-10-29. **The installed beta is a plausible port target,
but headless game collection is not ready or verified.** No game, Godot worker,
GUI, native simulation, or upstream deep doctor was launched for this assessment.
No compatibility check was disabled.

## Revision and observed installation

The latest upstream `main` was still
`7cb715916fc9abfb0281c0adf4939c74468e05a4`, exactly the revision already pinned by
STS2ML. There is no newer upstream beta implementation to adopt. Its documented
target is Windows STS2 v0.107.1, commit `59260271`.

The local Steam installation was read at
`~/.local/share/Steam/steamapps/common/Slay the Spire 2`.
Its `release_info.json` reports `v0.111.0`, commit `41cef1ea`; its exported managed
runtime configuration targets .NET 9 and includes runtime 9.0.7.

| Fingerprint | Inspected local Linux beta | Upstream documented Windows v0.107.1 |
| --- | --- | --- |
| `sts2.dll` SHA-256 | `2B40D2DF538DB1CEB5FA48D958C80AB730ADA1E07DB88A870AFF01A661768B9F` | `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52` |
| `SlayTheSpire2.pck` SHA-256 | `42443027622A6A82DE8AB21E81ED5B68E522C0F5647FB6A26A74C4A0970A0D34` | `42520EB8B0911C6C0F0BD102D92B33F41ABD4D26B83489817D0A6DBD7DD48587` |

These differing fingerprints establish that the installed files are outside the
pinned integration's boundary. They do not establish whether an API is
compatible. The beta's **Windows** fingerprints have not been measured; the
Linux values must not be accepted as its Windows fingerprint policy.

## Two different meanings of headless

| Path | What executes | Transport | Appropriate role after validation |
| --- | --- | --- | --- |
| Full application | The shipped game executable plus a bridge mod, normal run initialization, and native room/combat lifecycles | Loopback TCP with newline JSON RPC | Whole-run collection and evaluation |
| Reconstructed native | A separate Godot .NET host mounts the game's PCK and loads its assemblies; it reconstructs states and directly invokes native mechanics | Child-process stdin/stdout JSON | Tactical search and transition diagnostics |

The reconstructed path is not a replacement implementation of the rules in
Python, but it does reconstruct lifecycle/state. Its `fork`/`restore` handles
reconstruct and replay history; they do not clone a running game process.
The full-app client has no equivalent snapshot/restore API, so branching replays
an action prefix from a new run. Throughput claims for the two paths cannot be
interchanged. Upstream itself labels its full-app acceptance report historical,
rather than current public release certification.

Neither path is established by loading `sts2.dll` in a plain .NET console.
Upstream's feasibility probe explicitly requires a valid Godot engine context
for real card execution. Headless suppresses presentation; it does not remove
the engine. The simulator process and GPU training backend are separate concerns;
this assessment does not certify the RX 9070 XT's training stack.

## Concrete blockers

1. **Version boundary.** STS2ML's existing adapter checks the documented v0.107.1
   Windows hashes. Upstream's Python doctor also lists those hashes. Beta support
   needs a separately reviewed build profile and evidence, not removal of the
   existing checks. Upstream's reconstructed host reports its loaded hashes and
   checks supplied reset fingerprints, but this is not a beta compatibility audit.
2. **A10 is not applied by the full-app bridge.** `start_run` stores and echoes
   `RequestedAscension`, but its only references are inside
   `FullAppBridgeServer.cs`. The run-start hook applies character and seed without
   applying that ascension. An echoed `ascension=10` therefore cannot certify an
   A10 run. The port must set the native lobby's difficulty and assert the actual
   `RunState.AscensionLevel` in the first observation. Silent selection also needs
   that actual-state assertion rather than trusting the requested character.
3. **The full-app handshake is misleading for another build.** `hello.version`
   is hard-coded to `0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314`.
   It does not fingerprint the loaded beta, and does not provide all the metadata
   described by the historical protocol report. Add actual game, assembly, PCK,
   bridge revision, protocol/schema, and run identity before accepting data.
4. **Linux export layout is unsupported by the existing launcher.** Discovery
   requires `SlayTheSpire2.exe` and `data_sts2_windows_x86_64`; this installation
   has `SlayTheSpire2` and `data_sts2_linuxbsd_x86_64`. Full-app sandbox preparation
   uses `cmd /c mklink /J`, and profile isolation uses Windows `APPDATA` and
   `LOCALAPPDATA`. Renaming files or creating a fake Windows layout would not
   resolve those platform differences.
5. **Compilation/runtime validation is outstanding.** Upstream builds `net9.0`,
   with a .NET 9 SDK pin and Godot.NET.Sdk 4.5.1 for the reconstructed host. This
   machine exposed a .NET 10.0.12 runtime and no installed SDK; the game's bundled
   runtime is not an SDK. No SDK was installed and no C# build was attempted.

The full-app bridge's patch helpers can ignore missing methods and catch patch
failures. A port should make required hooks and presentation seams fail closed
and report their installation status, rather than infer success from a listening
TCP port.

## Static compatibility evidence

The local beta's ECMA-335 metadata was inspected without executing its assembly.
All **16 named full-app hook targets** in `FullAppBridgeMod.Initialize` exist,
with one matching method name each. The checked targets include the main menu,
run-start lobby, AutoSlayer, and combat/map/reward/rest/shop/event/terminal
handlers. The native lobby exposes ascension-related members, so a difficulty
port is plausible at the API-name level.

The beta contains the three full-app build references: `sts2.dll`, `0Harmony.dll`,
and `GodotSharp.dll`. The managed game metadata references .NET 9, GodotSharp 4.5,
and Harmony 2.4. These are useful positive signals; **name existence is not a
successful compile, matching method signature, valid Harmony patch, correct
state transition, or deterministic replay**. No Windows beta export was inspected.

Local, ignored evidence is under `artifacts/divine-beta-api-metadata.json` and
`artifacts/upstreams/divine-sts2/`. Only metadata summaries and this assessment
are intended for review; no game binaries or decompiled source are tracked.

## Smallest useful port and acceptance sequence

For the intended Windows desktop, keep the Windows launcher and export layout.
Obtain fingerprints from its own v0.111.0 installation, use a .NET 9 SDK, and
build the pinned full-app library against those local game references. A Linux
library build can override `GameDataDir` to the real Linux data directory, but
that would not validate the Windows build or port its launcher.

The first code changes should be narrowly scoped: apply and verify Silent/A10,
replace the hard-coded handshake with measured identity, make required hooks
explicitly checked, and adapt any compilation or runtime API differences found
against beta. Keep build profiles and resulting models separate by patch.

Then, in isolated sandboxes, require one bounded worker to reach a decision,
confirm actual character/difficulty/build, execute legal actions through combat
and a card reward, and terminate cleanly. Compare a fixed action prefix across
independent workers; then capture terminal outcomes, truncations, and an ordinary
game comparison on the same build. Expand to whole runs only after that gate.
The current STS2ML full-app projection still covers partial card rewards, so a
successful beta launch would not by itself provide a complete macro-decision
training environment.

A later Linux port additionally needs OS-aware discovery, link/copy handling,
native dependency deployment, a matching Linux Godot .NET host for reconstruction,
and verified Linux profile/userdata isolation. Loopback TCP and line-delimited
JSON are already portable; the process setup is the platform-specific part.

## Primary sources

- [Pinned compatibility boundary](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/docs/version-compatibility.md)
- [Full-app report and evidence caveat](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/docs/full-application-control-bridge.md)
- [Build settings](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/Directory.Build.props)
- [Discovery and export layout](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/python/sts2_native_sim/paths.py)
- [Full-app launch and transport](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/python/sts2_native_sim/full_app_client.py)
- [Run-start and hook installation](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/src/Sts2.NativeSim.FullAppBridge/FullAppBridgeMod.cs)
- [RPC handshake and requested ascension](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/src/Sts2.NativeSim.FullAppBridge/FullAppBridgeServer.cs)
- [Reconstructed worker setup](https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/python/sts2_native_sim/client.py)
