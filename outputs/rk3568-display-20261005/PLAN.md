# RK3568 显示独立候选：离线实现与验收

本候选继承已实测 UART/RNG DT；音频、I2C5、SPI3 与 MCU 不在该候选中启用。
所有构建产物保存在 `build/dtb-vN/`，已有目录拒绝覆盖。v5已在排线断开、亮度0范围上板，
74项只读接口与正常reboot返回通过；实际画面、电气背光、suspend/resume仍未验，见 [README.md](README.md)。

## 构建与核查

从仓库根目录执行：

```sh
python3 outputs/rk3568-display-20261005/build-dtb.py --revision v6
```

构建器读取一次锁定 kernel 的提交及工作区状态，核对已测 Image、配置、UART DTB，
以实际 CPP 输入、DTC、源码与审计脚本 SHA 记录可复现输入。v1–v5 为已有验证产物，
复现时改用未存在的新 revision（例如 v6）。
`--compile-only` 仅生成预处理源码和 DTB，不等同审计通过。

完整构建运行真实 CPP→DTC、公开审计脚本及逐项故障 DTB 测试；错误候选也保留。
审计比对所有属性，只接受明确列举的显示新增/替换属性和两个 loader memory-region 属性删除。
原 760 个 phandle、保留内存、memreserve 与其余属性必须不变；新 phandle 必须高于原最大值。

## 原机证据与候选选择

证据为 `outputs/android-board-20260928/android-live-tree.dts:5931` 的 DSI0，
及 SHA 锁定的 `live-sorted.dtb`。候选使用 5.10 SoC 节点定义，避免套用 Android 4.19 的 clock/PHY ID。

- VP1→DSI0，VP0 输入禁用；VOP2、VOP MMU、DSI0、video PHY0、PWM4 与 display-subsystem 启用。
- 720×720，35.5 MHz；水平前肩/同步/后肩 24/2/30，垂直 16/2/8；四项极性均 0。
- DSI 4 lanes、RGB888、flags `0xa03`：VIDEO、BURST、bit9 EOT、LPM；没有 bit10 非连续时钟。
- 完整 init 为 898 字节、180 条命令、内置累计延时 596 ms；exit `05 00 01 28 05 00 01 10`。
- reset GPIO0_A5 低有效，enable GPIO0_C5 高有效；固定 3.3 V 的 LCD regulator 来自 vcc3v3_sys，无 GPIO。
- prepare/reset/init/enable/disable/unprepare 延时 50/120/120/220/120/120 ms。
- PWM4 GPIO0_C3 mux1，无 pull，周期 25000 ns，通道 0、flags 0。
  原机 256 项亮度表逐字节保留；v5 初始值改为 index0，对应 duty0/255。
  用户确认屏幕排线已拔下，本轮不写亮度；接回屏幕后须取得新鲜的完整初始化证据，再显式设置亮度。

原 loader logo 长度 `0x2f7b00` 未页对齐，保留其 reserved-memory 范围，但删除 display-subsystem
的 `memory-region` / `memory-region-names`，所有 loader route 保持禁用。
这会触发预期的 loader logo 跳过告警；本候选不承诺零告警。

## 验证边界

manifest 始终标记 `board_tested=false`、`deployable=false`。
离线审计不能证明屏幕点亮、电气电平、DSI 数据传输、退出断电、亮度观感或 suspend/resume。
本轮只证明 DT 编译、原始参数/资源映射及严格属性边界；驱动错误传播由主任务另行实现和验证。

## 本轮离线结果

v1 首次编译因单 port 的冗余 address/size cells 新增告警而拒绝。
改用标准单 `port` 表示后，v2 编译、70 项精确属性差分与 102 个真 DTB 故障拒绝通过。
v3 压缩审计中重复的 phandle/命令结构记录并重新完整验证，面板字节及 DTB 不改变。
v4 增加保持序列长度、命令数甚至累计延时不变的 init 字节突变，以及保持亮度表长度的非默认档突变；
106 个真 DTB 故障均由审计脚本拒绝，250 项审计通过。
原 SoC DTS 的 18 种既有 DTC 告警仍存在，没有新增 DTC 告警。

v4 历史 DTB SHA256：`ac5a374c897ffed65306b5367a1ed2a35703ccd26d38fcd45c57dcc4067910a3`，166090 字节。
v5 改默认亮度为0，250项审计、107个真实故障DTB拒绝；保留70项差分与既有警告边界。
v5 SHA256：`650228482eaed6f95d9892fce217f436072d851cc47398696d52b85e08200f70`，166090 字节。
机器证据：`build/dtb-v5/{manifest.json,audit.json,fault-tests.json,dtc.log}`。

成功的 PWM probe 将占空比清零，但可保留 enabled；软件占空比0不能代替电气熄灭测量。
DSI bridge忽略prepare返回，模式枚举也不证明初始化成功。新补丁提供完整初始化完成诊断；
其含义仅是host接受全部命令，不是面板应答。早期v1/v2补丁按payload长度判断成功的假设已被真实
DSI host函数链否决，不能部署。最终候选撤销正返回值长度假设，只传播负errno。
