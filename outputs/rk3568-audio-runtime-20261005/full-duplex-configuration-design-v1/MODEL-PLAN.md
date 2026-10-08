# 真实 params caller-chain 的最小下一模型（未执行）

复用 `asoc-open-rollback-v1/model-green-v2` 的双 substream/真实 active、startup mark、PM
local-prefix 和 source extractor，不改该目录。旧模型 CPU hw_params body 虽被抽取，其
caller 的 cpu_ops/codec_ops/link_ops 没有 hw_params，codec 只有真实 sysclk setter；
旧成功不能覆盖 soc_pcm_hw_params、RK817 PLL 或晚段 slave_config。

后续另立新模型目录并带自己的 input-manifest/完整 runner/test 快照。用本设计14项输入
为起点，实施时重新核 actual 源普通文件/祖先/SHA，不用 mutable manifest 替换旧红例。
本目录43项 body SHA 是设计证据，不是已编译/运行的真实函数覆盖数量。

## 必须接入的生产体

| 段 | 真实入口及必须保持的副作用 |
| --- | --- |
| PCM caller | soc_pcm_hw_params、soc_pcm_params_symmetry、soc_pcm_codec_params_fixup、soc_pcm_hw_free；真实 card mutex、prefix 标签、cache 写入和 rollback 宏 |
| link | snd_soc_link_hw_params/hw_free/be_hw_params_fixup + asoc_simple_hw_params/set_clk_rate；不得交换 codec-before-CPU 顺序 |
| DAI | snd_soc_dai_hw_params/hw_free/set_sysclk、实际 iterate 宏与 fixup 参数拷贝；本次 stream_valid 有限 API shim 须明确边界，后续能力验证才抽取真实体 |
| codec | rk817_hw_params、set_dai_sysclk、DAC/ADC restart_and_apll 完整体；chip<=4 和 >4，两位宽 writes 与全部 I/O first-error |
| CPU | 既有冻结 checked hw_params/set_mclk/params_dirty/trcm/set_sysclk 与既有 gate；原单向 START/STOP 保留 |
| component/DMA | snd_soc_pcm_component_hw_params/hw_free、dmaengine_pcm_hw_params、snd_dmaengine_pcm_prepare_slave_config；slave_config 最晚失败/部分状态模型 |
| 关闭 | 最新 clean_locked/post_unlock、runtime deactivate/DAI active、simple shutdown 与本阶段 proposed hw_free callbacks |

源码 tuple/formats/register 常量从实际 headers 提取；给 params mask/interval 足够真实表示，
不能让 `params_format` 永远返回 S16 或把 S24/S32 当同一宽度。无 mask 修正的板 profile 仍
用真实 fixup/copy 路径；multi-codec 的人数不假造成已覆盖。

只对内核 API 副作用建模：I2C/regmap、CCF、DMA slave_config、PM、ASoC DAPM 调用与
ALSA constraints。分别保存 codec/I2S cache 和硬件值、old/new clock rate/parent、每个
调用/返回/顺序；失败注入可在写已发生后返回负 errno。实现 wrapper 并不证明真实外设
会按这类故障工作。Dapm/PL330 本体不进入本次最小模型时明确不覆盖，不称完整内核。

首先给旧生产体注册真实 hw_params callbacks，运行完整 caller；红例名单冻结后才开始
任何新候选生产修改。不要为了业务绿化提前换 machine/codec/CPU callbacks 成理想 shim。
codecs/shared controls 旁路可作为第二小单元加入真实入口，不先把所有电源代码加入大模型。

## 有价值的业务病例（拟定，不是测试结果）

