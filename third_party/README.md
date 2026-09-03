# Third-party source policy

Third-party source is kept outside the main repository history and pinned by a
Git submodule entry. Clone or restore it with:

```bash
git clone --recurse-submodules <rtctrl-platform-url>
# or, in an existing checkout:
git submodule update --init --recursive
./scripts/check-third-party.sh
```

| Path | Upstream | Pin | License | Required by default build |
| --- | --- | --- | --- | --- |
| `igh-ethercat` | `https://gitlab.com/etherlab.org/ethercat.git` | `1.6.12` / `381577314d1bedc14e156512616f6dd31fb52c88` | GPL-2.0 and LGPL-2.1 components; see upstream files | No |
| `linux-rk3588` | `https://github.com/orangepi-xunlong/linux-orangepi.git` | `orange-pi-5.10-rk35xx-rt` snapshot / `9f9e9d18574d0914c0d192a90c3babfe1fd63c95` | GPL-2.0; see upstream files | Only for the verified Orange Pi 5 Max kernel profile |

The main library does not download dependencies while CMake is running. IgH is
only used when `RTCTRL_ENABLE_IGH_ETHERCAT=ON`; the default build and the serial,
Dynamixel, and SocketCAN CAN-FD paths do not link to a vendor SDK.

Do not commit generated IgH files, kernel modules, installation prefixes, or a
machine sysroot. Those artifacts depend on the target kernel and toolchain and
belong under ignored `build/` or `.deps/` directories. The Git pin makes source
reproducible; it cannot make a kernel module portable across kernel releases.

The kernel submodule is a verified starting point, not a claim that one vendor
kernel image supports every RK3588 carrier. Board selection lives in
`platforms/<board>/profile.env`; another board may override the kernel source,
commit, defconfig, fragments, and DTB without changing the build scripts.
