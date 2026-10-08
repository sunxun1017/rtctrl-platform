# 旧生产 params/HW_FREE 调用链基线准备

目前只完成源码与 harness 准备，等待主控源/模型审查后执行。没有模型编译结果、Kbuild、
Image 或板验证。目录内的业务合同预计为旧实现红例，不能称共享配置已修复。

`model-v1/input-manifest.json` 独立绑定旧 model-green-v2 封存的完整输入、14 份最新普通
source/header 副本、actual integration-v4 的有限源码镜像和新的设计纠正证据。原模型、
旧 receipt、生产驱动、guard、START 门均保持。模型可用 70 个继承及 20 个新增的逐字
生产函数体；这个数表示来源身份，不代表 90 个函数全被运行。

新增的真实调用体包括 PCM params/symmetry/fixup/HW_FREE、link 和 DAI params/free
dispatcher、RK817 hw_params 与 DAC/ADC PLL restart、component params/free 和真实
generic DMA params/prepare_slave_config。沿真实机器顺序 codec child CCF→CPU child
CCF→codec sysclk cache→CPU sysclk，再进入 codec→CPU→component/DMA，未交换顺序。

准备的有限合同两方向镜像共 8 项：CPU 参数失败保留 peer rate、最后 component 失败
保留 peer rate、两向均 HW_FREE 后逐个 close 清三 cache，以及 component 失败清 rate
后合法单向 START 再请求 44100 应在首共享写前 profile EINVAL。预计观察断言 76 次；
重复标签代表镜像与健康/失败路径重复观察，不是 76 个独立测试。旧四项双 START/联合
STOP 红例在原模型留存，这个基线不宣称它们已解决。

健康运行同 rate 旧链由 machine CPU sysclk EBUSY 拒绝，没有 codec PLL 重启；健康
不同 rate 由 symmetry EINVAL 拒绝，两者作为正确观察。故障串接只从真实 component
error 路径形成 rate0，再经真实 prepare/PCM trigger 形成单向 START；不手写 cache0、
started mask。START 观察真实 C3 component/DMA→DAI 前缀；另在 CPU trigger 的第一个
regmap API 注入 errno，保留真实 prefix rollback 和第一错误。双 START 门继续拒绝。

内核 API 模型边界：regmap/I2C/CCF、PM/module、ALSA constraints、stream_valid、物理
位宽转换、DAPM update、DMA slave_config 和 DMA GO/STOP。实际 generic DMA 函数参与，
但不执行 PL330 descriptor、IRQ、quarantine 或硬件。codec HW_FREE/close 的 mute
endpoint 是只允许 mute=1 的 API shim；真实 digital_mute dispatcher 和 capture shutdown
体参与，不声称 RK817 GPIO/路由/静音寄存器真实行为通过。私有 mock 结构不是 kernel ABI。
Sticky CPU 故障 fixture 不声称正常 drain；重置 fixture 只隔离下一病例。

经主控审查后才可运行：

```
python3 -B outputs/rk3568-audio-runtime-20261005/full-duplex-params-baseline-v1/run-model.py \
  --model model-v1 \
  --manifest-sha256 07b6e6cd407d6c0e5d0772929d7a05fb9995bf8aaa3a09a5ccfc3bc869a5e84e \
  --attempt baselinev1
```

runner 要求三个环境各真实编译与执行，所有命令/stdout/stderr/ELF SHA 单独保留；预期旧
业务红返回 1，runner 仅在固定 8 红与 76 观察、完整 transcript/源码身份全等时接受旧
红复现。不执行生产 make；任何 harness 错误另立版本/attempt，不覆盖本版证据。
