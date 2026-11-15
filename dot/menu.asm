; ---------------------------------------------------------------------------
; The D80 menu: hold the DRIVE button (or CAPS SHIFT + DRIVE) while .d80 runs.
;
; Looks like the ZX Spectrum 128 / NextZXOS menu: a window with a black title
; bar and the rainbow stripes, the disks in A: and B:, and a list of items
; with a cyan selection bar.
;
;   cursor up / down (7 / 6, Q / A), ENTER   choose an item
;   X  swap the disks in A: and B:     S  snapshot (as a short press of DRIVE)
;   R  reset (cold start of MDOS and the 48K ROM)     SPACE  back
;
; Runs from its own Next page in MMU slot 7 (#E000), called by menu_entry in
; mdospatch.asm with MDOS paged in, interrupts off and the stack at the top
; of this page.  The 48K ROM is not visible (MDOS is), so the page carries
; its own copy of the ROM font, put there by the loader.  The screen rows
; the window uses are saved here and put back on return.
;
; Out: A = 0 back, 1 snapshot, 2 reset.
; Build: python tools/build_dot.py -> build/menu.bin (included by d80.asm)
; ---------------------------------------------------------------------------

    DEVICE ZXSPECTRUMNEXT
    OPT --zxnext

    INCLUDE "build/patches.inc"         ; MDB_* addresses in MDOS B

FONT        equ #EC00                   ; 48K ROM #3D00-#3FFF (copied by the loader)
SAVE        equ #F000                   ; saved screen rows (ROWS * 288 bytes)
SLOT6_PG    equ 0                       ; 48K page normally in MMU slot 6

; the window
TOP         equ 7                       ; title bar row
ROWS        equ 9                       ; title, A:, B:, 4 items, 2 x padding
LEFT        equ 8                       ; first column (centred)
WIDTH       equ 16                      ; "Swap A: and B:" + margins
ROW_A       equ TOP+1
ROW_B       equ TOP+2
ROW_ITEMS   equ TOP+4
N_ITEMS     equ 4
STRIPES     equ LEFT+WIDTH-6            ; 5 rainbow cells, then one black cell

ATTR_TITLE  equ #47                     ; bright: black paper, white ink
ATTR_BODY   equ #78                     ; bright: white paper, black ink
ATTR_DISK   equ #79                     ; bright: white paper, blue ink
ATTR_SEL    equ #68                     ; bright: cyan paper, black ink

FAT_DIRTY   equ #3E6C                   ; MDOS: FAT buffer changed, not written yet
FAT_DRIVE   equ #3E6E                   ; MDOS: drive of the FAT buffer
DIR_DRIVE   equ #3E71                   ; MDOS: drive of the directory buffer
DESC_A      equ #3E00                   ; MDOS drive descriptors (bit 0: drive exists)
DESC_B      equ #3E0C

    ORG #E000
menu:
    ld hl,SAVE : call copy_area         ; screen -> SAVE
    xor a : ld (sel),a
.draw:
    call draw
.sel:
    call paint_sel
.key:
    call get_key
    cp 'U' : jr z,.up
    cp 'D' : jr z,.down
    cp 13 : jr z,.enter
    cp 'X' : jr z,.swap
    cp 'S' : jr z,.snap
    cp 'R' : jr z,.reset
    jr .back                            ; SPACE
.up:
    ld a,(sel) : and a : jr z,.key
    dec a : ld (sel),a : jr .sel
.down:
    ld a,(sel) : cp N_ITEMS-1 : jr z,.key
    inc a : ld (sel),a : jr .sel
.enter:
    ld a,(sel)
    and a : jr z,.swap
    dec a : jr z,.snap
    dec a : jr z,.reset
.back:
    call restore
    xor a : ret
.swap:
    ld a,(FAT_DIRTY) : and a : jr nz,.key   ; MDOS still has to write a FAT
    ld hl,MDB_CUR_DRV                   ; the tables in use now belong to the other drive
    ld a,(hl) : xor 1 : ld (hl),a
    call disks_changed
    jr .draw
.reset:
    ld a,2 : ret                        ; (the 48K ROM clears the screen)
.snap:
    call restore
    ld a,1 : ret

restore:
    ld de,SAVE : jp copy_back

; MDOS must read FAT and directory again, and a drive "exists" if it has an image
disks_changed:
    ld a,#FF : ld (FAT_DRIVE),a : ld (DIR_DRIVE),a
    ld ix,DESC_A : xor a : call .exists
    ld ix,DESC_B : ld a,1
.exists:
    call set_of
    ld a,(hl) : inc hl : or (hl)
    res 0,(ix+0)
    ret z
    set 0,(ix+0)
    ret

; A = drive -> HL = img_secs of the image in it (the table set in use belongs
; to drive MDB_CUR_DRV, the other set is at MDB_OTH_TAB)
set_of:
    ld hl,MDB_CUR_DRV
    cp (hl)
    ld hl,MDB_IMG_SECS
    ret z
    ld hl,MDB_OTH_TAB
    ret

; ---- screen save ----------------------------------------------------------------
; HL = SAVE: copy the window rows of the screen to it
copy_area:
    ex de,hl
    ld c,TOP
.r: call row_addr                       ; HL = pixel line 0 of row C
    ld b,8
.k: push bc : push hl
    ld bc,32 : ldir
    pop hl : pop bc
    inc h
    djnz .k
    inc c : ld a,c : cp TOP+ROWS : jr nz,.r
    ld hl,#5800+TOP*32 : ld bc,ROWS*32 : ldir
    ret

; DE = SAVE: put the saved rows back
copy_back:
    ld c,TOP
.r: call row_addr
    ld b,8
.k: push bc : push hl
    ex de,hl : ld bc,32 : ldir : ex de,hl
    pop hl : pop bc
    inc h
    djnz .k
    inc c : ld a,c : cp TOP+ROWS : jr nz,.r
    ex de,hl : ld de,#5800+TOP*32 : ld bc,ROWS*32 : ldir
    ret

; C = character row -> HL = its first pixel line
row_addr:
    ld a,c : and #18 : or #40 : ld h,a
    ld a,c : and 7 : rrca : rrca : rrca : ld l,a
    ret

; C = character row -> HL = its attribute at column LEFT
attr_addr:
    ld l,c : ld h,0
    add hl,hl : add hl,hl : add hl,hl : add hl,hl : add hl,hl
    ld de,#5800+LEFT : add hl,de
    ret

; C = row, A = attribute: the window's part of the row
fill_attr:
    push af : call attr_addr : pop af
    ld b,WIDTH
.f: ld (hl),a : inc hl
    djnz .f
    ret

; C = row: blue text, but the frame cells at both ends keep black ink
disk_attr:
    call fill_attr                      ; HL = just after the row's last cell
    dec hl : ld (hl),ATTR_BODY
    ld de,-(WIDTH-1) : add hl,de : ld (hl),ATTR_BODY
    ret

; ---- the window -------------------------------------------------------------------
draw:
    ld c,TOP                            ; clear the window's pixels
.r: call row_addr
    ld a,l : add a,LEFT : ld l,a
    ld b,8
.k: push hl
    ld e,WIDTH
.z: ld (hl),0 : inc hl : dec e : jr nz,.z
    pop hl
    inc h
    djnz .k
    inc c : ld a,c : cp TOP+ROWS : jr nz,.r
    ld c,TOP : ld a,ATTR_TITLE : call fill_attr
    ld c,ROW_A : ld a,ATTR_DISK : call disk_attr
    ld c,ROW_B : ld a,ATTR_DISK : call disk_attr
    ld c,ROW_B+1
.b: ld a,ATTR_BODY : call fill_attr
    inc c : ld a,c : cp TOP+ROWS : jr nz,.b
    ; title and the rainbow
    ld bc,TOP*256+LEFT+1 : ld hl,t_title : call print
    ld c,STRIPES
    ld hl,stripe_attr
.s: push hl
    ld a,(hl)
    push af
    ld b,TOP : push bc : ld c,TOP : call attr_addr : pop bc
    ld a,c : sub LEFT : ld e,a : ld d,0 : add hl,de
    pop af : ld (hl),a                  ; ink = colour on the left, paper = on the right
    ld a,1 : call pchar                 ; the diagonal cell (C advances)
    pop hl : inc hl
    ld a,c : cp STRIPES+5 : jr nz,.s
    ; disks
    ld bc,ROW_A*256+LEFT+1 : ld hl,t_a : call print
    xor a : call disk_text
    ld bc,ROW_B*256+LEFT+1 : ld hl,t_b : call print
    ld a,1 : call disk_text
    ; items
    ld bc,ROW_ITEMS*256+LEFT+1 : ld hl,t_item0 : call print
    ld bc,(ROW_ITEMS+1)*256+LEFT+1 : ld hl,t_item1 : call print
    ld bc,(ROW_ITEMS+2)*256+LEFT+1 : ld hl,t_item2 : call print
    ld bc,(ROW_ITEMS+3)*256+LEFT+1 : ld hl,t_item3 : call print
    ; the frame: left and right lines, bottom line
    ld c,TOP+1
.v: call row_addr
    ld b,8
.vl:push hl
    ld a,l : add a,LEFT : ld l,a
    set 7,(hl)
    ld a,l : add a,WIDTH-1 : ld l,a
    set 0,(hl)
    pop hl
    inc h
    djnz .vl
    inc c : ld a,c : cp TOP+ROWS : jr nz,.v
    ld c,TOP+ROWS-1 : call row_addr
    ld a,h : add a,7 : ld h,a           ; its last pixel line
    ld a,l : add a,LEFT : ld l,a
    ld b,WIDTH
.h: ld (hl),#FF : inc hl
    djnz .h
    ret

; the selected item gets the cyan bar
paint_sel:
    ld c,ROW_ITEMS
.p: ld a,(sel) : add a,ROW_ITEMS : cp c
    ld a,ATTR_SEL : jr z,.s
    ld a,ATTR_BODY
.s: call fill_attr
    inc c : ld a,c : cp ROW_ITEMS+N_ITEMS : jr nz,.p
    ret

; A = drive, B/C = position after "A: ": its disk name
disk_text:
    push bc
    call set_of
    ld e,(hl) : inc hl : ld d,(hl)      ; DE = img_secs
    inc hl : inc hl : inc hl            ; fix_pg2, fix_pg7 -> page_table
    pop bc
    ld a,d : or e
    jr nz,.disk
    ld hl,t_none : jp print
.disk:
    ld a,(hl)                           ; first page of the image: boot sector
    nextreg #56,a
    push bc : ld hl,#C000+192 : ld de,name : ld bc,10 : ldir : pop bc
    nextreg #56,SLOT6_PG
    ld hl,name : jp print

; HL = text (0-terminated), B = row, C = column
print:
    ld a,(hl) : and a : ret z
    inc hl
    push hl
    call pchar
    pop hl
    jr print

; A = character (1 = rainbow diagonal), B = row, C = column (advanced)
pchar:
    push bc
    ld de,diagonal
    cp 1 : jr z,.glyph
    sub 32 : jr nc,.ok
    xor a                               ; control codes as space
.ok:cp 96 : jr c,.in
    ld a,'?'-32
.in:ld l,a : ld h,0
    add hl,hl : add hl,hl : add hl,hl
    ld de,FONT : add hl,de : ex de,hl   ; DE = glyph
.glyph:
    push bc : ld c,b : call row_addr : pop bc
    ld a,l : add a,c : ld l,a
    ld b,8
.l: ld a,(de) : ld (hl),a
    inc de : inc h
    djnz .l
    pop bc
    inc c
    ret

; ---- keyboard ---------------------------------------------------------------------
; wait until no key is down, then for a menu key -> A = 'U', 'D', 13, ' ',
; 'X', 'S' or 'R'
get_key:
.up:
    xor a : in a,(#FE) : and #1F : cp #1F : jr nz,.up
    ld b,0
.d: djnz .d                             ; a little debounce
.l: ld a,#EF : in a,(#FE)               ; 0 9 8 7 6 (CAPS + 7 / 6 = cursor up / down)
    ld c,'U' : bit 3,a : jr z,.got
    ld c,'D' : bit 4,a : jr z,.got
    ld a,#FB : in a,(#FE)               ; Q W E R T
    ld c,'U' : bit 0,a : jr z,.got
    ld c,'R' : bit 3,a : jr z,.got
    ld a,#FD : in a,(#FE)               ; A S D F G
    ld c,'D' : bit 0,a : jr z,.got
    ld c,'S' : bit 1,a : jr z,.got
    ld a,#FE : in a,(#FE)               ; CAPS Z X C V
    ld c,'X' : bit 2,a : jr z,.got
    ld a,#7F : in a,(#FE)               ; SPACE SYM M N B
    ld c,' ' : bit 0,a : jr z,.got
    ld a,#BF : in a,(#FE)               ; ENTER L K J H
    ld c,13 : bit 0,a : jr z,.got
    jr .l
.got:
    ld a,c
    ret

; rainbow: black | red | yellow | green | cyan | black, bright
stripe_attr:
    db #40|(2<<3)|0, #40|(6<<3)|2, #40|(4<<3)|6, #40|(5<<3)|4, #40|(0<<3)|5
diagonal:                               ; ink = left colour, "/" edge
    db #FE, #FC, #F8, #F0, #E0, #C0, #80, #00

t_title:    db "D80", 0                 ; as "128" in the 128 menu
t_a:        db "A: ", 0
t_b:        db "B: ", 0
t_none:     db "(no disk)", 0
t_item0:    db "Swap A: and B:", 0
t_item1:    db "Snapshot", 0
t_item2:    db "Reset", 0
t_item3:    db "Back", 0
sel:        db 0
name:       ds 10
            db 0

    ASSERT $ <= FONT, menu code overlaps the font
    ASSERT SAVE + ROWS*288 <= #FF00, the saved rows reach the menu's stack
    SAVEBIN "build/menu.bin", menu, $-menu
