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

The main library does not download dependencies while CMake is running. IgH is
only used when `RTCTRL_ENABLE_IGH_ETHERCAT=ON`; the default build and the serial,
Dynamixel, and SocketCAN CAN-FD paths do not link to a vendor SDK.

Do not commit generated IgH files, kernel modules, installation prefixes, or a
machine sysroot. Those artifacts depend on the target kernel and toolchain and
belong under ignored `build/` or `.deps/` directories. The Git pin makes source
reproducible; it cannot make a kernel module portable across kernel releases.
