# RK3568 源码 Linux Wi-Fi 对照（2026-10-04）

源码 5.10 内核、同源码编译的 bcmdhd 模块及源码联网工具已在实机完成
SDIO 枚举、固件加载、WPA2-PSK/CCMP 认证、DHCP 和网关 ICMP 通信。
**电脑到板子的 TCP 双向文件传输未通过，后续重连未完成认证并发生断开；整项网络验收仍为部分通过。**

测试结束已删除 RAM 认证文件、退出 WPA/传输进程、卸载模块；RAM/loop guard 通过后
用既有 SysRq 路径返回 Android 11。五个启动分区完整 SHA-256 前后一致，最后网络 ADB root 查询通过。
没有 saveenv、刷写启动分区或发送 MCU/电机命令。独立 Linux 的 PID1 全程在 RAM，本轮没有 Linux 块文件系统挂载。

机器结果见 [result.json](result.json)，脱敏读回见 [verification.txt](verification.txt)。
原始输出含板卡标识、SSID/BSSID 等环境资料，保留在忽略的 `private/`；公开结果只保存其 SHA。
口令及派生 PSK 没有写入宿主记录，板端认证配置仅位于 RAM，清理时确认不存在。

## 本轮恢复了什么

|层次|实测结果|边界|
|---|---|---|
|板级描述|独立 Wi-Fi DTS，90 项编译后审计、12 项故障注入拒绝|不复制 EVB 整板配置，不猜 SDIO 电源轨|
|SDIO|fe2c0000、4 bit，SDR104 实际 148.5 MHz；02D0:A9BF|本 Linux 枚举为 mmc2，不能沿用 Android 编号|
|主机驱动|新编译 bcmdhd.ko 真实加载、函数 1/2 绑定；284 个未定义符号全部有实际 vmlinux 导出|vermagic 相同还不够，Image 和完整配置也按 SHA/字节核对|
|芯片固件|611103 字节 firmware、2874 字节 NVRAM 打开成功；版本 7.45.96.150|firmware 仍为芯片二进制；NVRAM 是原板参数文本|
|联网用户空间|上游 wpa_supplicant 2.11、libnl 3.11.0、BusyBox 1.36.1、独立 C helper|本轮只验 WPA2-PSK；无 Android HAL/JNI/Jar/.so 依赖|
|网络|首次认证 COMPLETED，DHCP IPv4/默认路由/DNS 地址配置成功，网关回应|未验证实际 DNS 解析、互联网/TLS或长期运行|
|电脑互通|两次 TCP 连接超时，未生成成功的传输结果；双方到对端的 ARP 未解析|没有板端文件 SHA 往返成功结论|
|收尾|模块、wlan0、测试进程均已消失，认证文件删除；回到原 Android/root|SysRq 即时复位不等于正常 reboot/poweroff/MCU 生命周期验收|

Wi-Fi 片段来自原机证据：GPIO2_B1 active-low 为 SDIO pwrseq reset，
GPIO2_B2 active-high 为 host-wake，时钟引用 RK809 的第二个 32 kHz 输出。
原运行树的 `wifi_chip_type="ap6398s"` 保留为已有驱动配置输入；它不能单独证明实装模组型号。
实际 OTP/固件请求选择 AP6256/BCM43456c5 路线。UART0、I²C5/MCU 继续禁用。

## 构建输入与入口

Image 沿用 [RCU 修正板测](../rk3568-rcu-reset-20261004/README.md) 的已验证产物，
源码 commit 为 `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`，GCC 11.4，
release 为 `5.10.160-rt89-g9f9e9d18574d-dirty`。
本轮没有重新编译 Image；新增第四补丁只修 bcmdhd 在 `O=` 构建中的头文件路径。
前三项 Image 补丁与第四项模块构建补丁暂时应用，构建后第三方源码已恢复干净。

