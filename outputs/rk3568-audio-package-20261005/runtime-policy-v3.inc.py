# This frozen text is inserted by create-v3-tools.py into the real v3 module.
CPU_V10_MANIFEST = '92344de6c38aeb3353134150ec9bca75fad84dc3d2071e1bbd7d611fd0d73b56'
CPU_SOURCE = '87779ff23367aaaac07e8c980ee98dbdf59a93318e3a2782c52bdb011eb4417c'
CPU_INVENTORY = '7d36c8f14369b6b88ffbbc700a9b35c3d30a23d98eadd9cee88affa658a20a88'
CPU_DELTA = 'dd31e7208c71bdc7dac8b41c8d82f9e2702f77c743a80214044d8b28e5422437'
CPU_FILES = {
    RUNTIME + 'cpu-lifecycle-v11/source/manifest.json': CPU_MANIFEST,
    RUNTIME + 'cpu-lifecycle-v11/source/sound/soc/rockchip/rockchip_i2s_tdm.c': CPU_SOURCE,
    RUNTIME + 'cpu-lifecycle-v11/frozen-output-manifest.json': CPU_INVENTORY,
}
RUNTIME_FIXED = {
    'audio-session-guard': (RUNTIME + 'session-guard-v4/build/audio-session-guard', 741560,
                            '8740384398313be87a13245e854d6fc5a17a10f3794bdd83966e933c894c6f69'),
    'alsa-inspect': ('outputs/rk3568-audio-20261005/build/inspect-v4/alsa-inspect', 650408,
                     '118cf99482cdd65acdfae8c5e85530a76bf60c90b0b0498e8f285223f862a945'),
    'pcm-transfer': ('outputs/rk3568-audio-transfer-20261005/build/static-v1/pcm-transfer', 659736,
                     '2a6c765bd9c3c25b3456e60d68670231e81dcaf7781b827559cd701beed09e2e'),
}
GUARD_MANIFEST = '15a24232ebaab58a5642aba2d8b92e66216208480fc7decae5ea776f6b8dbb18'
GUARD_INVENTORY = 'b45792270eda2881b3d5de06406bd42df0c6b34d80fc46505ffde42a31efc4dd'
CODEC_SOURCE = '72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64'
CODEC_HEADER = '370f2c9451d0e871b627c7b9a9b90cc24e486c49cebe29c068d5b692f7802449'


def runtime_sums(blobs):
    return ''.join(metadata(blob)['sha256'] + '  ' + name + '\n' for name, blob in sorted(blobs.items())).encode()


def checked_inventory(directory, expected_sha):
    name = directory + '/frozen-output-manifest.json'
    data = read_ordinary(relative_path(name), 8 * 1024 * 1024)
    require(metadata(data)['sha256'] == expected_sha, 'Runtime frozen inventory identity')
    record = unique_json(data)
    files = record.get('files_sha256')
    require(isinstance(files, dict) and files, 'Runtime complete frozen inventory')
    verify_hash_map({directory + '/' + relative: sha for relative, sha in files.items()})
    return {'path': name, **metadata(data), 'verified_files': len(files)}


def codec_abi_names():
    build = relative_path('.deps/kernel/aiot-3568pq-audio-v2')
    names = {'.config', 'Module.symvers', 'vmlinux.symvers'}
    for name in names:
        path = build / name
        require(not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode), 'Codec ABI ordinary core file')
    for directory in ('include', 'arch/arm64/include'):
        path = build / directory
        require(not path.is_symlink() and path.is_dir(), 'Codec ABI ordinary include directory')
        for member in path.rglob('*'):
            mode = member.lstat().st_mode
            require(not member.is_symlink() and (stat.S_ISDIR(mode) or stat.S_ISREG(mode)), 'Codec ABI ordinary tree member')
            if stat.S_ISREG(mode):
                names.add(member.relative_to(build).as_posix())
    return names


def codec_elf_info(binary, exports):
    # The existing ELF auditor invokes objcopy; copy first to protect the production module.
    import uuid
    source = relative_path('outputs/rk3568-audio-20261005/build-codec.py')
    data = read_ordinary(source)
    audit = ModuleType('audio_v3_actual_codec_elf')
    audit.__file__ = str(source)
    exec(compile(data, str(source), 'exec'), audit.__dict__)
    output = fresh_directory(HERE / 'build' / ('codec-elf-audit-v3-' + uuid.uuid4().hex))
    copied = output / 'snd-soc-rk817.ko'
    write_new(copied, binary)
    actual = audit.audit_module(copied, output, exports)
    require(read_ordinary(copied) == binary, 'ELF audit copied module bytes preserved')
    trace = {'module_input': metadata(binary), 'actual_info': actual,
             'auditor_source_sha256': metadata(data)['sha256'],
             'files_sha256': {p.name: metadata(read_ordinary(p))['sha256'] for p in sorted(output.iterdir()) if p.is_file()},
             'scope': 'ACTUAL_COPY_ELF_READELF_NM_OBJCOPY_NO_PRODUCTION_FILE_WRITE', 'board_tested': False}
    write_new(output / 'receipt.json', json_bytes(trace))
    # Fresh trace paths are intentionally absent from the stable runtime identity.
    return actual


