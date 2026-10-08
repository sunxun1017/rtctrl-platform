#!/usr/bin/env python3
"""Verify the frozen offline evidence without changing any producer files."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(base, files):
    for name, expected in files.items():
        path = base / name
        assert path.is_file() and sha(path) == expected, str(path)
    return len(files)


def main():
    output = HERE / 'build/integration-evidence-v1.json'
    assert not output.exists()
    counts = {}
    bound = {}
    c3 = ROOT / 'outputs/rk3568-dma-lifecycle-20261005/C3-review-v2/receipt.json'
    assert sha(c3) == '97011370d4a66b385ab3855fa9cf2f2cf4c857728a1f969902f5e8dd9b10e975'
    receipt = json.loads(c3.read_text())
    counts['c3_frozen'] = verify(c3.parent, receipt['files_sha256'])
    bound[str(c3.relative_to(ROOT))] = sha(c3)
    for name, expected in receipt['files_sha256'].items():
        bound[str((c3.parent / name).relative_to(ROOT))] = expected
    cpu = HERE / 'build/i2s-v10-independent-review/inventory.json'
    assert sha(cpu) == '111c020d389bfcaab0088888bf85b1afc47bc62aeea14b00917e771bb48bfd8d'
    counts['cpu_independent'] = verify(cpu.parent, json.loads(cpu.read_text())['files_sha256'])
    bound[str(cpu.relative_to(ROOT))] = sha(cpu)
    formal = ROOT / 'outputs/rk3568-formal-dtb-20261005/sealed-v1/manifest.json'
    assert sha(formal) == '2ab968ebc6097fd03efe4e88dc2e845c38d8744f65c8816d3f1aeee6ac849a28'
    counts['formal_dt_files'] = verify(ROOT, json.loads(formal.read_text())['files_sha256'])
    bound[str(formal.relative_to(ROOT))] = sha(formal)
    package = ROOT / 'outputs/rk3568-audio-package-20261005/build/prepared-v1/receipt.json'
    assert sha(package) == '561c6d1e9422aefcb3f3a148c4ad486ef5b5679471984f0091e6285fed69e56c'
    prepared = json.loads(package.read_text())
    for name, meta in prepared['sources'].items():
        assert sha(ROOT / name) == meta['sha256'], name
        assert sha(package.parent / 'source-inputs' / name) == meta['sha256'], name
    for name, meta in prepared['evidence'].items():
        assert sha(package.parent / 'evidence' / name) == meta['sha256'], name
    counts['package_prepared'] = len(prepared['sources']) + len(prepared['evidence'])
    bound[str(package.relative_to(ROOT))] = sha(package)
    result = {'passed': True, 'counts': counts, 'files_sha256': bound,
              'verifier_sha256': sha(Path(__file__)), 'hardware_tested': False,
              'independent_runtime_reexecution': False}
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': True, 'counts': counts, 'output_sha256': sha(output)}))


if __name__ == '__main__':
    main()
