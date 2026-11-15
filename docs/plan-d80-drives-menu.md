# Plán: `.d80` — prázdný image, mechanika B:, NMI menu (stav 2026-11-15: hotovo, všechny fáze včetně menu ve stylu 128 ověřené na Nextu)

## Context
`.d80` dnes umí jednu disketu (A:), zápis na SD (`-w`) a SNAP na tlačítku DRIVE, vše ověřené na skutečném Nextu. Uživatel chce:
1. vytvořit prázdný (naformátovaný) image, do kterého jde zapisovat;
2. obsluhovat víc virtuálních mechanik najednou;
3. NMI menu s ovládáním D80.

Rozhodnutí uživatele:
- krátký stisk DRIVE = SNAP (jako dnes), podržení = menu;
- nejvýš **2 diskety** (A: + B:), načtené při startu;
- Next má 2 MB.

### Proveditelnost (ověřeno v ROM a vzorcích)
- **Prázdný image: ano, snadno.** FORMAT v MDOS 1.0 (`#13E4`–`#147F`) zapisuje:
  - boot sektor: nuly; na offset 128 deskriptory mechanik (`#3E00`, 48 B); na 176 deskriptor aktuální mechaniky (12 B); na 192 jméno (10 B); na 202–203 dva náhodné bajty (`LD A,R`); na 204 `SDOS` (z `#0F10`);
  - FAT (sektory 1–5): vyplněná `#DD`, záznamy datových sektorů 14…1439 = 0;
  - adresář (sektory 6–13) a data: `#E5`.

  Boot sektory vzorků (021, 036, 040) tomu odpovídají.
- **Víc mechanik: ano, ale strop jsou 2.** MDOS 1.0 inicializuje jen mechaniky 0 a 1 (`#2273 CP #02`) a výchozí tabulka deskriptorů `#0EF8` má 24 B, tedy dvě mechaniky. Víc mechanik by vyžadovalo přepsat MDOS, a to není potřeba. 2 × 90 stránek + 4 + menu se do 2 MB vejde.
- **NMI menu: ano.**
  - Spouští se ze stejné cesty jako SNAP (`snap_entry0`, NMI je povolené jen mimo MDOS).
  - Délku stisku pozná podle NextReg `#10` bit 1 (DRIVE drženo).
  - Kód menu běží z vlastní 8K stránky namapované do slotu 7 se zakázanými přerušeními a vlastním zásobníkem (stejný trik jako `sec_op`). Obrazovka se uloží do další stránky.
  - Za běhu není potřeba žádné API NextZXOS.

## Fáze 1 — prázdný image (`-n`)
- **CLI:** `.d80 -n new.d80` vytvoří 720K D80 image (80 stop, 2 strany, 9 sektorů) a hned ho spustí.
  - Jméno disku = jméno souboru bez přípony, nejvýš 10 znaků.
  - Pokud soubor existuje, příkaz skončí chybou a nic nepřepíše.
  - Kombinuje se s `-w` (bez něj by byl prázdný image k ničemu, ale povolíme to).
- **`dot/d80.asm`:**
  - nová rutina `make_blank`: `F_OPEN` s vytvořením nového souboru (`FA_WRITE|FA_CREATE_NEW`), pak 1440× `F_WRITE` po 512 B: boot sektor, 5 FAT sektorů, 8 sektorů adresáře, data `#E5`;
  - šablona boot sektoru se poskládá z konstant;
  - pak `F_CLOSE` a standardní cesta (open → `get_map` → načtení), takže `-w` funguje beze změny;
  - nové chybové hlášky: „File exists“, „Write error“.
- **`d80tool`:** `python -m d80tool new name.d80 [--name X]` se stejnou logikou (`d80tool/image.py`: `blank_image()`). Slouží jako reference pro testy a pro PC.
- **Ověření v modelu:**
  - `MdosImage(blank_image())` projde `check`;
  - boot → `CAT` ukáže prázdný adresář;
  - `SAVE *"test" CODE …` → soubor je v adresáři, `image.check` je OK;
  - s `-w` je karta shodná s RAM kopií.
