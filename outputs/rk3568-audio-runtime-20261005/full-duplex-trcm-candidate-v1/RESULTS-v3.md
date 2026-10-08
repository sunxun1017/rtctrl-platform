# CPU TRCM 私有候选实际有限结果

最终 CPU 位于 source-v3/sound/soc/rockchip/rockchip_i2s_tdm.c，SHA
e2b15d902c11f5cd9537d8af49430260c468c4d93b908b8823c63414d8210b97。
source-manifest-v3.json SHA
1de4056f3e4dc5aa43c51730cbb6250ab0c42ad828e01065bdbd5521fe1e7ede；
cpu-trcm-private-v3.patch SHA
57c50c1015eb5221e3ff6da47936ca01bba6189ad166a1a737c017fddbbdbcc7。
只有 CPU 文件新增 23 个有限 changed/new body 身份；params source-v4、原 SDK、Image、
DT 与其它候选均未写入。新 optional ops 字段 pcm_async_fault 由主控统一整合 header，
本模型有限 ops shape 不是实际产品头文件编译或 ABI 证明。

实际旧 model-v7 在 host、ASan+UBSan、AArch64 QEMU 均 compile0/run1：原 params
8 项通过、4 项 CPU 传输合同失败，73/95 观察通过，18 个有序 case；每组完整 stdout
三环境字节相同、execute stderr为空。runs-baseline7/receipt.json SHA
7ef2253c92ebba1ea430fd88224d1ed3a0018bb861149db2eccd1a105efeb373。
新 model-v8 同三环境 compile0/run0：12/12 合同、95/95 观察、18 case 全等。
runs-candidate8/receipt.json SHA
d2356a983f25cf09263732b37834b85d8a6a9dc46170ff7120605ff95b337e1e。

四项合同分别为 sequential_first_0_second_normal_START、
sequential_first_1_second_normal_START、concurrent_two_normal_START_commit_both、
shared_fault_joint_STOP_reaches_global_proof。最后一项用真实两个 START 后的 status IO
错误检查，替代旧仅手造 started=3 的反例；不是宣称旧不可达状态在板上曾发生。
原 params 八合同仍通过。模型执行了真实 PCM→C3 component/DAI 前缀、CPU 预约/提交、
方向 STOP、最后联合 STOP、owner prepare 与正常 close。并发 START 后通过 join 检查
状态；并发 event 顺序不宣称确定，相关 group 明确无完整 interleaving transcript。

source-v1 草案错误地把健康单 IRQ 视为 shared fault，按主控意见在 v2 改为本向
IRQ disable/ACK 与单向 XRUN；只有 status/IRQ IO 失败才 sticky、撤票、joint STOP 与
双通知。真实有限 native 8 body（action/lock/single/pre/do/undo/post/start入口）用
unlinked/atomic API 锁切片复现：DAI commit 后、真实 post_start 写 RUNNING 前，ISR
通知等待 stream lock；随后真实发布再执行 XRUN API 的真实 C3 STOP，peer 保留。
没有执行完整 ioctl、linked group、nonatomic 或完整 snd_pcm_stop_xrun 生产实现。
时间戳/锁/XRUN 是明确 API wrapper，不能据此称完整 ALSA 内核或硬件已验证。

v3 的 async hook 先 latch 首 errno 与撤 ticket validity。无 hclk/mclk lease 或
power_transition 时不做 MMIO，不造 STOP proof，保留实际 transport/owner 状态；
恢复合法访问后实际 joint STOP 仍保留首 errno。对应两个有限 API 状态切口已实跑。
IRQ fault 撤票保留 starting 借用，直到真实 C3 STOP 清理；没有把 epoch 失效或
PREPARED 下 XRUN 返回0称作 DMA GO 借用已归还。

另外 model-v9 加一项真实 CPU/DMA 接缝。从 DMA source-v5 抽取
substream_to_prtd、dmaengine_pcm_error、dmaengine_pcm_check_fault、
dmaengine_pcm_notify_fault 和 generic dmaengine_pcm_cpu_fault 五个真实 body，
调用实际 CPU pcm_async_fault。首次 cached -ENOSPC、随后 -EREMOTEIO 保留 DMA/CPU
首 -ENOSPC；notify 后 starting 借用仍为 BIT(0)，真实 CPU DAI commit 拒绝，再由
真实 C3 STOP 才归还该票据、停止本向 DMA API并取得 CPU STOP proof。同步 check 的
stop_xrun=false 没有虚构 PREPARED 的 XRUN drain。

model-v9 在三环境实际 compile0/run0：12/12 合同、100/100 完整有序观察、19 case。
完整 stdout 字节三等，SHA
7b8fbdd9eda3513e389cac201bab791ec2e77351a797f1e5effb4d8033bf5ac7；stderr均空。
run-model-v4.py SHA
dc9e78e423bc9fbbb0bc5750736eef7af11e86086d0c4de36790811a74d9210a；
model-v9/input-manifest.json SHA
c41de7dcb848c05a56287f1e7d58e7c26ecebdedc34ee90fc700333ad1defb05；
runs-candidate9/receipt.json SHA
38dac5bc940a3ca4c8296c5e997d8e64c92ebb4fed7bd4d1541232b740b3a52e。
runner 严核完整有序 label/case/count、summary、实际 input 前后及自身字节。14 个
actual SOURCE、五 private params/CPU、两个显式 external DMA-v5 普通源有限核回。
154 个 available body 是身份库存，不是执行 coverage；额外 DMA case 只在候选
执行，旧 v7 基线的95观察不可改口100。最后接缝沿用有限 prtd shape、cached
dmaengine_check_open API叶与显式 sink绑定，未执行真实 PL330 fanout/完整DMA提交。

历史均保留：precheck-failure-v1 的72/85准备计数错误未 compiler；runs-baseline2
三 compiler 未抽 runtime_suspend 失败；runs-candidate5 三 compiler 未抽 failstop
失败，均未执行业务模型。更正只补真实依赖与明确 API叶，无 warning豁免。旧 v1/v2
源码草案和各 model/runs 不覆盖。model-v8与v9使用相同稳定CPU v3字节，未新增CPU修改。

本段没有 Kbuild、Image、模块、DT 激活、板或外设测试，不授予硬件双 START。
实际 FIFO残留/重启样本质量、PL330异步fanout整合、native完整模式、codec共享IO/PM
仍由独立候选与主控整体构建/审查完成。关本向 DMAC/IRQ的quiet proof不等于FIFO清空。
主控后续新树应保留 simple-card-utils 的 pcm_params.h 直接include修正，并统一新
ops header、CPU与DMA代码；不能复用旧codec模块或将本模型当产品ABI证明。
