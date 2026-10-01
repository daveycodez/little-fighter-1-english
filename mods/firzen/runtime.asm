 ; Resident runtime overlay loader. Linked into MODS.COM at build time.
; Header exports are absolute offsets in the resident CS segment.
 dw rt_dispatch,rt_queue,rt_firzen,rt_patch_target,rt_balanced,rt_free
 dw rt_cheap,rt_easy,rt_irq65,rt_info,rt_cfg_search
rt_firzen db 0
rt_patch_target db 0
rt_balanced db 0
rt_free db 0
rt_cheap db 0
rt_easy db 0
rt_info:
rt_running db 0
rt_kind db 0
rt_image dw 0
rt_ds dw 0
rt_charbase dw 0
rt_header dw 0
rt_parent_ss dw 0
rt_parent_sp dw 0
rt_parent_psp dw 0
rt_child_psp dw 0
rt_file_ds dw 0
rt_file_dx dw 0
rt_error dw 0
rt_busy db 0
rt_execblock times 22 db 0
rt_queued_len dw 0
rt_queuebuf times 4096 db 0
rt_modes times 8 db 0
rt_ticks times 8 dw 0
rt_motion_x times 30 dw 0
rt_motion_frac times 30 dw 0
rt_motion_age times 30 dw 0
rt_native_crop dw 072eh,0
rt_native_draw dw 0298h,0
rt_native_menu_draw dw 02a1h,0
rt_native_freeze dw 0cad8h,0 ; file140A8 - (1400+61D0)
rt_native_fire dw 0c0e4h,0  ; file136B4 - (1400+61D0)
rt_native_packet dw 02f0ah,0
rt_site_arg db 0
rt_site_svc db 0
rt_site_file dd 0
rt_cannon_grh:
 incbin CANNON_PATH

; AL=flag,CX:DX=file offset,SI=on bytes,DI=off bytes,BL=size.
; Queue selected bytes in resident memory. No DOS write is performed.
rt_queue:
 pusha
 push ds
 push es
 cmp al,1
 je .selected
 mov si,di
.selected:
 xor bh,bh
 mov ax,bx
 add ax,6
 mov di,[cs:rt_queued_len]
 add ax,di
 cmp ax,4096
 ja .full
 push cs
 pop es
 push ax
 mov al,[cs:rt_patch_target]
 mov [es:rt_queuebuf+di],al
 mov [es:rt_queuebuf+di+1],bl
 mov [es:rt_queuebuf+di+2],dx
 mov [es:rt_queuebuf+di+4],cx
 mov cx,bx
 add di,rt_queuebuf+6
 cld
 rep movsb
 pop ax
 mov [cs:rt_queued_len],ax
.full:
 pop es
 pop ds
 popa
 ret

 ; SI=needle,DI=config,CX=length. Match active whole configuration lines.
rt_cfg_search:
 push bx
 push cx
 push dx
 push di
 push si
 push bp
 mov bx,si
 mov bp,di
 add bp,cx
.line:
 cmp di,bp
 jae .missing
 cmp byte [di],20h
 je .blank
 cmp byte [di],9
 jne .start
.blank:
 inc di
 jmp .line
.start:
 cmp byte [di],'#'
 je .skip
 cmp byte [di],';'
 je .skip
 mov si,bx
.compare:
 lodsb
 test al,al
 jz .boundary
 cmp di,bp
 jae .missing
 cmp al,[di]
 jne .skip
 inc di
 jmp .compare
.boundary:
 cmp di,bp
 jae .found
 mov al,[di]
 cmp al,13
 je .found
 cmp al,10
 je .found
 cmp al,20h
 je .found
 cmp al,9
 je .found
 cmp al,'#'
 je .found
 cmp al,';'
 je .found
.skip:
 cmp di,bp
 jae .missing
 mov al,[di]
 inc di
 cmp al,10
 jne .skip
 jmp .line
.missing:
 xor al,al
 jmp .return
.found:
 mov al,1
.return:
 pop bp
 pop si
 pop di
 pop dx
 pop cx
 pop bx
 ret

