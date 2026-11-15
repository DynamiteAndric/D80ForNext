.D80 - Didaktik D40/D80 disk images with MDOS 1.0 on the ZX Spectrum Next
=========================================================================

Copy the contents of this folder to the root of the Next SD card:

  /dot/D80               the dot command
  /sys/d80/mdos10.rom    MDOS 1.0 ROM (Didaktik_40-80_MDOS_v1_91, CRC32 545531FA)
  /d80/*.d80             disk images

The standard 48K ROM is taken from /machines/next/48.rom, which is part of
the normal Next SD card distribution.

Usage (NextBASIC or the command line):

  .d80 /d80/021.d80
  .d80 -r /path/mdos.rom -4 /path/48.rom /path/game.d80
  .d80 "c:/my disks/game.d80"      (quotes allow spaces and ':')
  .d80 -w /d80/021.d80             disk writes go back to the image file
  .d80 -t /d80/021.d80             -w plus a write self-test first

Writing to the SD card (-w):
  Without -w, disk writes change only the RAM copy and are lost on reset.
  With -w every sector MDOS writes also goes to the image file on the
  card (only into the file's own sectors; the FAT is never changed).
  Before starting, .d80 checks where the file lies on the card by reading
  sectors back. If a write fails, MDOS shows "Disk is write protected
  (Retry = R)". -t also writes the last image sector inverted, reads it
  back and restores it: use it for a first test. Keep a backup of images
  you care about.

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

Limits: 48K only; no SNAP button; a 720K image needs 90 free 8K pages;
-w needs an image in at most 128 fragments. Leave with a hard reset.
NextReg #7F holds the last progress marker: #E3 = MDOS started; bit 7 set
= .d80 failed at step (marker AND #7F), #20-#25 are the -w/-t steps.

The MDOS ROM is copyrighted: do not redistribute this folder with it.