|实测启动输入|字节数|SHA-256|
|---|---:|---|
|Image|34755072|e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457|
|Wi-Fi DTB|162422|3341cf513036528aaa0abd3b6c1fd0bc55cdb1dafe8b667c8431c03ae3b7d383|
|initramfs v5|4014387|1fad91e3926db3ee58088be4e27271e6ed56d3763bd49dd152f52e09c3873c7d|
|bcmdhd.ko|5169288|cbf55f844b59a57fb4ff67c1754df09dcee716a6385dbb463cce1ae846e4d956|
|最终 network-helper|652080|b713e277bfcd25384975acb31253254b93bdad4a70e529b403368f6dbb4dc6f6|

源码、构建/测试脚本和有效归档成员的最终 SHA 绑定于 `result.json`。
`module-check.json` 保留静态构建检查的 `board_loaded=false`，真实板测状态单列在最终结果，
不回写旧构建清单。旧 `ramfs-inputs*.json` 是各次准备的历史输入，不能当最终 helper 的源码清单。

在项目根目录的 Linux/WSL 环境执行以下入口；它们使用已准备的交叉工具链、DTC/CPIO/QEMU，
默认拒绝覆盖已有构建目录或模块。复测使用新目录，先保留已有证据。

```sh
python3 platforms/rk3568/boards/aiot-3568pq/build-firstboot.py \
    --variant wifi \
    --kernel third_party/linux-rk3588 \
    --dtc .deps/kernel/aiot-3568pq-rcu-reset/scripts/dtc/dtc \
    --output outputs/rk3568-source-wifi-20261004/build/dtb-v3

sh outputs/rk3568-source-wifi-20261004/build-module.sh
python3 outputs/rk3568-source-wifi-20261004/verify-module.py

sh outputs/rk3568-source-wifi-20261004/build-network-tools.sh
python3 platforms/rk3568/boards/aiot-3568pq/test-wifi-audit.py \
    outputs/rk3568-source-wifi-20261004/build/dtb-v3/rk3568-aiot-3568pq-wifi.dtb
```