; Find the last filename component at DS:DX. Preserve DX.
rt_basename:
 mov si,dx
 mov di,dx
.scan:
 lodsb
 test al,al
 jz .done
 cmp al,5ch
 je .new
 cmp al,'/'
 je .new
 cmp al,':'
 jne .scan
.new:
 mov di,si
 jmp .scan
.done:
 mov si,di
 ret

; All unhandled calls chain to the original DOS vector.
rt_dispatch:
 cmp ax,4b00h
 je rt_check_exec
 cmp ah,3dh
 je rt_check_open
rt_chain:
 jmp far [cs:OLD21]

rt_check_exec:
 cmp byte [cs:rt_busy],0
 jne rt_chain
 pusha
 call rt_basename
 mov ax,[si]
 and ax,0dfdfh
 cmp ax,'ST'
 je .start
 cmp ax,'CO'
 je .contest
 cmp ax,'FI'
 jne .no
 mov ax,[si+2]
 and ax,0dfdfh
 cmp ax,'GH'
 jne .no
 mov al,[si+4]
 and al,0dfh
 cmp al,'T'
 jne .no
 mov byte [cs:rt_kind],2
 mov word [cs:rt_header],1400h
 jmp .yes
.start:
 mov ax,[si+2]
 and ax,0dfdfh
 cmp ax,'AR'
 jne .no
 mov al,[si+4]
 and al,0dfh
 cmp al,'T'
 jne .no
 mov byte [cs:rt_kind],1
 mov word [cs:rt_header],0e00h
 jmp .yes
.contest:
 cmp byte [cs:rt_firzen],1
 jne .no
 mov ax,[si+2]
 and ax,0dfdfh
 cmp ax,'NT'
 jne .no
 mov al,[si+4]
 and al,0dfh
 cmp al,'E'
 jne .no
 mov ax,[si+5]
 and ax,0dfdfh
 cmp ax,'ST'
 jne .no
 add si,2
 mov byte [cs:rt_kind],3
 mov word [cs:rt_header],0c00h
.yes:
 cmp byte [si+5],0
 je .validname
 cmp byte [si+5],'.'
 jne .no
 mov ax,[si+6]
 and ax,0dfdfh
 cmp ax,'EX'
 jne .no
 mov al,[si+8]
 and al,0dfh
 cmp al,'E'
 jne .no
 cmp byte [si+9],0
 jne .no
.validname:
 popa
 jmp rt_exec
.no:
 popa
 jmp rt_chain

; While a Firzen-enabled game is running, substitute only its own resources.
rt_check_open:
 cmp byte [cs:rt_firzen],1
 jne rt_chain
 cmp byte [cs:rt_running],1
 jne rt_chain
 pusha
 call rt_basename
 mov di,rt_names
.next:
 cmp byte [cs:di],0
 je .no
 push si
 mov bx,di
.cmp:
 mov al,[si]
 cmp al,'a'
 jb .upper
 cmp al,'z'
 ja .upper
 sub al,20h
.upper:
 cmp al,[cs:bx]
 jne .skip
 inc si
 inc bx
 cmp byte [cs:bx],0
 jne .cmp
 cmp byte [si],0
 jne .skip
 add bx,1
 pop si
 mov [cs:rt_rewrite_name],bx
 popa
 push ds
 push cs
 pop ds
 push dx
 mov dx,[cs:rt_rewrite_name]
 pushf
 call far [cs:OLD21]
 pop dx
 pop ds
 ; Copy carry/error to the original interrupt frame.
 push bp
 mov bp,sp
 jc .error
 and word [ss:bp+6],0fffeh
 pop bp
 iret
.error:
 or word [ss:bp+6],1
 pop bp
 iret
.skip:
 pop si
.skipold:
 cmp byte [cs:di],0
 je .skipnew
 inc di
 jmp .skipold
.skipnew:
 inc di
.newend:
 cmp byte [cs:di],0
 je .advance
 inc di
 jmp .newend
.advance:
 inc di
 jmp .next
.no:
 popa
 jmp rt_chain
