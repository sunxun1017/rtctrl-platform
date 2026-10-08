# RK3568 ASoC 打开失败与共享时钟请求设计

目的：继续用户已授权的 Android→Linux 适配，先修复真实双 open/单 close 与打开失败时的资源归还。
保持已验证的单方向传输，当前不放宽双 START。设计依据为锁定5.10.160 SDK、已实机声音v12/C3源、
full-duplex-contract-v1的真实caller-chain红例，以及独立只读PM调用者审查。

## 当前缺陷

`soc_pcm_open()` 在 startup失败后先释放 `pcm_mutex`，再由 `soc_pcm_clean()` 重新加锁。
此间另一方向的正常 close可以覆盖rtd/DAI/component单指针startup/open/module标记。
失败方向尚未activate，`snd_soc_dai_active()==0` 不代表没有在途启动资源。
基线三环境实际红例已复现child-clock引用漏还及CPU指针未撤销；这是API模型中的允许调度，非板上注入。

PM get在mutex之前，put在解锁之后；component的单指针mark_pm还可被另一次open/close覆盖。
只锁住startup rollback不能修复PM引用归还。get失败当前只put_noidle失败成员，已成功prefix依赖外部clean。
来源调用者是PCM及compressed open/free；当前Image未编CONFIG_SND_SOC_COMPRESS，但源接口更改仍兼容两者。

simple-card shutdown在正常runtime_deactivate和DAI shutdown之后，无条件先向codec再向CPU发送sysclk0。
同一DAI的peer仍open时，codec请求先清空，CPU合法拒绝留下诊断。当前板只连接rk817-hifi的单CPU/单codec link。
rk817-voice共享component缓存，不在这次同DAI门的保证范围。

## 修正契约

1. 拆为私有 `soc_pcm_clean_locked()` 和 `soc_pcm_clean_post_unlock()`。
   正常close保持deactivate→DAI shutdown→link shutdown→component close→DAPM stop的次序。
   startup失败在原pcm_mutex连续持锁区内执行locked清理，不新增deactivate，原open errno保留。
   PM回调和pinctrl仍在锁外；不递归加锁，不省略C3排空/quarantine副作用。
2. PM get部分失败时，失败成员先put_noidle一次，再按本调用局部prefix索引归还已取得的每个引用。
   保留原释放顺序、first errno、mark_last_busy/put_autosuspend语义；后来成员不操作。
   返回0/1及-EACCES都已取得usage引用；-EACCES仍按原语义接受。
   get全部成功后，正常close或startup失败才归还全部本调用引用，不依赖共享mark_pm。
   保留helper签名及component结构，避免新增ABI字段；无导出符号变化。
3. PCM和compressed调用者的get失败分支不再执行clean/fullput，避免重复归还；
   该阶段尚未取得component/link/DAI启动资源。适当的pinctrl收尾保留且范围明确。
4. simple-card仅在实际CPU和codec DAI active均0时发送原两次sysclk0。
   peer仍open（含idle）或failed-open rollback时保留双方请求，child clock每次取得仍逐次disable一次。
   当前CPU零请求的STOP、IRQdrain、无substream和sticky门保持；最后owner退出才清请求。

## 验证与范围

使用真正runtime activate/deactivate、DAI active、startup/open/module/PM标记和ASoC dispatcher，
不能用每方向理想化marker替代生产单指针。PM计数、regmap/CCF/IRQ和调度切点是显式API模型。
实际函数红绿在host、ASan+UBSan、静态AArch64/QEMU运行；完整原单方向模型保留。
新鲜built-in Kbuild检查soc-pcm、soc-component、simple-card-utils；compressed source分支也检查，
不在板镜像启用compressed音频。独立审查后才整合新完整Image及匹配codec。

必要行为包括两方向顺序open/close、最后close、各startup失败前缀、原unlock gap、
full/partial PM get与另一open/close交错、-EACCES、返回1、重复device但不同component、
共享DAI不同runtime的引用计数。sticky和IRQ未排空时CPU零请求仍拒绝。

pinctrl的在途PM窗口属于已有独立边界：active0不证明无pending PM owner。
当前板profile为default-only，不能由本次修正宣称所有板的sleep-state切换并发安全。
PM引用平衡不代替callback drain、device kref、runtime_disable/barrier或remove许可。
该候选也不证明codec共享PLL/DAPM、第二START、单方向STOP保留peer、joint fault和双allocation隔离。
软件结果不自动授予硬件START、正式flash或充电/MCU操作。
