# 新声音软件整合的有限接受

2026-10-06。独立reviewer对CPU v3、DMA v5、控件/terminal v5指定差异和实际caller
进行只读审查，未发现具体阻塞问题。主控保留CPU PM首sticky errno优先门，再检查
共享参数owner/pending；同时统一新头文件、直接pcm_params include和实际构建。

接受依据包括真实descriptor借用/producers排空、先捕获全部故障回调再联合停止、
精确首错、C3失败清理、健康单IRQ保留peer，以及native unlinked atomic START锁
贯穿实际post_start的有限切片。codec的process shutdown只在client_mutex下借用card，
文件等待不持card/私有参数锁；解绑false与后续devm注销配对。

作者三环境实际记录为CPU/DMA接缝12/12合同、100/100观察，DMA37/37观察，
controls/terminal1471/1471观察。主控再以实际合PM owner门的CPU body新编译运行
三环境12/12与100/100；首次model-v10参数不符合既有CLI regex，在compiler前拒绝。
保留该失败，仅使用字节相同的model-v20和新argv后成功，没有放宽断言。

完整Image/modules实际退出0，89423 tracked输入前后一致，Image SHA e2a5590f…ae3f61。
canonical模块实际编译与ELF审核通过，SHA c43e470c…e13d85，37个imports精确对应
本次Module/vmlinux symvers；2020 generated记录前后保持。完整源库存对已接受audio-v4
只有11个文件变化，交付补丁在私有基线副本实际重放并逐字等于当前构建源。

追加独立只读审查核当前Image/vmlinux/canonical模块完整身份、实际新头依赖和MODULE
编译命令、新helper的vmlinux/ksymtab、37个实际U符号与2020 generated当前记录均相符，
日志没有新增compiler/modpost/undefined错误。完整构建stderr为V=1正常shell trace。
合PM CPU模型仍继承部分params-v4输入，不能当完整新Image/terminal ABI的运行模型；
生产头与最终codec绑定由上述实际Kbuild和符号闭合分别证明。

新离线RAM包也获独立只读有限接受。主控新CLI实际退出0、stderr空，39输入前后同，
36包文件完整SHA/CRC、raw+零padding、真实完整overlay与保存结果一致。reviewer另直接
解析组件和RSCE：九份resource DT及header DT都是新配对树，两logo与原包逐字相等；
包内18源码快照与当前工具一致。9输入、15格式及paired-DT检查实际通过。
主控回读共享构包器纯校验函数，是独立进程重算；不冒称算法独立实现。
包保留的原header编码地址存在已记录重叠，暂定RAM区间静态无重叠不代替实际搬运规则。
下一次必须fresh核bank/reserve/加载地址和U-Boot搬运，离线接受不授予刷写。
[新包主控实际回读](build/root-offline-next-audit-v1/receipt.json)。

接纳为离线checked-profile软件候选，尚不是板上全双工或正式刷写许可。MMIO/DMA、
真实调度、完整close/native linked/nonatomic等仍有未执行或API夹具边界。
5000ms仅约束文件等待，整个shutdown没有该时间上限；FAULT硬失败保资源不构成恢复。
不将MODVERSIONS=n的imports/vermagic当运行CRC，不将源码检查当安全卸载实测。

证据见[软件当前记录](SOFTWARE-PROGRESS-20261006.md)、
[主控最终绑定](build/root-audio-integration-v5/final-software-v1/receipt.json)及
[主控合并实际回归](root-cpu-pm-merge-v1/runs-merged2/receipt.json)。
