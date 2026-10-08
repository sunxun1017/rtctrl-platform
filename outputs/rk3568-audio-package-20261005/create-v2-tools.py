#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create additive v2 tools from frozen v1 sources; never overwrite a source."""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write_new(name, text):
    with (HERE / name).open('xb') as stream:
        stream.write(text.encode('utf-8'))


def change(text, before, after, count=1):
    assert text.count(before) == count, (before, text.count(before))
    return text.replace(before, after)


def main():
    text = (HERE / 'audio-package.py').read_text()
    text = change(text, 'stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit',
                  'stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= limit')
    text = change(text, "manifest.get('kernel_release') == '4.19.232'",
                  "manifest.get('kernel_release') == '5.10.160-rt89-g9f9e9d18574d-dirty'")
    for before, after in [('audio-package.py', 'audio-package-v2.py'),
                          ('build-audio-package.py', 'build-audio-package-v2.py'),
                          ('audit-audio-package.py', 'audit-audio-package-v2.py'),
                          ('test-audio-package.py', 'test-audio-package-v2.py'),
                          ('README.md', 'README-v2.md'), ('PLAN.md', 'PLAN-v2.md')]:
        # The two source snapshot lists are the only references in the core.
        text = change(text, "'" + before + "'", "'" + after + "'", count=2)
    write_new('audio-package-v2.py', text)

    for old, new in [('build-audio-package.py', 'build-audio-package-v2.py'),
                     ('audit-audio-package.py', 'audit-audio-package-v2.py')]:
        text = (HERE / old).read_text()
        text = change(text, "'audio-package.py'", "'audio-package-v2.py'")
        write_new(new, text)

    text = (HERE / 'test-audio-package.py').read_text()
    text = change(text, 'import json\n', 'import json\nimport re\n')
    text = change(text, "'audio-package.py'", "'audio-package-v2.py'", count=2)
    text = change(text, "'build-audio-package.py'", "'build-audio-package-v2.py'", count=2)
    text = change(text, "    fixed = core.fixed_inputs()\n", """    fixture_metadata_path = 'outputs/rk3568-rcu-reset-20261004/kernel-artifacts.json'
    fixture_metadata_data = core.read_ordinary(core.relative_path(fixture_metadata_path))
    fixture_metadata = core.unique_json(fixture_metadata_data)
    fixture_image_record = next(item for item in fixture_metadata['artifacts'] if item['file'] == 'Image')
    assert all(fixture_image_record[key] == core.metadata(image)[key] for key in ('bytes', 'sha256', 'crc32'))
    # Metadata comes from the frozen old Linux build record and the Image banner,
    # never from the implementation's accepted release constant.
    fixture_banner = re.search(rb'Linux version ([^ \\x00\\n]+) \\(', image)
    assert fixture_banner and fixture_banner.group(1).decode('ascii') == fixture_metadata['kernel_release']
    fixed = core.fixed_inputs()
""")
    text = change(text, "'image_memory_bytes': 35389440, 'kernel_release': '4.19.232'",
                  "'image_memory_bytes': struct.unpack_from('<Q', image, 16)[0],\n                      'kernel_release': fixture_metadata['kernel_release']")
    text = change(text, "'core_source': core.metadata((HERE / 'audio-package-v2.py').read_bytes())}",
                  """'core_source': core.metadata((HERE / 'audio-package-v2.py').read_bytes()),
              'fixture_release_evidence': {'path': fixture_metadata_path, **core.metadata(fixture_metadata_data),
                                           'banner_release': fixture_banner.group(1).decode('ascii')}}""")
    write_new('test-audio-package-v2.py', text)


if __name__ == '__main__':
    main()