- **Volitelně:** porovnat s disketou naformátovanou skutečným MDOS FORMAT v Fuse (syntaxe FORMAT se zjistí z tabulky `#05FF`).

**Stav fáze 1:**
- `d80tool.image.blank_image` a `python -m d80tool new` jsou hotové. Boot sektor je bajt po bajtu shodný s disketou 036, naformátovanou MDOS (při stejném ID disku).
- `.d80 -n`: `make_blank` (`F_OPEN` s `#06` = zápis + vytvořit jen nový; při chybě 18 se vypíše „File exists“), systémové sektory se zapisují po jednom, data `#E5` po 8K z dočasné stránky; `blank_sector` generuje obsah sektorů.
- Testy `TestBlank`: rozložení; asm `blank_sector` spuštěný v Z80 modelu dává stejné sektory jako Python (různá jména souborů); MDOS v modelu na prázdném image s `-w` provede `CAT` i `SAVE`, soubor je čitelný a karta je shodná s RAM.
- [hotovo 2026-11-15] Ověřeno uživatelem na skutečném Nextu.

## Fáze 2 — mechanika B:
- **CLI:** `.d80 [-w] [-n] a.d80 [b.d80]` (`-t` later removed); druhý poziční argument je B:. `-n` se týká jen obrazů, které neexistují.
- **Data v MDOS B (`dot/mdospatch.asm`):**
  - tabulky se rozdělí na dvě mechaniky: `img_secs`, `page_table` (104 B), `sd_n`, `sd_cs`, `sd_blk`;
  - B: dostane vlastní tabulky v `#2608`–`#26FF`, mapa extentů B: (`SD_MAP_B`, 768 B) půjde do `#3400`–`#36FF`;
  - pomocná rutina `drv_tables` podle `DRIVE` (`#3E6B`) nastaví ukazatel `IY` na tabulky mechaniky A: nebo B:. Alternativa je přepnout tabulky kopírováním při změně mechaniky, ale ukazatel je čistší.
  - `ASSERT`y na všechny hranice.
- **Ovladač:**
  - `sec_op`: místo `jp nz,sop_nodisk` pro mechaniku ≠ 0 se vezme tabulka mechaniky; mechanika bez obrazu (`img_secs` = 0) dál vrací `#0401`;
  - `disk_ready` a `#234B` (stopa 0): odpovídá „přítomno“, pokud má mechanika obraz. Inicializace `#2216` pak B: najde sama: dnes `#234B` hlásí stopu 0 jen pro `ixl`=0;
  - `sd_put`: tabulky a mapa vybrané mechaniky.
- **Loader (`d80.asm`):**
  - smyčka načítání obrazu se zopakuje pro B: (stránky, kontrola `SDOS`, `get_map`/`check_map` pro obě mechaniky, `-t` jen pro A:);
  - `MAX_PAGES` na mechaniku zůstává 104, `allocated` se zvětší na 2×104+6;
  - `build_dot.py` exportuje nové symboly, `mdospatch.py` dostane `PageMap` pro dvě mechaniky.
- **Zjistit:** jak se v MDOS 1.0 píše mechanika B: v příkazech (např. `LOAD *"b:jmeno"`, nebo jinak; najde se v rozboru jmen u `#05FF`, případně podle MDOS 2.1 `T_DRIVE`).
- **Ověření v modelu:**
  - `CAT` na A: i B:;
  - `LOAD` z B:;
  - `SAVE` na B: s `-w` → změní se jen karta B:, extenty A: zůstanou netknuté;
  - bez B: vypadá chování jako dnes (stávající testy).

