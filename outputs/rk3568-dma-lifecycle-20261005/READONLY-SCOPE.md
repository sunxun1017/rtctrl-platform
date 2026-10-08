# C3 只读状态与释放范围

候选以冻结 B、C1 v18 与 C2 v3 为基底；C1 v18 及历史红绿文件保留。最终 CPU
绑定 `outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10/sound/soc/rockchip/rockchip_i2s_tdm.c`，
SHA `cbd19c1a8b128d442f6321ebb9ce1d51524633536282862b6c06fa76b4f77b59`。
0011 是相对公开 0001–0010 的增量；CPU 全量候选补丁由另一作者提供，分别重放。
不发布、不部署；完整 Image 和板端 START 验收由主控后续进行。

PL330 AMBA device 增加只读 `rk3568_lifecycle_state`，设备名从实际 sysfs 发现。
`version/ready/error/stop_proven/stop_reads/pm_usage/leases/software/queued/descriptors/allocated`
是缓存/软件状态快照。show 使用 controller trylock，忙时返回 `-EAGAIN`；不操作
MMIO、PM、DMA、reset，不清 sticky，不建立新停稳证明。`ready=1` 要求本 provider
安装 checked callback、全 manager/physical channel 的缓存 STOPPED 证明存在、无
poison、无关闭/休眠事务、零真实 PM usage/owned PM lease、零软件用户/排队工作、
零私有/提交/退休 descriptor owner。allocated 可以包含静止的已分配 channel；它
不等于 core client ref，普通 codec/card 注销后应为 0。全控制器 proof 只在当前
checked invocation 持成功 PM lease、完成硬件与软件检查后采样，执行/错误撤销。
owner counter覆盖真正 get_desc→desc_release；软件 gate 与引用仍由原 C1 管理。

PCM core 在 `/sys/class/sound/dma_quarantine_bytes` 报告永久隔离总 allocation
字节数，读取只做 atomic read。不能用 PL330 ready 替代该全局字节数；正常退出
必须检查它为 0，并与 CPU v10 的只读证明、真实 FD/进程退出条件并列。两个快照
不能成为新 admission 的原子许可，更不能单凭 DROP/close 成功自动 warm reboot。
若未执行过 checked hooks，PL330 stop_proven 仍为 0，读取不会补做 MMIO。

device attribute 在真正 DMA core publication 前创建，create/register 失败先撤
attribute；remove 的首步先撤 attribute，再进行 client gate、PM/STOPPED/资源释放。
真实 device_remove_file→sysfs→kernfs 对 active reader 先禁止新入口再排空旧入口。
kernel 的 kernfs_drain wait 没有期限，本 profile 撤入口前开启 controller 内预置
500ms timer；超时调用既有 failstop（panic_timeout=0），owner 尚未销毁。成功返回
后 del_timer_sync 排空 timer callback，随后才允许线程/mcode/devres 生命周期继续。
reader_remove 不持 pch/controller/DMA core mutex，timer callback不取这些锁也不做
MMIO；普通 show 不开启 timer。500ms 是内核可服务 timer 时的关闭期限，无法保证
已失去 timer/IRQ 服务的系统继续执行代码。外部 MCU/硬件 watchdog 是否 reset 仍未知。
此设计不提供活跃 unbind 恢复能力；本阶段故障后的 driver/module teardown 会 failstop。

永久 token/list/动态 snd_dma_buffer 元数据位于 `pcm_memory.o`，真实 Makefile 将它
链接到 snd-pcm；成功 ownership transfer 完成校验及 card 计账检查后，
`__module_get(THIS_MODULE)` 为每个永久 owner 保留 snd-pcm 模块引用。token不持
runtime/card/substream/prtd/callback，snd-pcm-dmaengine 的软件排空不依赖该引用。
真实 try_stop_module 会拒绝有该引用的普通卸载。board config 的 SND_PCM、
SND_DMAENGINE_PCM、PL330 都是 built-in；MODULE_FORCE_UNLOAD=y，强制模块卸载
不属于此安全契约。PCM class attribute 在普通 module exit 前通过真实 class_remove_file
排空 reader；永久 owner 存在时普通 snd-pcm module exit 不会获准。

17项合成测试把真正 native pre_start/do_start、ASoC group/helper、generic PCM、
PL330 prep/submit/direct DBG/IRQ/checked、pcm_memory/memalloc 与 core dma_chan_put
连到同一 TU。CPU DAI 的 I/O故障为 callback 边界注入；CPU v10 precheck 是原函数。
card 正常场景先运行真实 native release/managed free/preallocate free，再调用真实
generic unregister→core dma_release_channel/dma_chan_put→void checked sync/free_chan；
ASoC unregister API 边界核对旧 runtime/area 已清后才释放 component。未模拟整个
ALSA device_disconnect/open admission；主控注销前确认 FD 关闭，既有 ASoC core
负责注销 admission。失败场景真实 void sync failstop，allocation先转永久 core owner，
thread/retired descriptor/PM保留，不靠 errno 阻止 devres。C1 回归继续覆盖真实 remove
的 client gate、软硬排空和先 proof 后毁 owner；kernfs 实测覆盖单个 attribute leaf，
不声称完整 sysfs subtree/device core 并发组合已由该小 fixture 验证。

MMIO register model 验证软件操作顺序及 deadline，没有 AXI 实测或电气停稳证明。
不支持本轮 full-duplex、未知 allocator/IOMMU；保护限制只用于安装 checked callback
的 PL330 PCM，其他 provider 沿其原 void synchronize API 契约。CPU、codec、DMA
各自 sticky/checked 都须通过，任何 poison/quarantine 非零不允许普通 warm reboot。
