# ADR-0006：可替换实现、采集后端注入与适配器构建能力

状态：Accepted，2026-09-10，v0.7。补充 ADR-0005。

## 问题与范围

v0.6 将实时核心与适配器分开，但采集 API 仍直接由 V4L2 文件实现，公共颜色字段
仍使用 V4L2 数值；模拟构建仍编译具体系统适配器；通用协议组合 HAL 的库里混合了
Dynamixel 实现。仅有接口名称或不同目录不能证明实现可以独立替换。

本次把可变实现隔离到组合根，保留固定容量队列和安全门控等核心约束。
操作系统线程运行环境仍是 C++/POSIX 定位，不宣称完成 RTOS 移植。

## 决策

- 采集采用 C 端口与适配器：`rtctrl_capture_backend` 回调表由组合根显式注入，
  公共层复制描述符；不用全局工厂、service locator、后端类型 switch 或动态插件 ABI。
- `rtctrl_capture` 管理公共句柄、借用状态、token 代次、元数据检查和失败状态；
  后端管理实际资源。一个句柄一个所有者，同一时刻只允许一个借用帧。
- V4L2 与 synthetic 各自有明确的配置和构造函数。消费者只持有 `rtctrl_camera*`。
  配置只在 create 时消费；后端需要保留的配置必须复制进自己的 context。
- 后端 open 失败时必须留下 NULL 或可 close 的 context。公共层负责调用 close；
  close 必须销毁 context，即使存在未归还帧或自身返回错误。
- 公共层将自己的 token 映射回后端 token。旧借用不能因为底层复用了缓冲编号而被接受。
  错误帧在返回给消费者之前被拦截并归还；致命错误后只允许关闭重建。
- 像素格式、色彩空间、量化范围、传递函数、YCbCr 矩阵使用平台定义的枚举。
  默认值仅在信息充分时解析；不明值明确为 UNKNOWN。`native_format` 仅供诊断，
  不能作为可移植图像处理的分支条件。
- 通用 HAL、具体电机协议、半双工链路及原生字节传输分别有独立 CMake target。
- 各系统适配器独立开关。关闭时不创建对应 target，也不编译源码；设备相关测试
  按能力选择，纯算法/协议测试继续运行。

## 依赖

```text
V4L2 main ─────────────→ rtctrl_vision_v4l2 ──┐
Synthetic main ────────→ rtctrl_capture_synthetic ─┤
                         通用帧消费者 ──────────┼→ rtctrl_capture → C contracts
                                               ┘

组合根 → rtctrl_hal_protocol（只依赖 IActuatorProtocol / IActuatorLink）
       → rtctrl_actuator_dynamixel → rtctrl_protocol_dynamixel
       → rtctrl_actuator_serial_link → IByteTransport
       → rtctrl_transport_serial（可选实际设备 I/O）

上游命令源 → rtctrl_source_framed → rtctrl_protocol_target
```

上述 target 中只有具体 V4L2、串口等适配器包含原生类型。
`rtctrl_protocol`、`rtctrl_hal` 等聚合 target 保留，但新组合根优先使用细粒度 target。

## 使用和扩展

```c
// 组合根选择后端；之后的消费者代码相同。
struct rtctrl_camera* camera = NULL;
struct rtctrl_synthetic_config config = {640, 480};
int rc = rtctrl_camera_create(rtctrl_synthetic_backend(), &config, &camera);
// 检查 rc 后调用 rtctrl_camera_acquire/release/close。
```

新增厂商后端：实现 `capture_backend.h` 的五个回调，提供独立配置与构造函数，
建立依赖 `rtctrl_capture` 的叶子 target。核心和 `capture_cli.c` 不需要增加分支。
后端只在创建句柄时选择；更换后端需要关闭旧句柄、重新创建，不支持在借用中热切换。

Synthetic 是真实可运行的第二种实现：无硬件、无系统时钟、无 V4L2 依赖，输出
确定性的 GRAY8 图像，未节流；时间戳为 0 且不声明 monotonic。
这适合接口/消费者测试，不冒充真实相机时序或真实传感器模拟。

## 构建能力

