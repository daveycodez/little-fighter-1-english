# Adding a custom LF1 character: Firzen implementation notes

These notes document how Firzen was added as character 12 without editing the
original game executables. They also explain the selection crashes, missing
heads, corrupted arena graphics, and menu lettering issues encountered during
integration, so the process can be reused for another character.

On **2026-09-30**, the user confirmed that Firzen renders correctly in game and
that the corrupted lines on the level are gone. That confirmation covers the
rendering fix; it does not establish that every move, tournament path, or mod
combination has completed in-game testing.

## 1. Preserve the original game and make the character optional

The configuration key is `firzen` in `mods.cfg`:

```ini
firzen=1
```

Firzen is a separate character alongside Julian. Disabling the key selects the
original character resources and omits the Firzen-specific engine patches.
F1 and `unlock_julian=1` unlock both characters when Firzen is enabled.
`balanced_julian=1` disables passive regeneration for both.

The important constraint was **no direct writes to START.EXE, FIGHT.EXE,
CONTEST.EXE, or PLAY.COM**. The older MODS implementation wrote patches to the
executable files. It was changed to queue the selected patch bytes and apply
them to loaded memory instead. The build's PLAY.COM-writing code was removed.

The resident loader in [runtime.asm](runtime.asm) intercepts DOS execution:

1. Recognize the supported game executable name.
2. Use DOS `INT 21h`, `AX=4B01h` to load the MZ executable without starting it.
3. Apply the existing mod overlays, then the enabled Firzen overlays.
4. Reserve and initialize the extra data-table space.
5. Enter the child's original CS:IP with its expected PSP and stack state.
6. Return to the parent through a termination trampoline when the child exits.

DOS performs the initial MZ relocations. Legacy patch bytes that overwrite
relocation words need their load-segment adjustment reapplied. File offsets
must not be treated as memory addresses: the executable header is not loaded
as part of the program image.

```text
loaded address = image_base_segment * 16 + file_offset - MZ_header_bytes
image_base_segment = child_PSP_segment + 0x10
```

The resource-open hook substitutes FZ-prefixed files only while an enabled
Firzen game module is running. The original resources remain separate inputs.
The configuration matcher ignores commented lines and rejects partial values
such as `firzen=10` when looking for `firzen=1`.

## 2. LF1 appearance uses a shared body, a head, and palette choices

An ordinary LF1 character does not require an entirely new body sprite sheet.
Most ordinary poses use the shared body sprites, a head overlay, and character
colors. Some special poses have the head baked into their body artwork and
therefore need recoloring or additional character-specific cells.

| Resource | Native layout | Firzen change |
| --- | --- | --- |
| HEAD.GRH | 11 columns, 5 rows; 18×13 pitch; 17×12 head pixels | Expand to 12 columns, 216×65 |
| HEAD2.GRH | Menu heads; 18-pixel column pitch; 17×15 available face area | Expand to 216×16; custom head plus native jaw rows |
| FACE.GRH | 6×2 portraits, each 50×50; whole sheet 300×100 | Fill unused final tile at x=250, y=50 |
| ACT1/ACT2 | 12 columns; 26×26 pitch; 25×25 body pixels | Preserve stock cells; append a row to ACT2 |
| WEAPON.GRH | Standard projectile cells on 18×14 pitch | Reuse stock fire/ice graphics; custom Cannon uses its own atlas |
| SUPER?.GRH | 106×152 character move panel | Provide the missing panel for character 12 |

The original stock pixels were preserved when building the expanded atlases.
Firzen's approved head remains 17×12. Native assets are not stretched. Preview
magnification is 4× nearest-neighbor scaling, separate from game asset sizes.

The approved appearance is recorded in
[firzen-approved.json](../../art/firzen/firzen-approved.json). Current colors are
hair 97/98, skin 83/81, shirt 66/77, and trousers 11/10. The portrait
background uses dark gold index 78, RGB (168, 120, 0).

### GRH and palette rules

A GRH file contains a 300-byte header followed by one indexed byte per pixel.
The first four bytes store big-endian 16-bit width and height:

```text
file_size = 300 + width * height
```

