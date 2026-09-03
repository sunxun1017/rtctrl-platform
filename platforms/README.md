# Platform profiles

Profiles follow one layout for every supported SoC and carrier:

```text
platforms/<soc>/common.env
platforms/<soc>/boards/<board>/profile.env
platforms/<soc>/boards/<board>/sdk.lock.env  # only when a vendor SDK is required
platforms/<soc>/boards/<board>/bsp/          # only board-specific overlays
```

`common.env` contains architecture and SoC-wide defaults. `profile.env` is the
single board entry point for userspace, kernel, DTB, and toolchain selection.
An optional `sdk.lock.env` records only vendor release provenance; it does not
duplicate board configuration. `scripts/check-linux-sdk.sh` verifies a local SDK
archive without importing its multi-gigabyte `repo` object store into this Git
repository.

The RV1126B Linux kernel is independently pinned as the public
`third_party/linux-rv1126b` submodule. The Alientek-only files live in
`rv1126b/boards/atk-dlrv1126b/bsp/kernel` and are applied to an ignored,
content-addressed working copy by `scripts/prepare-linux-kernel-source.sh`; the
public submodule therefore stays clean and updateable.

Kernel profiles are board-specific because a DTB, defconfig, BSP commit, and
physical wiring cannot be selected safely from the SoC name alone.

## RK3588 board profiles

The build system separates SoC-wide defaults from carrier-specific facts:

- `rk3588/common.env` selects ARM64, the cross-toolchain prefix, base defconfig,
  and real-time configuration fragments.
- `rk3588/boards/<board>/profile.env` pins a kernel Git commit and selects one
  DTB.
- generated kernels, modules, staged libraries, and manifests stay under
  ignored `.deps/`; no machine artifacts are committed.

`orangepi-5-max` is the first verified profile. It uses the official Orange Pi
5.10 RK35xx RT source because that exact tree contains its board DTS and enables
`ARCH_SUPPORTS_RT`; the non-RT 6.1 branch's RT fragment does not produce a
`PREEMPT_RT` ARM64 configuration at the audited commit.
This does not bind rtctrl's user-space architecture to Orange Pi.

To add another RK3588 board, copy the profile directory and provide a source
commit containing that board's DTS. Do not reuse the Orange Pi DTB merely because
the SoC is RK3588. Run `./scripts/cross-build-rk3588.sh --board NAME --plan`
before building, then verify the resulting kernel release against the target.

`bootstrap-aarch64.sh --install` uses distro packages when it has an interactive
Debian/Ubuntu root path. In a non-root environment with conda, it instead creates
an exact, Git-locked GCC 11 toolchain under `.deps/toolchains/aarch64-gcc11`;
the cross-build scripts discover that prefix automatically.
