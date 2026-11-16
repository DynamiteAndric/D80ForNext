; ---------------------------------------------------------------------------
; MDOS 1.0 (1991) patches for running Didaktik D40/D80 software on the Next.
;
; The Didaktik pages its ROM in on an opcode fetch from #0000/#0008 and out
; on a fetch from #1700.  The Next's DivMMC automap does the same in
; hardware, so the 48K ROM stays untouched (programs checksum it):
;
;   NextReg #B8 = #03  automap on fetch from #0000 and #0008
;   NextReg #B9 = #03  ... always (not only with ROM3)
;   NextReg #BA = #03  ... instant (the opcode there already comes from MDOS)
;   NextReg #BB = #40  no other entry points; bit 6 = 1 ENABLES the #1FF8-#1FFF
;                      off-trap (zxnext.vhd: delayed_off needs nr_bb(6) = '1')
;   port #E3    = MAPRAM + bank MDB: #0000-#1FFF = DivMMC bank 3 (read-only,
;                 holds MDA), #2000-#3FFF = bank MDB (MDOS #2000-#37FF + RAM)
;
; MDA = MDOS #0000-#1FFF, MDB = MDOS #2000-#37FF + 2K RAM #3800-#3FFF.
; Page-out: every JP #1700 becomes JP #1FF8, where a RET runs as the last
; instruction from DivMMC memory (the off-trap unmaps after that fetch, so
; the RET pops from normal memory, exactly like the RET at 48K #1700).
;
; The floppy driver is replaced by a copy from RAM pages that hold the disk
; image.  Values only known at run time are data bytes at fixed addresses
; (img_secs, page_table, fix_pg2, fix_pg7) filled in by the loader (dot
; command or tools/mdospatch.py).   Build:  python tools/build_dot.py
; ---------------------------------------------------------------------------

    DEVICE ZXSPECTRUMNEXT

    IFNDEF FILL
        DEFINE FILL 0
    ENDIF

; MDOS RAM / routines used by the driver
DRIVE       equ #3E6B           ; current drive number
SAVED_IX    equ #3EE7           ; IX saved by the original sector ops
DESC_SEL    equ #21AC           ; A=drive -> IX=descriptor, Z = not present
PAGE_RET    equ #1FF8           ; RET inside the DivMMC off-trap area
NR_PERIPH2  equ #06             ; bit 4: DivMMC NMI from the DRIVE button (SNAP)

; ===========================================================================
; MDA: MDOS #0000-#1FFF (page 0 of this build)
; ===========================================================================
    MMU 0, 0
    ORG #0000
    BLOCK #2000, FILL

    ; SNAP: the DRIVE button raises a DivMMC NMI, which automaps instantly at
    ; #0066 (NextReg #BB bit 1).  RST 0 enters the MDOS snapshot code exactly
    ; as on the D80 v2 (return address #0067).  The FDC NMI (JP (IX)) is gone
    ; with the replaced driver.  The NMI is only enabled while MDOS is paged
    ; out: every entry (#0000, #0008) turns it off, page_out turns it on.
    ORG #0000 : jp snap_entry0  ; was NOP / JR #0068
    ORG #000B : jp snap_entry8  ; was JP #0215
    ORG #0066 : rst 0           ; was JP (IX)

    ORG #005D : jp PAGE_OUT     ; every JP #1700
    ORG #012C : jp PAGE_OUT
    ORG #0182 : jp PAGE_OUT
    ORG #01C5 : jp PAGE_OUT
    ORG #02C8 : jp PAGE_OUT
    ORG #02E4 : jp PAGE_OUT
    ORG #0373 : jp PAGE_OUT
    ORG #0391 : jp PAGE_OUT
    ORG #0E09 : jp PAGE_OUT
    ORG #0E1B : jp PAGE_OUT
    ORG #1061 : jp PAGE_OUT
    ORG #1968 : jp PAGE_OUT

    ; Any other fetch of #1700 (user code that paged MDOS in and leaves with
    ; JP/CALL #1700) runs RST #38; isr_or_out tells it from an interrupt by
    ; the return address #1701.  The table at #1701 is data, never code.
    ORG #0038 : jp isr_or_out   ; was JP #25CE
    ORG #1700 : rst #38         ; was RET

    ; MDOS code at #1FF8-#1FFF would hit the off-trap: move it.
    ORG #1FE8                   ; was LD A,H / AND 1 / LD H,A / LD A,H / OR L / JR NZ,#1FF8
    ld a,h
    and #01
    ld h,a
    or l
    jp nz,moved_1ff8
    ORG PAGE_RET
    ret
    BLOCK 7, 0

; ===========================================================================
; MDB: MDOS #2000-#37FF + RAM (page 1 of this build): FDC driver replaced
; ===========================================================================
    MMU 1, 1
    ORG #2000
    BLOCK #2000, FILL

; --- drive init (#2216): keep the logic, drop the hardware access
    ORG #2218 : nop : nop       ; OUT (#81),A  (force interrupt)
    ORG #2244 : nop : nop       ; OUT (#87),A
    ORG #227A                   ; 8255 detection / OUT (#91) -> skip
    xor a
    ret

; --- FDC command helpers: "command done", track 0 seen on drives with an image
    ORG #2340
    xor a                       ; status: no error
    ret
    ORG #234B
    ld a,ixl                    ; descriptor #3E00 = drive 0, #3E0C = drive 1
    and a
    jr z,.a
    cp #0C
    ld a,1
    jr z,.a
    inc a                       ; C:, D: (#3E18, ...): never an image
.a: call drv_present
    ld a,#04                    ; bit 2 = track 0
    ret nz
    xor a
    ret

; --- per-sector operations called through #3E63 by the loop at #22B2
    ORG #236A : jp sec_read
    ORG #23BE : jp sec_write
    ORG #23D8
sec_format:                     ; (in place of the original WD Write Track code,
                                ; #23D8-#248D, which nothing else uses)
; The original #23D8 formats a whole track (WD Write Track): B = track, and C
; is not a sector (FORMAT #1394 passes its track count there).  Fill every
; sector of track B with #E5.  -> BC as sec_op: #0300 = OK, else the error
    ld c,0
sf_loop:
    push hl
    push bc
    ld a,2
    call sec_op                 ; (IX = the active drive's descriptor after it)
    ld a,c
    and a
    jr nz,sf_fail
    pop bc
    pop hl
    inc c
    ld a,c
    cp (ix+3)                   ; sectors per track
    jr c,sf_loop
    ld bc,#0300
    ret
sf_fail:
    pop hl                      ; (the saved BC: the error stays in BC)
    pop hl
    ret
    ASSERT $ <= #248E, sec_format overlaps #248E


; --- drive select: no OUT (#83)
    ORG #2567 : nop : nop
; --- disk ready check
    ORG #256D : jp disk_ready
; --- control register write: keep the shadow, drop OUT (#89)
    ORG #25BC
    ld (#3EE9),a
    ret

; ---------------------------------------------------------------------------
; New code in the unused EPROM area
; ---------------------------------------------------------------------------
    ORG #2700

; IM 1 interrupt or RST #38 from #1700 (page-out from user code)
isr_or_out:
    ex (sp),hl
    push af
    ld a,h
    cp #17
    jr nz,isr_mdos
    ld a,l
    dec a
    jr nz,isr_mdos
    pop af
    pop hl                      ; drop the #1701 return address, restore HL
    jp PAGE_OUT                 ; page out, then RET as the 48K ROM at #1700
isr_mdos:
    pop af
    ex (sp),hl
    jp #25CE                    ; original MDOS interrupt handler

; the code that was at #1FF8-#1FFF
moved_1ff8:
    dec d
    jp z,#2000
    ex (sp),hl
    call #22A2
    ex (sp),hl
    jp #2000

; #256D replacement.  In: A = drive.  Out: NZ = disk present (an image in it).
disk_ready:
    push af
    call drv_present            ; (A = H or L of the sector count)
    jr z,dr_none_pop
    pop af                      ; the drive again for DESC_SEL
    push bc
    call DESC_SEL
    pop bc
    set 7,(ix+0)                ; "motor running" as after the original check
    or #FF
    ret
dr_none_pop:
    pop af
    xor a
    ret

; Per-sector operation.  In: HL = buffer, B = logical track (cyl*2+side),
; C = sector 0..spt-1, IX = descriptor.  Out: C = 0 OK, else status (B = class).
; The calling loop saves AF, BC, DE, HL.
;
; The image page is mapped into MMU slot 7 (#E000), or slot 2 (#4000) when
; the buffer reaches into #E000-#FFFF.  While a user page is swapped out,
; interrupts are off and the stack is not used (SP may point into it).
sec_read:
    xor a
    jr sec_op
sec_write:
    ld a,1
    jr sec_op
sec_op:
    ld (op),a
    ld (SAVED_IX),ix
    call act_sel                ; IX, img_secs, page_table, sd_* of drive #3E6B
    jp z,sop_nodisk
    push hl
    ld e,(ix+3)                 ; sectors per track
    ld d,0
    ld hl,0
    ld a,b
    and a
    jr z,sop_addsec
sop_mul:
    add hl,de
    djnz sop_mul
sop_addsec:
    ld e,c
    add hl,de                   ; HL = logical sector
    ld (cur_lsn),hl
    ld de,(img_secs)
    or a
    sbc hl,de
    jp nc,sop_range
    add hl,de
    ld a,l
    and #0F
    add a,a
    ld d,a
    ld e,0                      ; DE = offset in the 8K image page
    ld b,4
sop_shr:
    srl h
    rr l
    djnz sop_shr
    ld bc,page_table
    add hl,bc
    ld a,(hl)
    ld (smc_map+3),a            ; image page
    pop hl                      ; HL = buffer
    ld (cur_buf),hl
    ld a,h
    cp #DE                      ; buffer may reach #E000?
    ld bc,#57E0                 ; B = NextReg (MMU7), C = window base high
    ld a,(fix_pg7)
    jr c,sop_win
    ld bc,#5240                 ; MMU2 at #4000
    ld a,(fix_pg2)
sop_win:
    ld (smc_unmap+3),a          ; page to put back
    ld a,b
    ld (smc_map+2),a
    ld (smc_unmap+2),a
    ld a,d
    or c
    ld d,a                      ; DE = sector in the window
    ld a,(op)
    and a
    jr nz,sop_regs
    ex de,hl                    ; read: HL = window, DE = buffer
sop_regs:
    ld bc,512
    cp 2
    di
smc_map:
    nextreg #57,0
    jr nz,sop_ldir
    ld h,d                      ; format: fill the sector with #E5
    ld l,e
    ld (hl),#E5
    inc de
    dec bc
sop_ldir:
    ldir                        ; write goes to the RAM copy only
smc_unmap:
    nextreg #57,0
    ld a,(op)                   ; write or format: also to the SD card (-w)
    and a
    jr z,sop_ok
    ld a,(sd_on)
    and a
    jr z,sop_ok
    ; on a private stack: the caller's stack may lie inside the buffer (the
    ; snapshot sends #3F80-#417F with MDOS's stack at #3FCx), and the card
    ; must get the bytes the RAM copy got
    ld (sd_sp),sp
    ld sp,SD_STACK
    call sd_put
    ld sp,(sd_sp)               ; (flags kept)
    jr c,sop_wfail
sop_ok:
    ei                          ; the original ops also end with EI
    ld a,(op)                   ; B = class as in the original ops (2 = read,
    and a                       ; 3 = write/format), C = 0 = OK.  FORMAT's
    ld bc,#0200                 ; verify (#13BB) needs B = 2 after a read
    ret z
    ld b,3
    ret
sop_wfail:
    ld bc,#0340                 ; SD write failed: "Disk is write protected (Retry = R)"
    ei
    ret
sop_range:
    pop hl
    ld bc,#0210                 ; record not found
    ei
    ret
sop_nodisk:
    ld bc,#0401                 ; drive not ready (as #24A2)
    ei
    ret

op:         db 0

    ASSERT $ <= #2800, driver code overlaps the loader data

; ---------------------------------------------------------------------------
; Drive B: (and the drive switch).  The driver works on one set of tables,
; img_secs .. page_table, sd_n .. sd_blk and sd_mapp, which belong to drive
; cur_drv; the other drive's set is kept here and swapped in by drv_sel.
; ---------------------------------------------------------------------------
    ORG #2610
oth_tab:    ds 108              ; = img_secs, fix_pg2, fix_pg7, page_table
oth_sd:     ds 3                ; = sd_n, sd_cs, sd_blk
oth_mapp:   dw SD_MAP_B         ; = sd_mapp
cur_drv:    db 0                ; drive whose tables are in use

; A = drive -> NZ if it holds an image (keeps all other registers); only
; A: (0) and B: (1) can
drv_present:
    cp 2
    jr nc,drv_none
    push hl
    ld hl,cur_drv
    cp (hl)
    ld hl,(img_secs)
    jr z,.t
    ld hl,(oth_tab)
.t: ld a,h
    or l
    pop hl
    ret

drv_none:
    xor a                       ; Z: no image
    ret

; The sector ops work on the active drive #3E6B, not on the incoming IX: the
; original ops (DRWSU #2493) select the drive from #3E6B and set IX from it.
; Programs reach the sector loop with any IX (X-MAGAZIN: #3E0C while A: is
; active).  -> IX = its descriptor, its tables in use; NZ if it holds an image.
; Keeps BC, DE, HL.
act_sel:
    push bc
    ld a,(DRIVE)
    call DESC_SEL
    pop bc
    ld a,(DRIVE)

; A = drive (0 = A:, 1 = B:) -> its tables in use; NZ if it holds an image.
; Keeps BC, DE, HL.  Other drives: Z, the tables stay as they are.
drv_sel:
    cp 2
    jr nc,drv_none
    push hl
    ld hl,cur_drv
    cp (hl)
    jr z,.same
    ld (hl),a
    push de
    push bc
    ld hl,img_secs
    ld de,oth_tab
    ld bc,108
    call .swap
    ld hl,sd_n
    ld de,oth_sd
    ld bc,3
    call .swap
    ld hl,sd_mapp
    ld de,oth_mapp
    ld bc,2
    call .swap
    pop bc
    pop de
.same:
    ld hl,(img_secs)
    ld a,h
    or l
    pop hl
    ret
.swap:
    ld a,(de)
    push af
    ld a,(hl)
    ld (de),a
    pop af
    ld (hl),a
    inc hl
    inc de
    dec bc
    ld a,b
    or c
    jr nz,.swap
    ret

    ASSERT $ <= #2700, drive B tables overlap the driver

; ---------------------------------------------------------------------------
; Data filled in by the loader
; ---------------------------------------------------------------------------
    ORG #2800
img_secs:   dw 0                ; number of 512-byte sectors in the image
fix_pg2:    db 10               ; page normally in MMU slot 2 (48K: bank 5)
fix_pg7:    db 1                ; page normally in MMU slot 7 (48K: bank 0)
page_table: ds 104              ; Next page of each 16-sector block
            ORG #2870
sd_on:      db 0                ; 1 = write sectors through to the SD card (-w)
sd_n:       db 0                ; number of extents in SD_MAP
sd_cs:      db #FE              ; SPI chip select of the card holding the image
sd_blk:     db 0                ; card flags bit 1: block addressing
cur_lsn:    dw 0
cur_buf:    dw 0
sd_arg:     ds 4
sd_sp:      dw 0                ; sector op's SP while sd_put runs
sd_mapp:    dw SD_MAP           ; extent table of the current drive
menu_pg:    db 0                ; Next page with the D80 menu (dot/menu.asm)
menu_iff:   db 0                ; menu: 1 = interrupts were on
menu_act:   db 0                ; menu: what to do on return
menu_usp:   dw 0                ; menu: the program's SP
m_af:       dw 0                ; menu: the program's registers
m_bc:       dw 0
m_de:       dw 0
m_hl:       dw 0
m_ix:       dw 0
m_iy:       dw 0
m_af2:      dw 0
m_bc2:      dw 0
m_de2:      dw 0
m_hl2:      dw 0
SD_STACK    equ #2900           ; private stack #28A0-#28FF
    ASSERT $ <= #28A0, loader data overlaps the sd_put stack
SD_MAP      equ #3000           ; DISK_FILEMAP extents of the image file
SD_MAX      equ 128             ; 6 bytes each: up to #32FF
SD_MAP_B    equ #3480           ; the same for drive B: (up to #377F)

    ORG #2900
; write the sector cur_lsn to the SD card (user pages are back, the stack is
; usable, interrupts are still off).  C = error.
sd_put:
    push ix
    ld a,(sd_n)
    ld b,a
    and a
    scf
    jr z,.x
    ld hl,(cur_lsn)
    ld ix,(sd_mapp)
    call sd_find
    jr c,.x
    ld hl,0                     ; format: #E5 fill
    ld a,(op)
    cp 2
    jr z,.w
    ld hl,(cur_buf)
.w: call sd_write
.x: pop ix
    ret

    INCLUDE "sdspi.asm"
    ASSERT $ <= SD_MAP, SD code overlaps the extent table

; ---------------------------------------------------------------------------
; Paging and the SNAP button (after the extent table)
; ---------------------------------------------------------------------------
    ORG SD_MAP + 6*SD_MAX
; Page out to the program: SNAP on, then RET at #1FF8 (off-trap)
PAGE_OUT:
    nextreg NR_PERIPH2,#10      ; value set by the loader: #06 with bit 4 set
nr06_on equ $-1
page_out_j:
    jp PAGE_RET

; MDOS entry through #0008 (RST 8): SNAP off while MDOS runs
snap_entry8:
    nextreg NR_PERIPH2,0        ; value set by the loader: #06 with bit 4 clear
nr06_off8 equ $-1
snap_entry8_j:
    jp #0215

; MDOS entry through #0000: reset, or RST 0 from the SNAP NMI at #0066
snap_entry0:
    nextreg NR_PERIPH2,0        ; value set by the loader
nr06_off0 equ $-1
snap_entry0_x:
    ex (sp),hl                  ; HL = return address
    push af
    ld a,h
    and a
    jr nz,.mdos
    ld a,l
    cp #67
    jr nz,.mdos
    ; SNAP.  An NMI accepted just after MDOS was entered or just before it
    ; leaves must not snapshot MDOS itself: look at the interrupted PC.
    ; Like MDOS's own #0068, this uses at most 6 bytes below the program's SP.
    push de
    ld hl,6
    add hl,sp                   ; DE, AF, HL, -> interrupted PC
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld hl,snap_win
.win:
    ld a,(hl)
    inc hl
    cp e
    ld a,(hl)                   ; (no flags changed until the next CP)
    inc hl
    jr nz,.next
    cp d
    jr z,.busy
.next:
    ld a,l
    cp low snap_win_end
    jr nz,.win
    ; A short press is SNAP.  CAPS SHIFT held, or DRIVE still held after
    ; about 0.4 s (NextReg #10 bit 1), opens the menu instead.
    push bc                     ; (8 bytes below SP, as MDOS's #0068)
    ld a,#FE
    in a,(#FE)
    rra                         ; CAPS SHIFT
    jr nc,.menu
    ld de,HOLD_LOOPS
.hold:
    ld bc,#243B
    ld a,#10
    out (c),a
    inc b
    in a,(c)
    and #02                     ; DRIVE button
    jr z,.snap
    dec de
    ld a,d
    or e
    jr nz,.hold
.menu:
    pop bc
    pop de
    pop af
    pop hl                      ; all registers the program's, (SP) = its PC
    jp menu_entry
.snap:
    pop bc
    pop de
    ld hl,#0067
.mdos:
    pop af
    ex (sp),hl                  ; (SP) = return address, HL restored
    jp #0068                    ; MDOS: reset / snapshot (#02E7 for #0067)
.busy:
    ld a,l                      ; HL = the entry after the match
    cp low snap_win_out + 1
    jr c,.keep
    ld hl,7                     ; MDOS was paging out: resume at PAGE_OUT
    add hl,sp                   ; (SNAP on again)
    ld (hl),high PAGE_OUT
    dec hl
    ld (hl),low PAGE_OUT
.keep:
    pop de
    ld a,i                      ; P/V = IFF2 = interrupt state before the NMI
    jp po,.di
    pop af
    pop hl
    ei
    ret                         ; not RETN: that would unmap MDOS
.di:
    pop af
    pop hl
    ret

; interrupted PCs at which MDOS is already paged in: entering ...
snap_win:
    dw #000B, snap_entry0, snap_entry0_x, snap_entry8, snap_entry8_j
snap_win_out:                   ; ... and leaving
    dw page_out_j, PAGE_RET
snap_win_end:
    ASSERT high snap_win == high snap_win_end, snap_win must not cross a 256-byte page

HOLD_LOOPS  equ 16000           ; x about 90 T = 0.4 s at 3.5 MHz

; ---------------------------------------------------------------------------
; The D80 menu (DRIVE held).  MDOS is paged in, interrupts are off (NMI) and
; SNAP is off.  The menu code runs from its own Next page in MMU slot 7 with
; its stack there (dot/menu.asm); the program's registers stay on its stack.
; ---------------------------------------------------------------------------
menu_entry:                     ; all registers the program's, (SP) = its PC
    ld (m_hl),hl                ; registers -> MDOS B (the program's stack is
    push af                     ; used only as by MDOS's own SNAP handler)
    pop hl
    ld (m_af),hl
    ld a,i                      ; P/V = IFF2 = interrupt state before the NMI
    ld a,0
    jp po,.iff
    inc a
.iff:
    ld (menu_iff),a
    ld (m_bc),bc
    ld (m_de),de
    ld (m_ix),ix
    ld (m_iy),iy
    exx
    ld (m_bc2),bc
    ld (m_de2),de
    ld (m_hl2),hl
    exx
    ex af,af'
    push af
    pop hl
    ld (m_af2),hl
    ex af,af'
    ld (menu_usp),sp
    ld a,(menu_pg)
    nextreg #57,a
    ld sp,0                     ; stack at the top of the menu page
    call MENU_CODE              ; -> A = 0 back, 1 snapshot, 2 reset
    ld (menu_act),a
    ld a,(fix_pg7)
    nextreg #57,a               ; the program's page back before its stack
    ld sp,(menu_usp)
    ld hl,(m_af2)
    push hl
    ex af,af'
    pop af
    ex af,af'
    exx
    ld bc,(m_bc2)
    ld de,(m_de2)
    ld hl,(m_hl2)
    exx
    ld ix,(m_ix)
    ld iy,(m_iy)
    ld bc,(m_bc)
    ld de,(m_de)
    ld a,(menu_act)
    dec a
    jr z,.snap
    dec a
    jr z,.reset
    ld a,(menu_iff)             ; back to the program
    and a
    ld hl,(m_af)
    push hl
    ld hl,(m_hl)
    jr z,.di
    pop af
    ei
    jp PAGE_OUT
.di:
    pop af
    jp PAGE_OUT
.snap:                          ; as a short press: MDOS saves SNAPSHOTnn
    ld hl,#0067
    push hl                     ; (SP) = #0067, then the program's PC
    ld hl,(m_af)
    push hl
    pop af
    ld hl,(m_hl)
    jp #0068
.reset:                         ; cold start of MDOS and the 48K ROM
    ld hl,#3EEF                 ; spoil the warm-start signature
    ld b,8
.r: ld (hl),#55
    inc hl
    djnz .r
    ld sp,#5C00                 ; any RAM: the 48K ROM sets its own stack
    ld hl,0
    push hl                     ; (SP) <> #0067: not a SNAP for snap_entry0
    jp #0000

MENU_CODE   equ #E000

    ASSERT $ <= SD_MAP_B, SNAP code overlaps the drive B extent table

    MMU 0, 0
    SAVEBIN "build/mda.bin", #0000, #2000
    MMU 1, 1
    SAVEBIN "build/mdb.bin", #2000, #2000
