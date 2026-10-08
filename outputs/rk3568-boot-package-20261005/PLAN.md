# RK3568 原始 boot v2 离线重建与审计计划

> 实施方式：当前 agent 顺序执行红绿验证；主控负责独立审查与现场操作。所有写入仅在本新目录，旧 PID1 与备份产物只读。

**目标：** 锁定公开 AOSP 工具，解析原始 40 MiB boot 分区备份，以原组件调用官方打包函数重建，证明逐字节一致，并提供资源与 DTB 清单。

**架构：** 独立审计程序读取 Android v2 header、组件、填充、SHA1 ID、RSCE 和 concatenated DTB。原包 builder 只接受锁定原备份与源码，导出组件，使用官方函数生成 raw 包后零填充至 40 MiB。先冻结原包结果，再独立构建主控已裁决的 RAM Linux 候选，不能用于正式 flash。

**技术：** Python 3 标准库；AOSP android11.0.0_r1 对应 commit 99894068024224a62595e051d69e748e2499f52e 的 mkbootimg.py；锁定仓库 resource_tool.c 的格式定义；现有 dtc 独立解码全部 DT。现有 fdtget 缺 libfdt.so.1，未使用。

## 固定约束

- 原备份：outputs/rk3568-backup-linux-20261003/original/boot.img，41943040 B，SHA256 0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28。
- header v2 / page 2048 / header_size 1660；kernel 33046536 B / ramdisk 822304 B / second 4491776 B / dtb 1650869 B；原 raw 40019968 B。
- mkbootimg.py SHA256 5579fb6bcb9e89e790a70fb9ccf3c00cf56e3e46aef74d84fcb0964887e5576e；不执行仓库中未知预编译 mkbootimg。
- RSCE 应包含 9 个 DTB 与 2 个 logo，每条 SHA1 校验；v2 DTB 字段独立含 11 个串接 FDT，不把运行 FDT 的 151680 B 套用到它。
- 历史现场 HW_ID=6/BOM_ID=7 选择 RSCE arch/arm64/boot/dts/rockchip/rk3568_smdt_3568a_v20.dtb。androidboot.dtb_idx=0 不证明 Linux 输入选了 concat 第零个。
- 本轮不接板、不写启动分区、不 flash/saveenv、不运行 bootm；若主控后续测原包，仅单地址 bootm PACKAGE_ADDR。
- 未来候选仅使用冻结 e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457 Image、162414 B uart.dtb 和 PID1 production-v3 的 972203 B initrd（SHA256 54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef）；不混入 display Image。v2 板测发现返回岛缺 52 applet 链接，不作为正式候选。
- 现 U-Boot 在 CLI 前已从 boot 资源 DT 初始化 PMIC/显示。RAM bootm 原包成功不证明修改 boot 后仍可达 CLI；USB 恢复未确认。
- 输出目录和所有 build 版本拒绝覆盖；明确区分离线完整性、现场执行和未验证的启动选择行为。

## 审查重点

1. 长度/偏移溢出、截断、组件与页填充边界：拒绝超界、非零 padding 或尾部异常。
2. header ID 与组件 SHA1 长度附加规则：独立计算后对照官方函数，不能仅对照 builder 自身。
3. RSCE 条目越界/重名/重叠、非法路径、SHA1 损坏与 FDT totalsize 错误：真实字节变异用例。
4. 串接 FDT 的数量、完整消费和结构边界；不能误认单个运行 FDT 为整字段。
5. 源码/原输入/重建输出被篡改与已有输出目录：冻结 SHA、实际官方打包调用、逐字节比较与拒绝覆盖。

## 文件与任务

- plan：本文件。README.md：结果、复现方法和候选 DT/RSCE 处置建议。
- sources/：锁定公开 mkbootimg.py 与同 commit 的 bootimg.h；source-lock.json 记录 URL、commit、SHA 和许可证。
- audit-boot.py：边界检查、完整原包解析、独立 SHA1 与 RSCE/FDT 审计；可作为模块导入。
- build-roundtrip.py：只读锁定输入，调用官方函数重建原包，导出组件、清单和证据；不能生成候选。
- test-boot-package.py：实际解析器与 CLI 的原输入及变异验证；证据只写新 build 目录。

### 任务 1：原包解析

- [x] 先用真实原文件写失败测试：header/完整布局、原 SHA1 ID、RSCE 11 项与 SHA1、concat 11 FDT，以及有界非法输入。
- [x] 保存红结果后实现只读解析；通过同组测试（39/39）。
- [x] 用锁定 C 格式定义和 dtc 交叉核实全部 20 个 DT 身份（20/20，warning 保留）。

### 任务 2：公开源码与官方 roundtrip

- [x] 下载官方源码到新目录，核 SHA256 与 commit；保存来源与许可。
- [x] 先证明不存在重建功能时正例失败；实现官方 write_header/write_data 路径。
- [x] 重建 raw 40019968 B；零填充至 41943040 B 后与原文件逐字节一致；测试证据 42/42。
- [x] 加入源码/输入篡改与输出覆盖拒绝验证。

### 任务 3：冻结与 DT 处置建议

- [x] 运行独立最终原包审计，封存源、测试、输入、输出 SHA 与红绿证据（original-freeze-v1）。
- [x] README 明确两个 DT 域及已知选择证据。主控已裁决仅 RAM 候选：保留 11 个 RSCE 名称和两 logo 原字节，9 个 DT payload 全部换锁定 UART 并重算 SHA1/offset；v2 dtb 字段同 UART。原启动分区保持只读，因此早期 U-Boot 仍用原资源。
- [ ] 主控完成独立审查及项目记忆整合；此 agent 不改全局记忆与其他目录。

### 任务 4：已授权 RAM 候选（原包冻结之后）

- [x] 新真实字节失败测试覆盖固定输入、官方打包、RSCE 名称/logo 保留、9 个相同 UART、单 v2 DT、完整 SHA1 ID、零填充及 40 MiB 边界（38 项红→绿）。
- [x] 实现独立候选 builder 与显式候选审计模式；原包默认审计仍要求 11 concat DT。
- [x] 核 Image 实际内存长度、候选内部偏移以及主控提供的暂定 0x20000000 包地址；header 目标区互相重叠，实际搬移/env 目标与保留区仍未现场核实。
- [x] 最终候选真实测试 43/43，新增有效 FDT 重算 ID/hash 后仍因 UART 锁定 SHA 不符拒绝；扩展审计后的原包完整回归 42/42。
- [ ] 全部新产物及红绿证据单独冻结，并独立解码候选 10 DT。标记 RAM_ONLY_NOT_FLASH_READY、未板测；主控负责上板和单地址 bootm。
