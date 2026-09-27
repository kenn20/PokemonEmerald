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

Run the repeatability gate before enabling live policy:

```sh
.venv/bin/python qualification.py \
  --rom "Pokemon - Emerald Version (USA, Europe)/Pokemon - Emerald Version (USA, Europe).gba" \
  --bios bios/gba_bios.bin --runs 3
```

The current installed PyBoy build fails this gate because it exposes no
read-only memory telemetry. That is an intentional stop signal; it must be
resolved by a backend build or mGBA adapter before Jev is allowed to choose.
