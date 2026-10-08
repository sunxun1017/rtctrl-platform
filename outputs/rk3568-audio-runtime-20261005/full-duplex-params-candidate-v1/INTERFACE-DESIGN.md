# 有限共享参数候选：准确接口与失败合同

这是已审 DESIGN-v3 的接口细化，先交主控审查，再修改本目录私有源码副本。当前没有
候选生产 body、模型执行、Kbuild、Image、模块或 DT 激活。目标只闭合已实际复现的
8 项 params/cache 合同，原四项双 START/共同 STOP 红例继续保留。

## 激活与默认分支

CPU 与 RK817 codec 各自的既有 DT node 增加候选属性
`rockchip,checked-shared-params-48k` 才选择新的 per-instance checked ops；本轮不添加
任何 DT 属性。CPU 同时必须已有 checked_lifecycle，并要求 master、TRCM=1、
bclk-fs=64、lrck-ratio=1；codec仅支持 rk817-hifi，48k/S16_LE/2ch、MCLK12288000。
CPU probe 使用自己的 DAI driver 副本选择 ops；codec probe 复制自己的两 DAI driver，
checked voice 的 startup/hw_params/set_sysclk/set_fmt 明确拒绝，不能修改全局 DAI数组。

未 opt-in 的实例保持原 ops，四个新 callbacks 为 NULL。core仅在当前 runtime 的单
CPU与单codec都选择完整checked ops后使用事务；mixed、multi-DAI、dynamic/no_pcm、
voice 或不完整callbacks在共享 I/O前明确拒绝。不能因全局静态ops有新指针就跳过所有
设备的legacy cache清理；没有新 callbacks 的 runtime继续原body行为。

## 头文件及四个可选 callbacks

在私有 `include/sound/soc-dai.h` 的 `snd_soc_dai_ops` 尾部增加：

```c
int (*hw_params_begin)(struct snd_pcm_substream *substream,
                     struct snd_pcm_hw_params *params,
                     struct snd_soc_dai *dai, u64 *cookie);
int (*hw_params_commit)(struct snd_pcm_substream *substream,
                      struct snd_soc_dai *dai, u64 cookie);
void (*hw_params_abort)(struct snd_pcm_substream *substream,
                      struct snd_soc_dai *dai, u64 cookie,
                      int first_error, bool shared_io_possible);
int (*hw_params_reuse)(struct snd_pcm_substream *substream,
                     struct snd_soc_dai *dai);
```

begin只做profile与owner验证、分配不回绕的generation、保存本方向旧owner和三cache/
sysclk请求；失败时自身不留下reservation。CPU begin先设置configuring冻结START，
codec begin随后。cookie只由该endpoint生成，commit/abort必须匹配cookie、substream、
方向与pending槽。reuse是只读pending查询，返回0首次/1同tuple复用/负errno，不产生
任何I/O、owner或缓存写入；没有准确pending substream时拒绝。不新增 current/task
白名单、rtd共享stack指针或跨模块exported私有helper。

增加header内的有限inline helpers：

```c
bool snd_soc_dai_hw_params_managed(struct snd_soc_dai *dai);
int snd_soc_dai_hw_params_reuse(struct snd_soc_dai *dai,
                             struct snd_pcm_substream *substream);
int snd_soc_dai_hw_params_release(struct snd_soc_dai *dai,
                               struct snd_pcm_substream *substream);
```

managed要求四callback完整；release只调checked的真实int hw_free callback并返回errno。
原 `snd_soc_dai_hw_free()` 为void且忽略callback返回，不改其默认语义。checked core分支
用release获取错误，legacy分支仍用原dispatcher。新header/ops改变内部ABI；本轮只做
源/model，不能借旧codec ABI、32imports/2020 headers或Image结论。

## 真实整链顺序

card pcm_mutex仍覆盖整个params调用。先保留真实symmetry EINVAL，再执行checked
runtime结构检查与严格完整format/profile验证；健康不同rate EINVAL是正确行为。
CPU begin先胜后，codec begin成功，两个reuse值必须相同；否则I/O前abort成功begin
的prefix。过这些门的running同profile请求由CPU begin首共享写前EBUSY拒绝。

machine仍执行codec child→CPU child→codec sysclk→CPU sysclk原顺序。两个endpoint
同tuple reuse时，machine整段跳过CCF getter/setter/reparent及shared_sysclk setter；
codec hw_params跳过全部PLL/rate/shared width写；CPU只准备该方向RAM DMA参数，不改
共享div/rate/parent/MMIO。第一次配置继续原真实codec/CPU函数与first errno检查。

