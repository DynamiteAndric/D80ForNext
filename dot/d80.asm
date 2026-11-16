; ---------------------------------------------------------------------------
; .D80 - boot a Didaktik D40/D80 disk image with MDOS 1.0 on the ZX Spectrum Next
;
;   .d80 [-w] [-r mdos.rom] [-4 48.rom] [-n] a.d80 [[-n] b.d80]
;
;   a.d80 goes into drive A:, the optional b.d80 into drive B:
;
;   -w  write disk changes through to the image files on the SD card
;   -n  create the image that follows as a blank formatted 720K D80 disk first
;       ("File exists" if it is there already)
;
; Loads the MDOS 1.0 ROM (default c:/sys/d80/mdos10.rom) and the 16K ROM:
; with -4 the given file, otherwise the machine menu asks for one of
; c:/machines/next/48.rom (ZX Spectrum 48K) or c:/sys/d80/gama.rom, didm.rom,
; kompakt.rom (Didaktik Gama, M, Kompakt); it
; checks both by CRC32 (rom48_crcs lists the accepted 16K ROMs), applies the
; patches from mdospatch.asm and loads the image into allocated 8K pages.
; Then it turns the Next into a 48K Spectrum with a Didaktik 80 (see
; mdospatch.asm for the DivMMC automap set-up) and cold-starts MDOS.
; The DRIVE button (DivMMC NMI) is the Didaktik SNAP button: MDOS saves
; SNAPSHOTnn to the disk and the program continues.
; There is no way back: leave with a hard reset.  Without -w, writes to the
; disk only change the RAM copy.  With -w the dot command asks esxDOS for the
; card sectors of the image (DISK_FILEMAP), checks them by reading sectors
; back with its own SPI code, and the MDOS driver writes every changed sector
; to the card (sdspi.asm).
;
; Build: python tools/build_dot.py   ->  dot/build/D80 (copy to c:/dot/D80)
; ---------------------------------------------------------------------------

    DEVICE ZXSPECTRUMNEXT
    OPT --zxnext


