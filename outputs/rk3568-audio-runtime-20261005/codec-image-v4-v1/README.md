# 新 integration-v4 Image 的冻结 RK817 codec 构建准备

本目录用于新 integration-v4 Image 的私有外部RK817模块。主控已通知完整Image成功，
最终工具通过只读预审后，build-v2实际编译及离线接口核对完成；产物审查与封存独立进行。
新builder参考旧v3流程，但不导入旧audit或复用其ABI结论。

实际Image SHA `48b9958d36e2b4821235520360530faac38c9f2dae072c2a2602dbda7e048595`，
Image manifest SHA `8df525843cac41fd0e272351bc41d0e573c25570cfed7e60f1990b9fe97aa33a`。
实际module 519072 bytes，SHA `aa594a46d660c929cdae71f81024659cf9f4beca032baf9a193ad6ded3476171`，
build-v2/manifest.json SHA `32241d1dfe9f2cbf17bae023065d87ee436173ba319a9f40b81ad5c7b1eb8e3c`。
compiler-version、真实make、readelf和两次nm共5命令均exit0、stderr为空；
ELF64 LE AArch64 ET_REL，32个实际undefined imports在实际Module.symvers与vmlinux.symvers中同项闭合。
vermagic严格等实际release/profile，包含实际init_module/cleanup_module符号，未发现__versions。
不从这些离线结果推导加载、卸载、实机或双方向START安全。

冻结源 SHA `72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64`，
header SHA `370f2c9451d0e871b627c7b9a9b90cc24e486c49cebe29c068d5b692f7802449`；
原SDK codec SHA `c510119eefe8fd82c1e100fde014d9ce30420aa2df9b1b74cf5e83b9e18ea6f3`。
`prepare_inputs.py` 只快照已冻结codec、原SDK及v3参考工具，逐普通文件和所有祖先核查；
不读取正在构建的v4 generated ABI，也不执行make。

实际运行要求root给出的两个精确SHA，核对新Image本身、输出副本、实际BUILD的Image、
config、Module/vmlinux symvers、完整source inventory绑定及generated release。
完整generated include/arch include/scripts和Makefile复制到本目录私有ABI影子；
实际外部obj-m只在影子运行，原v4 SOURCE/BUILD和完成Image作为只读输入。
原源码include/arch include/scripts有限全量inventory包含6360普通文件、目录祖先、4个明确SDK内文件链接，
以及13个scripts/dtc/include-prefixes目录链接。文件链接固定路径/文本/内部普通target/SHA；
目录链接固定路径/文本/内部普通target目录及祖先，原SDK与actual SOURCE都核对，
不递归链接目标、不为目录内容制造SHA。两类分开计数，不放宽其它symlink。

SOURCE固定三子树和六文件选集与Image的89423项tracked inventory要求精确成员键集相等，
再逐mode、bytes、SHA（link文本SHA）核对，缺失及多余项都拒绝。
prepared-inputs-v1.json硬锁SHA `6ef8c70f6b47acbf497b9b6eedbf0dde3a9ee6876e869832b24761238d0b6d0a`
及六项schema，不能覆盖mandatory codec/header锁；实际参与make的C/header另核。

root在Image完成后、codec前形成2020项current actual BUILD快照，
receipt `2f25e37f2a30732ebd378c2874f1d7a3c3d37f19b7fe1d6486646bac61998e58`、
inventory `bf3766426c2eb869442dc2703f6321eaad6143ebeaf63dad279c72eaf0f3e2a3`。
actual BUILD、root snapshot及私有shadow的完整键/bytes/Linux权限mode/SHA与此表核等。
这是Image完成后的实际生成输入旁证，不能称Image编译当时签名的全部generated ABI。

