# RK3568 随机数与源码 Linux 网络验证

2026-10-04，硬件随机数驱动与认证前的 CRNG 就绪检查通过。
源码 Linux 5.10 在 `PM=0`、仅 5 GHz 的条件下，完成电脑到板子再回电脑的 64 KiB TCP 传输，
上传、板端文件和回传 SHA-256 全部一致。收尾返回 Android 11，电量实测 60%，
五个启动分区和现有 rootfs 文件的完整 SHA 未变。机器结果见 [result.json](result.json)。

## 实际使用的启动输入

沿用已经板测的 Image 和 v5 initramfs，独立 DTB 只启用 `rng@fe388000`。
U-Boot 逐项检查读取长度与 CRC，在 RAM 修改 chosen/保留项后启动；没有 `saveenv` 或刷启动分区。

| 输入 | SHA-256 | 实机装载 CRC |
|---|---|---|
| Image | e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457 | c91762d1 |
| 新 Wi-Fi/RNG DTB，162418 字节 | ab0893cea485cb9972d93dfb3eaa61ec955cbf4314a3f0f39c43b418249e8035 | e58748ee |
| v5 initramfs | 1fad91e3926db3ee58088be4e27271e6ed56d3763bd49dd152f52e09c3873c7d | 816d3445 |

cache 仅以 `ro,noload` 挂载，用于校验并拷贝检查工具到 RAM，随后卸载。
实际 `fe388000.rng` 绑定 `rockchip-rng`，`rng_current=rockchip`；
内核在 0.749178 秒报告 `crng init done`，认证之前以及传输之后的单次
`getrandom(1, GRND_NONBLOCK)` 均成功。驱动质量声明 999 不等于随机统计质量验证。
[检查工具源码](entropy-check.c)、[独立构建及主机测试](entropy-manifest.json) 保留构建时边界，
其中 `board_tested=false` 是构建时状态；本轮实际板测结果另列于 result。

## 三组网络结果

所有组使用相同内核、DTB、BCMDHD 模块、原机 firmware/NVRAM 与源码 WPA/helper。
各组之间停止自己的进程、删除 RAM 凭据并卸载模块，重新启动与认证。

| 组 | 实际配置与连接 | DHCP/网关 | 电脑 TCP |
|---|---|---|---|
| 默认 | 没有配置文件；先 5220 MHz，后自动转到 2437 MHz | 通过 | 连接超时，电脑邻居未解析 |
| PM0 | RAM `/lib/firmware/config.txt` 仅 `PM=0\n`，5 字节；实际解析 PM=0，仍转到 2437 MHz | 通过 | 连接超时 |
| PM0 + 5 GHz | 同文件增加 `band=a\n`，12 字节；解析 `band=1`，本轮保持 5220 MHz | 通过 | 64 KiB 双向传输通过 |

实际上传、板端、回传 SHA：
`7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2`。
第三组电脑 ARP Flags 含 `0x2`，Windows 选择当前 Wi-Fi 路由；
板到电脑 ICMP 无回复，但实际 TCP 成功。没有修改 Windows 防火墙、代理或路由器。

该结果证明这一连接窗口可传输，不能把频段限制认作此前 ARP 问题的已确认根因。
两组有不同 RSSI、不同 AP/频段与时间条件；没有完成长时间、重连、休眠或吞吐验收。
PM=0 日志证明配置解析与驱动调用路径，没有读回固件当前 PM。
`band=a` 是源码配置名；`band=1` 不具有相同配置含义。

## 找到并独立修正的 BusyBox 问题

最初 `config_path=/rtctrl-pm0.txt` 没有生效，那个尝试没有进行认证，单独保留记录。
原因是实际 BusyBox 1.36.1 关闭 `FEATURE_CMDLINE_MODULE_OPTIONS`：
`parse_cmdline_module_options` 被展开为空字符串，`insmod` 的 FW/NVRAM/config 参数都没有进入内核。
驱动按照默认选择正确固件，不能把旧轮写成这些参数已经生效。

旧二进制 SHA：`5c2f1c653fdfe92d21c5baa68a64a460dd9aff3b8947d526048314700e1d5844`。
本轮网络测试仍沿用它，通过默认配置文件路径完成受控实验。

已经独立编译修正版本，唯一配置语义变化是该选项 `n→y`：

```sh
python3 outputs/rk3568-rng-network-20261004/build-busybox-module-options.py
```

新产物 1202816 字节，SHA：
`514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1`。
静态 AArch64、QEMU shell、51 个 applet 检查通过。
用旧/新真实 BusyBox 对象另行链接 syscall mock：旧版实测丢参数；
新版无参数、单参数、多参数、finit→init 回退 4 项传递测试通过。
mock 不转发真实模块系统调用，正式产物没有 mock。
来源、配置完整差分和测试绑定见 [manifest](busybox-module-options-manifest.json)。
新 BusyBox 尚未上板，也没有替换已验证的 rootfs/v5。

## 收尾与复现边界

所有实验组的 WPA/helper、凭据、接口、模块与本轮配置均已释放。
两个清理脚本版本分别有 11 项失败/重试 mock 检查与真实失败 red；
v3 两行配置的清理另经只读审查和实际板测。
失败清理会汇总失败并停留 Linux，复位入口另检查网络零残留、RAM 文件系统和 loop。
Linux PID1 保持 `/bin/sh /init`，最后只有 rootfs/devtmpfs/proc/sysfs/tmpfs，未 `switch_root`。
1080.849940 秒执行 SysRq 返回 Android；所捕获的源码 Linux dmesg 没有 WARNING/BUG/Call trace。

Android 最终 root、`boot_completed=1`、网络 ADB 可用，`printk=7/4/1/7`、`kptr_restrict=2`；串口已释放。
现有 rootfs 文件 SHA 仍为 `32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3`。
未操作电机或 MCU，普通 reboot/poweroff、完整 eMMC 裸机恢复仍未验收。
firmware/NVRAM 是本机私有二进制输入，许可缺口单列，没有把它们重新标为开源。

原始网络标识、串口和 Android 证据留在忽略的 `private/`；凭据仅在内存传送和板端 RAM 文件中使用。
`record-result.py` 从这些证据核验后生成不含网络标识或密钥的公开结果。
构建目录也忽略；构建器和测试拒绝覆盖已有记录。

下一步把修正后的 BusyBox、RNG 检查以及这轮已验证的网络启动顺序纳入独立新版 rootfs，
先验证新 BusyBox 在板端实际传递模块参数，再推进 Linux 正式启动入口与其他外设。