rt_rewrite_name dw 0
rt_names:
 db 'DATA.DAT',0,'FZDATA.DAT',0
 db 'HEAD.GRH',0,'FZHEAD.GRH',0
 db 'HEAD2.GRH',0,'FZHEAD2.GRH',0
 db 'FACE.GRH',0,'FZFACE.GRH',0
 db 'ACT2.GRH',0,'FZACT2.GRH',0
 db 'SUPERL.GRH',0,'FZSUPER.GRH',0
 db 0

; Load but do not execute. Apply overlays, then enter the child. The original
; caller's interrupt context remains on its stack until child termination.
rt_exec:
 pusha
 push ds
 push es
 mov [cs:rt_parent_ss],ss
 mov [cs:rt_parent_sp],sp
 mov [cs:rt_file_ds],ds
 mov [cs:rt_file_dx],dx
 mov byte [cs:rt_busy],1
 mov ah,62h
 pushf
 call far [cs:OLD21]
 mov [cs:rt_parent_psp],bx
 mov bp,sp
 mov ax,[ss:bp]
 mov si,[ss:bp+12]
 mov ds,ax
 push cs
 pop es
 mov di,rt_execblock
 mov cx,7
 cld
 rep movsw
 mov ax,[cs:rt_file_ds]
 mov ds,ax
 mov dx,[cs:rt_file_dx]
 mov bx,rt_execblock
 mov ax,4b01h
 pushf
 call far [cs:OLD21]
 jc rt_exec_error
 mov ah,62h
 pushf
 call far [cs:OLD21]
 mov [cs:rt_child_psp],bx
 mov ax,bx
 add ax,10h
 mov [cs:rt_image],ax
 mov dx,0f35h
 mov cx,4000h
 cmp byte [cs:rt_kind],1
 je .layout
 mov dx,2463h
 mov cx,5800h
 cmp byte [cs:rt_kind],2
 je .layout
 mov dx,0d06h
 mov cx,3400h
.layout:
 mov [cs:rt_charbase],cx
 add ax,dx
 mov [cs:rt_ds],ax
 mov byte [cs:rt_running],1
 call rt_apply_legacy
 cmp byte [cs:rt_firzen],1
 jne .enter
 call rt_apply_firzen
 ; Reserve table storage by moving the initial stack above the extension.
 ; Borland's startup derives its heap boundary from SS, keeping it separate.
 mov bx,[cs:rt_execblock+10h]
 mov es,bx
 mov di,[cs:rt_execblock+0eh]
 mov dx,[es:di]
 mov ax,0c0h
 cmp byte [cs:rt_kind],2
 je .stackdelta
 mov ax,100h
 cmp byte [cs:rt_kind],1
 je .stackdelta
 mov ax,60h
.stackdelta:
 add [cs:rt_execblock+10h],ax
 add bx,ax
 mov es,bx
 mov [es:di],dx
 mov ax,[cs:rt_ds]
 mov es,ax
 mov di,[cs:rt_charbase]
 xor ax,ax
 mov cx,1400
 cmp byte [cs:rt_kind],3
 jne .clearprivate
 mov cx,100h
.clearprivate:
 cld
 rep stosb
 ; Native menu portraits and AI priorities have independent 12-entry arrays.
 ; Add slot12 without letting it overwrite adjacent keyboard/score globals.
 mov ax,[cs:rt_ds]
 mov ds,ax
 cmp byte [cs:rt_kind],3
 je .seedcontest
 mov si,014dh
 mov di,44a0h
 mov cx,12
 cmp byte [cs:rt_kind],1
 je .seed
 mov si,00d8h
 mov di,5c60h
.seed:
 rep movsw
 cmp byte [cs:rt_kind],1
 jne .priorityseeded
 mov word [es:di],12
 mov si,0137h
 mov di,4480h
 mov cx,12
 rep movsw
.priorityseeded:
 mov ax,12
 cmp byte [cs:rt_kind],1
 je .lastentry
 mov ax,[ds:00eeh]
.lastentry:
 stosw
 jmp .enter
.seedcontest:
 mov si,0094h
 mov di,3400h
 mov cx,12
 rep movsw
 mov ax,12
 stosw
 mov si,00aah
 mov di,3420h
 mov cx,12
 rep movsw
 mov ax,12
 stosw
