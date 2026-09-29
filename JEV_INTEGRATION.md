# Jev integration slice

The Python controller owns the emulator, input timing, legal options, and
postconditions. Jev receives a projected state plus a finite choice set and
returns only an option ID.

## Live sidecar

Set `JEV_PROJECT` to a local checkout of `christianmat/jev-pokemon` and install
that checkout's Node dependencies. The sidecar uses its existing `GatewayJev`
client, including gateway retries, throttling, caching, and JSONL call logs.

```sh
export JEV_PROJECT=/path/to/jev-pokemon
export AI_GATEWAY_API_KEY=...
export JEV_COMMAND="npx --prefix $JEV_PROJECT tsx /path/to/PokemonEmerald/jev_sidecar.mts"
```

The sidecar defaults to `typesafe-ai/jev`; set `JEV_MODEL` to override it.
Never pass a ROM address or raw key sequence in the request. A malformed or
illegal response is an error and must stop the controller.

## Emulator gate

Run the capability/replay gate before enabling live policy. It accepts only the
SHA-256-pinned BPEE v1.0 ROM:

```sh
.venv/bin/python qualification.py \
  --rom "Pokemon - Emerald Version (USA, Europe)/Pokemon - Emerald Version (USA, Europe).gba" \
  --bios bios/gba_bios.bin --route /tmp/starter_route.json --runs 3
```

Generate the disposable route with `.venv/bin/python make_starter_route.py --output
/tmp/starter_route.json`. Qualification writes named PNG checkpoints and full
EWRAM snapshots under `/tmp/emerald-calibration-evidence` by default. A clean
three-run result is evidence for a human promotion of the map; the checked-in
map remains empty until that promotion is made from real ROM output.

The SHA-pinned `kenn20/PyBoyAdvance` fork provides public, read-only
`peek_u8`, `peek_u16`, and `peek_u32` APIs for EWRAM/IWRAM. The gate performs
1,000 peeks at the checkpoint and rejects any timing or framebuffer change;
then it requires three fresh emulator instances to produce the same named RAM
observation and framebuffer fingerprint.

The starter-state map remains disabled until the disposable calibration route
reaches Birch's menu and three fresh runs agree on its named RAM observations
and framebuffer fingerprint. The live episode is fail-closed in the meantime.
`starter_route.py` is the calibration lever for the next slice. It replays a
named, checked JSON input route and emits every EWRAM byte changed by one
selected action; use it to prove the starter phase, current Poké Ball, and
post-choice species fields before checking the map in. `starter_episode.py`
supports both `RecordedPolicy` tests and the live `PolicyClient` boundary.
Once the map is promoted, use `starter_acceptance.py` with the disposable
route for the three-run Jev acceptance test; it logs the semantic decision
and species postcondition.

## Human-visible test replay

Append `--ui` to either test command to watch the exact emulator frames and
named route steps that the test drives. The window is read-only: controller
input still comes only from the checked route or Jev policy, and closing it
before completion fails the run. A successful interactive run keeps its final
frame open until you close the window.

For a walkthrough rather than real-time playback, add `--ui-pause`. It stops
after every named route checkpoint; click the visible **Continue** button (or
press Space) to advance to the next controller action. Each UI run writes its
screenshots to a new timestamped directory under the evidence directory, so
an interrupted replay cannot be confused with an earlier run.

```sh
.venv/bin/python qualification.py \
  --rom "Pokemon - Emerald Version (USA, Europe)/Pokemon - Emerald Version (USA, Europe).gba" \
  --bios bios/gba_bios.bin --route /tmp/starter_route.json --runs 3 --ui --ui-pause
```

After the state map has been promoted, the same `--ui` flag on
`starter_acceptance.py` also shows the Jev starter-selection input.
