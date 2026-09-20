# Linux 平台化候选验证（2026-09-21）

## 范围

根据三页帕奇硬件框图推进 Linux，保持业务/核心与具体硬件解耦。
只有框图，没有板端访问或原板设备树。本轮增加通用配置与只读采集工具，
RK3568及AIoT-3568PQ事实独立放在平台数据中；没有改实时端口、连接执行器或部署。
驱动对应和后续步骤见 [板卡说明](../platforms/rk3568/boards/aiot-3568pq/README.md)。

## 真实 Kconfig 与交叉编译

- WSL Ubuntu 22.04，AArch64 GCC 11.4.0。
- 内核：`third_party/linux-rk3588`，Linux 5.10.160，干净commit
  `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`，厂商BSP。
- 输入：`platforms/rk3568/boards/aiot-3568pq/kernel-candidate.json`，
  `platforms/rk3568/linux-5.10.cfg`，板级 `peripherals.cfg`。
- 最终93项要求全部匹配；`prepare/modules_prepare` 成功。最初审计正确拦截了
  BT缺serdev及RGA2与MULTI_RGA互斥，随后根据此版本Kconfig修正。
- `.config` SHA256：`9ec2e842e0fb45808f514be9690a552e16a10f8c9a4a22913a230dd269d1967a`。
- 主输出：`.deps/kernel/aiot-3568pq-candidate/`，包含manifest。
  环境及工作目录隔离复核输出：`.deps/kernel/aiot-3568pq-cwd-verified/`；
  两份最终 `.config` 通过 `cmp` 一致。

生成和审计入口：

```sh
python3 scripts/prepare-linux-config.py \
  --candidate platforms/rk3568/boards/aiot-3568pq/kernel-candidate.json \
  --output .deps/kernel/aiot-3568pq-candidate --prepare-headers
python3 scripts/prepare-linux-config.py \
  --candidate platforms/rk3568/boards/aiot-3568pq/kernel-candidate.json \
  --check-config .deps/kernel/aiot-3568pq-candidate/.config
```

使用同一输出目录编译下列真实内核目标，全部exit0。`readelf -h`确认样本
fan53555.o为AArch64 ELF64可重定位对象。

```sh
make -C third_party/linux-rk3588 O="$PWD/.deps/kernel/aiot-3568pq-candidate" \
  ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j4 \
  drivers/regulator/fan53555.o drivers/power/supply/bq25700_charger.o \
  drivers/misc/eeprom/at24.o drivers/usb/typec/tcpm/fusb302.o \
  sound/soc/codecs/rk817_codec.o drivers/media/i2c/ov5695.o \
  drivers/tty/serial/8250/8250_dw.o
```

执行时PATH包含仓库 `.deps/host-tools/bin` 的flex/bison。
这些是驱动对象编译，不是完整Image、模块链接、DTB或真机验收。
manifest继续明确 `deployable=false`。

## 工具与回归

| 验证 | 实际结果 |
| --- | --- |
| `tests/test_linux_kernel_config.py` | 最终22项通过：错误/缺失配置、分层覆盖、候选格式、输出保护、路径字符及环境隔离 |
| `tests/test_linux_hardware_snapshot.py` | 最终18项通过：二进制DT、缺失/权限、白名单、链接/特殊文件、只读边界及致命失败传播 |
| 真实Kconfig污染环境实验 | 注入KCONFIG_AUTOHEADER/AUTOCONFIG/CONFIG和KBUILD_OUTPUT，执行真实headers准备；外部已有文件内容不变，错误输出目录未创建 |
| 只读工作目录实验 | 从0555空目录启动完整配置/headers流程；成功且调用目录保持空，merge临时文件位于输出目录 |
| release配置、构建、CTest | 本轮完整运行39/39通过，含当时两组BSP测试 |
| asan配置、构建、CTest | 本轮完整运行39/39通过；Python工具自身不因preset变为ASan插桩程序 |
| 审查修复后两组BSP测试 | release与asan各2/2通过，执行的是最终22+18用例 |
| 架构检查 | 34个模块头、49个源码/头边界检查通过 |
| Shell语法、`git diff --check` | 通过 |
| 全仓`format-check` | 未通过：现有未修改C++文件存在格式差异，如modules/safety/src/safety_policy.cpp、modules/transport/include/rtctrl/transport/byte_transport.hpp；未全仓重排 |

独立审查发现并修复了三个实际边界问题：Kconfig输出环境覆盖、Kbuild对路径的二次
shell解释、采集器子shell写状态失败及grep失败被当作成功；还将merge临时文件固定在
输出目录。相关失败用例先复现，再通过。真实采集器的strace夹具未打开 `/dev`。

完整39项CTest运行发生于另一并行任务接入PatchX codec前；后续协议测试和总数由
[协议验证记录](verification-patchx-protocol-20260921.md)单独说明，不混用两轮构建范围。
用户原有四个 `apps/face_recognition` 未提交文件保持未接管。

## 未完成的硬件验收

没有可刷机镜像、板级DTS、充电/电源实测、显示时序、BH6080描述符、摄像头实装型号、
Wi-Fi固件配对或CAP1188 SPI/SH3001驱动验收。Android采集命令需现场权限复验。
原机设备树后续提供；电机物理停机、使能和MCU watchdog不能从主机封帧编译推定。

## 后续PC验证交接

并行任务随后完成 [PTY与QEMU验证](verification-pc-qemu-20260921.md)：
Host release和ASan/UBSan各41/41，ARM64用户态codec、PTY和Dynamixel三项3/3。
PTY复现并修正Linux串口空闲被误判Closed的问题，详见该记录中的VMIN与O_NONBLOCK条件。
这些结果补充协议与系统调用层的执行证据，不扩大上文RK3568配置/对象编译的硬件验收范围。
