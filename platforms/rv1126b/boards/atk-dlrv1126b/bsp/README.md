# ATK-DLRV1126B BSP overlay

This directory contains the minimum board files required on top of the pinned
public Rockchip Linux 6.1 kernel. Files retain their upstream SPDX identifiers
and were derived from the vendor SDK release locked by `../sdk.lock.env`. Only
non-semantic whitespace is normalized to satisfy this repository's checks.

The overlay currently contains the normal 720x1280 board variant selected by
the vendor's default automatic-MIPI profile:

- `alientek_rv1126b_defconfig`;
- `rv1126b-alientek.dtsi`;
- `rv1126b-alientek-mipi720x1280.dts`.

It intentionally excludes generated firmware, binary downloads, root filesystems,
ISP tuning data, and alternative display/AMP/IPC variants. Those remain in the
version-locked vendor SDK until their redistribution terms and runtime need are
clear.

`scripts/prepare-linux-kernel-source.sh` creates a local clone from the public
kernel submodule below `.deps/`, copies this overlay into that clone, and can
compile the selected DTB. The public submodule is never patched in place.
