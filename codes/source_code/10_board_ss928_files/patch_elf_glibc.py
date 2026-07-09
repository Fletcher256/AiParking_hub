"""
Patch .gnu.version_r section of an ELF binary to downgrade GLIBC version
requirements. Replaces version strings AND their hashes in-place.
Same-length strings only (GLIBC_2.34 -> GLIBC_2.17, both 10 chars).
"""
import struct, sys

def elf_hash(name: str) -> int:
    h = 0
    for c in name.encode('ascii'):
        h = ((h << 4) + c) & 0xFFFFFFFF
        g = h & 0xF0000000
        if g:
            h ^= g >> 24
        h &= ~g & 0xFFFFFFFF
    return h

def patch_verneed(data: bytearray, old_ver: str, new_ver: str) -> int:
    assert len(old_ver) == len(new_ver), "Version strings must be same byte length"

    # Parse ELF64 header
    assert data[:4] == b'\x7fELF', "Not an ELF file"
    assert data[4] == 2, "Only ELF64 supported"
    # little-endian assumed (ELDATA2LSB)
    e_shoff     = struct.unpack_from('<Q', data, 40)[0]
    e_shentsize = struct.unpack_from('<H', data, 58)[0]
    e_shnum     = struct.unpack_from('<H', data, 60)[0]
    e_shstrndx  = struct.unpack_from('<H', data, 62)[0]

    # Read all section headers
    shdrs = []
    for i in range(e_shnum):
        base = e_shoff + i * e_shentsize
        sh_name, sh_type = struct.unpack_from('<II', data, base)
        sh_offset, sh_size = struct.unpack_from('<QQ', data, base + 24)
        shdrs.append({'name_idx': sh_name, 'type': sh_type,
                      'offset': sh_offset, 'size': sh_size})

    # Read section name string table
    shstr = shdrs[e_shstrndx]
    shstr_data = data[shstr['offset']: shstr['offset'] + shstr['size']]

    def sh_name_str(idx):
        end = shstr_data.index(b'\x00', idx)
        return shstr_data[idx:end].decode('ascii')

    # Locate .gnu.version_r and .dynstr
    SHT_GNU_verneed = 0x6ffffffe
    verneed_shdr = None
    dynstr_shdr  = None
    for s in shdrs:
        name = sh_name_str(s['name_idx'])
        if s['type'] == SHT_GNU_verneed:
            verneed_shdr = s
        if name == '.dynstr':
            dynstr_shdr = s

    if verneed_shdr is None or dynstr_shdr is None:
        print(f"  [!] .gnu.version_r or .dynstr not found — skipping '{old_ver}'")
        return 0

    old_hash = elf_hash(old_ver)
    new_hash = elf_hash(new_ver)
    old_bytes = old_ver.encode('ascii')
    new_bytes = new_ver.encode('ascii')

    print(f"  Patching '{old_ver}' (hash=0x{old_hash:08x}) "
          f"-> '{new_ver}' (hash=0x{new_hash:08x})")

    vr_base = verneed_shdr['offset']
    ds_base = dynstr_shdr['offset']
    patches = 0

    # Walk Elf64_Verneed linked list
    vn_pos = vr_base
    while True:
        vn_version = struct.unpack_from('<H', data, vn_pos)[0]
        vn_cnt     = struct.unpack_from('<H', data, vn_pos + 2)[0]
        vn_aux     = struct.unpack_from('<I', data, vn_pos + 8)[0]
        vn_next    = struct.unpack_from('<I', data, vn_pos + 12)[0]

        # Walk Elf64_Vernaux linked list
        va_pos = vn_pos + vn_aux
        for _ in range(vn_cnt):
            vna_hash  = struct.unpack_from('<I', data, va_pos)[0]
            vna_name  = struct.unpack_from('<I', data, va_pos + 8)[0]
            vna_next  = struct.unpack_from('<I', data, va_pos + 12)[0]

            # Resolve name from .dynstr
            name_off = ds_base + vna_name
            name_end = data.index(b'\x00', name_off)
            name = data[name_off:name_end].decode('ascii')

            if name == old_ver:
                # Patch string in .dynstr
                data[name_off: name_off + len(old_bytes)] = new_bytes
                # Patch hash in Elf64_Vernaux
                struct.pack_into('<I', data, va_pos, new_hash)
                patches += 1
                print(f"    patched entry at dynstr+0x{vna_name:x}, vernaux@0x{va_pos:x}")

            if vna_next == 0:
                break
            va_pos += vna_next

        if vn_next == 0:
            break
        vn_pos += vn_next

    return patches


def main():
    if len(sys.argv) < 2:
        print("Usage: patch_elf_glibc.py <binary>")
        sys.exit(1)

    filename = sys.argv[1]
    with open(filename, 'rb') as f:
        data = bytearray(f.read())

    total = 0
    for old, new in [('GLIBC_2.34', 'GLIBC_2.17'),
                     ('GLIBC_2.33', 'GLIBC_2.17')]:
        n = patch_verneed(data, old, new)
        total += n
        print(f"  -> {n} entries patched for '{old}'\n")

    if total == 0:
        print("Nothing patched — binary may already be clean or parsing failed.")
        sys.exit(1)

    with open(filename, 'wb') as f:
        f.write(data)
    print(f"Done. Wrote patched binary ({len(data)} bytes) to '{filename}'")


if __name__ == '__main__':
    main()