The palette comes from SYS/PAL. Its six-bit RGB components are expanded by
multiplying by four, and the game loads it beginning at VGA index 1. Index 0
is used for transparent sprite pixels. Use the existing fixed sprite palette
(indices 1–150) for new artwork; higher indices are used by the game's dynamic
color machinery. Shared body pixels 151–160 are mapped to the selected
character's skin, clothing, eye/mouth, and baked-hair colors.

Use the palette and format helpers in
[render_character_preview.py](../../export/render_character_preview.py).
Do not substitute arbitrary RGB colors merely because a PNG displays them.

## 3. External DATA.DAT is only part of adding a character

[FZDATA.DAT](../../SYS/FZDATA.DAT) adds Firzen's character record and new
projectile definitions. The character record is 75 bytes after parsing.
Character IDs 1–11 were already occupied; Firzen uses ID 12. Table storage also
needs the unused ID 0 entry, so the expanded character table contains
**13 records**, or 975 bytes.

Firzen uses `Head: 12` and `Face: 6 2`. The five head-color rows grow from
11 entries each to 12 entries each: 55 colors become 60 colors.

The engine also contains separate, fixed-size lookup tables and hardcoded
column counts. Adding a DAT record does not expand any of those automatically.
The menu, combat renderer, and tournament module each needed attention.

### Reserve new table storage instead of appending over adjacent globals

Appending record 12 to the original table would overwrite unrelated memory.
Character definitions and related lookup tables were relocated into reserved
space. References to those tables were then patched in loaded code.

The addresses below are **offsets within the module's DS**, not file offsets.
All ranges use an exclusive end.

| Module | Data | Range |
| --- | --- | --- |
| START | 13 character records | 0x4000–0x43CF |
| START | Head-color header and 60 words | 0x4401–0x447B |
| START | 13 head lookup words | 0x4480–0x449A |
| START | 13 portrait lookup words | 0x44A0–0x44BA |
| START | 13 selection-availability words | 0x44C0–0x44DA |
| FIGHT | 13 character records | 0x5800–0x5BCF |
| FIGHT | Head-color header and 60 words | 0x5BD1–0x5C4B |
| FIGHT | 13 AI-priority words | 0x5C60–0x5C7A |
| CONTEST | 13 head lookup words | 0x3400–0x341A |
| CONTEST | 13 portrait lookup words | 0x3420–0x343A |

The loader moves the returned initial SS upward before Borland startup:
START by 0x100 paragraphs, FIGHT by 0xC0, and CONTEST by 0x60. It preserves the
initial stack word. Borland startup derives its allocation boundary from SS,
keeping the new table area separate from the heap. Do not simply choose an
apparently unused address without checking startup, BSS, stack, and heap use.

Another subtlety: START's absolute DS:[0x2D04] is also a graphics-buffer segment
word. Only the indexed head-color-table references are relocated. A blanket
replacement of every occurrence of 0x2D04 would corrupt graphics pointers.

End-of-battle statistics also used five 11-character arrays on the stack.
They were expanded to 12 entries each, growing the frame from 146 to 156 bytes
and moving the array bases without overwriting the other locals.

## 4. Selection needs every associated asset and lookup

The first selection crashes had multiple contributing issues:

- The portrait and head lookup arrays had only entries 0–11. Firzen needed
  entry 12, seeded to head/portrait 12.
- Filename case folding initially changed punctuation, including the dot in
  `DATA.DAT`, so resource substitution failed. Only lowercase letters should
  be converted to uppercase.
- Selecting character 12 requests **SUPERL.GRH**. The letter L looked like a
  digit 1 in the game's error message. Without that file, the native loader
  takes its fatal missing-resource path. It is redirected to FZSUPER.GRH.

A later table-placement mistake made characters show the wrong heads. The
head lookup was initially placed at 0x4460, inside the head-color table, whose
range extends to 0x447B. Color parsing overwrote the lookup entries. Moving
head, portrait, and availability tables to the non-overlapping ranges above
resolved that problem.

Firzen's menu head also received a one-pixel upward draw adjustment. This
applies only to Firzen's menu overlay; it does not shift stock heads or resize
any head asset.

