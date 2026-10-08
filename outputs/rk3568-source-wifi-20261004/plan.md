# 源码 Linux Wi-Fi 对照

沿用已板测的 RCU 修正 Image，复原独立 SDIO/Wi-Fi 板级节点，编译同源码/配置的 bcmdhd 模块。
用户空间使用从上游源码编译的 wpa_supplicant、libnl 和已有 BusyBox；不复用 Android HAL/JNI/.so。
WPA2-PSK 为本次网络验收范围，芯片固件和板级 NVRAM 单独保留二进制依赖与 SHA。

1. 重新核实 Android/root/电量、SDIO 绑定与固件 SHA。
2. 编译并审计 Wi-Fi DTB；既有 firstboot 基础检查保持原样。
3. 同内核构建模块，确认所有未定义符号在实际 vmlinux 导出表闭合；交叉编译静态联网工具。
4. 上传新普通 cache 文件并校验 SHA；RAM 启动，不改启动分区或保存 U-Boot 环境。
5. 按 SDIO→模块/固件→接口→WPA→DHCP→双向文件 SHA 验证；认证只在 RAM 临时使用，不写日志。
6. 清理服务/模块/临时认证与挂载，按已验证的 RAM SysRq 路径返回 Android并比较启动分区 SHA。

未验收：正式 rootfs 自启动、正常 reboot/poweroff、MCU/电机、休眠、实时性及长时稳定性。