**Stav fáze 2:**
- Syntaxe v MDOS 1.0: rutina `#10E2` převede jedno písmeno A–D před `:` na číslo mechaniky (`#3E6B`), jinak hledá disk podle jména. Píše se tedy `CAT "b:"` nebo `LOAD *"b:jmeno"`.
- Odchylka od plánu: ovladač nepoužívá ukazatel `IY`, ale prohazuje tabulky. Aktuální sada (`img_secs`, `fix_pg2/7`, `page_table`; `sd_n/cs/blk`; nový ukazatel `sd_mapp`) patří mechanice `cur_drv`. Druhá sada je na `oth_tab`/`oth_sd`/`oth_mapp` (`#2610`). `drv_sel` je při změně mechaniky prohodí (113 B, asi 2 ms) a mapy extentů zůstávají na místě (`SD_MAP` `#3000`, `SD_MAP_B` `#3400`). Mechaniku sektorových operací určuje aktivní mechanika `#3E6B` (`act_sel`), ne příchozí IX — stejně jako původní `DRWSU` (`#2493`), který IX nastaví z `#3E6B` přes `DRVCMP`. (Opraveno 2026-11-15: výběr podle IX dával u 035-X-MAGAZIN „Device unavailable, 3:1“, protože program volá sektorovou smyčku s IX = `#3E0C` při aktivní A:. Zároveň opraveno `disk_ready`, které po `drv_present` předávalo do `DESC_SEL` místo čísla mechaniky zbytek `H or L`.) Jen `#234B` (inicializace, IX prochází descriptory) dál rozlišuje podle IX.
- `drv_present` používají `#234B` (stopa 0 při inicializaci) a `disk_ready`. Mechanika bez obrazu hlásí „not ready“.
- Loader: `load_drive`/`store_drive` pro A: a B:. Bez druhého obrazu se do B: zapíše `img_secs` = 0, protože oblast `#2610` jinak obsahuje šum EPROM.
- Odchylka od plánu: `-n` platí pro jméno obrazu, které následuje (`.d80 -w a.d80 -n b.d80`), takže hláška „File exists“ zůstává zachovaná.
- Testy `TestDriveB`:
  - `CAT "b:"`, `SAVE` a `LOAD` na B: s `-w`; A: zůstane beze změny a obě karty jsou shodné s RAM kopiemi;
  - bez B: hlásí `CAT "b:"` chybu a A: dál funguje.

  Celkem 28 testů prochází.
- ZEsarUX (`tools/zesarux_next_check.py --image-b`):
  - `.d80 -w 021.d80 diskb.d80` dojde ke stavu `E3`; tabulky B: v bance MDOS B jsou správně (1440 sektorů, 90 stránek, 1 extent, `#3400`);
  - `.d80 -w 021.d80 -n /d80/newdisk.d80` vytvoří soubor shodný s `blank_image` a načte ho do B:.
- Opravená chyba, kterou našel ZEsarUX (stav `#81`): parser přepsal ukazatel do příkazové řádky při druhém jménu.
- [hotovo 2026-11-15] Ověřeno uživatelem na skutečném Nextu.

## Fáze 3 — NMI menu (podržení DRIVE)
- **Rozpoznání stisku** (`snap_entry0`, větev SNAP, mimo okna závodu):
  - čte se NextReg `#10` bit 1 (vstup/výstup `#243B`/`#253B`);
  - smyčka s časovým limitem asi 0,5 s při 3,5 MHz (pevný počet průchodů, přerušení jsou vypnutá);
  - tlačítko uvolněno dřív → dnešní SNAP (`jp #0068`); stále drženo → `menu`.
  - Pozor: zápis do portu `#243B` mění vybraný NextReg. Program ho může mít nastavený (copper/NextReg přístup), proto se původní hodnota uloží a obnoví; je čitelná přes `IN` z `#243B`.
