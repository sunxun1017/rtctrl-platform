# RK3568 原机 Wi-Fi 与网络 ADB 验证（2026-10-03）

用户授权通过电脑连接的串口，让原 Android 板接入电脑当前使用的同一路由。
本记录只保存核验结果和不含凭据的命令，不保存密码、设备唯一标识或原始串口流。

## 已验证结果

| 项目 | 本次结果 |
| --- | --- |
| Windows 当前 Wi-Fi | `<已脱敏：现场 SSID>`，WPA2-Personal |
| 实际串口 | CH340 / COM8，1500000 / 8N1，无流控，DTR/RTS=false |
| 板子原系统 | 3568A，Linux 4.19.232 |
| 板端 Wi-Fi | `<已脱敏：现场 SSID>`，`Supplicant state: COMPLETED`，2.4 GHz |
| 板端 IPv4 | `<板端当次 IPv4>/24`，接口 `wlan0` |
| Windows IPv4 / 网关 | `<主机当次 IPv4>` / `<网关当次 IPv4>` |
| 网络 ADB | `<板端当次 IPv4>:5555`，`adb devices -l` 显示 `device` |
| 网络 shell | `adb shell id` 返回 uid=0；读取内核版本和设备型号成功 |
| 文件传输 | `/proc/config.gz` 拉取成功，36644 字节，板端与主机 SHA-256 一致 |

地址和端口属于本次现场快照，下次操作必须重新核实。
本次查询发现 `service.adb.tcp.port=5555`，实际已有 `:::5555` 监听；没有修改 ADB 端口或认证设置。

## 实际操作与验收

1. 在 Windows 枚举串口并查看当前 Wi-Fi，确认本次为 COM8 和目标 SSID。
2. 串口收到 `console:/ $` 后，查询 `cmd wifi help`、`status` 和 IPv4。
   初始 Wi-Fi 已启用但未连接，仅有回环 IPv4。
3. 发起扫描，确认目标 SSID 的 2.4 GHz 和 5 GHz AP 均可见。
4. 通过关闭串口回显、在非交互 shell 中用 `read` 接收密钥的方式提交连接。
   真实密钥没有放入保存的命令或采集文件；原生 `cmd wifi` 仍需将密钥作为进程参数传入，
   不声称它消除了板端短暂的 argv 暴露。
5. 再次查询 Wi-Fi 状态、地址、监听端口，随后从 Windows 连接网络 ADB。
6. 使用 ADB 读取身份、版本，并拉取内核配置，分别计算 SHA-256。

不含凭据的板端核验命令：

```sh
su 0 cmd wifi status
su 0 cmd wifi start-scan
su 0 cmd wifi list-scan-results
su 0 cmd wifi list-networks
su 0 ip -4 addr
su 0 ip -4 route
getprop init.svc.adbd
getprop service.adb.tcp.port
su 0 netstat -lnt
su 0 sha256sum /proc/config.gz
```

Windows 验收使用本次实际安装的 `adb.exe`，执行连接、设备枚举、shell 和 pull。
本次拉取的本地文件为 `kernel.config.gz`，仅保留本地，由本目录 `.gitignore` 排除。

板端与主机共同得到：

```text
709d54fd7827fae674a8f03746529150038dff7fc493f558cb1e2fc51cc75fff
```

## 本次限制与恢复

- 板端到路由器 ping 3/3 收到应答；板端到 Windows 的 ICMP 无应答，
  Windows 初次 ping 板子也未成功。不据此认定 LAN 不通，因为后续 ADB TCP、shell 和文件传输已实际通过；
  ICMP 无应答的根因没有进一步调查。
- Wi-Fi RSSI 约 -79 到 -82 dBm。36644 字节文件单次 pull 用时 6.673 秒；
  此单次测量不是持续吞吐或大镜像传输性能结论。
- 配网期间将串口内核日志级别临时降低；结束后通过 ADB 确认已恢复 `7 4 1 7`。
- 本板 `stty -g` 输出的恢复字符串被 `stty` 拒绝，报 `not integer`，并出现输入标志变化。
  已根据操作前的 `stty -a` 逐项恢复，最终输入标志和回显与初始记录一致；未做该实现的源码根因核查。
- 先前约定的 `/data/local/tmp/linux-port/boot-original.img` 本次查询不存在。
  本轮没有提取完整 boot，也没有制作或写入启动镜像。
- 未重启板子、刷写 eMMC、格式化存储卡或发送电机命令。
  SD 实物卡座、U-Boot 串口加载能力及 USB 恢复入口仍需独立核实。

当前教学路线为复用原 4.19 内核和配套设备树，先启动最小 Linux 用户空间；
本次网络通道验证不代表 Linux 移植或恢复刷机验证完成。

## 官方参考

- [AOSP Android 11 Wi-Fi shell 命令](https://android.googlesource.com/platform/frameworks/opt/net/wifi/+/android-11.0.0_r1/service/java/com/android/server/wifi/WifiShellCommand.java)：
  解释扫描、连接和状态查询；板端实际 help 和结果是本次能力依据。
- [Android ADB 文档](https://developer.android.com/tools/adb)：解释网络连接、shell 和文件传输。