.enter:
 mov es,[cs:rt_child_psp]
 mov word [es:0ah],rt_child_return
 mov [es:0ch],cs
 mov ax,[cs:rt_execblock+10h]
 cli
 mov ss,ax
 mov sp,[cs:rt_execblock+0eh]
 pop ax
 mov bx,[cs:rt_child_psp]
 mov ds,bx
 mov es,bx
 sti
 jmp far [cs:rt_execblock+12h]

rt_child_return:
 cli
 mov ax,[cs:rt_parent_ss]
 mov ss,ax
 mov sp,[cs:rt_parent_sp]
 sti
 mov byte [cs:rt_busy],0
 mov byte [cs:rt_running],0
 pop es
 pop ds
 popa
 push bp
 mov bp,sp
 and word [ss:bp+6],0fffeh
 pop bp
 xor ax,ax
 iret

rt_exec_error:
 mov [cs:rt_error],ax
 mov byte [cs:rt_busy],0
 pop es
 pop ds
 popa
 mov ax,[cs:rt_error]
 push bp
 mov bp,sp
 or word [ss:bp+6],1
 pop bp
 iret

; EAX=file offset -> ES:DI in the loaded MZ image. Header never loaded.
rt_address:
 movzx edx,word [cs:rt_header]
 sub eax,edx
 mov di,ax
 and di,0fh
 shr eax,4
 add ax,[cs:rt_image]
 mov es,ax
 ret

rt_apply_legacy:
 push ds
 push cs
 pop ds
 xor bx,bx
.next:
 cmp bx,[rt_queued_len]
 jae .done
 mov al,[rt_queuebuf+bx]
 cmp al,[rt_kind]
 jne .skip
 movzx ecx,byte [rt_queuebuf+bx+1]
 mov eax,[rt_queuebuf+bx+2]
 mov [rt_current_patch],eax
 mov [rt_current_length],cx
 call rt_address
 lea si,[rt_queuebuf+bx+6]
 cld
 rep movsb
 call rt_fix_patch_relocs
.skip:
 movzx ax,byte [rt_queuebuf+bx+1]
 add bx,ax
 add bx,6
 jmp .next
.done:
 pop ds
 ret
rt_current_patch dd 0
rt_current_length dw 0

rt_fix_patch_relocs:
 pusha
 mov si,start_legacy_relocs
 cmp byte [cs:rt_kind],1
 je .list
 mov si,fight_legacy_relocs
.list:
 mov cx,[cs:si]
 add si,2
.loop:
 jcxz .done
 mov eax,[cs:si]
 cmp eax,[cs:rt_current_patch]
 jb .next
 movzx edx,word [cs:rt_current_length]
 add edx,[cs:rt_current_patch]
 dec edx
 cmp eax,edx
 jae .next
 call rt_address
 mov ax,[cs:rt_image]
 add [es:di],ax
.next:
 add si,4
 loop .loop
.done:
 popa
 ret

rt_apply_firzen:
 push ds
 push cs
 pop ds
 mov si,start_patches
 cmp byte [rt_kind],1
 je .loop
 mov si,fight_patches
 cmp byte [rt_kind],2
 je .loop
 mov si,contest_patches
.loop:
 mov eax,[si]
 cmp eax,0ffffffffh
 je .done
 movzx cx,byte [si+4]
 add si,5
 call rt_address
 cld
 rep movsb
 jmp .loop
.done:
 mov ax,[rt_image]
 add ax,042dh
 mov [rt_native_menu_draw+2],ax
 mov ax,[rt_image]
 add ax,052bh
 mov [rt_native_crop+2],ax
 mov [rt_native_draw+2],ax
 mov ax,[rt_image]
 add ax,061dh
 mov [rt_native_freeze+2],ax
 mov [rt_native_fire+2],ax
 mov ax,[rt_image]
 add ax,015f1h
 mov [rt_native_packet+2],ax
 mov di,rt_modes
 mov cx,8
 xor ax,ax
 push cs
 pop es
 rep stosb
 mov di,rt_ticks
 mov cx,8+30*3
 rep stosw
