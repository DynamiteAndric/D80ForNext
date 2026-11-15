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
; command or d80tool.mdospatch).   Build:  python tools/build_dot.py
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

; --- FDC command helpers: "command done", track 0 seen only on drive 0
    ORG #2340
    xor a                       ; status: no error
    ret
    ORG #234B
    ld a,ixl                    ; descriptor #3E00 = drive 0, #3E0C = drive 1
    and a
    ld a,#04                    ; bit 2 = track 0
    ret z
    xor a
    ret

; --- per-sector operations called through #3E63 by the loop at #22B2
    ORG #236A : jp sec_read
    ORG #23BE : jp sec_write
    ORG #23D8 : jp sec_format

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

; #256D replacement.  In: A = drive.  Out: NZ = disk present (drive 0 only).
disk_ready:
    and a
    jr nz,dr_none
    push bc
    call DESC_SEL
    pop bc
    set 7,(ix+0)                ; "motor running" as after the original check
    or #FF
    ret
dr_none:
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
sec_format:
    ld a,2
sec_op:
    ld (op),a
    ld (SAVED_IX),ix
    ld a,(DRIVE)
    and a
    jp nz,sop_nodisk
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
    jr nc,sop_range
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
    ld bc,0
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
SD_STACK    equ #2900           ; private stack #2880-#28FF
    ASSERT $ <= #2880, loader data overlaps the sd_put stack
SD_MAP      equ #3000           ; DISK_FILEMAP extents of the image file
SD_MAX      equ 128             ; 6 bytes each: up to #32FF

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
    ld ix,SD_MAP
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

    ASSERT $ <= #3800, SNAP code overlaps the MDOS RAM

    MMU 0, 0
    SAVEBIN "build/mda.bin", #0000, #2000
    MMU 1, 1
    SAVEBIN "build/mdb.bin", #2000, #2000
