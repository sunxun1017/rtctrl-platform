# 2026-10-05 用户暂停，明天续做

用户明确结束今天工作并要求关机；停止适配、板测和审查推进，仅保存状态并正常关闭开发板。
TUN/路由保持；没有刷启动分区、saveenv、提交或推送。明天必须重新核当前板卡/供电/地址/串口/进程，
本页不是自动启动或自动测试指令。

已完成：

- 默认加载目的地实际 Linux/native3/普通重启→原Android，50/50；七保护SHA一致，完整FDT仅大小/SHA见证及chosen子集。
- C3 v8独立只读功能复核、主控实际重新编译/运行三环境各82/82；CPU v10接受，公共0011/0012精确SHA发布。
- 专用源码完整十二补丁Image/modules构建exit0，Image34755072B，SHA
  e48c4295b871623f3c4d0e18470d451b5c344b7e71d021c77f9b0cc297d89955，CRCfb920db9，memory35389440。
  `build/integration-v1/manifest.json` SHA5caa5a64816af8627baf880d46cae55876e5a6ed0985afc21fd623765c1860f5。
- 新Image精确ABI codec518904B/SHAe0aecc775367f93555c5776938102d419865a19128b25f64d74a8e9df387ca80；
  32 imports及2024 ABI文件核回，`build/integrated-codec-v1/manifest.json` SHA0dfeb4a9fc079d08068e8b2915ee05b4927d23f131768dfa3d88955cbd584c52。
- 新生产包另立v2修正合法空日志读取及Linux release；真实回归14/14、机械fixture62/62、production CLI/audit及主控新鲜audit均通过。
  `../rk3568-audio-package-20261005/build/ram-audio-v2/boot-padded.img`40MiB/
  SHA58e2a96f9da2c2ad1d60e0b42c92efa2d4c30efbfe76202738393f2e06974b8b/CRCfe7bd3a1。
  旧工具/红例/prepared-v1保持；新封存receipt SHA1ed275fbc3e98d03f005d1e3ecb474ced96e8bd2bc3e8ee5a805ef3d26af6dad。
- 精确回收三份有完整host备份且fresh SHA通过的旧cache普通文件59692016B；七保护/RCU/display/native3/v2包前后通过。
  cache11676→69972KiB，receipt在cache-reuse/build/audio-reclaim-plan-v1/android-reclaim-v1.json。
- guard v2动态UIO major关闭v1 alias模型缺口，作者501×3；本Image CONFIG_UIO=n，不称本板可达UIO故障。
  binary741432B/SHA8cf5190071fa61285605864014a1015e307b15bc274b7b15e7893d1c5e23a5ae；
  manifest c55d5fd2f0e004eb3fb3322df8d6696766c8441c19ddcc9a840243f77d824835；
  outputfreeze872966e7260eef4fb7a7c597f34637841ec00a1a3a554ef4e34b1fb97eef4dfe/1128SHA。
  v1独立不放行：UIO alias及/run1MiB noexec例子，v2文档改/tmp8MiB exec。v2最终只读复核被用户暂停中断，未作完成声明。

尚未完成与明天第一步：

1. `prepare-audio-board-trial.py`已生成`build/board-audio-v1`七文件/44514723B、九项live音频DT属性、
   load/boot/copy-aux会话；inputmanifest SHA2f1a0ce6c4a986c72b8413ce20cef8c0534b1d77b0a7ecc8195163a77dbe828c。
   exact core diff为两项策略修正加新snapshot文件名；先漏识别新文件名的拒绝记录保留。
2. `stage-reviewed-audio.ps1`在host输入遍历`aux.sha256`时Get-Item失败，在第一次ADB命令前退出。
   没有新audio cache目录/上传/上板。该文件名可能与Windows AUX保留名有关，尚未实证根因。
   下一步保留此失败后将新版本校验清单命名为audio-files.sha256，再核真实普通文件身份和SHA。
3. 完成guard v2独立只读复核，主控必要新模型复验和1128冻结SHA核回；当前没有START许可。
4. 新鲜Android/root/七保护/native缓存校验→普通cache文件暂存→新鲜Uboot banks/gd/env/CRC，
   kernel4MiB/FDT gd A100000/IR64MiB临时目的地，单bootm进入native3。
5. 核新Image身份/live音频DT/CPU及两DMA缓存状态/held通道实际数量，copy aux到/tmp/audio，
   再正常codec插入、控件OFF/MIC OFF/Resume OFF、单线程独占域及guard分阶段验证。
   playback零样本/capture仅帧统计，方向分开；硬停不确定保持禁止warm reboot/旧RAM复用。
   正常card/codec→CPU注销收尾、额外debugfs正常卸载，再native原生回RAM/七挂载guard/普通重启/Android七SHA。
6. 正式early DT/USB恢复/生产服务与接回实物屏幕声音/MCU契约仍未闭合。只有板子，屏幕/耳机/喇叭/电机未接；无SD卡座。
   DMO是用户断电近0Ω测量，但引脚身份不确定，不称确认USB D−短路或恢复可用。

关机已实际记录原Android正常请求→原MCU driver watchdog off/power off→kernel `reboot: Power down`。
COM8随后从设备列表消失，采集Read报Access denied使初版receipt未更新成功字段；原错误与raw保留，
另立`private/android-poweroff-observation-v2.json`按完整raw SHA确认Power down，不覆盖初版。
原Android关机日志有xhci Host halt failed -110和invalid GPIO，不能写为零错误；不是新Linux关机验收。
本任务ADB转发已正常断开收尾；物理电源轨未测量，主控没有直接发送MCU帧或强制复位。