.doneinit:
 pop ds
 ret

; Software hook dispatcher. Saved frame BP+2/IP,+4/CS,+6/FLAGS.
; PUSHAD locals: EAX=-4,ECX=-8,EDX=-12,EBX=-16,ESI=-28,EDI=-32.
rt_irq65:
 cmp ax,0f165h
 jne .gamehook
 push cs
 pop es
 mov bx,rt_info
 iret
.gamehook:
 push bp
 mov bp,sp
 pushad
 push ds
 push es
 movzx eax,word [ss:bp+4]
 sub ax,[cs:rt_image]
 shl eax,4
 movzx edx,word [ss:bp+2]
 add eax,edx
 movzx edx,word [cs:rt_header]
 add eax,edx
 mov [cs:rt_site_file],eax
 mov di,start_sites
 cmp byte [cs:rt_kind],1
 je .find
 mov di,fight_sites
 cmp byte [cs:rt_kind],2
 je .find
 mov di,contest_sites
.find:
 cmp dword [cs:di],0ffffffffh
 je .return
 cmp eax,[cs:di]
 je .found
 add di,6
 jmp .find
.found:
 mov al,[cs:di+4]
 mov [cs:rt_site_svc],al
 mov al,[cs:di+5]
 mov [cs:rt_site_arg],al
 cmp byte [cs:rt_site_svc],1
 je rt_compare
 cmp byte [cs:rt_site_svc],2
 je rt_actor
 cmp byte [cs:rt_site_svc],3
 je rt_motion
 cmp byte [cs:rt_site_svc],4
 je rt_crop
 cmp byte [cs:rt_site_svc],5
 je rt_draw
 cmp byte [cs:rt_site_svc],9
 je rt_ai_boss
 cmp byte [cs:rt_site_svc],10
 je rt_menu_head
.return:
 pop es
 pop ds
 popad
 pop bp
 iret

rt_compare:
 mov bx,[ss:bp-16]
 mov ax,[ds:bx+3418h]
 cmp word [ds:bx+33f2h],1
 jne .weapon
 cmp ax,12
 jne .cmp
 cmp byte [cs:rt_site_arg],11
 jne .cmp
 mov ax,11
 jmp .cmp
.weapon:
 cmp word [ds:bx+33f2h],2
 jne .cmp
 cmp byte [cs:rt_site_arg],26
 jne .element
 cmp dword [cs:rt_site_file],0a47eh
 je .homing
 cmp dword [cs:rt_site_file],0a4b4h
 je .homing
 cmp dword [cs:rt_site_file],0a579h
 jne .cmp
.homing:
 cmp ax,29
 je .skull
 cmp ax,30
 jne .cmp
.skull:
 mov ax,26
 jmp .cmp
.element:
 cmp ax,29
 jne .ice
 mov ax,16
 jmp .cmp
.ice:
 cmp ax,30
 jne .cmp
 mov ax,18
.cmp:
 xor dx,dx
 mov dl,[cs:rt_site_arg]
 cmp ax,dx
 pushf
 pop ax
 and ax,08d5h
 and word [ss:bp+6],0f72ah
 or [ss:bp+6],ax
 jmp rt_irq65.return

rt_ai_boss:
 mov bx,[ss:bp-16]
 push es
 mov ax,40h
 mov es,ax
 mov ax,[es:6ch]
 pop es
 and ax,1
 add ax,11
 mov [ds:bx+2ccah],ax
 jmp rt_irq65.return

; Native special dispatcher hook. Leave normal actors completely unchanged.
rt_actor:
 mov si,[ss:bp-28]
 mov ax,si
 mov dx,34h
 mov [ss:bp-4],ax
 mov [ss:bp-12],dx
 imul bx,si,34h
 cmp word [ds:bx+3418h],12
 jne .normal
 cmp word [ds:bx+33f2h],1
 jne .normal
 mov di,[ds:bx+341ch]
 cmp di,2
 ja .normal
 mov ax,di
 inc ax
 mov di,si
 cmp al,3
 jne .checkmode
 cmp byte [cs:rt_modes+di],4
 je .active
