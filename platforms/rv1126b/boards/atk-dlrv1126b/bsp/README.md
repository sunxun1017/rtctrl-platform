# ATK-DLRV1126B BSP overlay

This directory contains the minimum board files required on top of the pinned
public Rockchip Linux 6.1 kernel. Files retain their upstream SPDX identifiers
and were derived from the vendor SDK release locked by `../sdk.lock.env`. Only
non-semantic whitespace is normalized to satisfy this repository's checks.

The overlay currently contains the normal 720x1280 board variant selected by
the vendor's default automatic-MIPI profile:

- `alientek_rv1126b_defconfig`;
- `rv1126b-alientek.dtsi`;
- `rv1126b-alientek-mipi720x1280.dts`;
- `rv1126b-alientek-mipi720x1280-ov13850-csi1.dts`, an opt-in variant for an
  ATK-MCOV13850 connected to the board's CSI1 connector.

The CSI1 camera variant maps the connector to I2C4, CSI2 D-PHY3 and MIPI2 CSI2,
as defined by the vendor board file. It uses two CSI-2 data lanes because the
pinned OV13850 driver is fixed to two lanes. The existing default DTB remains
the platform default and is not changed by this variant.

Build the opt-in camera DTB with:

```sh
./scripts/prepare-linux-kernel-source.sh \
    --platform atk-dlrv1126b \
    --build-dtb \
    --dtb rockchip/rv1126b-alientek-mipi720x1280-ov13850-csi1.dtb
```

Install the maintained BSP overlay into a verified vendor SDK and generate a
dedicated SDK configuration without modifying the vendor board configuration:

```sh
./scripts/prepare-linux-kernel-source.sh \
    --platform atk-dlrv1126b \
    --sdk-root /absolute/path/to/atk_dlrv1126b_linux6.1_sdk \
    --install-overlay \
    --dtb rockchip/rv1126b-alientek-mipi720x1280-ov13850-csi1.dtb
```

Replace `--install-overlay` with `--build-sdk-kernel` to install the overlay,
select the generated `99_rtctrl_atk_dlrv1126b_defconfig`, and build the SDK
`output/firmware/boot.img` in one command. Use `--plan` first to validate and
show the resolved paths without changing the SDK.

The reset and power GPIOs follow the existing CSI1 definitions in the vendor
BSP. Confirm the connector schematic and the exact module/lens identity before
deploying; the placeholder lens name must also be aligned with the production
RKAIQ tuning file.

It intentionally excludes generated firmware, binary downloads, root filesystems,
ISP tuning data, and alternative display/AMP/IPC variants. Those remain in the
version-locked vendor SDK until their redistribution terms and runtime need are
clear.

`scripts/prepare-linux-kernel-source.sh` creates a local clone from the public
kernel submodule below `.deps/`, copies this overlay into that clone, and can
compile the selected DTB. The public submodule is never patched in place.