- **Stránky** (loader je alokuje a vyplní):
  - **MENU**: kód menu + font 768 B (zkopírovaný z 48K ROM `#3D00` ze stránek `pg_r0`/`pg_r1`, protože při mapovaném MDOS 48K ROM vidět není) + zásobník;
  - **SCR**: záloha `#4000`–`#5AFF` (6912 B) a okraje (BORDCR `#5C48` + poslední zápis do `#FE` se nedá přečíst, takže okraj obnovíme z BORDCR).

  Čísla stránek se uloží do MDOS B (`menu_pg`, `scr_pg`).
- **Vstup do menu** (kód v MDOS B, `#33xx`):
  - uloží všechny registry programu na jeho zásobník (jako handler SNAP);
  - `ld (menu_sp),sp`, `nextreg #57,menu_pg`, `ld sp,#FFxx`, `call #E000`;
  - po návratu namapuje zpět stránku programu (`fix_pg7`), obnoví registry a IFF podle IFF2, nebo pokračuje SNAPem;
  - obrazovka se kopíruje přes slot 2/okno, stejně jako v `sec_op`.
- **Menu (jednoduchý text, klávesnice přes port `#FE`):**
  - `A`/`B` — vložit/vysunout disketu v A:/B: (vysunutá = obraz zůstane v RAM, mechanika hlásí „not ready“);
  - `X` — prohodit A: ↔ B:;
  - `S` — snapshot: obnoví obrazovku a pokračuje SNAP cestou se stejnými registry;
  - `R` — reset (cold start MDOS + 48K);
  - `Space`/`Enter` — návrat do programu.

  Zobrazí jména disků (z boot sektoru, offset 192) a jestli je zapnuté `-w`.
- **Výměna diskety:** MDOS si může držet FAT nebo adresář v bufferech `#3800`/`#3A00`/`#3C00`. Je třeba zjistit, jak MDOS pozná výměnu diskety (bit 7 deskriptoru „motor běží“ / `#3EE2`), a po výměně ji vynutit, např. smazat bit 7 a bit „buffer platný“. To je hlavní riziko fáze. Ověří se v modelu: výměna mezi dvěma `CAT` musí ukázat nový adresář a `SAVE` nesmí zapsat starou FAT na nový disk.
- **Velikost dot příkazu:** dnes 3632 B, limit asi 6,6 K. Menu (~1–1,5 K) se vejde. Kdyby ne, načte se ze souboru `c:/sys/d80/menu.bin`.

**Stav fáze 3:**
- Rozpoznání stisku v `snap_entry0` (MDOS B): při CAPS SHIFT se otevře menu hned; jinak se NextReg `#10` bit 1 (fyzické tlačítko DRIVE, `i_SPKEY_BUTTONS`) čte asi 0,4 s. Uvolnění → SNAP. Pod SP programu se zapíše 10 B, stejně jako u MDOS `#0068` (2 B NMI + 8 B).
- `menu_entry` (MDOS B, `#338F`):
  - registry programu se ukládají do proměnných v MDOS B (`m_af` … `m_hl2`), ne na zásobník programu; IFF podle `LD A,I`;
  - stránka menu jde do slotu 7, SP na její vrchol, `call #E000`;
  - návrat (`EI` podle IFF2), `JP PAGE_OUT`; snapshot jako krátký stisk (`#0067` + `#0068`); reset (pokazit podpis `#3EEF`, `JP #0000`).
- `dot/menu.asm` (762 B, `build/menu.bin`, loader ho přes `INCBIN` kopíruje do vlastní stránky):
  - kopie fontu na `#EC00`, záloha řádků 6–17 obrazovky na `#F000`;
  - jména disků z boot sektoru (stránka obrazu dočasně ve slotu 6);
  - vysunutí = bit 15 `img_secs`; prohození = `cur_drv xor 1` (tabulky zůstávají na místě);
  - po změně: `#3E6E` = `#3E71` = `#FF` a bit 0 deskriptorů (`#3E00`/`#3E0C`) podle toho, jestli mechanika má obraz;
  - při `#3E6C` (neuložená FAT) se změna odmítne.
