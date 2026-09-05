# RV1126B AI 相机执行步骤

这份文档是“下一步做什么”的顺序清单。不是时间计划，而是依赖关系：前一阶段没有通过，不进入下一阶段。

```text
硬件资料 -> 设备树/驱动 -> sensor probe -> V4L2 出图
-> ISP 图像质量 -> 采集服务 -> 数据/标注 -> RKNN 部署
-> 跟踪/事件 -> rtctrl 安全接入 -> 运维/故障/OTA/量产
```

## 阶段 1：确认硬件资料

先创建 `docs/develop camera/hardware.md`，记录：板卡型号、摄像头完整模组型号、镜头、CSI 接口、I2C 总线和地址、MIPI lane 数和顺序、输入时钟、AVDD/DVDD/IOVDD、reset/pwdn GPIO、有效电平、目标分辨率和帧率。

对照以下文件检查仓库当前假设：

- `platforms/rv1126b/boards/atk-dlrv1126b/bsp/kernel/arch/arm64/boot/dts/rockchip/rv1126b-alientek-ov13850-csi1.dtsi`
- `platforms/rv1126b/boards/atk-dlrv1126b/bsp/kernel/arch/arm64/boot/dts/rockchip/rv1126b-alientek-mipi720x1280-ov13850-csi1.dts`
- `platforms/rv1126b/boards/atk-dlrv1126b/bsp/README.md`
- `third_party/linux-rv1126b/drivers/media/i2c/ov13850.c`

通过条件：你能明确回答“摄像头接哪个 CSI、哪个 I2C、什么地址、几条 lane、哪些 GPIO 控制电源和复位”。不能确认的地方先标出来，不要凭猜测写 DTS。

## 阶段 2：修改设备树

### 2.1 sensor 节点

逐项核对：

- `compatible = "ovti,ov13850"`；
- I2C 地址；
- `clocks`/`clock-names`；
- `avdd-supply`、`dovdd-supply`、`dvdd-supply`；
- `reset-gpios`、`pwdn-gpios`；
- `rockchip,camera-module-index`；
- `rockchip,camera-module-facing`；
- `rockchip,camera-module-name`；
- `rockchip,camera-module-lens-name`。

`camera-module-lens-name` 不要长期写 `default`，它应和真实镜头以及 RKAIQ/IQ 资产对应。

### 2.2 endpoint 和链路

确认 sensor endpoint 和 CSI D-PHY endpoint 两端互相引用；`data-lanes`、lane 顺序、`remote-endpoint`、CSI 实例、`link-frequencies` 必须与原理图和驱动 mode 一致。当前仓库已有 CSI1/CSI2 D-PHY3/MIPI2 的 OV13850 变体，但“DTS 能编译”不代表物理连接正确。

### 2.3 内核配置

确认 defconfig 至少包含 V4L2、OV13850、Rockchip CSI/D-PHY、RKISP、DMA-BUF；调试阶段打开 media controller/debugfs，生产配置再收敛。RGA、RKNPU 暂时不是 sensor probe 的前置条件，但后面要验证。

### 2.4 编译

先执行 `--plan`，确认路径后再构建：

```bash
git submodule update --init --depth 1 third_party/linux-rv1126b
./scripts/prepare-linux-kernel-source.sh \
  --platform atk-dlrv1126b \
  --plan
./scripts/prepare-linux-kernel-source.sh \
  --platform atk-dlrv1126b \
  --build-dtb \
  --dtb rockchip/rv1126b-alientek-mipi720x1280-ov13850-csi1.dtb
```

通过条件：DTB 编译成功，每个 GPIO、regulator、lane、I2C 属性都有硬件依据，且没有修改公共 `third_party/linux-rv1126b` 工作树。

## 阶段 3：刷入并验证 sensor probe

保留旧 DTB 作为回滚方案。刷入新 DTB 后先只看传感器，不要同时排查 AI：

```bash
dmesg -w
dmesg | grep -Ei 'ov13850|csi|dphy|mipi|rkisp|v4l2|media|i2c|regulator'
```

确认：I2C 能读到 chip ID；时钟、电源和 reset/pwdn 时序正常；没有重复地址和持续初始化错误；重启多次结果一致。

常见判断：`probe failed` 先查 I2C/供电/时钟/GPIO；找不到设备先查总线号/pinctrl/上拉；chip ID 错误先查实际模组和地址；MIPI 错误先查 lane、endpoint、时钟和 mode。

通过条件：内核稳定 probe 出 OV13850，并保存 boot log、`dmesg`、DTB hash 和失败复现步骤。

## 阶段 4：验证 Media Controller 和 V4L2 出图

先查看 media graph，再查看 `/dev/video*` 的能力：格式、分辨率、FPS、buffer 数、内存类型和 DMABUF 支持。优先选择驱动最稳定的 mode，不要一开始追求最高分辨率。

写 `tools/vision/v4l2_probe`，至少输出：节点、格式、宽高、FPS、帧数、丢帧数、帧间隔 P95、最后时间戳、内核错误、CPU、内存和温度。

先验证单帧，再验证连续 1 分钟，再验证长时间采集。检查花屏、错行、颜色、撕裂、时间戳单调性和实际 FPS。

通过条件：相同命令重复启动/停止都能稳定出图，连续采集无持续错误，所有能力已经记录成报告。

## 阶段 5：ISP、镜头和图像质量

确认真实镜头、RKAIQ/IQ 文件、调参版本、sensor mode 和 AI 输入路径。采集正常室内、暗光、逆光、反光、运动、遮挡、空场景和远近目标。

每次修改 IQ 都保存版本和前后样本。评价标准不是“画面更鲜艳”，而是曝光是否稳定、运动拖影是否可接受、颜色是否一致、模型输入范围是否固定。