`set_sysclk`没有substream参数，pending期间只验证精确12288000、clk_id和方向，成功
不写cache、不编程时钟、不转移reservation；其它频率/零请求拒绝。真正hw_params
按它显式的substream+tuple取得自己的pending clock，不借公共sysclk setter发布。
同一个pending只允许一次apply；重复/错误substream不能再执行共享I/O。正请求在已有
owner而无pending时只允许同值无I/O验证；公共零请求仍满足旧最后close与STOP/IRQ门。

组件最后成功后才codec commit，再CPU commit。codec先发布本次owner/cache，保留
该cookie的undo快照；CPU最后成功才发布owner/cache并释放configuring。codeccookie的
undo有效到同card下一次begin/release；card mutex保证CPU提交失败后的abort先完成。
每个endpoint都有两固定slots，不分配动态owner表，不用DAI active或rate非零代替owner。

## 回滚、cache与不确定硬件

任一阶段保留第一errno。组件失败仍走真实component prefix hw_free；checked DAI不能
再走legacy rate0清理或将失败member靠core重复hw_free来撤销。abort倒序撤销全部成功
begin的endpoint，包括已经commit的codec。恢复本调用前owner、三cache及软件sysclk
请求；没有调用set_sysclk(0)/clk_set_rate(0)，也不多归还startup/PM/childclock引用。

core在首次shared阶段即machine调用前将`shared_io_possible=true`。如果首次配置随后
失败，不能证明物理CCF/codec/MMIO未改变，abort保守latch dirty/fault并禁START；即使
具体失败可能早于第一写，也不把该物理状态称clean。reuse时该标志为false，因为本轮
已明确禁止共享写；其末段slave_config错误只撤销本次params owner，peer tuple保持。
DMA失败方向的slave_config物理状态未验证，不称该方向DMA已恢复或允许START。

checked成功路径由endpoint commit维护DAI三cache，core不提前覆盖；checked error与
HW_FREE跳过legacy无条件rate0/active1清cache。endpoint hw_free只移除自己的owner，
有peer则重新保持shared tuple，最后params-owner退出清三cache。HW_FREE幂等；pending
或本向running时拒绝，不能解除别人的reservation。CPU移除本向prepared位；正常close
在既有STOP/IRQ排空后再兜底release自己的params-owner。最后open仍走现有simple
shutdown/zero门释放MCLK请求及各自child lease，params-owner不等于open-owner。

CPU commit观察IRQ/PM/runtime_error与generation；任何失效返回实际第一errno，core
abort已经提交的codec。CPU原sticky/IRQ/descriptor边界保持，未通过的端点不能START。
reuse使旧“第二向CPU CCF错误”触发点不可达，模型应明确这项消除触发的机制，不能假写
CCF以继续注入。另用真实CPU commit错误路径验证peer cache/已commit codec undo，
用首次共享配置API错误验证dirty/fault与第一errno，不改原8项合同的含义。

## 锁顺序与未闭合入口

card pcm_mutex为外层；CPU spinlock只做有限状态/MMIO，begin不持它进入codec。
configuring跨CCF/I2C/睡眠操作保持，但CPU锁已释放；codec params_mutex只覆盖其owner
与本endpoint apply，允许I2C睡眠，不能反向取CPU锁。codec commit先完成并释放codec
锁，CPU commit最后单独取CPU锁；abort同样不同时持两锁。不会将PM put移入card锁。

checked voice共享入口本轮拒绝；hifi/voice共用同component而不是两份PLL。直接sysclk与
重复apply仅做上述有限门，不泛称所有rk817路径已仲裁。原codec path controls、power
helpers、set_fmt、系统PM/DAPM副作用，以及CPU PPM/control旁路仍需独立闭合/审查，
本轮候选不能因此获Image/板/START许可。真实PCM/C3 START整链与前缀rollback参与
模型，不能只测CPU trigger或以API DMA GO模型宣称PL330运行。

## 本轮五文件修改边界

- `include/sound/soc-dai.h`：四可选hooks及三个有限inline helper。
- `sound/soc/soc-pcm.c`：checked整链事务、局部cookie prefix、成功commit/错误abort、
  checked HW_FREE cache归属；default-empty保留原caller。
- `sound/soc/generic/simple-card-utils.c`：checked纯验证与idle-reuse分支；原callback
  签名和simple-card ops接线不改变。
- `sound/soc/rockchip/rockchip_i2s_tdm.c`：显式opt-in per-instance ops、两个owner/
  pending、CPU gate/owned apply/commit/abort/free，pending clock验证与旧START门。
- `sound/soc/codecs/rk817_codec.c`：显式opt-in per-instance hifi/拒绝voice ops、
  component两owner/pending及mutex、reuse/first apply/commit/undo/free。

无DT修改、无需本阶段改C3/DMA算法。source/private header身份与新body将按这五个
有限输入映射，不新扫SDK、不重复大库存、不创建生产build。
