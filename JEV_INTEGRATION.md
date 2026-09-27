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
  --bios bios/gba_bios.bin --runs 3
```

The SHA-pinned `kenn20/PyBoyAdvance` fork provides public, read-only
`peek_u8`, `peek_u16`, and `peek_u32` APIs for EWRAM/IWRAM. The gate performs
1,000 peeks at the checkpoint and rejects any timing or framebuffer change;
then it requires three fresh emulator instances to produce the same named RAM
observation and framebuffer fingerprint.

No BPEE v1.0 starter-state map is checked in yet, so this command completes
the non-timing capability check but exits fail-closed and does not enable Jev.
Once a checked-in map is validated, the same gate will require three fresh
runs to agree on its semantic RAM observation and framebuffer fingerprint.
`starter_route.py` is the calibration lever for the next slice. It replays a
named, checked JSON input route and emits every EWRAM byte changed by one
selected action; use it to prove the starter phase, current Poké Ball, and
post-choice species fields before checking the map in. `starter_episode.py`
uses `RecordedPolicy` only. Live Jev stays disabled until that route and map
pass the replay gate.