def validate_codec(manifest, module, image, image_manifest_data, image_manifest):
    require(manifest.get('image_sha256') == metadata(image)['sha256'] and
            manifest.get('image_manifest_sha256') == metadata(image_manifest_data)['sha256'], 'Codec exact new Image binding')
    require(manifest.get('source_sha256') == CODEC_SOURCE and manifest.get('header_sha256') == CODEC_HEADER and
            manifest.get('abi_unchanged') is True and manifest.get('module_symvers_sha256') == image_manifest['module_symvers_sha256'],
            'Codec source/ABI binding')
    info = manifest.get('module', {})
    require(info.get('bytes') == len(module) and info.get('sha256') == metadata(module)['sha256'], 'Codec module complete content binding')
    require(len(module) >= 64 and module[:6] == b'\x7fELF\x02\x01' and
            struct.unpack_from('<HH', module, 16) == (1, 183), 'Codec AArch64 ET_REL')
    expected_vermagic = image_manifest['kernel_release'] + ' SMP preempt_rt mod_unload aarch64'
    require(info.get('metadata', {}).get('vermagic') == [expected_vermagic] and
            b'vermagic=' + expected_vermagic.encode() + b'\0' in module, 'Codec exact vermagic')
    require(info.get('imports_resolved') is True and info.get('elf_has_interp') is False and info.get('elf_has_needed') is False,
            'Codec complete ELF audit boundary')
    imports = info.get('imports')
    require(isinstance(imports, dict) and imports and all(value['provider'] == 'vmlinux' for value in imports.values()), 'Codec built-in imports only')
    exports = {}
    symvers = read_ordinary(relative_path(PRODUCTION + 'Module.symvers')).decode()
    for line in symvers.splitlines():
        fields = line.split('\t')
        require(len(fields) >= 4, 'Image symvers format')
        exports[fields[1]] = {'crc': fields[0], 'provider': fields[2], 'export_type': fields[3], 'namespace': fields[4] if len(fields) > 4 else ''}
    require(all(exports.get(name) == value for name, value in imports.items()), 'Codec actual new Image imports')
    require(all(manifest.get(name) is False for name in ('board_tested', 'unload_tested', 'deployed')), 'Codec offline boundary')
    for name, key in [(RUNTIME + 'build-integrated-codec-v2.py', 'builder_sha256'),
                      ('outputs/rk3568-audio-20261005/build-codec.py', 'audit_source_sha256')]:
        require(metadata(read_ordinary(relative_path(name)))['sha256'] == digest(manifest[key]), 'Codec build/audit tool binding')
    abi = manifest.get('abi_inventory')
    require(isinstance(abi, dict) and abi.get('.config') == CONFIG and
            abi.get('Module.symvers') == image_manifest['module_symvers_sha256'] and
            abi.get('vmlinux.symvers') == image_manifest['vmlinux_symvers_sha256'], 'Codec complete ABI inventory')
    require(set(abi) == codec_abi_names(), 'Codec ABI exact ordinary file set')
    verify_hash_map({'.deps/kernel/aiot-3568pq-audio-v2/' + name: sha for name, sha in abi.items()})
    for name, expected in [('rk817_codec.c', CODEC_SOURCE), ('rk817_codec.h', CODEC_HEADER)]:
        require(metadata(read_ordinary(relative_path(RUNTIME + 'build/integrated-codec-v2/modules/' + name)))['sha256'] == expected,
                'Codec compiled source snapshot binding')
    require(info == codec_elf_info(module, exports), 'Codec actual complete ELF audit binding')


def runtime_inputs(image, image_manifest_data, image_manifest):
    blobs = {name: read_locked(*fields) for name, fields in RUNTIME_FIXED.items()}
    guard_dir = RUNTIME + 'session-guard-v4'
    guard_data = read_ordinary(relative_path(guard_dir + '/build/manifest.json'), 4 * 1024 * 1024)
    require(metadata(guard_data)['sha256'] == GUARD_MANIFEST, 'Guard v4 build manifest identity')
    guard = unique_json(guard_data)
    require(guard['binary_sha256'] == metadata(blobs['audio-session-guard'])['sha256'] and
            guard['inspector_sha256'] == metadata(blobs['alsa-inspect'])['sha256'], 'Guard v4 executable/inspector binding')
    guard_inventory = checked_inventory(guard_dir, GUARD_INVENTORY)
    codec_path = RUNTIME + 'build/integrated-codec-v2/'
    codec_data = read_ordinary(relative_path(codec_path + 'manifest.json'), 4 * 1024 * 1024)
    codec = unique_json(codec_data)
    blobs['snd-soc-rk817.ko'] = read_ordinary(relative_path(codec_path + 'modules/snd-soc-rk817.ko'))
    validate_codec(codec, blobs['snd-soc-rk817.ko'], image, image_manifest_data, image_manifest)
    files = {name: {'path': RUNTIME_FIXED[name][0] if name in RUNTIME_FIXED else codec_path + 'modules/' + name,
                    **metadata(blob)} for name, blob in blobs.items()}
    record = {'files': files, 'codec_manifest': {'path': codec_path + 'manifest.json', **metadata(codec_data)},
              'guard_manifest': {'path': guard_dir + '/build/manifest.json', **metadata(guard_data)},
              'guard_inventory': guard_inventory, 'guard_version': 4, 'cpu_version': 11,
              'cpu_source_sha256': CPU_SOURCE, 'cpu_manifest_sha256': CPU_MANIFEST, 'cpu_inventory_sha256': CPU_INVENTORY,
              'guard_v4_original_CPU_v10_input_kept': True,
              'guard_v4_sysfs_protocol_unchanged_by_CPU_v11': True,
              'guard_is_collector_not_START_authorization': True,
              'board_tested': False, 'physical_sound_verified': False, 'formal_flash_ready': False}
    return record, blobs