CONTEST.EXE uses its own static head/portrait lookups. Its rendering and CPU
boss-outcome checks were extended too. Updating START and FIGHT alone would
leave a separate tournament path using the old assumptions.

## 5. The arena corruption was a buffer overflow

**Expanding a GRH file is not enough. The game's allocation and cache-copy
sizes must grow with it.** This was the cause of the large striped blocks on
the level and corrupted projectile graphics.

Firzen's additional special poses expanded ACT2 from 312×130 to 312×156.
The game still allocated the old fixed amount, then loaded the larger file.
That overwrote the neighboring projectile atlas buffer.

| Allocation/copy | Old value | Required new value |
| --- | --- | --- |
| ACT2 allocation | 300 + 312×130 = 40,860 bytes | 300 + 312×156 = 48,972 bytes |
| Cached first head row | 3,000-byte allocation | 300 + 216×13 = 3,108 bytes |
| Width copied into cached head row | 198 pixels | 216 pixels |

The old 3,000-byte head allocation was sufficient for the stock 198×13 cache
(2,874 bytes), but not for the expanded cache. Moreover, copying only the old
198-pixel width omitted Firzen's column entirely. These are independent
requirements: **allocate enough memory and copy the full new width**.

The FIGHT file-offset patches for this repository's executable are:

| File offset | Change |
| --- | --- |
| 0x1791C | ACT2 allocation immediate → 48,972 |
| 0x178F4 | Head-row allocation immediate → 3,108 |
| 0x17993 | Cached head-row copy width → 216 |

These patches affect loaded memory only. The builder asserts the expected
original instructions before constructing its patch manifest. Offsets must
be reverified for a different executable version.

## 6. Reuse boss behavior without inheriting Julian's artwork

Character ID 12 is treated like Julian's ID 11 for applicable boss behavior,
including regeneration and boss-selection logic. However, Julian has special
artwork paths which Firzen must not inherit. Rendering comparisons at FIGHT
file offsets 0x17463, 0x19212, and 0x19705 are deliberately excluded from the
boss aliasing.

Character IDs and weapon IDs are separate namespaces. Weapon type 12 is an
existing projectile. Never turn every numeric 12 into Julian or use a blanket
`type >= 11` replacement across combat objects. The type shim checks the
entity class before applying an alias and preserves the native CMP flags.

The extra hooks use INT 65h, separate from the existing gore INT 60h handler.
Graphics wrappers must preserve the original far-call arguments and register
behavior. The stock projectile renderer was compared with and without these
hooks using the same captured state and produced identical output pixels.

## 7. Special moves and their additional assets

| Move | Implementation |
| --- | --- |
| Cannon | New types 27/28, own 29-pixel-wide graphics, held attack, fixed-point movement |
| Disaster | New types 29/30 cloned from Firen fireball and Freeze iceball |
| Polar Volcano | Native Freeze cyclone followed by native Firen explosion |

Cannon's leading image is 29×15; the continuation is 29×9. They are stored in
a 29×31 atlas, with the continuation beginning at y=16. A custom crop/draw path
handles their sizes. Ordinary projectiles retain the original renderer, and
the impact state returns to the native hit graphic. Cannon emits every three
game ticks and moves at approximately 100 native pixels/second at normal
LF1 speed. Movement adds to the engine's current projectile position so camera
adjustments are respected. Holding stops on release or depleted MP, with
`free_supers` and `cheap_supers` accounted for.

Disaster emits fire, ice, fire, ice, one at a time, from alternating upper and
lower lanes. The clones retain their native burn/freeze collision behavior.
Only the homing-related comparisons alias them to Julian's type-26 skull
projectile. Owner and target fields remain native, with the chase timer and
velocity adjustments handled by the existing code.

Polar Volcano uses added poses 121–124 derived from Freeze's poses 111–114,
and pose 125 derived from Firen's explosion pose 93. Native ice/fire effects
are retained while character pixels are recolored. Its AI-triggered state is
normalized to start with the cyclone, then transitions immediately to the
explosion. The wrapper restores Firzen's character identity after the native
Firen producer runs.

The weapon-definition records are 18 bytes each. Types 27–30 fit in the
existing table; its final word ends immediately before the collision pool at
DS:0x3148. Adding type 31 would require another capacity/layout review rather
than blindly appending a row.

