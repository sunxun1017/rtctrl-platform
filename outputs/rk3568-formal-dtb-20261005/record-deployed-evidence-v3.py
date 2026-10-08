#!/usr/bin/env python3
"""Bind existing deployment review and selected actual RAM-boot log facts without board access."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def main():
    raw_path = ROOT / 'outputs/rk3568-pid1-20261005/private/audio-v3-boot-20261006-v1.raw.txt'
    raw = raw_path.read_bytes()
    rows = raw.decode('utf-8').splitlines()
    exact = ['=> bootm 20000000', 'DTB: arch/arm64/boot/dts/rockchip/rk3568_smdt_3568a_v20.dtb',
             'ANDROID: fdt overlay OK', 'ANDROID: Hash OK', 'Booting IMAGE kernel at 400000 with fdt at a100000...']
    excerpts = []
    for wanted in exact:
        found = [(number, line) for number, line in enumerate(rows, 1) if line.strip() == wanted]
        assert len(found) == 1, wanted
        excerpts.append({'line': found[0][0], 'text': found[0][1]})
    refs = ['outputs/rk3568-boot-package-20261005/FORMAL-EARLY-REVIEW.md',
            'outputs/rk3568-boot-package-20261005/PLAN-v2.md']
    report = {'status': 'EXISTING_DEPLOYMENT_EVIDENCE_REFERENCED_ONLY',
              'raw_reference': {'path': raw_path.relative_to(ROOT).as_posix(), 'bytes': len(raw), 'sha256': sha(raw)},
              'selected_exact_lines': excerpts,
              'references_sha256': {rel: sha((ROOT / rel).read_bytes()) for rel in refs},
              'deployed_uboot_image_sha256_from_existing_binary_review': '4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e',
              'early_path_from_existing_deployed_binary_review': {'board_init_resource_read': '0xa04480 -> 0xa05030', 'gd_replace_DM_rebuild': '0xa050f8'},
              'late_component4_from_existing_deployed_binary_review': {'branch': '0xa28b3c', 'env_fdt_addr_r_vs_gd': '0xa28b54', 'different_reloads_RSCE': '0xa28b5c -> 0xa0379c'},
              'deployed_emmc_match_object_from_existing_review': {'driver': '0xb210d0', 'oftable': '0xae93f8', 'probe': '0xa4f198', 'compatible': 'snps,dwcmshc-sdhci'},
              'actual_ram_boot_log_overlay_success_once': True,
              'log_proves_new_bridge_candidate_early_DM': False,
              'failure_swallowing_is_existing_review_not_exercised_in_this_log': True,
              'exact_deployed_overlay_disassembly_reproduced_here': False,
              'kernel_real_libfdt_does_not_claim_exact_deployed_binary': True,
              'board_access': False, 'script_sha256': sha(Path(__file__).read_bytes())}
    out = HERE / 'build/deployed-evidence-v3'
    out.mkdir(parents=True, exist_ok=False)
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n', newline='\n')
    print(json.dumps({'selected_lines': len(excerpts), 'raw_sha256': sha(raw), 'board_access': False}))


if __name__ == '__main__':
    main()
