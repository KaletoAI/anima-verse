#!/usr/bin/env python3
"""Rename libcef.so's undefined `mallinfo` import to `mallinf_` (see native/cef_shim/mallinfo_shim.c).

Usage: patch_cef_mallinfo.py <libcef.so>   (edits the file in place; run it on a private copy, never on the host's
artifacts). Idempotent. Refuses unless the name is exactly one undefined dynamic symbol whose string bytes no other
dynamic symbol name shares (undefined names are not in the GNU hash table, so only .dynstr changes, by one byte).
"""
import mmap
import struct
import sys

OLD, NEW = b'mallinfo', b'mallinf_'


def main(path: str) -> int:
    with open(path, 'r+b') as fh, mmap.mmap(fh.fileno(), 0) as mm:
        if mm[:4] != b'\x7fELF' or mm[4] != 2 or mm[5] != 1:
            sys.exit(f'{path}: not a little-endian ELF64 file')
        shoff = struct.unpack_from('<Q', mm, 0x28)[0]
        shentsize, shnum, shstrndx = struct.unpack_from('<HHH', mm, 0x3A)
        secs = [struct.unpack_from('<IIQQQQIIQQ', mm, shoff + i * shentsize) for i in range(shnum)]
        shstr = secs[shstrndx][4]

        def cstr(base: int, off: int) -> bytes:
            return mm[base + off:mm.find(b'\0', base + off)]

        by_name = {cstr(shstr, s[0]): s for s in secs}
        dynsym, dynstr = by_name[b'.dynsym'], by_name[b'.dynstr']
        names = []
        for i in range(dynsym[5] // 24):
            st_name, _info, _other, shndx, _value, _size = struct.unpack_from('<IBBHQQ', mm, dynsym[4] + i * 24)
            names.append((st_name, cstr(dynstr[4], st_name), shndx))
        hits = [n for n in names if n[1] in (OLD, NEW)]
        if len(hits) != 1 or hits[0][2] != 0:
            sys.exit(f'{path}: expected exactly one undefined {OLD.decode()} import, found {hits}')
        off, name, _ = hits[0]
        if name == NEW:
            print(f'{path}: already patched')
            return 0
        shared = [n for n in names if n[0] != off and n[0] < off + len(OLD) and n[0] + len(n[1]) > off]
        if shared:
            sys.exit(f'{path}: the string of {OLD.decode()} is shared with {shared[:3]}')
        mm[dynstr[4] + off:dynstr[4] + off + len(NEW)] = NEW
        mm.flush()
    print(f'{path}: {OLD.decode()} -> {NEW.decode()}')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