## 8. Write the move panel on a clean background

The move panel uses lettering baked into the stock GRH images. It is not the
same narrow font as the runtime NEWFONTS resource.

The builder samples stock glyph ink at x=`2 + character_index * 8`, using a
7×9 mask and an eight-pixel advance. Sampling the wrong cell origin included
neighboring letters and made words look distorted. A space must be an explicit
empty mask; copying a supposed space from an existing label can pick up ink.
Move labels can have different kerning from names: Ice Blast’s narrow I
places its c at x=8, not x=10. That c and the a from Davis are sampled
explicitly to avoid clipped shapes. The additional capital C/V masks use the
same native pixel grid.

Each move title is now drawn onto a **fresh opaque 104×16 blue band**, then
pasted over the entire old title area. This prevents old Whirlwind lettering
or other pixels from remaining behind Polar Volcano. The 13-character name
fits the 106-pixel panel with the existing spacing.

Do not paint over the border while clearing text. The builder restores both
outermost columns, x=0 and x=105, from the stock panel after all overlays,
including the MP-cost patches. Both columns were checked pixel for pixel.

DAT costs are internal units: 50/100/125 correspond to the panel's native
20p/40p/50p presentation. Preserve the existing control icons and cost style.
The running game caches its images, so replacing the GRH file requires a
fresh launch to see the new panel.

## 9. Build, inspect, and validate

The main implementation files are:

| File | Purpose |
| --- | --- |
| [build_assets.py](build_assets.py) | Build separate FZ DAT/GRH resources from native assets and approved artwork |
| [build_runtime.py](build_runtime.py) | Decode references, assert signatures, generate patch/site tables, invoke NASM |
| [runtime.asm](runtime.asm) | DOS loader, resource substitution, native behavior shims and Firzen controllers |
| [build_mods_com.py](../../build_mods_com.py) | Assemble the resident MODS program and queue existing mod selections |
| [test_runtime.py](test_runtime.py) | Execute compiled 16-bit hook bytes with Unicorn |

```sh
python3 mods/firzen/build_assets.py
python3 build_mods_com.py
python3 -m mods.firzen.test_runtime
```

The current instruction-level suite contains 15 tests covering flags,
configuration parsing, patch queues, table spacing, graphics allocations,
Cannon cadence and camera motion, alternating Disaster shots, the
cyclone/explosion transition, loader dispatch, tournament lookups, and
statistics-frame capacity.

Additional native-renderer checks established:

- Every one of Firzen's **152 opaque head pixels** matched the approved sprite
  when emitted by the game's actual rendering instructions.
- The untouched projectile path produced **zero differing output pixels**
  with and without the new graphics hooks in the captured-state comparison.
- Existing stock head/body pixels were unchanged in the expanded source
  atlases.
- Original executable and launcher hashes remained unchanged.

These checks complement actual gameplay. They do not replace checking a new
character's moves, collisions, recovery animations, AI, mode transitions, and
mod combinations in DOSBox. The user performs the in-game keyboard testing.

## 10. Reuse this process for the next character

Before extending another atlas or adding another ID, enumerate every consumer
of that count: parser tables, static lookups, sprite-coordinate divisors,
allocated buffers, cache-copy dimensions, result arrays, and separate modules.
The character-count limit and the eight-fighter match limit are different.

Keep this sequence:

1. Establish the approved native head, portrait, palette, and special poses.
2. Add external character data and all resources requested by its ID, including
   the move-help panel.
3. Reserve non-overlapping table space and seed each independent lookup.
4. Update every affected allocation and copy size from the actual dimensions.
5. Add only the needed runtime behavior hooks; retain native behavior elsewhere.
6. Compare stock output, validate the compiled hooks, and check original hashes.
7. Test selection from both neighbors, normal gameplay, specials, and mode
   transitions in a fresh DOS session.

The decisive lesson from Firzen is that a correct-looking PNG and a valid DAT
record can still corrupt the game. The loaded engine's memory layout,
allocation sizes, cached copies, and ID-specific resource paths must agree
with the expanded assets.
