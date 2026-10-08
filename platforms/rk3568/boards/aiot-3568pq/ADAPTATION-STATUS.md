# AIoT-3568PQ Android→Linux 当前验收状态

2026-10-06。目标是可维护的 Linux 板级支持和产品接口。当前已通过源码 Linux 的内存启动、
原生用户态返回和顺序单方向声音传输；完整迁移尚未完成。板子在第五轮声音试验后正常返回原 Android。
运行状态、地址、PID和电量只对对应记录时刻有效，下一次操作前重新确认。

## 已有证据与尚未闭合的部分

| 项目 | 当前证据 | 后续验收 |
| --- | --- | --- |
| 源码内核与声音镜像 | 固定 SDK `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`、14公共+1私有补丁实际重放，完整 Image/modules 构建；RK817模块匹配实际 ABI | 正式启动介质和产品服务 |
| 内存启动包 | 完整40MiB文件上传校验、U-Boot全包CRC、一次RAM bootm、实际kernel notes及完整live FDT回核 | CLI前资源DT/early DM、正式分区启动和恢复 |
| I2S/RK809声音 | 自然初始休眠；48k/S16_LE/2ch顺序播放和采集各24576帧，单START，停止/释放/关闭和前后严格检查通过 | 同时双方向、并发客户端、真实声学效果 |
| 声音资源清理 | 正常声卡解绑、codec卸载、CPU解绑后16项时钟引用全零，DMA通道/工作/隔离缓冲为零 | 双方向共同故障和长期运行 |
| 原生PID1返回 | 软件codec/PTY自检及回收、回RAM、旧根/cache卸载、loop detach、独立guard、普通restart回Android | 产品服务退出、物理poweroff与电源轨 |
| 原系统保留 | 当轮七项保护对象和三项native缓存完整SHA与试验前相同 | 不扩大为全盘或所有网络状态的证明 |
| USB | 音频RAM轮既有USB host/UAC枚举；USB2 peripheral候选已离线审查 | DMO引脚身份、VBUS/ID、电脑枚举和裸机恢复；未激活候选 |
| 显示 | 软件接口已有独立记录；用户已拔下屏幕排线 | 实际显示、背光、退出和电气状态 |
| 新电池与充电 | 电量计生命周期与缺失参数拒绝候选离线验证；电池标签参数待用户后补 | 新电池标定、充电器/Type-C实装和策略；算法继续禁用 |
| MCU与执行器 | 原缓存ABI、串口软件协议和接口边界已有记录；本轮仅板子，电机未连接 | 真实身份/反馈/安全停止、watchdog、ACK及物理关机；不猜命令 |

## 第五轮最新声音证据

新Image-v4和匹配codec实际RAM启动后，四种双open、配置、逐个关闭顺序各34操作完整通过；
两单向各24576帧/98304B完整传输，14严格资源检查通过。正常卸载后DMA allocated/quarantine
与16音频时钟计数均为零；native codec/PTY自检、正常RAM返回与普通重启回Android通过。
七保护对象和三native输入全SHA保持。采集路由OFF，因此不构成实际收音验收。

[第五轮正式汇总](../../../../outputs/rk3568-audio-runtime-20261005/build/board-results-20261006-v5-r3/result.json)
SHA8d504646…99550a；[实际汇总入口](../../../../outputs/rk3568-audio-runtime-20261005/build/collector-cli-v5-attempt3/receipt.json)
和[主控完整回读](../../../../outputs/rk3568-audio-runtime-20261005/build/root-board-results-v5-r3-review.json)。
两个失败入口均保留，没有重跑板程序。全双工及完整迁移仍未完成。

## 第四轮声音实际结果

Image SHA `965acb13577032b2f0a44f13508b6a97947398e223a6eab6d04f86d9c7d381fe`，
codec SHA `d62205da6efae956ceb8b78059dc90fa405dfef82f94bdb7b8f003a6330ecbf7`。
完整包SHA `eb2da84a0ab0eb7fc615f641ab2880bb067a72ec5b972a109e7237472243afe6`，CRC `50c2904d`。
这些是文件身份；板上kernel notes与此构建一致，不是完整运行内存Image的SHA测量。

首次codec观察已自行suspended；首次严格guard通过，没有执行PM on→auto诊断。
两方向均单次START、DROP/HW_FREE/close成功，旧sysclk清零-22诊断消失。
采集49152样本全零，Playback/MIC/Resume始终OFF，不能据此证明麦克风或喇叭声音。
播放raw有一处合并残行，只有94条WRITE完整可辨，不能称逐笔I/O trace完整。
STOP属性报告驱动此前MMIO读取的缓存结果，guard自身不再次测量硬件STOP。

正常清理和返回后，fresh ADB确认原Android `root / 4.19.232 / 11 / boot_completed=1`。
当轮七项保护对象和三项native缓存完整SHA相同。没有刷写启动分区或saveenv，TUN设置保持原样。
109项是证据断言，不能写成109项独立硬件测试。

证据入口：

- [第四轮有限实机汇总](../../../../outputs/rk3568-audio-runtime-20261005/build/board-results-20261006-v4/result.json)
- [第四轮完整构建清单](../../../../outputs/rk3568-audio-runtime-20261005/build/integration-v3/manifest.json)
- [全量live FDT审查](../../../../outputs/rk3568-audio-runtime-20261005/build/root-live-fdt-v4-audit/independent-review.json)
- [当日过程与失败记录](../../../../outputs/rk3568-audio-runtime-20261005/SESSION-20261006.md)
- [全双工实际调用链与剩余契约](../../../../outputs/rk3568-audio-runtime-20261005/build/full-duplex-review-v1/README.md)
- [正式启动与early DM边界](../../../../outputs/rk3568-boot-package-20261005/FORMAL-EARLY-REVIEW.md)
- [MCU接口](MCU-INTERFACE.md)和[电源生命周期](POWER-LIFECYCLE.md)

