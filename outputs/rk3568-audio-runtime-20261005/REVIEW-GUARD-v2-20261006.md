# guard v2 独立只读复核与主控复验

2026-10-06，独立 reviewer `/root/audio_guard_v2_review_1006` 只读复核，未修改、编译、运行模型或操作硬件。
结论：v2 可用于本次 native3 单线程 PID1/BusyBox shell/单线程 helper、无产品服务的人工只读检查；
未发现新的实现阻断。这不单独许可 START、解绑或重启。

独立核回 SHA256SUMS 1128/1128、37 冻结输入；静态 AArch64 ET_EXEC，无 INTERP/动态节。
生产 binary 741432B/SHA8cf5190071fa61285605864014a1015e307b15bc274b7b15e7893d1c5e23a5ae；
manifest c55d5fd2f0e004eb3fb3322df8d6696766c8441c19ddcc9a840243f77d824835，
inventory872966e7260eef4fb7a7c597f34637841ec00a1a3a554ef4e34b1fb97eef4dfe。
实际 Image/config 相符且 CONFIG_UIO=n。v1 UIO别名问题不是本板已发生故障。

动态 UIO major 从本次 `/proc/devices` 字符区域解析，FD按st_rdev分类；两次扫描前后完整注册表一致。
实际UIO/module/device引用生命周期支持class删除但FD仍持有时major注册继续存在。
CPU14键、DMA11键、STOP缓存、held channel allocated和HCLK例外，16clock缓存计数、
原inspector及额外Resume OFF要求均匹配冻结实现。新增模型确实把注册表解析结果送入共享FD分类器。
作者三环境各501行无重复、stderr空，由reviewer只读核对，不冒称独立运行。

主控另行实际调用冻结模型ELF，新增61项UIO组合在host/ASan+UBSan/AArch64 QEMU各61/61通过，
并再次核1128 SHA，证据 `build/guard-v2-root-recheck-v1/result.json`。
此次是冻结binary复跑，未重新编译，不是板测。

独立提醒：guard README收尾未显式列出 `/tmp/audio-debug` 卸载；已有HANDOFF要求此项。
本次主控必须正常umount并核成功，再进入native返回；不用force/lazy卸载。

真实限制：顶层PID FD而非每TID；非原子快照；STOP为驱动缓存；失败/SIGALRM不证明inspector同步回收。
失败后停止依赖动作，只读核PID1收养回收及相关FD；collector板端调用、实际idle和完整返回闭环待现场验证。
