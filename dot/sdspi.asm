; ---------------------------------------------------------------------------
; Raw SD card access over the Next SPI ports.  This file is included by both
; mdospatch.asm (writes at MDOS run time) and d80.asm (map check, self-test).
;
; The includer defines these variables:
;   sd_cs   db  chip select value: #FE = SD card 0, #FD = SD card 1
;   sd_blk  db  0 = byte-addressed card (SD v1/MMC), else block-addressed (SDHC)
;   sd_arg  ds 4  card address of the next command (little endian)
;
; The card was initialised by NextZXOS; CRC checking is off (SPI mode default).
; Every wait has a time-out, so a missing or broken card cannot hang the Next.
; Routines return NC = OK, C = error.  They use AF, BC, DE, HL (sd_find: IX).
; Reads work whether port #EB returns the byte of the current or of the
; previous exchange: every loop reads until a known value appears.
; ---------------------------------------------------------------------------

SD_CS_PORT  equ #E7
SD_SPI      equ #EB

; HL = logical sector, IX = extent table (4-byte card address, 2-byte sector
; count per entry, as from DISK_FILEMAP), B = number of entries (> 0)
; -> sd_arg = card address of that sector.  C if the sector is not mapped.
sd_find:
    ld e,(ix+4)
    ld d,(ix+5)
    or a
    sbc hl,de
    jr c,.found                 ; sector < count: it is in this extent
    ld de,6
    add ix,de
    djnz sd_find
    scf
    ret
.found:
    add hl,de                   ; HL = sector offset inside the extent
    ld de,0                     ; DE:HL = offset in card units
    ld a,(sd_blk)
    and a
    jr nz,.add
    ld e,h                      ; byte addressing: offset * 512
    ld h,l
    ld l,0
    sla h
    rl e
    rl d
.add:
    ld a,(ix+0)
    add a,l
    ld (sd_arg),a
    ld a,(ix+1)
    adc a,h
    ld (sd_arg+1),a
    ld a,(ix+2)
    adc a,e
    ld (sd_arg+2),a
    ld a,(ix+3)
    adc a,d
    ld (sd_arg+3),a
    or a
    ret

; select the card and wait until it is ready (MISO high)
sd_begin:
    ld a,#FF
    out (SD_SPI),a              ; 8 clocks with CS high
    ld a,(sd_cs)
    out (SD_CS_PORT),a
    ld de,0
.w: in a,(SD_SPI)
    cp #FF
    ret z                       ; Z, NC
    dec de
    ld a,d
    or e
    jr nz,.w
    scf
    ret

; deselect the card (keeps flags)
sd_end:
    push af
    ld a,#FF
    out (SD_CS_PORT),a
    out (SD_SPI),a
    pop af
    ret

; A = command byte (#40 + n), argument in sd_arg -> A = R1, Z if R1 = 0
sd_cmd:
    out (SD_SPI),a
    ld hl,sd_arg+3
    ld b,4
.a: ld a,(hl)
    out (SD_SPI),a
    dec hl
    djnz .a
    ld a,#FF
    out (SD_SPI),a              ; CRC byte (not checked in SPI mode)
    ld b,16
.r: in a,(SD_SPI)
    bit 7,a
    jr z,.ok
    djnz .r
    ret                         ; NZ: no response
.ok:
    and a
    ret

; CMD17: read the sector at sd_arg into HL (512 bytes)
sd_read:
    push hl
    call sd_begin
    jr c,sd_fail_pop
    ld a,#51
    call sd_cmd
    pop hl
    jr nz,sd_fail
    ld de,0
.t: in a,(SD_SPI)               ; wait for the data token
    cp #FE
    jr z,.data
    cp #FF
    jr nz,sd_fail               ; error token
    dec de
    ld a,d
    or e
    jr nz,.t
    jr sd_fail
.data:
    ld bc,SD_SPI                ; B = 0: 256 bytes per INIR
    inir
    inir
    in a,(SD_SPI)               ; CRC
    in a,(SD_SPI)
    call sd_end
    or a
    ret

sd_fail_pop:
    pop hl
sd_fail:
    call sd_end
    scf
    ret

; CMD24: write 512 bytes from HL to the sector at sd_arg; HL = 0 writes
; 512 x #E5 (a freshly formatted sector)
sd_write:
    push hl
    call sd_begin
    jr c,sd_fail_pop
    ld a,#58
    call sd_cmd
    pop hl
    jr nz,sd_fail
    in a,(SD_SPI)               ; one byte gap (Nwr), clocked by a read: some
                                ; emulators count every written byte as data
    ld a,#FE
    out (SD_SPI),a              ; start token
    ld a,h
    or l
    jr z,.fill
    ld bc,SD_SPI
    otir
    otir
    jr .crc
.fill:
    ld b,0
    ld a,#E5
.f: out (SD_SPI),a
    out (SD_SPI),a
    djnz .f
.crc:
    ld a,#FF
    out (SD_SPI),a
    out (SD_SPI),a
    ld b,16
.d: in a,(SD_SPI)               ; data response xxx0sss1
    cp #FF
    jr nz,.resp
    djnz .d
    jr sd_fail
.resp:
    and #1F
    cp #05                      ; accepted
    jr nz,sd_fail
    ld c,16                     ; busy (MISO low) for up to 16 x 64K reads
    ld de,0
.b: in a,(SD_SPI)
    and a
    jr nz,.done
    dec de
    ld a,d
    or e
    jr nz,.b
    dec c
    jr nz,.b
    jr sd_fail
.done:
    call sd_end
    or a
    ret
