.D80 - Didaktik D40/D80 disk images with MDOS 1.0 on the ZX Spectrum Next
=========================================================================

Copy the contents of this folder to the root of the Next SD card:

  /dot/D80               the dot command
  /sys/d80/mdos10.rom    MDOS 1.0 ROM (Didaktik_40-80_MDOS_v1_91.rom, CRC32 545531FA),
                         not included; download it from
                         https://cygnus.speccy.cz/download_roms.php
  /sys/d80/gama.rom      optional Didaktik ROMs for the machine menu, not
  /sys/d80/didm.rom      included (Didaktik_Gama_1989.rom, Didaktik_M_1992.rom,
  /sys/d80/kompakt.rom   Didaktik_Kompakt_93.rom from the same page)
  /d80/demo.d80          a demo disk (RUN starts its menu)

The standard 48K ROM is taken from /machines/next/48.rom, which is part of
the normal Next SD card distribution.

Usage (NextBASIC or the command line):

  .d80 [-w] [-r mdos.rom] [-4 48.rom] [-n] a.d80 [[-n] b.d80]

  .d80 /d80/demo.d80
  .d80 -w /d80/demo.d80                  disk writes go back to the image file
  .d80 -w /d80/demo.d80 /d80/data.d80    a second image in drive B:
  .d80 -w /d80/demo.d80 -n /d80/data.d80 ... created as a blank disk first
  .d80 -w -n /d80/small.d40              a blank 360K D40 disk (*.d40)
  .d80 -r /path/mdos.rom -4 /path/48.rom /path/game.d80
  .d80 "c:/my disks/game.d80"            (quotes allow spaces and ':')

While loading, a window shows each step with a progress bar. When all is
ready it says "Press any key"; the next key starts MDOS. Without -4 it
first asks for the machine if a Didaktik ROM is on the card (see below).

Writing to the SD card (-w):
  Without -w, disk writes change only the RAM copy and are lost on reset.
  With -w every sector MDOS writes also goes to the image file on the
  card (only into the file's own sectors; the FAT is never changed).
  Before starting, .d80 checks where the file lies on the card by reading
  sectors back. If a write fails, MDOS shows "Disk is write protected
  (Retry = R)". Keep a backup of images you care about.

Blank disks (-n):
  -n creates the image name that follows it as a freshly formatted disk:
  360K D40 (40 tracks) for a *.d40 name, otherwise 720K D80. The disk name
  is the file name (up to 10 characters). An existing file is never
  overwritten: .d80 stops with "File exists".

Machine menu (Didaktik ROMs):
  Without -4, .d80 first asks for the machine, e.g.: 1 ZX Spectrum 48K
  (/machines/next/48.rom), 2 Didaktik Gama (/sys/d80/gama.rom), 3 Didaktik M
  (/sys/d80/didm.rom), 4 Didaktik Kompakt (/sys/d80/kompakt.rom). Press the
  digit, or the cursor keys and ENTER; ENTER alone takes the 48K. Only the
  machines whose ROM file is on the card are listed, numbered without
  gaps; with no Didaktik ROM there is no menu. -4 file
  skips the menu:  .d80 -4 /sys/d80/kompakt.rom /d80/demo.d80
  Accepted by CRC32 (Didaktik ROMs from cygnus.speccy.cz, see above):
  Sinclair 48K (DDEE531F), Didaktik_Gama_1989.rom (45C29401),
  Didaktik_M_1992.rom (57264D4F), Didaktik_Kompakt_93.rom (34752ABA).
  Other ROMs stop with "Unknown machine ROM". Not emulated: the
  Gama's second 32K bank (OUT 95,1), the 8255 printer port, and the
  Didaktik ULA timing (the Next uses 48K timing). OUT 31 also drives the
  Next's DAC A if the DACs are enabled. The ROMs are not included.

Drive B:
  A second image goes into drive B:. In MDOS use the drive letter:
  CAT "b:", LOAD *"b:name", SAVE *"b:name" CODE 16384,6912.

SNAP button and D80 menu (the DRIVE button):
  A short press saves a snapshot SNAPSHOTnn of the running program to the
  current disk; the program goes on. LOAD *"SNAPSHOT00" loads it back.
  Holding DRIVE (or CAPS SHIFT + DRIVE) opens the D80 menu: cursor keys
  (7/6 or Q/A) and ENTER, or the keys X (swap A: and B:), S (snapshot),
  R (reset) and SPACE (back to the program).

Starting images from the NextZXOS browser:
  Add the lines from browser-d80.cfg to the end of /nextzxos/browser.cfg
  (do not replace that file, it holds the other associations):

    D80:.d80 -w "|"
    D40:.d80 -w "|"

  Then select a .d80 file in the browser and press ENTER. Disk writes go
  back to the image file (-w); drop the -w for read-only starts.
  If browser.cfg already has D80/D40 lines, replace them.

The Next becomes a 48K Spectrum with a Didaktik 80. Then use RUN (loads the
"run" menu from disk), CAT, LOAD *"name" and so on.

Limits: 48K only, MDOS 1.0 only; at most two drives; a 720K image needs
90 free 8K pages (two images: a 2 MB Next); -w needs an image in at most
128 fragments. The DRIVE button no longer opens the NextZXOS NMI menu.
Leave with a hard reset.
NextReg #7F holds the last progress marker: #07 = waiting for the key,
#E3 = MDOS started; bit 7 set = .d80 failed at step (marker AND #7F),
#20-#22 are the -w steps.

The MDOS ROM is copyrighted: do not redistribute this folder with it.
