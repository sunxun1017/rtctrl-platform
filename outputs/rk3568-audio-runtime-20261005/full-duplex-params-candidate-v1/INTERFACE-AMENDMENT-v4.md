# 主控评审后的准确 v4 接口

本记录补充最初 INTERFACE-DESIGN.md，发生冲突时以本记录为准。source-v1/v2/v3是
未编译的工作草案，保留原字节；当前待模型审查源码是source-v4，五文件47个有限
新增/修改函数身份，source-manifest-v4.json 889c0e25655b29bbda10061b6f0ac569741b892a20cd0316695498442be8037c。
本轮没有Kbuild/Image/模块/DT激活或板端动作。

可选ops现在是6个：begin(ss,params,dai,u64 *cookie)、commit(ss,dai,u64 cookie)、
abort(ss,dai,u64 cookie,int first_error,bool shared_io_possible)、
reuse(ss,dai)、free_check(ss,dai)、fault(dai,int first_errno)。
managed要求6项及真实int hw_free完整；任意partial新hook在I/O前拒绝。默认全部空
保持原函数路径。两个probe的DT显式opt-in与实例ops副本保持，probe尚未模型执行。

固定两slot软件state及8个header owner/查询helper只在endpoint锁内执行。cookie达到
U64_MAX后拒绝EOVERFLOW，绝不回绕。begin失败不留预约；commit仅识别匹配的
pending+transaction+cookie。重复或陈旧commit返EINVAL无mutation。CPU匹配提交失败
保留预约直到core最后CPU abort，不能提前让peer START进入codec undo窗口。
codec失败commit局部撤销匹配pending，CPU预约仍保护全链。abort幂等，旧cookie
不影响新generation。

正sysclk仅无I/O/no-cache验证clk_id=0、12288000及合法IN/OUT。真实parse_clk
缺省clk_direction为IN，init_dai可在任何pending/owner前调用正请求，必须支持此
有限初始化路径；OUT属性同样支持。正setter没有substream，不认证其调用者。
零请求仍只接受CPU OUT/codec IN及现有last-close/STOP/IRQ门。

HW_FREE先两个只读free_check，再CPU release锁内复核竞争START，再codec release。
codec后段拒绝会留下真实半释放状态，core同时latch两端FAULT并保持clock lease，
不能写缓存冒充原子回滚。正常mute/link/component释放继续全部真实callback前缀，
保存第一errno，任何释放失败同样FAULT，fault本身不能联合停止已运行peer。
两个旧释放dispatcher为void并吞callback int，因此soc-pcm新checked helper保留
实际顺序/last前缀而收集errno；default仍使用原dispatcher。本TU不能借soc-component.c
静态soc_component_ret，当前使用合法dev_err。

params错误顺序现在是component prefix cleanup、machine cleanup、codec abort、CPU
最后abort。任何清理错误不能被原params errno覆盖；首次shared阶段之后的失败保持
sticky/dirty，HW_FREE/close不洗掉它，不造物理clock restore。

RK817新增shared_open[2]独立于params-owner；checked startup记录实际open identity。
shutdown只清匹配自己的open，peer即使idle且没有params也保留共享clock。最后capture
close仍调用原void rk817_codec_shutdown，其两I/O错误吞失是未闭合边界，不算参数
事务证明。基线RK817没有startup/prepare/runtime-PM；新增startup不能冒称旧路径已有。

系统PM、manual path controls/power helpers及其它入口仍另行调查。真实ASoC component
suspend wrapper为void会忽略callback errno，不能仅以codec callback EBUSY宣称系统PM
fail-closed。原四项dual START/共同STOP红例不在本轮目标；新ops/header内部ABI改变，
以后需整套真实编译，不能复用旧codec模块或旧ABI验收。