.checkmode:
 cmp [cs:rt_modes+di],al
 jne .init
 cmp word [ds:bx+3414h],1100
 je .init
 cmp word [ds:bx+3414h],2800
 jne .active
.init:
 mov [cs:rt_modes+di],al
 shl di,1
 mov word [cs:rt_ticks+di],0
 cmp word [ds:bx+341ch],2
 jne .active
 mov word [ds:bx+3414h],2800
.active:
 mov di,si
 shl di,1
 mov cx,[cs:rt_ticks+di]
 inc word [cs:rt_ticks+di]
 cmp word [ds:bx+341ch],2
 je rt_volcano
 mov word [ds:bx+3406h],0
 mov word [ds:bx+3408h],0
 mov word [ds:bx+340ah],0
 mov word [ds:bx+3414h],1101
 mov word [ds:bx+3412h],35
 cmp cx,4
 jb .done
 mov word [ds:bx+3412h],43
 cmp word [ds:bx+341ch],1
 je .disaster
 ; Cannon: release Attack (or easy-super key) to stop, or exhaust MP.
 cmp cx,4
 je .lead
 cmp byte [cs:rt_free],1
 je .input
 cmp word [ds:bx+3420h],0
 jle .end
.input:
 cmp word [ds:bx+3404h],3
 jae .aihold
 mov di,[ds:bx+3404h]
 movzx ax,byte [ds:di+145h]
 shl ax,1
 mov di,ax
 cmp word [ds:di+2e6eh],0
 jne .held
 cmp byte [cs:rt_easy],1
 jne .end
 mov di,[ds:bx+3404h]
 cmp di,2
 ja .end
 movzx ax,byte [cs:rt_easy_keys+di]
 shl ax,1
 mov di,ax
 cmp word [ds:di+2e6eh],0
 je .end
 jmp .held
.aihold:
 cmp cx,40
 jae .end
.held:
 mov ax,cx
 sub ax,4
 xor dx,dx
 mov di,3
 div di
 test dx,dx
 jnz .done
 mov dx,28
 call rt_spawn
 cmp byte [cs:rt_free],1
 je .done
 imul bx,si,34h
 mov ax,3
 cmp byte [cs:rt_cheap],1
 jne .drain
 mov ax,1
.drain:
 sub [ds:bx+3420h],ax
 jns .done
 mov word [ds:bx+3420h],0
 jmp .end
.lead:
 mov dx,27
 call rt_spawn
 jmp .done
.disaster:
 cmp cx,28
 jae .end
 mov ax,cx
 sub ax,4
 xor dx,dx
 mov di,6
 div di
 test dx,dx
 jnz .done
 cmp ax,4
 jae .done
 test ax,1
 jnz .iceshot
 mov dx,29
 call rt_spawn
 jmp .done
.iceshot:
 mov dx,30
 call rt_spawn
 jmp .done
.end:
 imul bx,si,34h
 mov word [ds:bx+3414h],1
 mov word [ds:bx+3412h],1
 mov byte [cs:rt_modes+si],0
.done:
 ; Skip the native special branch, then use native movement and cleanup.
 add word [ss:bp+2],15ac8h-15971h
 jmp rt_irq65.return
.normal:
 jmp rt_irq65.return
rt_easy_keys db 10h,16h,47h

; Native Freeze cyclone followed by the native Firen explosion. Temporarily
; use Firen's definition only inside his explosion producer, then restore.
rt_volcano:
 mov di,si
 cmp byte [cs:rt_modes+di],4
 je .fire
 push si
 call far [cs:rt_native_freeze]
 add sp,2
 imul bx,si,34h
 cmp word [ds:bx+3414h],1000
 jae .done
 mov byte [cs:rt_modes+si],4
 mov word [ds:bx+3414h],2300
.fire:
 mov word [ds:bx+3418h],6
 mov word [ds:bx+341ch],1
 push si
 call far [cs:rt_native_fire]
 add sp,2
 imul bx,si,34h
 mov word [ds:bx+3418h],12
 mov word [ds:bx+341ch],2
 cmp word [ds:bx+3414h],1000
 jb .finished
 mov word [ds:bx+3412h],125
 jmp .done
