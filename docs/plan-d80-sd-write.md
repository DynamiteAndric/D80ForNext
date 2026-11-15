# Plan: `.d80 -w` — write disk changes back to the SD card (status 2026-11-15)

## Context
`.d80` v1 is read-only: `SAVE *`, `ERASE`, `MOVE`, formatting and game saves change only the RAM copy of the image and are lost on reset. Once `.d80` hands over to MDOS, NextZXOS and esxDOS are gone, so the FAT file system is not available any more.

## Design
1. **At load time, while NextZXOS still runs:** `DISK_FILEMAP` (esxDOS `#85`) is called on the freshly opened image. It returns the card addresses of the file as extents of 6 bytes each (4-byte card address, 2-byte sector count). `A` holds the card flags: bit 0 = card 0/1, bit 1 = block addressing. With byte addressing the address grows by 512 per sector (the z88dk wrappers `asm_esx_disk_filemap` / `asm_esx_disk_stream_sectors` confirm this). The table goes straight into MDOS B at `SD_MAP` (`#3000`, up to 128 extents).
2. **Check before trusting the map:** the extents must cover the whole image. With our own SPI code (CMD17), the dot command reads the first sector of every extent and the last sector of the image, and compares each one with the copy it has just loaded through esxDOS. Any difference, or more than 128 extents, aborts `.d80` with an error. Nothing is written in that case.
3. **At run time (MDOS):** after the RAM copy is updated, `sec_write` / `sec_format` also write the sector to the card with CMD24 over SPI (port `#E7` chip select: `#FE` card 0, `#FD` card 1; port `#EB` data). This happens with interrupts off, after the user page is mapped back. A card error returns `BC = #0340` (WD status "write protect", class 3). MDOS then shows `Disk is write protected (Retry = R)`, and `R` retries the write.
4. **Opt-in:** only `.d80 -w image.d80` writes. Without `-w`, v1 behaviour stays. The browser line becomes `D80:.d80 -w "|"` if the user wants it.
5. **Self-test `-t`** (implies `-w`): after the map check, it writes the last image sector inverted, reads it back, writes the original back and reads that back too. This tests CMD24 on the real card without changing the file. It is used for the ZEsarUX check and as a first test on hardware.

The SPI code (`dot/sdspi.asm`) is shared: the dot command and `mdospatch.asm` both include it. Writing only ever touches sectors inside the file's own extents, and the file size does not change, so the FAT is never modified.

## Progress markers (NextReg `#7F`)
`#20` = DISK_FILEMAP, `#21` = map check, `#22` = check of the last sector, `#23`–`#25` = self-test (write inverted / restore / done). A failure keeps the step and sets bit 7, so `#A3` means the self-test failed.

## Steps
1. [x] `dot/sdspi.asm`: `sd_find` (LSN → card address), `sd_read` (CMD17), `sd_write` (CMD24, data or a `#E5` fill), and timeouts on every wait.
2. [x] `dot/mdospatch.asm`: `cur_lsn`/`cur_buf`, an SD write after `smc_unmap`, and the data `sd_on`, `sd_n`, `sd_cs`, `sd_blk` and `SD_MAP`.
3. [x] `dot/d80.asm`: the options `-w`/`-t`, `DISK_FILEMAP`, the map check and the self-test.
4. [x] Python model: `z80mini` real port I/O (OUT, INI/OUTI blocks), an SPI SD card in `nextmmu` (a fragmented, block- or byte-addressed card), and `mdospatch.build_pages(..., sd=...)`.
5. [x] Tests (`tests/test_d80dot.py`, `TestSdWrite`): `SAVE *` in the model, then check that the card holds the same bytes as the RAM image; also a byte-addressed card, the `#E5` format fill and a write error followed by a retry.
6. [x] ZEsarUX: `.d80 -t` runs the map check and the self-test on the emulated card (marker `#7F`).
7. [x] Docs and `dist/`. [x] Real Next (2026-11-15): the `-t` self-test passed, and the user confirmed that writing works.

## Results
- **Model:** `SAVE *"test" CODE 16384,6912` on disk 021 writes 16 sectors (FAT, directory, data). The card holds exactly the RAM copy, and no sector outside the extents is touched. This holds for a fragmented file, block- and byte-addressed cards, and both read behaviours of port `#EB`. A refused write shows `Disk is write protected (Retry = R)`; `R` after the card recovers finishes the save. The `#E5` format fill was tested by calling `sd_put` directly, because the MDOS 1.0 `FORMAT` syntax is not known yet.
- **ZEsarUX 13 (NextZXOS 2.06H):** `.d80 -t "/d80/021.D80"` gets a real `DISK_FILEMAP` and passes the CMD17 map check and the CMD24 self-test (marker `#E3`). The image file is unchanged afterwards.
- **Emulator quirk found:** ZEsarUX treats every byte *written* after the command as CRC → token → data. The Nwr gap before the start token is therefore clocked with a read (`IN`). Real cards accept that as well.
