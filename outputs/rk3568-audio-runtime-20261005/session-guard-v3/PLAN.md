# 单向声音会话只读检查器 v3

主控本次新 RAM 现场确认 AMBA name 为 `fe550000.dmac`，v2 固定 `fe550000.dma` 造成身份拒绝。
此版只改生产字符串一个字符，保留所有生命周期与执行域门槛。原 501 模型及 parser/model driver
逐字节保留并在三环境复跑；实际生产 canonical_device/main 的受控 syscall 模型新增 13 项三环境。
先用 v2 生产源码重现 dmac 被拒绝、旧 dma 通过 canonical 的两项红例，再构建 v3。
模型输出与真实 sysfs 接受严格区分；不连接板、串口、ADB，不修改网络、TUN 或内核。
最终产物登记原版本 SHA 前后核回、静态 ELF、参数拒绝和对 v2 等长字节差异块。

仅离线开发。工具负责三个静止边界：`bound`（前置及每次 helper 退出后）、
`card-unbound`（主控已正常解除 card/codec）、`cpu-unbound`（主控已正常注销 CPU PCM 组件）。
工具读取只读 lifecycle 属性、PCM proc 状态、cached controls、clock 缓存引用计数和本次可见顶层 PID FD；
不调用 PCM ioctl，不读 MMIO、不发 PM 请求、不改控件、不挂载、不解绑、不卸载、不重启。

输入冻结为 CPU v10 的实际完整源码、DMA C3-review-v2/source 的 13 文件 manifest、
既有 alsa-inspect/pcm-config/pcm-transfer 契约、音频 DT 与 BusyBox52 清单。
实现使用静态 C，可在原有 BusyBox52/native PID1 v3 环境工作；Python 只用于宿主离线构建、
模型回归和 SHA 清单。模型只测试真实解析器，不声称板测或 DMA 硬停验收。

解析器拒绝缺字段、重复字段、未知字段、未知版本、尾随文本、errno、溢出和不稳定快照。
每一边界收集两次静止状态，两次必须相同。非零 sticky、未证明 STOP、软件/descriptor/lease
残留、quarantine 非零、相关 FD 或未知进程可见性均拒绝。

CPU 仍绑定时，v10 probe 持有唯一 HCLK 引用直到 cleanup/devres；因此 `hclk_lease=1`
及 hclk_i2s1_8ch enable/prepare=1 是明确例外。MCLK/数据时钟引用必须为零，CPU 退出后
HCLK 也必须为零。频率和父级保持允许，不把无引用的 RX 12.288MHz 配置认作仍在运行。
此内核 clk_summary 会进 get_rate_recalc/get_phase，可能调用 provider MMIO；工具因此只读取
16 个 clock 目录中的 clk_enable_count/clk_prepare_count/clk_protect_count 三个 debugfs u32，
不读取 summary/rate/phase。debugfs 由主控按既有流程只读挂载，检查器不挂载任何文件系统。

`allocated` 是 DMA 物理 channel 分配数量，不等于执行 owner。真实 generic PCM 注册即请求
tx/rx，close/card 解绑只停止/清理运行对象，组件注销才 release channel。绑定阶段的预期数
由主控按本次 live DT 和真实绑定明确给出；工具不内置初始 2。CPU 退出阶段才要求零。
本版限定 I2S1 的 tx/rx 都来自 dmac1（fe550000）的冻结 DT；换 DT/映射须先重新审查。

最终交付包含可读实机步骤、静态 AArch64 辅件、host/ASan/QEMU 解析器模型回归、
实际 BusyBox52 清单核对与全输入/输出 SHA。START 许可、完整 Image/codec ABI、加载身份、
本机电源/救援条件、最终 native 回 RAM 与 reboot 仍由主控人工分阶段裁决。

独立审查 v1 发现 UIO path alias 的分类缺口，v2 从 /proc/devices 的字符区域获取动态 uio major，
按字符 FD st_rdev 检查；每次扫描前后及整个会话两次注册表均须稳定，未知/冲突/读取失败拒绝。
无 uio 注册正常记录 absence；主控实际 integration-v1 config 已核 CONFIG_UIO=n，alias 只作模型缺口。
本次执行域为 fresh native 单线程 PID1/BusyBox 救援 shell/单线程 helper、无产品服务；不扩展线程扫描。
SIGALRM/失败不保证 inspector 同步回收，主控停止后续动作，只读收集并等待 PID1 收养/回收。
辅件与小日志仅暂存 /tmp/audio（native3 /tmp=8MiB exec tmpfs），只读 debugfs 用 /tmp/audio-debug；
/run=1MiB/noexec 不用于执行辅件，不改 mount flags，不把40MiB启动包复制到 tmpfs。
