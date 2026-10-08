# 锁定 5.10 ASoC PREPARE / HW_FREE 错误边界

输入为 Linux `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`，只改
`sound/soc/soc-pcm.c` 与 `sound/core/pcm_native.c`。codec 已发布 0006、0007、0009
保持冻结；本补丁不修改 codec、共享 PMIC cache、DMA 或 PL330。

实际调用链核查：该树 `snd_soc_dai_ops` 只有 `mute_stream`，没有旧版
`digital_mute` 字段或 legacy fallback。真实 `snd_soc_dai_digital_mute()` 对无
ops / 无 callback / capture 且 `no_capture_mute` 返回 `-ENOTSUPP`。只对实际会执行
的 callback 检查返回值；callback 本身返回 `-ENOTSUPP` 仍是真失败。

1. 先抽取锁定的真实函数和 helper，写行为测试，留下未修源码红证据。
2. `soc_pcm_prepare()` 在第一次实际 unmute 失败后停止后续 unmute，保存首 errno。
   重新 checked 静音此前已尝试和刚失败的 DAI，尽力完成全部这些 callback；清理
   错误不能覆盖首 errno。紧接着发送 DAPM STREAM_STOP 配对该次 STREAM_START。
   不递归调用持有同一 PCM mutex 的 `hw_free`。此前 link/component/DAI prepare
   失败尚未启动 DAPM，保持原有早退路径。
3. `soc_pcm_hw_free()` 收集实际适用、active==1 的 mute 首 errno；仍执行后续静音、
   参数清零、machine/component/DAI 清理，再向显式 HW_FREE 返回首 errno。
   保留 `snd_soc_link_hw_free()`、`snd_soc_pcm_component_hw_free()`、
   `snd_soc_dai_hw_free()` 的公开 void ABI。本板未安装这些 hw_free callbacks；
   本补丁不承诺其他板这些 callback 内的错误全部可见，close 仍可能忽略错误。
4. `snd_pcm_do_prepare()` 的 prepare callback 或 reset 失败调用现有
   `snd_pcm_set_state(SETUP)`，它保留 DISCONNECTED。成功路径保持原有 reset 与
   PREPARED 设置。进入 do_prepare 后，SETUP 和 PREPARED 重入失败都通过真实
   START pre_action 拒绝，trigger callback 不执行。buffer-access/pre_action 的
   前置拒绝尚未尝试驱动准备，保留既有状态；不扩展为全部 ioctl 错误失效机制。
5. 绿色证据用新目录，绑定源、抽取片段、harness、编译器、ELF、stdout 哈希。
   GCC host、ASan/UBSan、静态 AArch64/QEMU；全部公开 board patch 在独立最小
   源文件集重放，字节比较并拒绝被篡改依赖、源与已有输出。原内核只读且 clean。

测试保留真实 `snd_soc_dai_digital_mute` / `_soc_dai_ret` / DAI prepare、activity、
stream-valid / PCM action、SETUP helper、reset、sync_stop、显式 HW_FREE 与 START
状态检查。假边界仅为 callback、DAPM event、锁、调度、buffer/QoS 与硬件 I/O；
单个未链接 PCM 是当前板路径。链接 PCM 的跨 substream 事务回滚不是本次范围。
reset 在 ASoC prepare 成功后失败时，本补丁只使 PCM 状态失效；不会隐式调用
HW_FREE 或撤销此前成功的 DAPM start，仍需用户显式 HW_FREE/close。测试没有
将这个路径误称为已完成硬件资源回滚。

仍禁止上板 START：generic DMA 的 sync_stop、PL330 的 terminate/tasklet/资源
释放同步以及真实 progress 验证另行设计。host/QEMU 的 START 只调用 fake trigger，
不能证明 DMA 安全、真实中断、真实 DAPM widget 电气状态或音频输出成功。

生产源仅保留原 license/copyright；生成片段/二进制/测试结果由本目录 ignore，
独立结果目录内封存输入，不引用可变外部 harness。没有硬件操作或 Git 修改。
