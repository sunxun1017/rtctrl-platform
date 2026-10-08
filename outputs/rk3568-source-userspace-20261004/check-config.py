#!/usr/bin/env python3
"""Check the resolved firstboot Kconfig, not just the fragment text."""
import importlib.util
from pathlib import Path
import sys

repo = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("config", repo / "scripts/prepare-linux-config.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
actual = module.settings(Path(sys.argv[1]).read_text())
disabled = ["ROCKCHIP_MULTI_RGA", "ARM_SCMI_POWER_DOMAIN", "RESET_SCMI", "CHARGER_RK817"]
required = ["ARM_SCMI_PROTOCOL", "COMMON_CLK_SCMI", "COMMON_CLK_ROCKCHIP", "CLK_RK3568",
            "RESET_CONTROLLER", "MFD_RK808", "REGULATOR_RK808", "REGULATOR_FAN53555",
            "ROCKCHIP_IODOMAIN", "ROCKCHIP_THERMAL", "MMC_SDHCI_OF_DWCMSHC",
            "BLK_DEV_LOOP", "EXT4_FS", "DEVTMPFS", "UNIX98_PTYS"]
for name in disabled:
    assert actual.get("CONFIG_" + name, "n") == "n", f"Unused driver still enabled: {name}"
for name in required:
    assert actual.get("CONFIG_" + name) == "y", f"Required built-in missing: {name}"
assert actual.get("CONFIG_SECURITY", "n") == "n", "Security policy requires a separate review"
print(f"PASS: {len(disabled)} unused drivers disabled, {len(required)} required built-ins retained")
