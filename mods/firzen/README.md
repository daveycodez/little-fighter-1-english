# Firzen runtime mod

See [implementation notes](IMPLEMENTATION_NOTES.md) for the runtime loader,
menu integration, memory layouts, and the rendering glitches and fixes.

Set `firzen=1` in `mods.cfg` to add Firzen as character12 alongside Julian.
Set `firzen=0` to use the original character data and graphics. F1 and
`unlock_julian=1` unlock both bosses while Firzen is enabled.
`balanced_julian=1` disables passive health regeneration for both.

All executable changes are applied to loaded DOS memory. The builder and
runtime never write START.EXE, FIGHT.EXE, CONTEST.EXE or PLAY.COM. Separate
FZ-prefixed assets are selected only while the enabled mod is running.

| Move | Native input, facing right | MP |
| --- | --- | --- |
| Cannon | Left, Right, Right, Attack; hold Attack | 20 to start; continuous drain |
| Disaster | Right, Down, Up, Attack | 40 |
| Polar Volcano | Up, Down, Left, Right, Attack | 50 |

With `easy_supers=1`, P1 uses Q/E/Z; hold Q for Cannon. The other player
shortcuts remain the standard mod controls. Mirror horizontal inputs when
facing left.

Cannon emits its leading ball and mirrored continuation at100 native pixels
per second, every3 normal game ticks. Disaster emits four homing projectiles
in fire/ice/fire/ice order, from alternating upper/lower lanes. Their native
burn/freeze collision effects remain intact. Polar Volcano uses the native
Freeze cyclone followed immediately by the native Firen explosion.

## Assets

The approved head and appearance are described in
`art/firzen/firzen-approved.json`. Graphics use the original DOS palette:
hair97/98, warm gold66/77 and charcoal11/10. Native heads are17×12,
portraits50×50, and body cells25×25. Preview magnification uses nearest
integer scaling; game assets stay at their native sizes.

`build_assets.py` expands the head atlases to12 columns, adds the portrait
in FACE's unused final slot, adds recolored cyclone/explosion poses to ACT2,
and builds the Cannon atlas and native-font move panel. All original stock
pixels remain unchanged outside the previously unused portrait slot.

## Build and validation

Requires Python with Pillow/Capstone, NASM and Unicorn for instruction tests.

```sh
python3 mods/firzen/build_assets.py
python3 build_mods_com.py
python3 -m mods.firzen.test_runtime
```

Restart the DOS emulator after changing configuration; MODS is resident for
the duration of that DOS session. The existing PLAY.COM invokes it.

Tests execute the compiled16-bit hooks and check native type aliases,
configuration parsing, legacy patch queues, graphics buffer sizes, table
spacing, Cannon controls, alternating Disaster shots, the freeze/explosion
transition, tournament lookups, and end-of-battle statistics storage. Cannon motion also
respects the engine’s camera adjustments.
On2026-09-30, the user confirmed correct in-game Firzen rendering and no
remaining level corruption. Special moves and mode combinations still need
their separate in-game checks.
