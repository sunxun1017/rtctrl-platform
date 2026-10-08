# ASoC 打开失败与同DAI共享请求候选复核

2026-10-06。接受四份私有源码进入下一版离线 Image 整合；不授予双方向 START 或正式刷写许可。
主控已重新编译执行，独立只读审查 `/root/battery_dt_audit_1006` 未发现当前限定范围的阻断项。

候选 `asoc-open-rollback-v1/candidate-v1.patch` SHA
`179cf3c1bc7d37124e1d7aae792cbe105bb2f6a2ab726077ed7c6fb577dce7f7`。
四文件以 actual v3 基线严格逐hunk重放，结果与候选逐字相同：

| 文件 | 候选SHA256 |
| --- | --- |
| sound/soc/soc-pcm.c | 9ba2247294f745488133b3d0b307686249b4c2cd23045ea1bfba517dd57aed37 |
| sound/soc/soc-component.c | ea81b958a6cdf035a29de112e07f15f55f774d4f67a02b68ca1eae6c0ce5d85c |
| sound/soc/soc-compress.c | d9a1b4de08206c232ccfef37a85a25f65053ebb7a7b2bbcd36cff2c22a918bc8 |
| sound/soc/generic/simple-card-utils.c | 4b2094f708f5bec2b73938ec217eedae67f5df962ee0847bee8f2c29eddbcd73 |

失败startup在原pcm_mutex区内完成清理，不deactivate尚未activate的方向；正常close排序保持。
PM get部分失败逐次归还本调用取得的prefix，失败当前项put_noidle一次；full get后才full put。
PCM和compressed get失败caller不再二次清理/归还；0/1/-EACCES、重复device按每次get持引用。
simple-card只有同CPU和codec DAI的active都零才发送原codec0→CPU0，child clock归还不跳过。
CPU v12、C3排空/quarantine、first errno、sticky与IRQ零请求门、单运行方向START门和结构ABI保持。

作者真实函数红68/绿70；独立逐body SHA与完整unit重建均exact。
主控[新鲜六次编译执行](build/root-asoc-candidate-v2/result.json)在host、ASan+UBSan、AArch64/QEMU：
原代码0/25，候选21/25；两版110/110观察，compile0/run1、stderr空，完整stdout SHA与作者各版相同。
110是重复场景的观察断言次数，74个唯一标签，不是110项独立硬件测试。
4个剩余红例为两种顺序的第二START、并发双START及假设双running的共同STOP证明；保留原拒绝。
新额外观察包含实际module/open/close标记、11个startup失败prefix首errno、实际PCM/compressed caller、
同device多次引用、EACCES/正1和underflow/逐次put计数、共享DAI不同runtime及CPU sticky/IRQ拒绝。
首次root解析工具不支持实际跨行inline声明，未编译即拒绝；原失败记录保留。
v2只加局部真实prefix/brace抽取，未修改旧source_utils、候选源或模型。

[实际Kbuild对象](asoc-open-rollback-v1/kbuild-v2/receipt.json) SHA
`4f1403bd8aec74ee0ea1e24ff65ffca1ffe9c7b82399d7732f629417446b54dd`：
5+3实际Kbuild/nm/ar步骤exit0、stderr空，四AArch64 ET_REL对象无-DMODULE，分别进入obj-y thin built-in.a。
三项使用原配置1268f306…fed912；compressed单独影子仅在三份配置/头中精确追加2flags，
属于预处理源码分支编译，未由Kconfig生成、没有compressed配置或ABI验收，原板配置仍禁用。
8395项有限原输入（13protected/2020实际ABI/6362头与脚本，其中4个明确内部link）独立重核零错。
此前kbuild-v1库存碰源码内link的拒绝发生于编译前，保留失败。
这次对象验证不证明新SDK整合位置、完整Image链接或压缩产品配置。

PM core/CCF/regmap/IRQ/调度、组件与codec回调和平台DMA仍为明确API模型。
同DAI gate不覆盖RK817 voice共享缓存；泛型pinctrl在途PM窗口、codec PLL/DAPM、共享参数、
第二START、方向STOP与双DMA共同故障仍未闭合。PM平衡不代替drain/remove许可。
需要新完整Image、匹配codec ABI、包审和严格前后检查后，才另立有限双open/单close实机矩阵。
当前板最后一次操作仍是第四轮正常返回原Android；无新板操作或网络/TUN修改。