通过条件：固定输入格式/尺寸/颜色范围/归一化；曝光不频繁跳变；ISP 版本变化可追溯。

## 阶段 6：相机采集服务

把临时命令变成 `camera-service`：负责 V4L2 生命周期、format/FPS、buffer pool、序列号、单调时间戳、有限队列、FPS/丢帧/延迟统计、断流恢复。

推荐边界：

```text
capture thread -> bounded frame queue -> preprocess worker
                                      \-> recorder/diagnostic worker
```

网络、磁盘和日志不能阻塞采集线程。第一版可以先用拷贝路径保证正确性，再用 DMA-BUF/零拷贝 benchmark 证明优化收益。

通过条件：systemd/supervisor 可以启动、停止和拉起服务；杀掉服务后能恢复；长时间运行没有明显内存增长。

## 阶段 7：数据、标注和回放

设备采集的每张图或每段视频都保存 device_id、镜头、分辨率、曝光环境、时间、sensor/ISP/应用版本。训练、验证、测试集按场景/设备/时间隔离，不能把同一段视频的相邻帧随机打散。

实现：采集工具、脱敏/整理工具、标注转换工具、固定测试集、PC/板端统一预处理和离线回放工具。回放工具要能比较检测结果、事件结果和延迟。

通过条件：同一输入在 PC 和板端预处理定义一致；模型修改后可以使用固定困难集回归；误报和漏报可以回流数据集。

## 阶段 8：RKNN 模型部署

先选择一个小任务：人员检测、指示灯分类或物料到位分类。顺序固定为：PC 训练/评估 -> 固定输入和后处理 -> INT8 校准 -> RKNN 转换 -> 板端加载 -> 测预处理/NPU/后处理/端到端延迟 -> 测温度/内存/长稳 -> 保存 model card 和 hash。

model card 必须记录数据版本、类别、输入、量化、转换工具、目标 SoC、precision/recall/F1 或 mAP、板端延迟、温度、已知失败样本和适用边界。

通过条件：模型能在板端稳定加载/推理/卸载；与 PC 基线差异可解释；版本不匹配或文件损坏会被拒绝。

## 阶段 9：跟踪、规则和事件状态机

按顺序加入：检测框过滤 -> 多目标跟踪 -> ROI/越界线/方向/停留时间 -> 连续帧确认 -> 消失确认 -> 冷却去重 -> 证据帧 -> 故障状态。

事件至少有 `schema_version`、device、boot_id、sequence、开始/结束时间、类型、状态、置信度、model_version、rule_version、证据 hash 和 health。

通过条件：同一事件不会逐帧重复告警；短暂遮挡不会造成开始/结束抖动；重启和断网重传不会重复产生业务事件；不可信时输出 `FAULT/UNKNOWN`。

## 阶段 10：安全接入现有 rtctrl

先只接入结构化状态，例如 `PERSON_IN_ZONE`、`CAMERA_FAULT`、`VISION_UNKNOWN`，不要让视觉服务直接调用电机 HAL。

```text
vision event
 -> version/sequence/timestamp/valid_until 检查
 -> confidence/health/权限检查
 -> 安全状态机和限幅
 -> rtctrl 控制输入
```

通过条件：过期消息、sequence 倒退、版本错误和健康异常都会被拒绝；视觉服务退出时控制域有明确安全行为；AI 误判不能绕过急停、硬限位和人工接管。

## 阶段 11：产品服务和远程运维

再拆分 `camera-service`、`ai-service`、`event-service`、`device-agent` 和 supervisor/watchdog。提供健康接口、结构化日志、日志轮转、磁盘上限、诊断包、配置 schema、心跳、断网缓存、幂等上传和恢复后的补传。

必须能看到：FPS/丢帧/断流、ISP 错误、预处理/NPU/后处理/端到端 P50/P95/P99、温度/频率/内存/磁盘、模型/IQ/规则/固件版本、事件数、上传失败和服务重启。

通过条件：不接串口、不 SSH 也能查看健康、修改受控配置、导出诊断包、升级和回滚。

## 阶段 12：故障、安全和量产

主动测试：拔摄像头、MIPI/ISP 错误、杀服务、模型损坏、NPU 超时、磁盘写满、文件系统只读、断网、DNS 失败、时间跳变、高温、反复断电、OTA 中断和配置损坏。

每个故障都必须写明：如何检测、用户看到什么、系统怎样降级、多久恢复、日志如何证明。

量产前补齐：固件/模型/配置完整性校验或签名、A/B/回滚升级、序列号和密钥烧录追踪、相机/存储/网络/NPU/温度/RTC 工厂测试、散热/电源/EMC/ESD、许可证清单。

通过条件：设备可以无人值守运行；故障不静默；服务可恢复；日志和数据不会无限增长；每个设备的固件、模型、配置、IQ 和测试报告可追溯。

## 当前下一步

现在只做阶段 1 和阶段 2：

1. 建立 `hardware.md`，核对 OV13850 模组和 CSI1 实际连接；
2. 对照 `ov13850-csi1.dtsi`，逐项确认 I2C、GPIO、regulator、clock、lane、endpoint；
3. 执行 `prepare-linux-kernel-source.sh --plan`；
4. 编译指定 OV13850 CSI1 DTB；
5. 刷入开发板，保存串口和 `dmesg`；
6. 只有 sensor probe 稳定后，才进入 V4L2 出图。

阶段 2 的完成标志不是“DTB 编译成功”，而是：真实硬件信息和 DTS 一一对应，内核能稳定 probe 传感器，重启多次结果一致，并且保存了可复现的日志和 DTB 版本。