模块构建必须沿用上述 Image 的实际构建目录、配置和导出符号表，不能换一份同名 release 的 Image。
联网工具源码归档校验值和版本固定在 `build-network-tools.sh`，上游入口为
[wpa_supplicant 2.11](https://w1.fi/releases/wpa_supplicant-2.11.tar.gz) 与
[libnl 3.11.0](https://github.com/thom311/libnl/releases/download/libnl3_11_0/libnl-3.11.0.tar.gz)。
本地归档的 `.proxy.tar.gz` 只是本次下载文件名；脚本不修改系统代理。
`wpa-LICENSE`、`libnl-LICENSE` 保留上游说明；BCMDHD 保留源码自身许可证，不改标成本项目 MIT。

两份原板固件必须从已授权的本机备份取得并核对 SHA，脚本不下载、不猜造、也不发布固件。
firmware SHA 为 `06d3bebe4b193b5db97b7f99bde94e2e85ca95dc35677079ecf86f8f9b0eb734`，
NVRAM SHA 为 `c36643f35c32b9248bbb34870a3ab152237907713e999533592acd925dd04410`。
新完整归档可通过 `prepare-initramfs.py --revision v6` 等未用修订号生成，
但必须重新计算加载范围/CRC/SHA并重新板测，不能冒称就是本次的 v5。

本次 v5 为已上传的初始 gzip/newc 加一个最终 helper-only gzip/newc；
`prepare-overlay.py` 固定检查旧基底 SHA，用于本轮减少传输，不是任意新归档的通用升级器。
有效成员按后者覆盖，记录器已核对最终 helper、WPA、模块、init 和 DHCP 脚本与源产物一致。
固定输入与构建步骤便于追查和重建功能；没有跨机器、跨时间逐字节可复现的验收结论。
模块 debug 信息仍有宿主构建路径，不能宣称二进制已全面脱敏。

## 板端验证顺序与本轮修正

1. 原 Android 只读确认 root、完整配置/SDIO/固件/五个启动分区 SHA。
2. 新普通 cache 文件上传并校验，U-Boot 逐项加载 CRC，再仅在 RAM 修改 FDT/环境和 booti。
3. `linux-wifi-device.json` 验 SDIO、模块、固件与 wlan0；固件路径设置在 PID1 可见的 RAM namespace。
4. helper 暂停串口回显接收派生凭据，生成 0600 RAM 文件；终端输入没有被采集到宿主日志。
5. `linux-wpa.json` / `start-wifi.sh` 所示顺序完成配置适配、WPA 启动和状态读回，再 DHCP/网关/传输。
6. `linux-cleanup.json` 要求认证文件、模块、接口和测试进程均已消失；`return-android.json` 再独立验 RAM/loop。
7. Android 再次完整比较启动分区 SHA，恢复 printk 7/4/1/7，确认 kptr_restrict=2。

最小 WPA 构建没有 `CONFIG_DEBUG_FILE`，因此不支持 `-f`；使用 shell 重定向记录日志。
`CONFIG_NO_CONFIG_WRITE=y` 连 `update_config=0` 也不解析，启动前删除该行。
标准 helper 输出继续保留这行，便于明确区分凭据接收与此最小构建的配置适配。
`start-wifi.sh` 是相同流程的公开脚本，本次实际发送等价命令，**它没有打包在实测 initramfs 内**。
静态 glibc 链接有 NSS 相关警告；本轮数值地址/WPA2 路径实测可用，没有所有解析或认证功能的兼容承诺。

最小 BusyBox 的 `ping` 不接受 `-c`，本轮原命令失败后改为单次 `ping <网关>`，实际获得 alive 回应；
`ip` 没有 neighbor 子命令，邻居读回使用 `/proc/net/arp`。失败尝试没有计入成功结果。
helper 的 QEMU/真实 PTY 测试覆盖回显恢复、半行输入后 SIGINT/TERM/HUP 清空输入队列、
拒绝覆盖已有文件、传输断开删除部分文件和本地双向内容一致；QEMU TCP 成功不能代替真机无线传输。

Android 网络 ADB 在准备期间间歇超时，最终小型 helper overlay 改经串口上传。
两次 Base64 大段输入的板端内容变成了小写，与将 Base64 全部转小写后的解码 SHA 完全相符；
具体发生在哪一层仍未定位。最终用小写 hex/xxd 完成，字节数与 SHA 在板端重读确认一致。
第一次 hex helper 采集等待过短导致工具早报失败，随后原始输出及独立重读都确认 digest 正确，
不能把工具超时写成传输文件损坏；公开叠加输入以最终 SHA 为准。

## 网络未通过项与接续条件

最初固件从 5 GHz 自动漫游至 2.4 GHz，认证和 DHCP 成功；之后信号读回变为约 −79 dBm。
板子能回应网关，双方到对端 ARP 没有完成；Windows 18765/TCP 两次连接超时。
临时 RAM BSSID 限制没有阻止固件再次漫游，WPA 停在 ASSOCIATED；
随后直接选择 2.4 GHz 重连时，观察到 −87/−86 dBm、停在 ASSOCIATED 及连接失败/断开。
已采集输出没有明确的认证超时原因，不能把这些状态认作已定位的四步握手超时。
这些观察不足以确定是天线/信号、接入点转发隔离、漫游/固件或驱动问题。
未修改路由器、Windows 防火墙、代理、TUN 或 Android 持久认证配置。

收尾 Android 报告电量 22%、AC/USB powered=false。下一轮先重新核实供电和天线/链路条件，
复测局域网 ARP 与固定 64 KiB 双向 SHA，再把同一套源码工具纳入正式 rootfs。
最后一次 Android 网络 ADB root 可用只是当时快照，不保证下次仍可连接。
正式 rootfs 自启动、普通 reboot/poweroff、MCU/watchdog、电机、蓝牙、Wi-Fi 休眠、实时性与长时稳定仍未验收。
芯片 firmware、原 DDR/loader/trust 与 MCU 固件缺口保持单列，不宣称完整整机已开源。
