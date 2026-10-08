# PCM 双 open、逐个关闭的无 START 检查器

遵循 `docs/superpowers/specs/2026-10-06-rk3568-pcm-peer-idle-design.md`。只新增本目录，旧 pcm-config/pcm-transfer/guard、ASoC 候选、public patches、顶层文档和项目记忆均不改。当前已经完成作者离线实现/执行与静态构建，**尚待主控和独立审查，尚未封存或板测**。

| 项目 | 实际结果 |
|---|---|
| 主源码 `pcm-peer-idle.c` | SHA `4edc171fd8bb57c10d844bbfdfa72f83dd090de3f96f143bab8459fd7e22c8d2` |
| `parameters.h` | SHA `26ae04bc98a5e466bc24a18ab76b5841c9c52a0e265d5610cdedc2d4011536f9`；旧 pcm-config 从文件起点到 print_caps 前的完整原字节 prefix |
| 锁定 SDK asound UAPI | SHA `138cb9e8de8df6cdf2abb05806d7f61078fb7ea44063e5914bea277ef55a0447` |
| `models-green-v1/result.json` | SHA `29d6cafc9f5b9022c0d9e26280f92017715ac07a0efd18b30eb1dd38f6da35ba`；host、ASan+UBSan、AArch64 QEMU 各 **1032/1032** |
| `production-v2/pcm-peer-idle` | 真正静态 ELF64 LE AArch64，655136 B；SHA `7693a052b6318ec3e965451fcb94609e97cb48e693715b847b62032cc684e661`；CRC `e5c2ba24` |

用法只接受这个明确顺序、完整参数，不提供卡号或顺序默认值：

```sh
pcm-peer-idle --card 1 --open-first playback --close-first capture
```

卡号限定单数字 0..7，两个方向均可独立选 playback/capture，共四种顺序。错误参数在任何信号或设备边界调用前拒绝。部署程序的这条有效设备命令尚未执行；仅由模型执行实际 main，另在真实静态目标上实际执行三个非法参数拒绝。

流程先恢复默认 SIGALRM、解除继承屏蔽、设置五秒期限，核 controlC 与完整 rk809 card ID 后关闭 control。依次打开所选第一方向和另一方向，各自检查字符设备/116 major、协议版本、完整 `fe410000.i2s-rk817-hifi rk817-hifi-0` id/name、card/device/subdevice/stream/subdevices，再做完整及精确 REFINE、HW_PARAMS 和 SETUP/双零指针检查。默认动态 minor，不猜测旧静态 minor，也不把 USB 音频当目标卡。

两向固定参数为 48kHz、S16_LE、2ch、RW_INTERLEAVED、period 256 帧×4、buffer 1024 帧。每次请求前重新清空输出字段，HW_PARAMS 返回的三 mask 和九参数必须严格匹配。第一方向 HW_FREE 成功后核 OPEN 并 close；只有这组操作全部成功，才读 peer STATUS，要求其仍为 SETUP、appl_ptr/hw_ptr 均零，再释放 peer。OPEN 检查要求状态，记录实际指针；零指针约束针对 SETUP。

没有 PREPARE、START、DROP、SW_PARAMS、READ/WRITE、声音控件、驱动绑定或 PM 配置调用。正常流程共 34 个边界操作、18 个 ioctl（七种白名单），每次只尝试一次，操作记录有唯一连续序号。日志保存在 64 个固定记录的有界数组，资源释放后有界输出，保留首个操作、序号和 errno。

任何失败立即停止正常流程，只归还已取得资源。非负 HW_PARAMS 返回视为取得配置，因此异常正返回或返回参数漂移也需一次 HW_FREE。每个 HW_FREE/close 最多一次，标记在尝试前撤下；EINTR 也不重试 close。失败清理不增加 STATUS 请求，另一方向仍继续归还，第二个清理错误不覆盖第一错误。

## 离线执行证据

`model.c` 只包裹外部 libc/syscall 边界，调用真实生产 main；没有复制生产清理算法来冒充执行。资源和阶段模型独立检查取得/释放次数、逐个方向顺序、全部配置阶段、第一 close 后必需的 peer 状态、禁止正常流程在首错误后推进，以及所有额外 ioctl/替代设备和数据路径。`run-models.py` 保存源/UAPI、每次 argv/exit/stdout/stderr、真正对象和可执行文件，三环境都实际执行。

1032 项覆盖四顺序、每个失败前缀的 EIO/EINTR/异常正返回、第二 open/params 失败、card/PCM 身份漂移及未终止字符串、参数/mask/boundary 漂移、SETUP/OPEN/peer 状态错误、指针非零、HW_FREE/close 失败、多个资源双失败和首错误保持、卡号两端及非法参数。另实际建立继承 SIG_IGN+blocked SIGALRM，在第二方向 HW_PARAMS 模型中的 interruptible pause 等待，三个环境均约五秒由 SIGALRM 结束。

TDD 先执行真实旧单端 `pcm-config.c` main：`models-red-v2` 在新四种参数/顺序下 0/4，因为旧程序拒绝该双端接口；随后才实现新 main。`models-red-v3` 用最终 runner 再核同一四红，匹配当前源码工具库存。`models-red-v1` 仅为模型最初漏 sys/ioctl.h 的编译失败，不计红例。`production-v1` 仅是 audit 漏掉旧 helper 已允许的三种 FORTIFY libc 输出符号而拒绝的初次构建；v2 窄补 `__printf_chk/__fprintf_chk/__snprintf_chk`，生产 C 及三环境绿色结果不变。上述历史输出保留。

可在本目录的新直接子目录独立复跑；以下路径是示例，必须尚不存在：

```sh
python3 -B outputs/rk3568-audio-runtime-20261005/pcm-peer-idle-v1/run-models.py --phase red --out outputs/rk3568-audio-runtime-20261005/pcm-peer-idle-v1/review-red-v1
python3 -B outputs/rk3568-audio-runtime-20261005/pcm-peer-idle-v1/run-models.py --phase green --out outputs/rk3568-audio-runtime-20261005/pcm-peer-idle-v1/review-green-v1
python3 -B outputs/rk3568-audio-runtime-20261005/pcm-peer-idle-v1/build-production.py --models outputs/rk3568-audio-runtime-20261005/pcm-peer-idle-v1/review-green-v1 --out outputs/rk3568-audio-runtime-20261005/pcm-peer-idle-v1/review-production-v1
```

## 验证边界

系统调用模型不证明真实内核 PM、CCF、DMA、ASoC 清理或共享 sysclk 缓存；STATUS 也不直接测缓存。五秒默认信号只约束可以递交信号的等待，不能保证终止内核不可中断等待；信号终止绕过用户态日志/清理，实际内核 fd 释放仍由内核完成。资源操作完成后解除 timer 再有界输出，输出阻塞也不据此声称有严格五秒保证。

严格 guard 只在全部 PCM 关闭的前后使用。本程序没有 START 许可，不证明全双工、物理声音或整机迁移完成。实际四顺序矩阵必须等待新 ASoC 候选源码、完整 Image、codec ABI、打包身份及审查全部闭合，由主控独占设备操作；本任务不接触板、串口、ADB、TUN、网络或服务。
