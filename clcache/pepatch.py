import pefile, struct, sys, hashlib, mmap
from . __main__ import printTraceStatement

def exception_hook(exc_type, exc_value, exc_traceback):
    import traceback
    s = traceback.format_exception(exc_type, exc_value, exc_traceback)
    printTraceStatement(''.join(s))
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

sys.excepthook = exception_hook


def print(msg):
    printTraceStatement(f'patcher: {msg}')


def format_guid_from_hex(hex_string):
    first = hex_string[6:8] + hex_string[4:6] + hex_string[2:4] + hex_string[:2]
    second = hex_string[10:12] + hex_string[8:10]
    third = hex_string[14:16] + hex_string[12:14]
    return "{0}-{1}-{2}-{3}-{4}".format(first, second, third, hex_string[16:20], hex_string[20:])


def is_dot_net_assembly(pe):
    clr_header = pe.OPTIONAL_HEADER.DATA_DIRECTORY[14]
    if clr_header.VirtualAddress != 0:
        return clr_header.VirtualAddress


def map_file(fname):
    fd = open(fname, 'r+b', buffering=0)
    data = mmap.mmap(fd.fileno(), 0, access=mmap.ACCESS_WRITE)
    return data


def set_field(pe, field):
    pe.__data__[field.__file_offset__: field.__file_offset__ + field.sizeof()] = field.__pack__()


def update_timestamp(pe, stamp=b'\0' * 32):
    pe.FILE_HEADER.TimeDateStamp = int.from_bytes(stamp[-4:], byteorder='little')
    set_field(pe, pe.FILE_HEADER)
    if hasattr(pe, 'DIRECTORY_ENTRY_DEBUG'):
        for x in pe.DIRECTORY_ENTRY_DEBUG:
            x.struct.TimeDateStamp = int.from_bytes(stamp[-4:], byteorder='little')
            set_field(pe, x.struct)
            if x.struct.Type == 16:
                assert x.struct.SizeOfData == 36
                pe.__data__[x.struct.PointerToRawData + 4: x.struct.PointerToRawData + 36] = stamp[:32]
    if hasattr(pe, 'DIRECTORY_ENTRY_EXPORT'):
        pe.DIRECTORY_ENTRY_EXPORT.struct.TimeDateStamp = int.from_bytes(stamp[-4:], byteorder='little')
        set_field(pe, pe.DIRECTORY_ENTRY_EXPORT.struct)


def update_assembly(assembly_path):
    file_data = map_file(assembly_path)
    pe = pefile.PE(data=file_data, fast_load=True)
    clr_header_rva = is_dot_net_assembly(pe)
    if not clr_header_rva:
        return None
    print('Original Hash {}'.format(hashlib.sha256(file_data).hexdigest()))
    pe.parse_data_directories(directories=[
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DEBUG'], pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])


    pe.OPTIONAL_HEADER.CheckSum = 0
    set_field(pe, pe.OPTIONAL_HEADER)
    update_timestamp(pe)

    file_data_mm = file_data
    file_data = memoryview(file_data)

    clr_header_offset = pe.get_offset_from_rva(clr_header_rva)

    clr_header = struct.unpack_from("<IHHII", file_data, clr_header_offset)
    metadata_header_rva = clr_header[-2]
    metadata_header_size = clr_header[-1]

    metadata_header_offset = pe.get_offset_from_rva(metadata_header_rva)

    metadata_header = file_data[metadata_header_offset:]

    clr_version_length = struct.unpack_from("<I", metadata_header, 12)[0]
    stream_count = struct.unpack_from("<H", metadata_header, clr_version_length + 18)[0]
    current_offset = clr_version_length + 20
    for c in range(stream_count):
        offset, size = struct.unpack_from("<II", metadata_header, current_offset)
        current_offset += 8
        name = b""
        while b"\x00" not in name:
            name += metadata_header[current_offset:current_offset + 4]
            current_offset += 4
        name = name.strip(b"\x00")
        if name == b"#GUID":
            guid = metadata_header[offset: offset + size]
            break

    extracted_mvid = format_guid_from_hex(guid.hex())
    guid[0:16] = b'\0' * 16

    hash = hashlib.sha256(file_data).digest()
    print('Temp Hash {}'.format(hash.hex()))

    guid[0:16] = hash[:16]
    update_timestamp(pe, hash)
    print('Final Hash {}'.format(hashlib.sha256(file_data).hexdigest()))
    file_data_mm.flush()
    return {"mvid": extracted_mvid.lower()}


def main():
    if len(sys.argv) > 1:
        print(sys.argv[1])
        if update_assembly(sys.argv[1]):
            print(f"{sys.argv[1]} patched")
        else:
            print(f"{sys.argv[1]} not patched")


if __name__ == "__main__":
    main()