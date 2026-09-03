# Platform profiles

Linux userspace profiles describe portable CPU/ABI build inputs without
claiming support for a particular carrier's kernel or peripherals.
`atk-dlrv1126b/userspace.env` is the first such profile and is consumed by
`scripts/cross-build-linux-userspace.sh`. Its support and validation boundary is
documented in `docs/rv1126b.md`. The adjacent `sdk.env` locks the vendor SDK
release and manifest commit; `scripts/check-linux-sdk.sh` verifies a local SDK
archive without importing its multi-gigabyte `repo` object store into this Git
repository.

Kernel profiles are board-specific because a DTB, defconfig, BSP commit, and
physical wiring cannot be selected safely from the SoC name alone.

## RK3588 board profiles

The build system separates SoC-wide defaults from carrier-specific facts:

- `rk3588/common.env` selects ARM64, the cross-toolchain prefix, base defconfig,
  and real-time configuration fragments.
- `<board>/profile.env` pins a kernel Git commit and selects one DTB.
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
