# Plan: replace the third-party sample disks with a generated demo disk (status 2026-11-16: done)

## Context
`images/` and `dist/d80/` held 25 real Didaktik disks (games, magazines). They cannot be published. Tests, screenshots and the `dist/` package depended on them, mainly on disk 021 (its `run` menu, HEXAGONIA as a running IM 2 program for the SNAP and menu tests, and a `CAT` long enough to scroll).

## Done
1. `tools/basic.py`: a small 48K BASIC tokenizer (keywords, hidden 5-byte numbers, strings and `REM` kept as text).
2. `tools/image.py`: `add_file` writes a file into an image as MDOS `SAVE *` does (FAT chain, directory entry with attributes `#0F`, `param2 = #8000` for non-BASIC files).
3. `tools/demo_image.py`: builds the demo disk "D80 Demo": `run` menu, `demo` loader, `democode` (IM 2 with I = `#80`, busy-waits for each frame, so no `HALT` in the main loop), `counter`, `screen1`–`4`, `data01`–`20`. Copy in `dist/d80/demo.d80`.
4. Tests build the demo disk in memory. HEXAGONIA → the IM 2 demo (`(im, i) == (2, #80)`), the `CAT` check → `data10`. `test_tools` covers the tokenizer, `add_file`, a broken chain (corrupted FAT) and a synthetic raw snapshot.
5. Checks that need real disks (SNAPSHOT-PACKER unpacking, X-MAGAZIN drive descriptor, KOMPAKT boot sector, all chains on all disks) read `emulators/images/` (git ignores it) and are skipped without it.
6. Screenshots in `docs/images/` were regenerated from the demo disk.

## Open
- The old disks are still in the git history (`main` on GitHub). Removing them from there needs a history rewrite (`git filter-repo --path images --path dist/d80 --invert-paths`) and a force push.
