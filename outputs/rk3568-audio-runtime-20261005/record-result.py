#!/usr/bin/env python3
"""Publish bounded acceptance facts from immutable private board evidence."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target = HERE / "result.json"
    if target.exists():
        raise ValueError("Refusing existing result")
    private = HERE / "private"
    before = json.loads((private / "android-before.json").read_text())["sections"]
    after = json.loads((private / "android-after-pcm.json").read_text())["sections"]
    keys = [name for name in before if name.endswith("_sha256")]
    if len(keys) != 7:
        raise ValueError("Missing protected partition/rootfs evidence")
    unchanged = {}
    for name in keys:
        for record in [before, after]:
            if record[name]["exit_code"]:
                raise ValueError("Failed hash collection")
        unchanged[name] = before[name]["output"] == after[name]["output"]
    if not all(unchanged.values()):
        raise ValueError("Protected input changed")
    interface = (private / "linux-interface-v2.raw.txt").read_text().replace("\r", "")
    closed = (private / "closed-state-v2.raw.txt").read_text().replace("\r", "")
    returned = (private / "return-android-v2.raw.txt").read_text().replace("\r", "")
    for marker in ["PCM_CONFIGURATION_AND_CLOSED_STATE_VERIFIED_NO_START",
                   "PCM_CLOCK_COUNTS_RESTORED_INACTIVE_RX_CONFIGURATION_RETAINED",
                   "PCM_RAM_ONLY_RESET_READY"]:
        if not re.search("(?m)^" + marker + "$", closed):
            raise ValueError("Missing closed-state evidence: " + marker)
    for stream in ["playback", "capture"]:
        if not re.search(r"(?m)^PCM_INFO card=1 device=0 subdevice=0 stream=" + stream + r" id=", interface):
            raise ValueError("Missing target PCM identity")
    if interface.count("PCM_STATE configured=SETUP appl_ptr=0 hw_ptr=0\n") != 2:
        raise ValueError("Both configured states not observed")
    if interface.count("PCM_STATE freed=OPEN\n") != 2:
        raise ValueError("Both freed states not observed")
    reset = re.search(r"\[\s*([0-9.]+)\] sysrq: Resetting", returned)
    if not reset:
        raise ValueError("Missing return reset")
    linux_return = returned.split("DDR ", 1)[0]
    if re.search(r"WARNING:|Call trace:|BUG:|kernel panic", linux_return, re.I):
        raise ValueError("Unexpected Linux return warning")
    if after["android"]["output"].strip() != "11" or after["boot_completed"]["output"].strip() != "1":
        raise ValueError("Android return not verified")
    evidence = ["android-before.json", "android-after-pcm.json", "linux-interface-v2.raw.txt",
                "closed-state-v2.raw.txt", "return-android-v2.raw.txt", "fd-baseline.raw.txt"]
    record = {"source_kernel_sha256": sha(ROOT / "outputs/rk3568-rcu-reset-20261004/Image"),
              "module_sha256": sha(HERE / "driver-modules-v1/modules/snd-soc-rk817.ko"),
              "pcm_tool_sha256": sha(HERE / "build/pcm-production-v1/pcm-config"),
              "board_tested": True, "pcm_parameters_both_directions_passed": True,
              "format": "S16_LE", "rate": 48000, "channels": 2,
              "period_size": 256, "periods": 4, "buffer_size": 1024,
              "configured_state": "SETUP, appl_ptr=hw_ptr=0", "freed_state": "OPEN; later closed",
              "runtime_after": "suspended", "controls_after": ["OFF", "MIC OFF", "Resume OFF"],
              "gpio148_after": "spk-ctl out hi ACTIVE LOW; same as before",
              "dma_after": "dma1chan2=fe410000.i2s:tx; dma1chan3=fe410000.i2s:rx; bindings same",
              "dma_descriptor_queue_directly_observed": False, "prepare_or_start_called": False,
              "pcm_frame_io_performed": False, "electrical_or_acoustic_acceptance": False,
              "selected_clock_rows_checked": 16, "clock_reference_counts_restored": True,
              "clock_configuration_not_restored": "RX frac/clk/mclk retain 12288000Hz; clk_rx parent rx_src -> rx_frac, all 0/0/0 counts",
              "original_full_interface_outcome": "pcm-rejected; retained, whole-clock-byte equality failed",
              "independent_readonly_closed_state_outcome": "closed-state-verified; no PCM retry or clock writes",
              "private_evidence_sha256": {name: sha(private / name) for name in evidence},
              "protected_sha256_unchanged": unchanged, "sysrq_reset_uptime_seconds": float(reset.group(1)),
              "normal_reboot_poweroff_tested": False, "android_return": "11 / 4.19.232 / boot_completed=1",
              "battery_before_percent": 87, "battery_after_percent": 81,
              "tun_settings_changed": False, "startup_partition_written": False}
    target.write_text(json.dumps(record, indent=2) + "\n")
    lines = [line for line in interface.splitlines() if re.match(r"^(PCM_|ALSA_CARD |ALSA_CONTROL |ALSA_CODEC_)", line)]
    (HERE / "pcm-configuration.txt").write_text("\n".join(lines) + "\n")
    print(json.dumps({"pcm_parameters": True, "independent_closed_state": True,
                      "protected_hashes_unchanged": len(unchanged), "battery_after": 81}))


if __name__ == "__main__":
    main()