- Odchylky od plánu:
  - CAPS SHIFT + DRIVE otevře menu vždy, jako záloha pro případ, že bit 1 registru `#10` nehlásí hotkey F10;
  - okraj se nemění, takže ho není třeba obnovovat;
  - zápis NextReg do portu `#243B` se neobnovuje (48K programy NextRegy nepoužívají).
- Testy `TestMenu` (celkem 35 testů prochází):
  - návrat nechá program beze změny (registry, PC, obrazovka, RAM);
  - krátký stisk je dál SNAP; CAPS SHIFT otevře menu;
  - snapshot z menu;
  - prohození, vysunutí a vložení, pak `SAVE` na B:; prohození do prázdné mechaniky;
  - reset.
- ZEsarUX: loader alokuje stránku menu a naplní ji přesně `menu.bin` + fontem; NextReg `#BB` = `#42`.
- [hotovo 2026-11-15] Ověřeno uživatelem na skutečném Nextu (podržení DRIVE menu otevře).
- Úprava po testu (na přání uživatele):
  - vysunutí/vložení (`1`/`2`, bit 15 `img_secs`) odstraněno, při dvou předem načtených obrazech nemá smysl;
  - řádek o `-w` odstraněn;
  - menu vypadá jako menu ZX Spectrum 128 / NextZXOS: okno se sloupci 8–23 (16 znaků) a řádky 7–15, titulek jen „D80“ (jako „128“); rámeček má černý inkoust i v modrých řádcích s disky, černý titulek s duhovými šikmými pruhy (buňky s úhlopříčným znakem, ink = barva vlevo, paper = barva vpravo), modré řádky s disky, bílé tělo s rámečkem a azurový pruh výběru;
  - ovládání kurzorem (`7`/`6`, `Q`/`A`) a `ENTER`, zkratky `X`/`S`/`R`/`SPACE` zůstávají.
- Testy: `test_swap` (zkratka i kurzor), `test_cursor_keys`; celkem 36 testů.

## Model a testy
- `d80tool/nextmmu.py`:
  - dvě mechaniky (`PageMap` pro A: i B:);
  - NextReg `#10` bit 1 (`drive_held` s počtem kroků) a čtení/zápis portu `#243B`;
  - alokované stránky MENU/SCR;
  - `press_snap(hold_steps=…)`.
- `tests/test_d80dot.py`: nové třídy `TestBlank`, `TestDriveB`, `TestMenu`; stávajících 23 testů musí dál projít.
- Náhledy obrazovek menu přes `tools/preview_d80.py` (`--keys` + nová akce `HOLD`).

## Dokumentace
- Nový `docs/plan-d80-drives-menu.md` (tento plán, průběžný stav).
- README (CLI, menu, limity).
- `docs/mdos10-notes.md`: FORMAT layout, inicializace mechanik, výměna diskety.

## Pořadí a odhad
1. Fáze 1, prázdný image: malá, nezávislá, hned použitelná s `-w`.
2. Fáze 2, B:: střední; většina práce je rozdělit tabulky ovladače.
3. Fáze 3, menu: největší; riziko je v cache MDOS při výměně diskety a v délce stisku na skutečném hardwaru (hotkey F10 vs. fyzické tlačítko).

Po každé fázi build (`python tools/build_dot.py`), všechny testy, a potom test na skutečném Nextu, který provede uživatel.

## Ověření end-to-end (skutečný Next)
- `.d80 -w -n /d80/new.d80` → `SAVE *"x"` → reset → `.d80 /d80/new.d80` → `CAT` ukáže `x`.
- `.d80 -w /d80/021.d80 /d80/new.d80` → `LOAD` z A:, `SAVE` na B:, `CAT` obou mechanik.
- Krátký stisk DRIVE → `SNAPSHOTnn` jako dnes. Podržení → menu → `X` → `CAT` ukáže prohozené disky → `Space` → program pokračuje se stejnou obrazovkou.
