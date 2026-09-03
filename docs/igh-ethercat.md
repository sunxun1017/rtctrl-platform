# IgH EtherCAT 接入

项目通过可选的 `rtctrl_igh_ethercat` target 接入 IgH EtherCAT Master 1.6 `ecrt` API。默认构建不要求安装 IgH；启用后，配置阶段和实时周期阶段保持分离。

## 构建

本机默认从 `/opt/etherlab` 查找 IgH：

```bash
cmake --preset igh
cmake --build --preset igh -j8
ctest --preset igh --output-on-failure
```

其他安装位置可以直接配置：

```bash
cmake -S . -B build/igh -G Ninja \
  -DRTCTRL_ENABLE_IGH_ETHERCAT=ON \
  -DRTCTRL_IGH_ROOT=/path/to/etherlab
```

启用选项后如果找不到 `ecrt.h` 或 `libethercat`，CMake 会立即失败，不会静默退化为模拟实现。IgH kernel master、网卡驱动和 `/dev/EtherCATN` 必须由目标机单独安装配置。

## 已实现的 ecrt 生命周期

`IghMaster::activate()` 在非实时阶段完成：

1. `ecrt_request_master()` 独占指定 master；
2. 创建一个 process-data domain；
3. 按 alias/position/vendor/product 创建并校验 slave configuration；
4. 配置 SyncManager、PDO assignment 和 PDO mapping；
5. 登记普通或 Complete Access startup SDO；
6. 注册 domain PDO entry，并把字节/bit offset 回写给调用者；
7. 配置 Distributed Clocks，选择第一个启用 DC 的从站作为 reference clock；
8. 激活 master 并取得 process-data image。

实时线程每周期严格执行：

```text
receive(application_time_ns)
  -> ecrt_master_receive
  -> ecrt_domain_process
  -> master/domain/slave state snapshot
  -> 应用读取输入 PDO、写入输出 PDO
send()
  -> ecrt_domain_queue
  -> DC reference/slave clock synchronization
  -> ecrt_master_send
```

周期路径不分配内存。`state()` 同时给出 link、响应从站数、AL 状态、Working Counter 以及所有配置从站的 online/operational 状态；只有这些条件全部满足时 `ready()` 才返回 true。

## 配置模型

公共头文件不暴露 `ecrt.h` 类型。部署叶子使用以下固定容量描述：

- `PdoEntryMapping`：对象字典 index/subindex/bit length；
- `PdoMapping`：一个 RxPDO 或 TxPDO；
- `SyncManagerConfig`：方向、PDO 列表和 watchdog；
- `SlaveConfig`：总线位置、严格 vendor/product identity 和可选 DC 参数；
- `StartupSdoConfig`：激活时由 IgH 下载的普通或 Complete Access SDO；
- `DomainEntryRegistration`：需要进入实时 process image 的条目及 offset 输出位置。

PDO、SyncManager、AssignActivate 和位宽必须来自从站 ESI/XML 或厂商手册。适配器不会扫描后猜测 PDO，也不会假设 CiA 402 控制字、运行模式、缩放比例或安全行为。
`StartupSdoConfig::data` 会按给定字节原样交给 IgH，不自动执行大小端转换；调用者必须按对象字典类型准备 payload。PDO assignment/mapping 对象应通过 PDO 配置结构完成，不应重复放进 startup SDO。

典型的 L0 结构为：

```text
SharedMotorRegion
  <-> 设备协议/单位换算/使能与 SafeStop 状态机
  <-> IghMaster::process_data()
  <-> IgH ecrt domain
  <-> EtherCAT slaves
```

## Distributed Clocks

对需要 DC 的从站设置 `DistributedClockConfig::enabled=true`，并从 ESI 填入 `assign_activate`、SYNC0/SYNC1 周期和 shift。`receive()` 的 `application_time_ns` 必须每周期单调递增；通常传入实时循环的纳秒时钟。IgH 主要依赖增量和相位，运行中不得切换时钟源。

## 安全边界

IgH bus/domain 激活不等于电机安全使能。通用层无法知道哪个 PDO 是控制字、制动器或 STO：

- 激活前确保从站硬件 watchdog 和 STO 生效；
- process image 初始为零不应被假设成任意驱动器的 SafeStop；
- 上层必须在收到完整、在线且 OP 的反馈后才进入设备使能状态机；
- WKC、link、online 或 operational 任一异常都应停止命令续租并进入设备定义的安全路径；
- `close()` 是非实时资源释放，不替代先发送安全控制字、从站 watchdog 或硬件 STO。

## 真机检查

```bash
ls -l /dev/EtherCAT0
/opt/etherlab/bin/ethercat master
/opt/etherlab/bin/ethercat slaves
```

当前仓库的配置契约测试不访问 master 设备。真机测试必须在已加载 IgH kernel master、绑定专用网卡并连接实际从站的目标机完成。