.finished:
 mov byte [cs:rt_modes+si],0
.done:
 add word [ss:bp+2],15ac8h-15971h
 jmp rt_irq65.return

; SI=caster slot,DX=new projectile kind. A free native entity is initialized
; with the normal projectile fields; elemental behavior remains table-driven.
rt_spawn:
 pusha
 push dx
 mov di,8
.search:
 imul bx,di,34h
 cmp word [ds:bx+33f2h],0
 je .found
 inc di
 cmp di,30
 jb .search
 pop dx
 jmp .return
.found:
 pop dx
 mov word [ds:bx+33f2h],2
 mov [ds:bx+3418h],dx
 mov word [ds:bx+33f8h],1
 mov word [ds:bx+3412h],1
 mov word [ds:bx+3414h],1
 mov word [ds:bx+3416h],0
 mov word [ds:bx+340eh],54
 mov word [ds:bx+3404h],0ffffh
 mov [ds:bx+3410h],si
 mov word [ds:bx+3406h],0
 mov word [ds:bx+3408h],0
 mov word [ds:bx+340ah],0
 push bx
 imul bx,si,34h
 mov ax,[ds:bx+3402h]
 mov cx,[ds:bx+33fch]
 mov bp,[ds:bx+33feh]
 mov si,[ds:bx+3400h]
 sub si,5
 cmp dx,29
 jb .cannon
 sub si,2
 sub bp,6
 cmp dx,30
 jne .normalpos
 add bp,12
.normalpos:
 imul ax,13
 jmp .position
.cannon:
 imul ax,27
.position:
 add cx,ax
 pop bx
 mov [ds:bx+33fch],cx
 mov [ds:bx+33feh],bp
 mov [ds:bx+3400h],si
 ; PUSHA saved the caster SI at SS:SP+2.
 mov si,sp
 mov si,[ss:si+2]
 imul si,34h
 mov ax,[ds:si+3402h]
 mov [ds:bx+3402h],ax
 mov si,di
 shl si,1
 mov [cs:rt_motion_x+si],cx
 mov word [cs:rt_motion_frac+si],0
 mov word [cs:rt_motion_age+si],0
 cmp dx,29
 jb .return
 imul ax,8
 mov [ds:bx+3406h],ax
 mov ax,-3
 cmp dx,30
 jne .depth
 mov ax,3
.depth:
 mov [ds:bx+3408h],ax
.return:
 popa
 ret

; Entered after native projectile prologue's MOV SI,[BP+6]. Preserve normal
; projectiles. Cannon has its own fixed-point speed and normal hit packets.
rt_motion:
 mov di,[ss:bp]
 mov si,[ss:di+6]
 mov [ss:bp-28],si
 imul bx,si,34h
 cmp word [ds:bx+33f2h],2
 jne .normal
 mov dx,[ds:bx+3418h]
 cmp dx,27
 jb .normal
 cmp dx,28
 ja .normal
 mov di,si
 shl di,1
 inc word [cs:rt_motion_age+di]
 cmp word [cs:rt_motion_age+di],90
 ja .remove
 mov ax,[cs:rt_motion_frac+di]
 add ax,1000
 xor dx,dx
 mov cx,182
 div cx
 mov [cs:rt_motion_frac+di],dx
 imul ax,word [ds:bx+3402h]
 add [ds:bx+33fch],ax
 mov ax,[ds:bx+33fch]
 mov [cs:rt_motion_x+di],ax
 cmp ax,-50
 jl .remove
 cmp ax,380
 jg .remove
 mov word [ds:bx+3406h],0
 mov word [ds:bx+3408h],0
 mov word [ds:bx+340ah],0
 push si
 mov ax,25
 push ax
 mov ax,2012
 cmp word [ds:bx+3418h],28
 je .damage
 mov ax,2020