| 开关 | 控制的实现 |
| --- | --- |
| RTCTRL_ENABLE_POSIX_SHM | POSIX 映射/打开共享内存；SharedMemoryHal 本身只消费注入的 region |
| RTCTRL_ENABLE_KERNEL_MAILBOX | Linux mailbox HAL 与 UAPI codec |
| RTCTRL_ENABLE_SERIAL | Linux 串口/RS485 原生实现 |
| RTCTRL_ENABLE_SOCKETCAN | Linux CAN/CAN-FD 实现 |
| RTCTRL_ENABLE_V4L2 | Linux V4L2 采集及其 CLI |
| RTCTRL_ENABLE_IGH_ETHERCAT | 既有可选 IgH adapter |

`control-sim` preset 显式关闭前四项；`vision-synthetic` preset 使用 vision-node 产品
并关闭 V4L2。development/release 在受支持平台默认保留既有适配器。
开关为 CMake cache：切换产品时使用各自 build 目录，或显式重设开关。

```sh
cmake --preset control-sim
cmake --build --preset control-sim -j8
ctest --preset control-sim

cmake --preset vision-synthetic
cmake --build --preset vision-synthetic -j8
ctest --preset vision-synthetic
./build/vision-synthetic/rtctrl_camera_synthetic /tmp/frame.gray
```

## v0.6 → v0.7 迁移

- 原 `rtctrl_camera_config`/`rtctrl_camera_open` 改为显式适配器入口
  `rtctrl_v4l2_config`/`rtctrl_v4l2_open`，创建入口现已迁至适配器专属的
  `rtctrl/adapters/v4l2/capture.h`；应用须显式链接 `rtctrl_vision_v4l2`。
  该头文件和库目标不再作为平台公共 API 安装导出。
- 通用消费者只包含 `vision/capture.h`，链接 `rtctrl_capture`。
- 公共格式的 `fourcc` 改为 `pixel_format` 和诊断用 `native_format`；颜色字段
  必须按 `vision/image_format.h` 解释，不再使用 V4L2 枚举比较。
- 保存的 JSON 元数据使用 `schema_version: 2`，明确记录上述两种格式信息。
- 原来只链接 `rtctrl_hal_protocol` 却使用 Dynamixel 或 HalfDuplexSerialLink 的调用方，
  需要显式链接 `rtctrl_actuator_dynamixel` 或 `rtctrl_actuator_serial_link`。
- 版本升为 0.7，SameMinorVersion 不把新 package 当作 0.6 二进制兼容替换。
  现有 mailbox UAPI、ControlLink 线协议、控制数据和实时执行行为不变。

## 验证要求

1. 无 V4L2 的构建运行真实 synthetic 后端，使用同一个通用消费者。
2. 注入另一个测试后端，验证描述符生命周期、错误清理、token 重映射、背压与失败状态。
3. 颜色转换覆盖显式/default/UNKNOWN、多平面 NV12 和 HDR 元数据。
4. 关闭原生适配器时 target 不存在；纯控制/协议测试不依赖缺失实现。
5. 安装后的 C 消费者分别只链接通用核心、或显式链接 synthetic 后端。
6. CMake 依赖闭包和递归头文件检查禁止通用层重新引入具体后端。

## 2026-09-12: Optional borrowed DMA-BUF

V4L2 export_dmabuf defaults to zero (MMAP only). Nonzero requires VIDIOC_EXPBUF
for every buffer plane with O_CLOEXEC | O_RDWR. Unsupported or partially failed
export fails open and cleans all acquired descriptors, mappings and the device;
there is no silent fallback.

Consumers must check dmabuf_valid; descriptor 0 is valid. The backend owns the
descriptor and consumers must not close it. Device consumers must finish before
frame release or camera close. Copying or duplicating the descriptor does not
extend the frame contents' lifetime: QBUF permits the producer to overwrite it.

allocation_size describes the full exported allocation. data_offset locates the
payload in that allocation; data already points to the payload and size excludes
the offset. CPU consumers must not apply the offset twice. Export alone does not
prove downstream format compatibility, cache synchronization or end-to-end
zero-copy operation.

Adding fields changes public structure sizes and nested array layouts. Existing
binaries are incompatible: rebuild all producers, consumers and adapters together.
Zero-initialize configurations and frames; source consumers using zero-initialized
configuration retain MMAP behavior.

The syscall-fake camera test covers default MMAP, exports, descriptor 0, payload
offset, release without descriptor close, close with an outstanding lease, partial
export failure and invalid export results. Real device import, synchronization and
performance require board validation.
