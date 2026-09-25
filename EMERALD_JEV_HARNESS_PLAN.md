# Emerald Jev Harness — Base ROM v1

## Summary

- The proposed model is broadly right, but it needs middle layers. Jev should not receive raw emulator state or output raw buttons. It should choose a legal semantic action; code performs the controller inputs and verifies the outcome.
- Target one checksum-verified US Pokémon Emerald v1.0 ROM profile. Version matters because RAM layout, symbols, and menu behavior can differ across revisions and difficulty hacks.
- First proof: load a user-local checkpoint at the Birch starter decision, have Jev choose the starter and legal battle actions, and verify victory in the first forced battle.

## The 10 core concepts

1. **ROM profile** — SHA-256 identity, RAM symbols, menu contracts, and supported-state rules.
2. **mGBA bridge** — Lua adapter exposes frame stepping, RAM reads, framebuffer capture, button masks, and save states.
3. **Frame driver** — applies/releases buttons for measured frame durations and waits for game readiness.
4. **Raw observation** — gathers memory, frame image, and emulator metadata at a stable frame boundary.
5. **State decoder** — converts profile-specific RAM into typed map, party, battle, flags, cursor, and input state.
6. **Screen reader** — narrowly reads visible dialogue/menu text when telemetry cannot safely say what is on screen.
7. **Goal and route** — deterministic objective progression and routine movement; Jev does not plan the whole game.
8. **Situation classifier** — distinguishes routine waiting/movement from a real choice requiring Jev.
9. **Legal-choice policy** — builds a compact branch-specific prompt, calls configurable Jev, validates its returned choice/probabilities, and falls back safely.
10. **Action verifier and evidence** — compiles the chosen intent into cursor-relative inputs, confirms the expected state transition, checkpoints/retries when safe, and writes replayable JSONL records.

Runtime flow:

```text
mGBA → observation → typed state + visible prompt → goal/classifier
     → legal options → Jev → validated intent → button sequence
     → mGBA → verification/log
```

There is no separate “game action API”: emulator controller input is the game’s action surface. This follows the key boundary in the Red reference: typed state and legal options go to Jev, while code owns button execution.

## Implementation changes

- Create a Python controller plus version-pinned mGBA Lua bridge, communicating through a small local request/response protocol; feature-test the required mGBA scripting primitives at startup.
- Define stable interfaces: `EmulatorAdapter`, `RomProfile`, `Observation`, `GameState`, `Branch`, `PolicyClient`, `InputCompiler`, and `Verifier`.
- Make telemetry primary; use screenshot/OCR only for visible prompts and menu confirmation.
- Implement the base-US-v1.0 profile only. Reject unknown ROM hashes clearly. Add difficulty hacks later as independent profiles rather than assuming compatibility.
- Keep ROMs, battery saves, and emulator save states user-local. Provide a checksum manifest and local checkpoint creation/validation command.
- Provide a configurable Jev client via environment variables, plus recorded-response and deterministic fake clients for offline replay/testing.
- Record each decision with ROM-profile ID, state fingerprint, prompt projection, legal choices, Jev response, compiled buttons, verification result, and retry/fallback reason.

## Test plan

- Unit-test decoding, legal battle-option generation, cursor-relative input compilation, invalid-policy fallback, and unsupported-ROM rejection.
- Contract-test the mGBA bridge with a fake adapter: frame timing, key masks, observation, and save-state round trips.
- Replay-test the starter-to-first-battle flow against recorded Jev responses.
- Run a local ROM smoke test from the user-local checkpoint: selected starter is in the party, battle starts, Jev actions remain legal, battle ends in victory, and the JSONL log is complete.
- Add a profile-isolation test showing a future difficulty-hack profile cannot silently use base-ROM addresses.

## Assumptions

- Base target is a legally obtained US v1.0 Emerald dump, identified by SHA-256.
- v1 gives Jev starter/menu and battle decisions; deterministic code owns routine navigation, timing, recovery, and verification.
- Difficulty hacks are explicitly out of v1, but the profile boundary is designed for them from the start.