旧17/21/23/24/25项helper结果及对应builder版本保留；当前preflight-v6实际30项通过，
含真实旧before/after guard表达式对拥有目录中物理header漂移的1业务红→新identity拒绝，
以及missing/extra/conflicting-lock拒绝。旧红只验证该生产guard表达式，不冒充旧全builder运行。
增加真实完整SOURCE正例和typed DTC目录链接正例、wrong-kind/text/missing/unknown拒绝。
当前builder `ac8e0fabbb5ee9dee12b136e576560c98e2efe9484727db1227338507a5c1fee`
获得独立只读最终工具预审接受，随后才执行build-v2。30项检查是有限helper观察，
没有把synthetic形状接受称为实际Image/模块结果。v6 result SHA
`3ba81b6c96c742637e0650ab61da468c194b9af49b960aa30fda39753cbf4f5b`。
旧build-v1在输入阶段拒绝DTC目录链接，steps=[]，没有调用compiler或make；
其builder快照、failure.traceback/failure.json、外层实际argv/exit/stdout/stderr原样保留。
后续实际模块使用独立build-v2，不覆盖或重命名失败attempt。

每个真实子命令保留argv/exit/stdout/stderr；失败attempt保留，不写成功manifest。
实际编译前后及audit后重复有限输入清单，实际primary `.cmd` 要引用本次冻结源码且含-DMODULE。
module must be actual ELF64 LE AArch64 ET_REL；记录真实readelf/nm和ELF sections/modinfo，
vermagic精确比较actual release/profile。真实undefined imports必须同时由实际Module.symvers和
vmlinux.symvers同项提供、provider=vmlinux且无namespace；自身Module.symvers必须空。
核对冻结codec必须有的imports与PMIC regmap借用禁止项，记录模块init/exit符号。

实际config MODVERSIONS=n时要求实际module没有__versions，明确不声称CRC运行时校验；
精确header/源码/两个symvers绑定不能替代板加载、引用生命周期或unload安全。
codec source/header不改，板config仍RK817=n，由外部模块选择；不启COMPRESS或双START。
未测试control/PCM/DAPM/PLL/PM/remove/voice共享/硬件；不操作板、串口、ADB、TUN或网络服务。

`preflight.py` 对有限manifest/symvers/ordinary ancestry/错误ELF helper执行synthetic拒绝检查，
并只读比对真实SOURCE选集与root2020 ABI；不能将synthetic形状通过写成Image完成或模块兼容通过。
实际module已获独立只读产物接受及主控离线整合接受；原core seal/Image/public源/SDK不写。

主控独立fresh只读audit复核作者5命令，并重新运行3个ELF/nm工具，32imports及完整输入仍等；
root receipt SHA `bfbba6268dc8934a3b59585983c554f076cc7252dd5d62566fbc9216a148a518`，
tool SHA `d762c989e050fb06cc7b5f9d66257961cde638b415513ed9716611214c2c4456`。
本目录review-evidence-v1包含其12个普通文件副本及逐bytes/mode/SHA输入清单，
input-manifest SHA `89ea591bde2900c03a5e1f1788907ad867f00aa1a486bf7839d645535dcfa723`。
root未重新编译模块；副本不冒充新的Image构建或板验证。
主控最终接受文档SHA `797e51e4f62190dc9c389d4a1624293c705b8c2bf78b5166fe0c01ddd55354db`，
review-evidence-v2普通副本及input-manifest SHA
`4fe691a86e62c9901c702f4f0e6145c88dd4025d93df01f958ee410aacbc4be4` 与原件核回。
离线module允许下一轮包整合，board/START/unload/全双工许可仍全部为false。

封存工具仅核回已完成的有限范围，不运行make或硬件操作；所有owned普通文件及祖先、
完整generated shadow、对象/.cmd/module、旧失败和历史工具都纳入逐SHA/bytes/mode表与SUM。
外部输入普通文件单列；actual SOURCE的17链接及production helper读取的原SDK13目录链接
共30typed links单列，链接文本与目标类型/内部位置/普通祖先核对，目录内容不遍历。
外部original SOURCE全选集继续对Image完整inventory锁成员，actual/root/shadow generated2020继续等。