.damage:
 push ax
 push word -7
 mov ax,[ds:bx+3402h]
 imul ax,5
 push ax
 push word [ds:bx+3402h]
 push word 5
 push word 5
 push word [ds:bx+3400h]
 push word [ds:bx+33feh]
 mov ax,[ds:bx+3402h]
 imul ax,13
 add ax,[ds:bx+33fch]
 push ax
 call far [cs:rt_native_packet]
 add sp,22
 jmp .done
.remove:
 mov word [ds:bx+33f2h],0
.done:
 add word [ss:bp+2],0ab1fh-0a3fch
.normal:
 jmp rt_irq65.return

 ; Only Firzen's custom menu head needs the one-pixel vertical adjustment.
rt_menu_head:
 mov bx,[ss:bp-28]
 shl bx,1
 xor dx,dx
 cmp word [ds:bx+16bh],12
 jne .args
 mov dx,1
.args:
 mov si,7
.copy:
 mov ax,si
 shl ax,1
 mov di,bp
 add di,ax
 mov ax,[ss:di+6]
 cmp si,2
 jne .push
 sub ax,dx
.push:
 push ax
 dec si
 jnz .copy
 call far [cs:rt_native_menu_draw]
 add sp,14
 jmp rt_irq65.return

; Replace the weapon atlas crop only for Cannon's larger native cells.
rt_crop:
 mov si,[ss:bp-28]
 imul bx,si,34h
 cmp word [ds:bx+33f2h],2
 jne .original
 cmp word [ds:bx+3418h],27
 jb .original
 cmp word [ds:bx+3418h],28
 ja .original
 push cs
 push word rt_cannon_grh
 push word [ds:4d9fh]
 push word [ds:4d9dh]
 mov ax,15
 mov dx,0
 cmp word [ds:bx+3418h],27
 je .size
 mov ax,9
 mov dx,16
.size:
 push ax
 push word 29
 push dx
 push word 0
 call far [cs:rt_native_crop]
 add sp,16
 jmp rt_irq65.return
.original:
 mov si,8
.copy:
 mov ax,si
 shl ax,1
 mov di,bp
 add di,ax
 push word [ss:di+6]
 dec si
 jnz .copy
 call rt_native_inputs
 call far [cs:rt_native_crop]
 add sp,16
 call rt_native_outputs
 jmp rt_irq65.return

rt_draw:
 mov si,[ss:bp-28]
 imul bx,si,34h
 cmp word [ds:bx+33f2h],2
 jne .original
 cmp word [ds:bx+3418h],27
 jb .original
 cmp word [ds:bx+3418h],28
 ja .original
 push word 0
 push word [ds:4dbfh]
 push word [ds:4dbdh]
 push word [ds:4d9fh]
 push word [ds:4d9dh]
 mov ax,[ds:bx+33feh]
 add ax,[ds:bx+3400h]
 sub ax,13
 cmp word [ds:bx+3418h],27
 je .y
 add ax,3
.y:
 push ax
 mov ax,[ds:bx+33fch]
 sub ax,14
 push ax
 call far [cs:rt_native_draw]
 add sp,14
 jmp rt_irq65.return
.original:
 mov si,7
.copy:
 mov ax,si
 shl ax,1
 mov di,bp
 add di,ax
 push word [ss:di+6]
 dec si
 jnz .copy
 call rt_native_inputs
 call far [cs:rt_native_draw]
 add sp,14
 call rt_native_outputs
 jmp rt_irq65.return

rt_native_inputs:
 mov eax,[ss:bp-4]
 mov ecx,[ss:bp-8]
 mov edx,[ss:bp-12]
 mov ebx,[ss:bp-16]
 mov esi,[ss:bp-28]
 mov edi,[ss:bp-32]
 mov ds,[ss:bp-34]
 mov es,[ss:bp-36]
 ret
rt_native_outputs:
 mov [ss:bp-4],eax
 mov [ss:bp-8],ecx
 mov [ss:bp-12],edx
 mov [ss:bp-16],ebx
 mov [ss:bp-28],esi
 mov [ss:bp-32],edi
 mov [ss:bp-34],ds
 mov [ss:bp-36],es
 ret

%include "patches.inc"
