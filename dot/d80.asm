; ---------------------------------------------------------------------------
; .D80 - boot a Didaktik D40/D80 disk image with MDOS 1.0 on the ZX Spectrum Next
;
;   .d80 [-w] [-t] [-r mdos.rom] [-4 48.rom] image.d80
;
;   -w  write disk changes through to the image file on the SD card
;   -t  like -w, plus a write self-test on the last sector of the image
;       (written inverted, read back, restored, read back)
;
; Loads the MDOS 1.0 ROM (default c:/sys/d80/mdos10.rom) and the standard
; 48K ROM (default c:/machines/next/48.rom), checks both by CRC32, applies the
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

WIN         equ #8000                   ; MMU slot 4 window used while loading
WIN_REG     equ #54
MAX_PAGES   equ 104
MDOS_CRC    equ #545531FA               ; MDOS 1.0 (1991), 14336 bytes
ROM48_CRC   equ #DDEE531F               ; Sinclair 48K ROM

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
    ld hl,msg_usage : call print
    jp restore_ok
.have:

    nextreg #7F,#02
; ---- MDOS ROM -> pages P_A (#0000-#1FFF) and P_B (#2000-#37FF + RAM) -----
    call alloc : ld (pg_a),a
    call alloc : ld (pg_b),a
    call alloc : ld (pg_r0),a
    call alloc : ld (pg_r1),a

    nextreg #7F,#03
    ld hl,name_mdos : call fopen
    call crc_init
    ld a,(pg_a) : ld bc,#2000 : call read_page
    ld a,(pg_b) : ld bc,#1800 : call read_page
    ld bc,1 : call read_more            ; the file must end here
    ld a,b : or c : ld hl,msg_mdos : jp nz,fail
    call fclose
    ld hl,MDOS_CRC & #FFFF : ld de,MDOS_CRC >> 16 : call crc_check
    ld hl,msg_mdos : jp nz,fail
    ld a,(pg_b) : nextreg WIN_REG,a     ; clear the 2K RAM at #3800
    ld hl,WIN+#1800 : ld de,WIN+#1801 : ld bc,#07FF : ld (hl),0 : ldir

    nextreg #7F,#04
; ---- 48K ROM -> pages R0, R1 (goes into the alternate ROM) ---------------
    ld hl,name_48 : call fopen
    nextreg #7F,#41
    call crc_init
    ld a,(pg_r0) : ld bc,#2000 : call read_page
    nextreg #7F,#42
    ld a,(pg_r1) : ld bc,#2000 : call read_page
    nextreg #7F,#43
    call fclose
    nextreg #7F,#44
    ld hl,ROM48_CRC & #FFFF : ld de,ROM48_CRC >> 16 : call crc_check
    ld hl,msg_48 : jp nz,fail

    nextreg #7F,#05
; ---- patches ----------------------------------------------------------------
    ld a,(pg_a) : nextreg WIN_REG,a
    ld hl,patch_mda : call apply
    ld a,(pg_b) : nextreg WIN_REG,a
    ld hl,patch_mdb : call apply

    nextreg #7F,#06
; ---- disk image -> allocated pages -------------------------------------------
    ld hl,name_img : call fopen
    ld a,(flag_w) : and a
    call nz,get_map                     ; must follow the open directly
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
    ld a,(flag_t) : and a
    call nz,write_test

    nextreg #7F,#07
; ---- fill the loader data in MDOS B ------------------------------------------
    ld a,(pg_b) : nextreg WIN_REG,a
    ld a,(flag_w) : ld (WIN+MDB_SD_ON-#2000),a
    ld a,(n_ext) : ld (WIN+MDB_SD_N-#2000),a
    ld a,(sd_cs) : ld (WIN+MDB_SD_CS-#2000),a
    ld a,(sd_blk) : ld (WIN+MDB_SD_BLK-#2000),a
    ld hl,(img_secs) : ld (WIN+MDB_IMG_SECS-#2000),hl
    ld a,10 : ld (WIN+MDB_FIX_PG2-#2000),a
    ld a,1 : ld (WIN+MDB_FIX_PG7-#2000),a
    ld hl,img_pages : ld de,WIN+MDB_PAGE_TABLE-#2000 : ld bc,MAX_PAGES : ldir
    ; SNAP: NextReg #06 bit 4 (DivMMC NMI from the DRIVE button) is set while
    ; the program runs and cleared while MDOS is paged in
    ld a,#06 : call nr_read
    or #10 : ld (WIN+MDB_NR06_ON-#2000),a
    and #EF : ld (WIN+MDB_NR06_OFF0-#2000),a : ld (WIN+MDB_NR06_OFF8-#2000),a
    ld (s_nr06-STUB+stub_src),a
    ld a,(old_win) : nextreg WIN_REG,a

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
    ld a,(n_alloc) : cp MAX_PAGES+4
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

; ---- CRC32 (reflected, poly #EDB88320) ----------------------------------------
crc_init:
    ld hl,#FFFF : ld (crc),hl : ld (crc+2),hl
    ret

; HL = data, BC = length
crc_add:
    ld a,b : or c : ret z
    push bc
    ld a,(hl) : inc hl
    push hl
    ld hl,(crc) : ld de,(crc+2)
    xor l : ld l,a
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
    ld (crc),hl : ld (crc+2),de
    pop hl : pop bc
    dec bc
    jr crc_add

; DE:HL = expected CRC -> Z if (crc) xor #FFFFFFFF matches
crc_check:
    ld a,(crc) : cpl : cp l : ret nz
    ld a,(crc+1) : cpl : cp h : ret nz
    ld a,(crc+2) : cpl : cp e : ret nz
    ld a,(crc+3) : cpl : cp d
    ret

; ---- SD write-through (-w) -------------------------------------------------------
; image just opened: card extents -> MDOS B page at SD_MAP, card flags -> sd_cs/sd_blk
get_map:
    nextreg #7F,#20
    ld a,(pg_b) : nextreg WIN_REG,a
    ld hl,WIN+MDB_SD_MAP-#2000
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
    ld ix,WIN+MDB_SD_MAP-#2000
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
    ld ix,WIN+MDB_SD_MAP-#2000
    ld a,(n_ext) : ld b,a
    ld hl,(sd_lsn)
    call sd_find
    ld hl,msg_sdchk : jp c,fail
    ret

; -t: write the last image sector inverted, read it back, restore it, read back
write_test:
    nextreg #7F,#23
    ld hl,(img_secs) : dec hl : ld (sd_lsn),hl
    call sd_locate
    ld hl,sd_buf : call sd_read         ; the original (equal to the RAM copy)
    jr c,.bad
    call invert
    ld hl,sd_buf : call sd_write
    jr c,.bad_restore
    ld hl,sd_buf2 : call sd_read
    jr c,.bad_restore
    ld hl,sd_buf : ld de,sd_buf2 : call cmp512
    jr nz,.bad_restore
    nextreg #7F,#24
    call invert
    ld hl,sd_buf : call sd_write
    jr c,.bad
    ld hl,sd_buf2 : call sd_read
    jr c,.bad
    ld de,sd_buf2 : call cmp_ram
    nextreg #7F,#25
    ret
.bad_restore:
    call invert                         ; try to put the original back
    ld hl,sd_buf : call sd_write
.bad:
    ld hl,msg_sdwr : jp fail

invert:
    ld hl,sd_buf : ld bc,512
.i: ld a,(hl) : cpl : ld (hl),a
    inc hl : dec bc : ld a,b : or c : jr nz,.i
    ret

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
    cp 't' : jr nz,.not_t
    ld (flag_t),a
    ld (flag_w),a
    jr .next
.not_t:
    cp 'w' : jr nz,.not_w
    ld (flag_w),a
    jr .next
.not_w:
    ld de,name_mdos : cp 'r' : jr z,.opt
    ld de,name_48 : cp '4' : jr z,.opt
    ld hl,msg_usage : scf : ret
.opt:
    call skip_sp
    call copy_tok
    jr .next
.image:
    ld de,name_img
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

; HL = text (last char has bit 7 set)
print:
    ld a,(hl) : and #7F : rst #10
    bit 7,(hl) : inc hl
    jr z,print
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
msg_usage:  db ".d80 [-w] [-t] [-r mdos.rom] [-4 48.rom] image.d8", '0'|#80
msg_stack:  db "Stack in #8000-#9FF", 'F'|#80
msg_mem:    db "Out of memor", 'y'|#80
msg_open:   db "File not foun", 'd'|#80
msg_read:   db "Read erro", 'r'|#80
msg_short:  db "File too shor", 't'|#80
msg_mdos:   db "Not MDOS 1.0 RO", 'M'|#80
msg_48:     db "Not a 48K RO", 'M'|#80
msg_img:    db "Not an MDOS dis", 'k'|#80
msg_big:    db "Image too bi", 'g'|#80
msg_fmap:   db "Image not mappable on SD car", 'd'|#80
msg_sdchk:  db "SD card check faile", 'd'|#80
msg_sdwr:   db "SD write test faile", 'd'|#80
sdos:       db "SDOS"

name_mdos:  db "c:/sys/d80/mdos10.rom", 0
            ds 64-22
name_48:    db "c:/machines/next/48.rom", 0
            ds 64-24
name_img:   ds 64

args:       dw 0
err_msg:    dw 0
entry_sp:   dw 0
old_turbo:  db 0
old_win:    db 0
handle:     db #FF
crc:        ds 4
pg_a:       db 0
pg_b:       db 0
pg_r0:      db 0
pg_r1:      db 0
pg_tmp:     db 0
img_secs:   dw 0
n_img:      db 0
n_alloc:    db 0
img_pages:  ds MAX_PAGES
allocated:  ds MAX_PAGES+4
flag_w:     db 0
flag_t:     db 0
n_ext:      db 0
sd_cs:      db #FE
sd_blk:     db 0
sd_arg:     ds 4
sd_lsn:     dw 0

    INCLUDE "build/patches.inc"         ; patch_mda, patch_mdb, MDB_* offsets

end:
sd_buf      equ end                     ; 2 x 512 bytes after the binary
sd_buf2     equ end+512
    ASSERT end+1024 <= #3E00, dot command too big
    SAVEBIN "build/D80", start, end-start
