# 真实参数 caller 模型待执行清单

source-v4五源已交只读审；model-v4/input-manifest.json SHA
221a81e3fce4d32a33b460d4f4fe0427e1e0922513f44df9d6978c728e2a057d。
precheck-v4实际exit0：12个actual SOURCE有限映射、5个private源、128个available真实body
逐字/逐SHA绑定，未编译或执行。128不是执行coverage，也没有probe或ABI证明。

固定业务12行：原8个params/cache合同预期绿，原4个双START/共同STOP合同继续红。
固定观察116次、21个有序event case groups；runner核全部有序label/case/count及
最终summary一致，并核三环境完整stdout字节相等。观察次数不等于独立测试数量。
不新增Kbuild/Image/module/DT激活/硬件。

真实核心顺序为symmetry→CPU begin→codec begin→machine→codec→CPU→component/DMA
→codec commit→CPU commit。free为两端纯check→CPU锁内复核release→codec release
→mute/link/component真实callback顺序。旧open/PM/clean和singleSTART/C3前缀仍是
生产body，四旧红例先经过新的完整params caller及prepare。

关键有限病例：

- 两方向顺序配置，第二路0共享CCF/PLL/codec I/O；旧CPU CCF错误注入在reuse路径
  实际不再触发，contract保存peer缓存；component末段ENOSPC撤销自己的owner。
- active=2时两次HW_FREE最后清三cache；真正normal close维持原双active0门并平衡
  PM及合成child clock引用。
- late component失败后peer真实prepare+singleSTART；不同rate保留symmetry EINVAL，
  同profile running请求begin EBUSY，均无共享写。
- 首次CPU CCF/codec I/O错误保存首errno，恢复软件request/cache而留下两端FAULT；
  HW_FREE不洗掉故障，不造物理时钟恢复。
- codec已commit、CPU IRQ类fault提交失败，undo包含codec；另用power_transition
  状态切口使CPU commit EBUSY，在它退出后、core codecabort前真实C3 START仍EBUSY，
  随后原链终端abort释放预约。
- duplicate/stale commit无mutation、cookie不回绕、重复/wrong-substream apply拒绝；
  CPU预约时真实C3 START及HW_FREE都在DMA/mute/owner改变前拒绝。
- 真实asoc_simple_init_dai的初始IN与明确OUT固定正sysclk成功且无I/O/cache发布；
  非profile正值拒绝。set_sysclk不认证owner。
- partial/mixed hooks拒绝，checked voice startup/set_fmt/set_sysclk/params拒绝；默认
  全空hook仍走真实legacy cache/free路径。
- 后段codec release callback errno注入留下CPU已清、codec owner未清的真实半状态；
  mute/component/link errors保第一errno并继续prefix，FAULT阻止未来START，不声称
  联合停止已经运行peer。

模型边界：实例与48k/master/TRCM状态是显式synthetic注册，未执行probe。codec mute、
CCF/I2C/PM/DAPM/约束、DMA/PL330是API wrapper；codec first apply调用完整实际PLL/rate/
width生产函数。三个optional component free和machine free是明确errno API fixtures；
late codec release一例替换单个callback为ENXIO，其余release调用实际生产body。CPU提交
故障及PM状态切口是允许的调度/状态注入，不是实际IRQ或系统PM运行。event记录自身
用host mutex避免新并发观察器数据竞争，不能据此证明真实kernel锁或硬件。

原prepare instrumentation匹配失败保存在prepare-attempt-v1，未执行compiler；model-v1
是partial副本。model-v2/v3是未执行的准备阶段，旧extra生产体未写回被readonly SHA
门捕获；precheck-failures-v1明确记录这一失败及首次错误SHA参数。model-v4是更正后的
新版本，旧字节保留。真实执行仍待主控门；系统PM/manualcodec controls另审，原最后
capture shutdown的void错误吞失也未算本轮闭合。