; esxDOS / NextZXOS API (rst #08 + function byte)
M_P3DOS     equ #94
F_OPEN      equ #9A
F_CLOSE     equ #9B
F_READ      equ #9D
DISK_FILEMAP equ #85
IDE_BANK    equ #01BD
FA_READ     equ #01
FA_WRITE    equ #02
FA_CREATE_NEW equ #04                   ; create, fail if the file exists
F_WRITE     equ #9E
ESX_EEXIST  equ 18
WIN_T       equ 4                       ; progress window: title row
WIN_B       equ 18                      ; ... last row (columns 1-30)

WIN         equ #8000                   ; MMU slot 4 window used while loading
WIN_REG     equ #54
MAX_PAGES   equ 104
MDOS_CRC    equ #545531FA               ; MDOS 1.0 (1991), 14336 bytes
ROM48_CRC   equ #DDEE531F               ; Sinclair 48K ROM
GAMA89_CRC  equ #45C29401               ; Didaktik Gama 80k '89 (Didaktik_Gama_1989.rom)
DIDM92_CRC  equ #57264D4F               ; Didaktik M 1992 (Didaktik_M_1992.rom)
KOMP93_CRC  equ #34752ABA               ; Didaktik Kompakt 1993 (Didaktik_Kompakt_93.rom)

    ORG #2000

start:
    di                                  ; the NextZXOS interrupt handler must not run
                                        ; while one of our pages is in slot 4
    ld (args),hl
    ld (entry_sp),sp
    ld a,#07 : call nr_read : ld (old_turbo),a
    nextreg #07,3                       ; 28 MHz while loading
    ld a,WIN_REG : call nr_read : ld (old_win),a
    ld hl,(entry_sp)                    ; the stack must not be in the window
    ld a,h : and #E0 : cp #80
    ld hl,msg_stack : jp z,fail

    nextreg #7F,#01
    call parse
    jp c,fail
    ld a,(name_img) : and a
    jr nz,.have
    ld hl,msg_usage : call say
    jp restore_ok
.have:
    call screen_init                    ; the progress window
    call choose_rom                     ; no -4: choose the machine

    nextreg #7F,#02
; ---- MDOS ROM -> pages P_A (#0000-#1FFF) and P_B (#2000-#37FF + RAM) -----
    call alloc : ld (pg_a),a
    call alloc : ld (pg_b),a
    call alloc : ld (pg_r0),a
    call alloc : ld (pg_r1),a

    nextreg #7F,#03
    ld hl,msg_rom_m : call say
    ld hl,name_mdos : call fopen
    call crc_init
    ld a,(pg_a) : ld bc,#2000 : call read_page
    ld a,(pg_b) : ld bc,#1800 : call read_page
    ld bc,1 : call read_more            ; the file must end here
    ld a,b : or c : ld hl,msg_mdos : jp nz,fail
    call fclose
    ld hl,MDOS_CRC & #FFFF : ld de,MDOS_CRC >> 16 : call crc_check
    ld hl,msg_mdos : jp nz,fail
    ld hl,msg_ok : call say
    ld a,(pg_b) : nextreg WIN_REG,a     ; clear the 2K RAM at #3800
    ld hl,WIN+#1800 : ld de,WIN+#1801 : ld bc,#07FF : ld (hl),0 : ldir

    nextreg #7F,#04
; ---- machine ROM (48K or Didaktik) -> pages R0, R1 (goes into the alternate ROM) ---------------
    ld hl,msg_rom_4 : call say
    ld hl,name_48 : call fopen
    nextreg #7F,#41
    call crc_init
    ld a,(pg_r0) : ld bc,#2000 : call read_page
    nextreg #7F,#42
    ld a,(pg_r1) : ld bc,#2000 : call read_page
    nextreg #7F,#43
    call fclose
    nextreg #7F,#44
    call rom48_known
    ld hl,msg_48 : jp nz,fail
    ld hl,msg_ok : call say

    nextreg #7F,#05
; ---- patches ----------------------------------------------------------------
    ld a,(pg_a) : nextreg WIN_REG,a
    ld hl,patch_mda : call apply
    ld a,(pg_b) : nextreg WIN_REG,a
    ld hl,patch_mdb : call apply

; ---- the D80 menu page: menu code (#E000) + the 48K ROM font at #EC00 --------------
    nextreg #7F,#0C
    call alloc : ld (pg_menu),a
    ld a,(pg_r1) : nextreg WIN_REG,a    ; font: 48K ROM #3D00-#3FFF
    ld hl,WIN+#1D00 : ld de,sd_buf : ld bc,768 : ldir
    ld a,(pg_menu) : nextreg WIN_REG,a
    ld hl,WIN : ld de,WIN+1 : ld bc,#1FFF : ld (hl),0 : ldir
    ld hl,menu_bin : ld de,WIN : ld bc,menu_len : ldir
    ld hl,sd_buf : ld de,WIN+MENU_FONT : ld bc,768 : ldir
    ld a,(pg_b) : nextreg WIN_REG,a
    ld a,(pg_menu) : ld (WIN+MDB_MENU_PG-#2000),a

; ---- drive A: and B: --------------------------------------------------------------
    ld hl,name_img : ld (cur_name),hl
    ld a,'A' : ld (cur_letter),a
    ld a,(flag_na) : ld (flag_n),a
    ld hl,WIN+MDB_SD_MAP-#2000 : ld (map_win),hl
    call load_drive
    ld hl,WIN+MDB_IMG_SECS-#2000 : ld de,WIN+MDB_SD_N-#2000
    call store_drive

    xor a : ld (n_img),a : ld (n_ext),a  ; drive B: (img_secs 0 = no disk)
    ld hl,0 : ld (img_secs),hl
    ld a,(name_img_b) : and a
    jr z,.no_b
    nextreg #7F,#0B
    ld hl,name_img_b : ld (cur_name),hl
    ld a,'B' : ld (cur_letter),a
    ld a,(flag_nb) : ld (flag_n),a
    ld hl,WIN+MDB_SD_MAP_B-#2000 : ld (map_win),hl
    call load_drive
.no_b:
    ld hl,WIN+MDB_OTH_TAB-#2000 : ld de,WIN+MDB_OTH_SD-#2000
    call store_drive
    jp loaded

; (cur_name) -> image in allocated pages, img_secs, img_pages; with -w also
; the card extents at (map_win) and n_ext, sd_cs, sd_blk (checked)
load_drive:
    ld a,(flag_n) : and a
    call nz,make_blank                  ; -n: create a formatted image first
    nextreg #7F,#06
    ld a,(cur_letter) : call pr_char    ; "A: name [######      ] ok"
    ld hl,msg_colon : call say
    call say_name
    ld hl,(cur_name) : call fopen
    ld a,(flag_w) : and a
    call nz,get_map                     ; must follow the open directly
    call img_steps : call bar_init      ; 45 pages for *.d40, else 90
    ld hl,0 : ld (img_secs),hl
.page:
    ld a,(n_img) : cp MAX_PAGES
    ld hl,msg_big : jp nc,fail
    call alloc
    ld hl,img_pages : ld a,(n_img) : ld e,a : ld d,0 : add hl,de
    ld a,(pg_tmp) : ld (hl),a
    ld hl,n_img : inc (hl)
    ld a,(pg_tmp) : nextreg WIN_REG,a
    ld bc,#2000 : call read_more        ; BC = bytes read
    ld a,b : or c : jr z,.eof
    push bc
    ld a,b : srl a                      ; sectors = BC / 512
    ld hl,(img_secs) : ld e,a : ld d,0 : add hl,de : ld (img_secs),hl
    ld a,(n_img) : dec a
    call z,check_sdos                   ; first page: boot sector signature
    call bar_step
    pop bc
    ld a,b : cp #20 : jr z,.page        ; full page: there may be more
    jr .done
.eof:
    ld hl,n_img : dec (hl)              ; last page stayed empty
    ld hl,n_alloc : dec (hl)
    ld a,(pg_tmp) : call free
.done:
    call fclose
    ld hl,(img_secs) : ld a,h : or l
    ld hl,msg_img : jp z,fail

    ld a,(flag_w) : and a
    call nz,check_map
    jp say_ok

; the loaded drive -> MDOS B: HL = its table (img_secs, fix_pg2, fix_pg7,
; page_table), DE = its sd_n, sd_cs, sd_blk (WIN addresses)
store_drive:
    ld a,(pg_b) : nextreg WIN_REG,a
    ld bc,(img_secs) : ld (hl),c : inc hl : ld (hl),b : inc hl
    ld (hl),10 : inc hl                 ; fix_pg2: 48K bank 5
    ld (hl),1 : inc hl                  ; fix_pg7: 48K bank 0
    push de
    ex de,hl : ld hl,img_pages : ld bc,MAX_PAGES : ldir
    pop hl
    ld a,(n_ext) : ld (hl),a : inc hl
    ld a,(sd_cs) : ld (hl),a : inc hl
    ld a,(sd_blk) : ld (hl),a
    ret

loaded:
    nextreg #7F,#07
; ---- fill the loader data in MDOS B ------------------------------------------
    ld a,(pg_b) : nextreg WIN_REG,a
    ld a,(flag_w) : ld (WIN+MDB_SD_ON-#2000),a
    ; SNAP: NextReg #06 bit 4 (DivMMC NMI from the DRIVE button) is set while
    ; the program runs and cleared while MDOS is paged in
    ld a,#06 : call nr_read
    or #10 : ld (WIN+MDB_NR06_ON-#2000),a
    and #EF : ld (WIN+MDB_NR06_OFF0-#2000),a : ld (WIN+MDB_NR06_OFF8-#2000),a
    ld (s_nr06-STUB+stub_src),a
    ld a,(old_win) : nextreg WIN_REG,a
    ld hl,msg_key : call say            ; wait for a key, then start
.rel: xor a : in a,(#FE) : cpl : and #1F : jr nz,.rel
.prs: xor a : in a,(#FE) : cpl : and #1F : jr z,.prs

; ---- point of no return -------------------------------------------------------
    di
    ; stub labels are run-time addresses: patch the source copy
    ld a,(pg_a) : ld (s_pg_a-STUB+stub_src),a
    ld a,(pg_b) : ld (s_pg_b-STUB+stub_src),a
    ld a,(pg_r0) : ld (s_pg_r0-STUB+stub_src),a
    ld a,(pg_r1) : ld (s_pg_r1-STUB+stub_src),a
    ld a,#09 : call nr_read : or #08 : ld (s_nr09-STUB+stub_src),a   ; bit 3: clear MAPRAM
    ld a,#0A : call nr_read : or #10 : ld (s_nr0a-STUB+stub_src),a   ; bit 4: DivMMC automap on
    nextreg #7F,#E0
    ld hl,stub_src : ld de,STUB : ld bc,stub_len : ldir
    jp STUB

; ---------------------------------------------------------------------------
; Runs from the printer buffer: DivMMC banks and ports are rewritten here.
; ---------------------------------------------------------------------------
STUB equ #5B00
stub_src:
    DISP STUB
    ld sp,#5C00                         ; slot 2 is always bank 5
    nextreg #06,0                       ; (value patched: no DRIVE NMI until MDOS pages out)
s_nr06 equ $-1
    nextreg #7F,#E1
    ld hl,.cont : push hl : retn        ; RETN drops the DivMMC automap
.cont:
    xor a : out (#E3),a                 ; CONMEM off
    nextreg #50,#FF : nextreg #51,#FF   ; ROM in slots 0/1
    nextreg #09,0                       ; (value patched: clear MAPRAM)
s_nr09 equ $-1
    ; alternate ROM = standard 48K ROM, ROM3 locked
    nextreg #8C,#F0                     ; enable, writes go to the alt ROM, lock ROM3
    nextreg WIN_REG,0
s_pg_r0 equ $-1
    ld hl,WIN : ld de,#0000 : ld bc,#2000 : ldir
    nextreg WIN_REG,0
s_pg_r1 equ $-1
    ld hl,WIN : ld de,#2000 : ld bc,#2000 : ldir
    nextreg #8C,#B0                     ; enable, alt ROM replaces reads, lock ROM3
    nextreg #7F,#E2
    ; DivMMC bank 3 = MDOS A, bank 4 = MDOS B
    ld a,#83 : out (#E3),a              ; CONMEM, bank 3 at #2000
    nextreg WIN_REG,0
s_pg_a equ $-1
    ld hl,WIN : ld de,#2000 : ld bc,#2000 : ldir
    ld a,#84 : out (#E3),a              ; CONMEM, bank 4 at #2000
    nextreg WIN_REG,0
s_pg_b equ $-1
    ld hl,WIN : ld de,#2000 : ld bc,#2000 : ldir
    ; automap like the Didaktik: instant on fetch from #0000/#0008 only
    nextreg #B8,#03 : nextreg #B9,#03 : nextreg #BA,#03
    nextreg #BB,#42                     ; #1FF8-#1FFF off-trap (bit 6 = 1 enables it) and
                                        ; instant automap at #0066 on the DRIVE NMI (SNAP)
    nextreg #0A,0
s_nr0a equ $-1
    ld a,#44 : out (#E3),a              ; MAPRAM (bank 3 read-only at #0000) + bank 4
    ; plain 48K memory map, paging locked
    ld bc,#1FFD : xor a : out (c),a
    ld bc,#DFFD : out (c),a
    ld bc,#7FFD : ld a,#30 : out (c),a  ; ROM 1, lock, bank 0
    nextreg #52,10 : nextreg #53,11 : nextreg #54,4
    nextreg #55,5 : nextreg #56,0 : nextreg #57,1
    nextreg #C0,0                       ; normal IM 2 vectors
    nextreg #22,0                       ; no line interrupt
    nextreg #07,0                       ; 3.5 MHz
    im 1
    nextreg #7F,#E3
    jp #0000                            ; automap -> MDOS cold start
    ENT
stub_len equ $-stub_src

; ---------------------------------------------------------------------------
; helpers
; ---------------------------------------------------------------------------

; A = NextReg number -> A = value
nr_read:
    push bc
    ld bc,#243B : out (c),a
    inc b : in a,(c)
    pop bc
    ret

; allocate an 8K page -> A = (pg_tmp) = page; fails with an error message
alloc:
    ld a,(n_alloc) : cp 2*MAX_PAGES+6
    ld hl,msg_mem : jp nc,fail
    ld hl,#0001                         ; H = 0 (ZX memory), L = 1 (allocate)
    push hl : pop ix
    exx
    ld de,IDE_BANK : ld c,7
    rst #08 : db M_P3DOS
    di
    ld hl,msg_mem : jp nc,fail
    ld a,e : ld (pg_tmp),a
    ld hl,allocated : ld a,(n_alloc) : ld c,a : ld b,0 : add hl,bc
    ld a,e : ld (hl),a
    ld hl,n_alloc : inc (hl)
    ld a,e
    ret

; A = page to free (errors ignored)
free:
    ld e,a
    ld hl,#0003                         ; H = 0 (ZX memory), L = 3 (free)
    push hl : pop ix
    exx
    ld de,IDE_BANK : ld c,7
    rst #08 : db M_P3DOS
    di
    ret

; HL = file name -> (handle); fails with an error message
fopen:
    push hl : pop ix
    ld a,'*' : ld b,FA_READ
    rst #08 : db F_OPEN
    di
    jr c,.err
    ld (handle),a
    ret
.err:
    ld hl,msg_open : jp fail

fclose:
    ld a,(handle) : cp #FF : ret z
    rst #08 : db F_CLOSE
    di
    ld a,#FF : ld (handle),a
    ret

; A = page, BC = bytes: read exactly BC bytes into the page, add them to the CRC
read_page:
    nextreg WIN_REG,a
    push bc
    nextreg #7F,#50
    call read_more
    nextreg #7F,#51
    pop hl
    or a : sbc hl,bc
    ld hl,msg_short : jp nz,fail
    ld hl,WIN : jp crc_add              ; BC = length

; BC = max bytes -> BC = bytes read into WIN
read_more:
    ld a,(handle)
    ld hl,WIN : push hl : pop ix
    rst #08 : db F_READ
    di
    ld hl,msg_read : jp c,fail
    ret

; first image page: "SDOS" at offset 204 of the boot sector
check_sdos:
    ld hl,WIN+204 : ld de,sdos : ld b,4
.l: ld a,(de) : cp (hl) : jr nz,.bad
    inc hl : inc de : djnz .l
    ret
.bad:
    ld hl,msg_img : jp fail

; HL = patch table (dw offset, db len, bytes ...; dw #FFFF), page mapped at WIN
apply:
    ld e,(hl) : inc hl : ld d,(hl) : inc hl
    ld a,d : and e : inc a : ret z
    ld a,d : add a,WIN >> 8 : ld d,a
    ld c,(hl) : ld b,0 : inc hl
    ldir
    jr apply

; ---- CRC32 (reflected, poly #EDB88320), table-driven ----------------------------
; The table is built at CRC_TAB (256-aligned, over the code and data from
; `once` on, which are not needed any more) as four 256-byte planes: byte k
; of entry i at CRC_TAB + k*256 + i.  The area is reused for sd_buf after the
; ROM checks.
crc_init:
    ld hl,#FFFF : ld (crc),hl : ld (crc+2),hl
    ld a,(crc_ready) : and a : ret nz   ; the table is built once
    ld c,0                              ; C = entry
.entry:
    ld l,c : ld h,0 : ld de,0           ; DE:HL = C
    ld b,8
.bit:
    srl d : rr e : rr h : rr l
    jr nc,.nx
    ld a,d : xor #ED : ld d,a
    ld a,e : xor #B8 : ld e,a
    ld a,h : xor #83 : ld h,a
    ld a,l : xor #20 : ld l,a
.nx:
    djnz .bit
    push hl
    ld a,l : ld l,c : ld h,CRC_TAB>>8 : ld (hl),a
    pop af : inc h : ld (hl),a          ; (A = old H)
    inc h : ld (hl),e
    inc h : ld (hl),d
    inc c
    jr nz,.entry
    ld a,1 : ld (crc_ready),a
    ret

; HL = data, BC = length.  crc = (crc >> 8) xor T[(crc xor byte) & #FF]
crc_add:
    ld a,b : or c : ret z
    push bc : pop ix                    ; IX = count
    ld de,(crc) : ld bc,(crc+2)         ; E, D, C, B = crc bytes 0..3
.byte:
    ld a,(hl) : inc hl
    xor e
    push hl
    ld l,a : ld h,CRC_TAB>>8
    ld a,(hl) : xor d : ld e,a          ; new byte 0 = byte 1 xor T0
    inc h : ld a,(hl) : xor c : ld d,a  ; new byte 1 = byte 2 xor T1
    inc h : ld a,(hl) : xor b : ld c,a  ; new byte 2 = byte 3 xor T2
    inc h : ld b,(hl)                   ; new byte 3 = T3
    pop hl
    dec ix
    ld a,ixh : or ixl
    jr nz,.byte
    ld (crc),de : ld (crc+2),bc
    ret

; DE:HL = expected CRC -> Z if (crc) xor #FFFFFFFF matches
crc_check:
    ld a,(crc) : cpl : cp l : ret nz
    ld a,(crc+1) : cpl : cp h : ret nz
    ld a,(crc+2) : cpl : cp e : ret nz
    ld a,(crc+3) : cpl : cp d
    ret

; The 16K ROM: the Sinclair 48K ROM or a Didaktik ROM that keeps every 48K ROM
; address MDOS uses (checked with tools/romcompat.py before adding it here)
; -> Z if the CRC is one of rom48_crcs
rom48_known:
    ld ix,rom48_crcs
.next:
    ld l,(ix+0) : ld h,(ix+1) : ld e,(ix+2) : ld d,(ix+3)
    ld a,l : or h : or e : or d : jr z,.no
    call crc_check : ret z
    ld bc,4 : add ix,bc : jr .next
.no:
    inc a                               ; NZ
    ret

rom48_crcs:
    dd ROM48_CRC, GAMA89_CRC, DIDM92_CRC, KOMP93_CRC
    dd 0

; ---- SD write-through (-w) -------------------------------------------------------
; image just opened: card extents -> MDOS B page at SD_MAP, card flags -> sd_cs/sd_blk
get_map:
    nextreg #7F,#20
    ld a,(pg_b) : nextreg WIN_REG,a
    ld hl,(map_win)                     ; extent table of this drive
    push hl : pop ix
    ld de,MDB_SD_MAX
    ld a,(handle)
    rst #08 : db DISK_FILEMAP
    di
    ld hl,msg_fmap : jp c,fail
    ld c,#FE                            ; bit 0: card 1 -> CS #FD
    bit 0,a : jr z,.c0
    ld c,#FD
.c0:ld b,a
    ld a,c : ld (sd_cs),a
    ld a,b : and #02 : ld (sd_blk),a
    ld a,MDB_SD_MAX & #FF : sub e : ld (n_ext),a    ; entries returned (DE <= 128)
    ld hl,msg_fmap : jp z,fail
    ret

; the extents must cover the image, and the first sector of each extent and
; the last image sector must read back from the card as loaded by esxDOS
check_map:
    nextreg #7F,#21
    ld ix,(map_win)
    ld a,(n_ext) : ld b,a
    ld hl,0                             ; HL = first sector of the extent
.ext:
    push bc
    push ix
    push hl
    ld de,(img_secs)
    or a : sbc hl,de
    pop hl : push hl                    ; C: the extent starts inside the image
    call c,verify_sector
    pop hl
    pop ix
    ld a,(pg_b) : nextreg WIN_REG,a     ; the extent table again
    ld e,(ix+4) : ld d,(ix+5)
    pop bc
    add hl,de
    jr c,.last                          ; > 64K sectors: surely covered
    ld de,6 : add ix,de
    djnz .ext
    ld de,(img_secs)                    ; HL = sectors mapped
    or a : sbc hl,de
    ld hl,msg_fmap : jp c,fail          ; too fragmented (more than SD_MAX extents)
.last:
    nextreg #7F,#22
    ld hl,(img_secs) : dec hl
    ; fall through

; HL = logical sector: read it from the card into sd_buf and compare it with
; the RAM copy; fails with msg_sdchk
verify_sector:
    ld (sd_lsn),hl
    call sd_locate
    ld hl,sd_buf : call sd_read
    ld hl,msg_sdchk : jp c,fail
    ld de,sd_buf
    ; fall through

; DE = 512 bytes that must equal sector (sd_lsn) of the RAM copy
cmp_ram:
    call map_lsn
    call cmp512
    ret z
    ld hl,msg_sdchk : jp fail

; HL, DE = 512 bytes each -> Z if equal
cmp512:
    ld bc,512
.c: ld a,(de) : cp (hl) : ret nz
    inc de : inc hl
    dec bc : ld a,b : or c : jr nz,.c
    ret

; (sd_lsn) -> image page in WIN, HL = the sector in WIN (keeps DE)
map_lsn:
    push de
    ld hl,(sd_lsn)
    ld a,l : and #0F : add a,a : add a,WIN>>8
    push af
    ld b,4
.s: srl h : rr l : djnz .s
    ld de,img_pages : add hl,de
    ld a,(hl) : nextreg WIN_REG,a
    pop af : ld h,a : ld l,0
    pop de
    ret

; (sd_lsn) -> sd_arg; fails with msg_sdchk
sd_locate:
    ld a,(pg_b) : nextreg WIN_REG,a
    ld ix,(map_win)
    ld a,(n_ext) : ld b,a
    ld hl,(sd_lsn)
    call sd_find
    ld hl,msg_sdchk : jp c,fail
    ret

; ---- -n: create a blank (formatted) 720K D80 image ------------------------------
; Same layout as blank_image in tools/image.py (what MDOS 1.0 FORMAT writes).
; Fails with "File exists" rather than overwrite anything.
BLANK_SECS  equ 1440                    ; D80: 80 tracks x 2 sides x 9 sectors
BLANK_D40   equ 720                     ; D40 (*.d40): 40 tracks
BLANK_DATA  equ 14                      ; first data sector (after boot, FAT, directory)

make_blank:
    nextreg #7F,#08
    ld hl,msg_new : call say            ; "New disk name [####    ] ok"
    call say_name
    call img_steps                      ; *.d40: a 360K D40 disk, else 720K D80
    push af : call bar_init : pop af    ; (a bar step per 16 data sectors)
    ld hl,BLANK_SECS-BLANK_DATA
    cp 45 : ld a,0 : jr nz,.d80
    ld hl,BLANK_D40-BLANK_DATA : inc a
.d80:
    ld (blk_d40),a : ld (blk_left),hl
    ld hl,(cur_name) : push hl : pop ix
    ld a,'*' : ld b,FA_WRITE|FA_CREATE_NEW
    rst #08 : db F_OPEN
    di
    jr nc,.open
    cp ESX_EEXIST
    ld hl,msg_exists : jp z,fail
    ld hl,msg_open : jp fail
.open:
    ld (handle),a
    ld hl,0 : ld (blk_sec),hl
.sys:                                   ; boot sector, FAT, directory: one by one
    ld hl,(blk_sec) : call blank_sector
    ld hl,sd_buf : ld bc,512 : call fwrite
    ld hl,(blk_sec) : inc hl : ld (blk_sec),hl
    ld a,l : cp BLANK_DATA : jr nz,.sys
    ; data sectors: #E5 in 8K chunks from a temporary page
    nextreg #7F,#09
    call alloc
    nextreg WIN_REG,a
    ld hl,WIN : ld de,WIN+1 : ld bc,#1FFF : ld (hl),#E5 : ldir
.data:
    ld hl,(blk_left) : ld a,h : or l : jr z,.done
    ld de,16 : or a : sbc hl,de
    jr nc,.full
    ld hl,(blk_left) : ld e,l           ; fewer than 16 sectors left
    ld hl,0
.full:
    ld (blk_left),hl
    ld a,e : add a,a : ld b,a : ld c,0  ; BC = sectors * 512
    ld hl,WIN : call fwrite
    call bar_step
    jr .data
.done:
    ld hl,n_alloc : dec (hl)            ; give the temporary page back
    ld a,(pg_tmp) : call free
    ld a,(old_win) : nextreg WIN_REG,a
    call fclose
    jp say_ok

; HL = data, BC = length: write to (handle); fails with msg_write
fwrite:
    push bc
    push hl : pop ix
    ld a,(handle)
    rst #08 : db F_WRITE
    di
    pop hl
    ld de,msg_write : jp c,.bad
    or a : sbc hl,bc                    ; all bytes written?
    ret z
.bad:
    ex de,hl : jp fail

; HL = sector number -> sd_buf = that sector of a blank image (bytes 202-203
; of the boot sector are random, from R)
blank_sector:
    ld a,h : or a : jr nz,.e5
    ld a,l : cp 6 : jr nc,.e5
    and a : jr z,.boot
    ld e,#00 : call .fill               ; FAT sectors 1-5 (341 entries each):
    ld a,l : cp 1 : jr nz,.not1         ; entries 14 .. sectors-1 free
    ld hl,sd_buf : ld bc,21 : ld e,#DD : call .fill_hl   ; entries 0-13 reserved
    jr .last
.not1:
    ld b,a
    ld a,(blk_d40) : and a
    ld a,b : jr z,.d80
    cp 3 : jr c,.last                   ; D40: sector 2 free, 3 up to 719, 4-5 reserved
    ld hl,sd_buf+57 : jr z,.part
    ld e,#DD : jp .fill
.d80:
    cp 5 : jr nz,.last                  ; D80: sectors 2-4 free, 5 up to 1439
    ld hl,sd_buf+114
.part:                                  ; HL .. end of sd_buf reserved
    ex de,hl : ld hl,sd_buf+512 : or a : sbc hl,de
    ld b,h : ld c,l : ex de,hl
    ld e,#DD : jp .fill_hl
.last:
    ld a,#0D : ld (sd_buf+511),a        ; filler nibble of the 341st entry
    ret
.e5:
    ld e,#E5
.fill:
    push hl
    ld hl,sd_buf : ld bc,512
    call .fill_hl
    pop hl
    ret
.fill_hl:                               ; HL = start, BC = length (> 1), E = byte
    ld (hl),e
    ld d,h : ld e,l : inc de
    dec bc
    ldir
    ret
.boot:
    ld e,0 : call .fill
    ld hl,blank_desc : ld de,sd_buf+128 : ld bc,60 : ldir
    ld a,(blk_d40) : and a : jr z,.d80t
    ld a,40 : ld (sd_buf+178),a         ; D40: 40 tracks
.d80t:
    ld hl,sd_buf+192 : ld bc,10 : ld e,' ' : call .fill_hl
    call disk_name                      ; HL = name, B = length (<= 10)
    ld de,sd_buf+192
    ld a,b : and a : jr z,.noname
    ld c,b : ld b,0 : ldir
    jr .id
.noname:
    ld hl,no_name : ld bc,10 : ldir
.id:
    ld a,r : ld (sd_buf+202),a
    ld a,r : rlca : xor #A5 : ld (sd_buf+203),a
    ld hl,sdos : ld de,sd_buf+204 : ld bc,4 : ldir
    ret

; (cur_name) -> HL = file name without directory and extension, B = its length
; (at most 10)
disk_name:
    ld hl,(cur_name) : ld d,h : ld e,l  ; DE = start of the last path component
.find:
    ld a,(hl) : and a : jr z,.got
    inc hl
    cp '/' : jr z,.sep
    cp ':' : jr nz,.find
.sep:
    ld d,h : ld e,l
    jr .find
.got:
    ld h,d : ld l,e : ld b,0
.len:
    ld a,(de) : and a : ret z
    cp '.' : ret z
    ld a,b : cp 10 : ret z
    inc de : inc b
    jr .len

; drive descriptors #3E00 at the time of FORMAT (the most common state on the
; sample disks) and the descriptor of the formatted drive (offset 176)
blank_desc:
    db #01,#18,#50,#09,#00,#18,#5E,#09,#00,#00,#00,#00
    db #01,#18,#50,#09,#00,#18,#5E,#09,#00,#00,#00,#00
    db #01,#18,#5E,#09,#00,#18,#5E,#09,#00,#00,#00,#00
    db #01,#18,#5E,#09,#00,#18,#5E,#09,#00,#00,#00,#00
    db #01,#18,#50,#09,#00,#18,#5E,#09,#00,#00,#00,#00
no_name:    db "NoNameDisk"

    DEFINE SD_READ_ONLY                 ; the loader only reads the card (map check)
    INCLUDE "sdspi.asm"

; ---- argument parsing -----------------------------------------------------------
; [-r mdos] [-4 rom48] image ; tokens end at space, ':', CR or 0
parse:
    ld hl,(args)
    ld a,h : or l : ret z
.next:
    call skip_sp
    call at_end : ret z
    cp '-' : jr nz,.image
    inc hl : ld a,(hl) : inc hl
    or #20
    cp 'w' : jr nz,.not_w
    ld (flag_w),a
    jr .next
.not_w:
    cp 'n' : jr nz,.not_n
    ld (flag_n),a
    jr .next
.not_n:
    ld de,name_mdos : cp 'r' : jr z,.opt
    ld de,name_48 : cp '4' : jr nz,.usage
    ld (flag_4),a
    jr .opt
.usage:
    ld hl,msg_usage : scf : ret
.opt:
    call skip_sp
    call copy_tok
    jr .next
.image:                                 ; first image -> A:, second -> B:
    ld de,name_img : ld bc,flag_na
    ld a,(de) : and a : jr z,.store
    ld de,name_img_b : ld bc,flag_nb
    ld a,(de) : and a
    jr nz,.usage                        ; a third image
.store:
    ld a,(flag_n) : ld (bc),a           ; -n applies to the image that follows it
    xor a : ld (flag_n),a
    call copy_tok
    jr .next

skip_sp:
    ld a,(hl) : cp ' ' : ret nz
    inc hl : jr skip_sp

at_end:
    ld a,(hl)
    and a : ret z
    cp #0D : ret z
    cp ':'
    ret

; HL = token -> DE (max 63 chars, 0-terminated); a "quoted" token may hold spaces and ":"
copy_tok:
    ld b,63
    ld a,(hl) : cp '"' : jr z,.quoted
.c: ld a,(hl)
    cp ' ' : jr z,.e
    cp #0D : jr z,.e
    cp ':' : jr z,.e
    and a : jr z,.e
    ld (de),a : inc hl : inc de
    djnz .c
.e: xor a : ld (de),a
    ret
; "token" may hold spaces and ':' (the browser passes "|")
.quoted:
    inc hl
.q: ld a,(hl)
    cp #0D : jr z,.e
    and a : jr z,.e
    inc hl
    cp '"' : jr z,.e
    ld (de),a : inc de
    djnz .q
    jr .e

; ---- progress report ----------------------------------------------------------
; A clear screen with a window in the style of the 128 menu: black title bar
; with the rainbow, white body.  Text goes through RST #10 with AT positions.
screen_init:
    ld a,7 : out (#FE),a                ; white border, white (not bright) screen
    ld hl,#4000 : ld de,#4001 : ld bc,#17FF : ld (hl),0 : ldir
    inc hl : inc de : ld bc,#2FF : ld (hl),#38 : ldir
    ld c,WIN_T : ld a,#47 : call row_fill   ; title bar: black paper, white ink
.b: inc c : ld a,#78 : call row_fill    ; body: white paper, black ink (bright)
    ld a,c : cp WIN_B : jr nz,.b
    ld hl,#5800+WIN_T*32+24 : ld de,stripe_attr
    ld b,5
.a: ld a,(de) : ld (hl),a : inc hl : inc de
    djnz .a
    ld hl,#4000+((WIN_T&#18)<<8)+((WIN_T&7)<<5)+24
    ld b,8                              ; DE = diagonal (after stripe_attr)
.p: ld a,(de) : push hl
    ld (hl),a : inc l : ld (hl),a : inc l : ld (hl),a : inc l : ld (hl),a : inc l : ld (hl),a
    pop hl : inc h : inc de
    djnz .p
    ld hl,msg_hello : jp say

; C = row, A = attribute: columns 1-30
row_fill:
    push af
    ld l,c : ld h,0 : add hl,hl : add hl,hl : add hl,hl : add hl,hl : add hl,hl
    ld de,#5801 : add hl,de
    pop af
    ld b,30
.f: ld (hl),a : inc hl
    djnz .f
    ret

; ---- progress bar: BAR_W cells from column BAR_C of the current window line ----
BAR_C       equ 16
BAR_W       equ 12

; (cur_name) -> A = steps of the bar: 45 pages for a *.d40 image (360K), else 90 (720K)
img_steps:
    ld hl,(cur_name) : ld de,0          ; DE = the last '.'
.s: ld a,(hl) : and a : jr z,.e
    cp '.' : jr nz,.n
    ld d,h : ld e,l
.n: inc hl
    jr .s
.e: ld a,d : or e
    ld a,90 : ret z
    ex de,hl
    inc hl : ld a,(hl) : or #20 : cp 'd'
    ld a,90 : ret nz
    inc hl : ld a,(hl) : cp '4'
    ld a,90 : ret nz
    inc hl : ld a,(hl) : cp '0'
    ld a,90 : ret nz
    ld a,45
    ret

; A = column -> HL = pixel line 0 of that cell in the current line (uses E)
bar_addr:
    ld e,a
    ld a,(line) : ld l,a
    and #18 : or #40 : ld h,a
    ld a,l : and 7 : rrca : rrca : rrca
    add a,e : ld l,a
    ret

; A = steps for the full bar: draw the empty bar
bar_init:
    ld (bar_total),a
    xor a : ld (bar_acc),a
    ld a,BAR_C : ld (bar_col),a
    call bar_addr
    ld c,0                              ; pixel line
.l: push hl                             ; lines 0 and 7 stay blank (a gap
    ld a,c : and a : jr z,.n            ; between the bars of two lines)
    cp 7 : jr z,.n
    cp 1 : jr z,.full
    cp 6 : jr z,.full
    ld (hl),#80 : inc l                 ; left edge, inside, right edge
    ld d,BAR_W-2
.z: ld (hl),0 : inc l
    dec d : jr nz,.z
    ld (hl),#01
    jr .n
.full:                                  ; top and bottom line
    ld d,BAR_W
.f: ld (hl),#FF : inc l
    dec d : jr nz,.f
.n: pop hl
    inc h : inc c
    ld a,c : cp 8 : jr nz,.l
    ret

; one step done: fill the cells it completes (keeps all registers but AF)
bar_step:
    push hl : push de : push bc
    ld a,(bar_acc) : add a,BAR_W
.w: ld hl,bar_total
    cp (hl) : jr c,.x
    sub (hl) : push af
    call bar_cell
    pop af
    jr .w
.x: ld (bar_acc),a
    pop bc : pop de : pop hl
    ret

; fill the next cell of the bar, if there is one left
bar_cell:
    ld a,(bar_col) : cp BAR_C+BAR_W : ret nc
    call bar_addr
    inc h
    ld b,4
.c: inc h : ld (hl),#FF                 ; pixel lines 2-5
    djnz .c
    ld hl,bar_col : inc (hl)
    ret

; the bar full (an image smaller than 720K), "ok", then the next line
say_ok:
    ld b,BAR_W
.f: push bc : call bar_cell : pop bc
    djnz .f
    ld a,22 : call pr_char.out          ; (.out: a 13 here is a row, not a new line)
    ld a,(line) : call pr_char.out
    ld a,BAR_C+BAR_W+1 : call pr_char.out
    ld hl,msg_ok+1 : jp say

; the image's name (no directory, no extension) and a space
say_name:
    call disk_name
    ld a,b : and a : jr z,.sp
.l: ld a,(hl) : call pr_char
    inc hl
    djnz .l
.sp:ld a,' ' : jr pr_char

; A = character -> RST #10 (the current NextZXOS screen mode), with NextZXOS's
; own page in the window slot; keeps all registers but AF.  13 = next line of
; the window.
pr_char:
    cp 13 : jr nz,.out
    push hl
    ld hl,line : inc (hl)
    ld a,22 : call .out                 ; AT line, 2
    ld a,(hl) : call .out
    pop hl
    ld a,2
.out:
    push hl : push de : push bc : push ix
    ld c,a
    ld a,WIN_REG : call nr_read : push af
    ld a,(old_win) : nextreg WIN_REG,a
    ld a,c : rst #10
    di
    pop af : nextreg WIN_REG,a
    pop ix : pop bc : pop de : pop hl
    ret

; HL = text, last character with bit 7 set
say:
    ld a,(hl) : and #7F : call pr_char
    bit 7,(hl) : inc hl
    jr z,say
    ret


; ---- exits ------------------------------------------------------------------------
; HL = error message (bit-7 terminated); may be reached from nested calls
fail:
    ld (err_msg),hl
    ld a,#7F : call nr_read             ; keep the step marker, bit 7 = failed
    or #80 : nextreg #7F,a
    ld sp,(entry_sp)
    call restore
    call fclose
.f: ld a,(n_alloc) : and a : jr z,.r
    dec a : ld (n_alloc),a
    ld hl,allocated : ld e,a : ld d,0 : add hl,de
    ld a,(hl) : call free
    jr .f
.r: ld hl,(err_msg)
    xor a : scf                         ; A = 0, HL = message: NextZXOS custom error
    ret

restore_ok:
    ld sp,(entry_sp)
    call restore
    and a
    ret

restore:
    ld a,(old_win) : nextreg WIN_REG,a
    ld a,(old_turbo) : nextreg #07,a
    ei
    ret

; ---- data -----------------------------------------------------------------------
msg_usage:  db ".d80 [-w] [-r mdos.rom] [-4 48.rom] [-n] a.d80 [[-n] b.d80", ']'|#80
msg_exists: db "File exist", 's'|#80
msg_hello:  db 22,WIN_T,2, 20,0,21,0,18,0,19,1, 17,0,16,7, "Didaktik D80 MDOS 1.0"
            db 17,7,16,0, 13|#80          ; (AT, INVERSE 0, OVER 0, FLASH 0, BRIGHT 1, colours)
msg_key:    db 22,WIN_B-1,9, "Press any ke", 'y'|#80
choice:     db 0
flag_4:     db 0                        ; -4 given: no machine menu
line:       db WIN_T+1                  ; window row of the text
stripe_attr: db #50, #72, #66, #6C, #45  ; rainbow: ink = colour on the left, paper = on the right
diagonal:   db #FE, #FC, #F8, #F0, #E0, #C0, #80, #00
msg_rom_m:  db "MDOS RO", 'M'|#80
msg_rom_4:  db "Machine RO", 'M'|#80
msg_ok:     db " ok", 13|#80
msg_colon:  db ":", ' '|#80
msg_new:    db "New", ' '|#80             ; (+ a 10-character name: still left of the bar)

msg_write:  db "Write erro", 'r'|#80
msg_stack:  db "Stack in #8000-#9FF", 'F'|#80
msg_mem:    db "Out of memor", 'y'|#80
msg_open:   db "File not foun", 'd'|#80
msg_read:   db "Read erro", 'r'|#80
msg_short:  db "File too shor", 't'|#80
msg_mdos:   db "Not MDOS 1.0 RO", 'M'|#80
msg_48:     db "Unknown machine RO", 'M'|#80
msg_img:    db "Not an MDOS dis", 'k'|#80
msg_big:    db "Image too bi", 'g'|#80
msg_fmap:   db "Image not mappable on SD car", 'd'|#80
msg_sdchk:  db "SD card check faile", 'd'|#80
sdos:       db "SDOS"

name_mdos:  db "c:/sys/d80/mdos10.rom", 0
            ds 64-22
name_48:    db "c:/machines/next/48.rom", 0
            ds 64-24
name_img:   ds 64
name_img_b: ds 64
cur_name:   dw name_img                 ; image being created / loaded
map_win:    dw WIN+MDB_SD_MAP-#2000     ; its extent table in MDOS B (in WIN)
cur_letter: db 'A'                      ; drive being loaded (progress report)
bar_total:  db 1                        ; progress bar: steps for the full bar
bar_acc:    db 0                        ; ... BAR_W per step, a cell per bar_total
bar_col:    db 0                        ; ... next cell to fill
flag_na:    db 0                        ; -n given for image A: / B:
flag_nb:    db 0

args:       dw 0
err_msg:    dw 0
entry_sp:   dw 0
old_turbo:  db 0
old_win:    db 0
handle:     db #FF
crc:        ds 4
crc_ready:  db 0
pg_a:       db 0
pg_b:       db 0
pg_r0:      db 0
pg_r1:      db 0
pg_menu:    db 0
pg_tmp:     db 0
img_secs:   dw 0
n_img:      db 0
n_alloc:    db 0
img_pages:  ds MAX_PAGES
allocated:  ds 2*MAX_PAGES+6
flag_w:     db 0
flag_n:     db 0
blk_sec:    dw 0
blk_left:   dw 0
blk_d40:    db 0                        ; -n: 1 = a 360K D40 disk
n_ext:      db 0
sd_cs:      db #FE
sd_blk:     db 0
sd_arg:     ds 4
sd_lsn:     dw 0

    INCLUDE "build/patches.inc"         ; patch_mda, patch_mdb, MDB_* offsets

MENU_FONT   equ #0C00                   ; = FONT - #E000 in menu.asm
menu_bin:   INCBIN "build/menu.bin"     ; the D80 menu (dot/menu.asm)
menu_len    equ $-menu_bin

; Used only before the ROMs are checked: the CRC table may overwrite it.
once:
; ---- machine menu (no -4): which 16K ROM goes into the alternate ROM ----------
; The items are the first lines of the progress window; the bar stays on the
; choice and the progress report goes on below them.  Keys 1-4 choose
; directly; 6/7 (cursor keys) move the bar, ENTER takes it.  A Didaktik
; choice puts c:/sys/d80/<file> into name_48.
N_ROMS      equ 4
ROM_ROW     equ WIN_T+2                 ; first item row (the first window line)

choose_rom:
    ld a,(flag_4) : and a : ret nz
    ld hl,msg_choose : call say         ; the items, then a blank line
    xor a : ld (choice),a
.loop:
    call .bar
.rel: xor a : in a,(#FE) : cpl : and #1F : jr nz,.rel
.scan:
    ld a,#F7 : in a,(#FE) : cpl : and #0F : jr nz,.digit   ; 1-4
    ld a,#BF : in a,(#FE) : rra : jr nc,.take               ; ENTER
    ld a,#EF : in a,(#FE)
    bit 4,a : jr z,.down                                    ; 6
    bit 3,a : jr z,.up                                      ; 7
    jr .scan
.digit:
    ld e,-1
.dl: inc e : rra : jr nc,.dl
    ld a,e : ld (choice),a
    call .bar
    jr .take
.up:
    ld a,(choice) : and a : jr z,.loop
    dec a : ld (choice),a : jr .loop
.down:
    ld a,(choice) : cp N_ROMS-1 : jr z,.loop
    inc a : ld (choice),a : jr .loop
.take:
    ld a,(choice) : and a : ret z       ; the 48K ROM: name_48 as it is
    add a,a
    ld l,a : ld h,0 : ld de,rom_files-2 : add hl,de
    ld a,(hl) : inc hl : ld h,(hl) : ld l,a
    push hl
    ld hl,rom_dir : ld de,name_48 : ld bc,11 : ldir
    pop hl
.c: ld a,(hl) : ld (de),a : inc hl : inc de
    and a : jr nz,.c
    ret
; the bar on item (choice), the other items white
.bar:
    ld bc,N_ROMS<<8 | ROM_ROW : ld e,0  ; B = items, C = row, E = item
.d: push bc : push de
    ld a,(choice) : cp e
    ld a,#78 : jr nz,.n                 ; body: white paper, black ink
    ld a,#68                            ; the bar: cyan paper
.n: call row_fill
    pop de : pop bc
    inc c : inc e
    djnz .d
    ret

msg_choose: db "1 ZX Spectrum 48K", 13, "2 Didaktik Gama", 13
            db "3 Didaktik M", 13, "4 Didaktik Kompakt", 13, 13|#80
rom_files:  dw name_gama, name_didm, name_kompakt
rom_dir:    db "c:/sys/d80/"
name_gama:  db "gama.rom", 0            ; Didaktik_Gama_1989.rom
name_didm:  db "didm.rom", 0            ; Didaktik_M_1992.rom
name_kompakt: db "kompakt.rom", 0       ; Didaktik_Kompakt_93.rom
end:
; After the ROM checks the same area holds sd_buf (a sector, the font copy).
sd_buf      equ once                    ; 512 bytes (768 for the font copy)
CRC_TAB     equ (once+255) & #FF00      ; CRC table (only while the ROMs are checked)
    ASSERT end <= #3E00, dot command too big
    ASSERT once+1024 <= #3E00, no room for sd_buf
    ASSERT CRC_TAB+1024 <= #3E00, no room for the CRC table
    SAVEBIN "build/D80", start, end-start