全双工先闭合双open的共享请求保留，再处理共享参数、第二START/单方向STOP、共同故障和退出。
每段保留单方向回归；完整软件和新镜像绑定通过后，另立有限实机矩阵。
现有单方向guard或镜像构建成功不自动许可双START，也不能代替外接设备与正式恢复验收。

## 公共补丁与下一段声音候选

已实机验证的关闭请求清零和自然初始休眠修正，已分别整理为公共0013/0014。
14补丁完整源重放与actual Image-v3一致；新鲜built-in对象的运行节、反汇编和去调试后整体字节相同，
封存证据经主控及独立只读审查通过。这一段没有生成新Image或新增硬件验收。
见[公共整合](../../../../outputs/rk3568-audio-runtime-20261005/public-integration-v1/README.md)和
[独立审查](../../../../outputs/rk3568-audio-runtime-20261005/public-integration-v1/independent-review-v1.json)。

下一候选处理ASoC打开失败与另一方向关闭交错时的资源归还，以及同DAI peer存在时的共享sysclk请求。
真实函数模型已复现原代码失败路径；四源候选已通过三环境和主控fresh回归及独立封存审查。
无START的双open/逐个close程序完成离线回归后，已在新Image-v4/codec组合实机完成四种有限顺序，各34操作完整核回。
第二START、共享TRCM停止和双DMA共同故障契约仍未完成。

候选将25项业务红例中的21项修复；110项是边界观察、包含74个唯一标签。
四源实际Kbuild通过，compressed分支仅手动预处理源码检查，板配置仍禁用。
4357普通文件/4358SUM与8488外部普通输入、4个单列SDK内部链接已由主控和独立审查核回。
新独立audio-v4完整Image/modules已实际编译通过，public14+privateASoC1共15补丁，完整89423源库存核回。
新Image SHA48b9958d…048595、CRC6908ddc6；新codec及v5启动包离线绑定通过，已一次RAM启动完成本轮有限板验。
新60B notes/a2008d93…b6436和GNU51e22386…0de907已板核；完整live FDT168064B/ddb3fe03…692d15与前轮全语义同。板子现已正常返回原Android。
见[核心离线接受](../../../../outputs/rk3568-audio-runtime-20261005/REVIEW-ASOC-OPEN-ROLLBACK-20261006.md)和
[检查器离线接受](../../../../outputs/rk3568-audio-runtime-20261005/REVIEW-PCM-PEER-IDLE-20261006.md)。

[新完整构建](../../../../outputs/rk3568-audio-runtime-20261005/build/integration-v4/manifest.json)和
[无START有限板验计划](../../../../outputs/rk3568-audio-runtime-20261005/BOARD-PLAN-PEER-IDLE-20261006.md)已保存。

新codec模块519072B/SHAaa594a46…476171，32imports同时对实际Module/vmlinux symvers核等，
current generated2020普通和SOURCE6360普通+17单列SDK links完整选集匹配，主控fresh及独立直接ELF审查接受。
MODVERSIONS=n、不宣称运行CRC证明；本轮已正常加载和卸载，card/CPU组件正常解绑，14严格guard通过。
见[新module离线接受](../../../../outputs/rk3568-audio-runtime-20261005/REVIEW-CODEC-IMAGE-v4-20261006.md)。

本轮各单向24576frames/98304B有限传输通过，OFFcapture全零只证明当前关闭路由的数据读取。最终DMA allocated/quarantine与16音频clock计数都归零；两个native自检、RAM return63及ordinary reboot通过。新Android返回七保护+三native全SHA保持，TUN设置未改。实机原始捕获均以板stat/fullSHA绑定并完整导出；正式collector-r3已实际exit0/stderr空，190有限输入前后及主控回读一致，63完整原始导出与结果匹配。首次1024-only格式拒绝、第二次状态唯一性误拒及其他外围失败均保留。
见[详细本轮记录](../../../../outputs/rk3568-audio-runtime-20261005/SESSION-20261006.md)和[新Android返回](../../../../outputs/rk3568-audio-runtime-20261005/build/audio-return-v5-r2.json)。

最新声音软件已离线整合：共享参数八合同及CPU四项双START/共同STOP合同均在有限真实caller模型中通过；最终CPU/DMA接缝三环境12/12合同、100/100观察，DMA37/37，controls/terminal1471/1471。主控合入PM首sticky优先与owner门后新编译回归通过，并统一新头与直接pcm_params依赖。完整audio-v5 Image/modules实际退出0，89423 tracked源前后同、对已接受audio-v4只有11文件差异；新canonical codec实际编译与37imports闭合，2020 generated前后同。Image SHA e2a5590f…ae3f61、模块c43e470c…e13d85均尚未板验。

新40MiB离线RAM启动候选已构建并经主控新CLI完整回读，SHA90e663bc…59dc0b1/CRC4427a536；新DT只增加CPU/codec两项配对bool。当前物理验收仍以上述v5单方向实机为准；新双向录放、FIFO样本、实际声音/显示、全平台关机、供电参数及正式恢复/启动需另外验证。codec文件排空helper的5000ms不代表整个shutdown时间上限，MODVERSIONS=n不宣称运行CRC。用户明天接外设，今天未新增板操作或改变TUN。见[软件当前记录](../../../../outputs/rk3568-audio-runtime-20261005/SOFTWARE-PROGRESS-20261006.md)和[离线交付](../../../../outputs/rk3568-audio-runtime-20261005/offline-next-delivery-v1/README.md)，完整迁移未完成。