| 病例 | 核心可观测合同 |
| --- | --- |
| A→B / B→A 两 idle 同配置 | 首次 shared transcript；第二次共享 PLL/rate/reparent 写0；两独立 params owner、无重复引用 |
| 同向重复同 tuple | 不重复 owner、共享 I/O；独立 buffer 参数仍真实到达最后 component |
| 第二向 S24/S32/不同 ch/rate | 完整不同格式或非法 profile 在任何 shared I/O 前返回 EINVAL；旧 rate/cache/owner/refs 不动 |
| 合法单方向 START 后，第二向 params | 健康同 rate 在 machine CPU sysclk 处 EBUSY且无 codec PLL，健康不同 rate symmetry EINVAL均为正确观察；晚 component 失败清 rate 后的 44100 旧链 CCF/cache先变再EBUSY，候选 profile EINVAL且首共享写0 |
| 第二向 cpu hw_params 失败 | codec prefix 被 hw_free，真实旧 core 清 peer rate 红例；候选恢复 peer 三 cache 字段和配置 owner |
| 最后 DMA slave_config 失败 | codec/CPU 成功后 core 完整 prefix 回滚；仅撤销失败方向，peer 三 cache/请求保留 |
| machine 早失败 | codec child rate/CPU child rate/codec setter/CPU setter 每个首失败；真实 link 失败直接 goto out，必须在 machine 自清 |
| codec 内首/中/最后 I/O 失败 | 失败 DAI 不在 core --i rollback 内；真实 callback 自清本次 owner/cache，保留首 errno与 dirty |
| CPU CCF/parent/dirty-read/write 失败 | 自有 reservation 撤销；已有 peer 请求不清；hardware unknown 禁 START且必要 lease 不释放 |
| fallback/恢复也失败 | 第一次 errno 不覆盖，第二失败 transcript保留，绝不能把恢复尝试当 old hardware 已证明 |
| HW_FREE A、B仍 configured；再 HW_FREE B但均 open | A释放仅A owner，B不丢 cache；最后params清三DAI cache；仍open时不误发sysclk0/disable startupref |
| 第一个 close、最后 close | 最新 same-DAI active门/CPU zero gate真实运行；第二 open引用存在时请求保留，最后关闭才清 |
| 第一 params失败而仍有两 open | cache旧0但 pointers仍在；公共set_sysclk0仍拒绝，事务abort内部还原不借用zeroAPI |
| voice/hifi sibling 与 direct sysclk/fmt/control | 不能用 hifi两bit忽略component sibling；不一致/零/PLL旁路必须拒绝或以未闭合业务红例保留 |

首/中/末失败只为区分真正不同的 prefix/resource行为；不靠增加同义标签制造覆盖数量。
错误与引用分别记 get/put、pending/commit/abort 次数，underflow也应报错，不能用饱和计数
隐藏 double release。正返回、ENOTSUPP 的 machine 既有约定按真实代码处理；checked profile
所需 callbacks缺失不能被“not supported等于成功”带过。

## 确定性竞争，不伪造全双工

pthread/barrier 设置在真实 API wrapper 的边界：begin前/两个端点预约后/machine CCF前、
codec PLL内、CPU I/O后/最后 component前、finish前/abort内。A单向合法 START 与 B params
各做“START先胜”和“reservation先胜”；验证没有门检查到共享写的空窗。另覆盖 IRQ令
ticket失效、PM transition、HW_FREE/close 阻塞于真实 card mutex、control/sibling绕过。
相同 card mutex 覆盖的两个 hw_params 不应虚构成同时执行；用真实等待/互斥观测证明串行。

不持 CPU lock 等待 codec/I2C/CCF/PM；实际锁顺序应体现在 wrapper 的 assert 中。旧IRQ
captured-pointer/C3 descriptor quarantine 的既有观察保留，不因本轮绿化拿掉原约束。
无需新建双channel PL330执行器，也不能把DMA stub的正常参数配置当DMA GO已通过。

## 后续执行门

1. 先新建基线 caller 模型，固定真实函数 unit SHA 与红例名单、旧成功回归和精确断言行数。
2. 主控审接口成本/源码范围后，另立候选及对应 begin/end/abort 函数、真实caller差异抽取。
3. host、ASan+UBSan、AArch64 QEMU各实际编译执行，逐 stderr、退出、固定业务名单/数量、
   真实unit重建与 I/O transcript 验收；旧双START/jointSTOP四红仍必须存在且名字不变。
4. 独立源码/模型复核后才做相关 Kbuild/整套Image/codec重建。若 ops/header ABI改变，
   旧内核/module/2020 ABI/32imports 结论不能借用，全部重新绑定。
5. 此轮只有设计。没有开始上述1—4，不产生板START、guard放宽或正式刷写许可。

基线另保留真实 soc_pcm_trigger 的 component/DMA→DAI 顺序与 C3 rollback；未抽取的
DMA GO/STOP 为 API 模型，不能称 PL330 实机。健康不同 rate 的合法 EINVAL不计业务失败；
44100 的候选首写前 EINVAL 与旧晚 EBUSY按不同合同观察，不统一成同一 errno。
