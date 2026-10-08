# v5声音内存启动包的最终离线接受

2026-10-06。主控已新执行审核CLI，独立只读审查随后接受实际包。
本记录冻结后仅供封存引用；后续板验写入独立结果，不改本文件。

- 最终生产工具：`8857237d9dbbf8022cd0cd0b26c630da4caee3c615a47015de244e7434b2b45c`。
- 实际manifest：`709b70b8c07a69ac71458f32a4925b7c8caef9f8231b501d575d19a27457f531`。
- 实际package receipt：`0215466d4e5d47122a714d572873e0a43e86806eb1625c82237e0a44637787be`。
- 完整40MiB padded：`86d835f6b45ac2f451ca9245fdf9e1e11358445db0bbb5b5fa43e5dac323b4dd`，CRC `ce635dcf`。
- raw 40482816B：`15591de389ba751171ea1949bb0a8193252fa13ad0e95d7a9326bb2114e37e0f`；尾部1460224B全部为零。

独立审查核回41普通候选文件的完整SHA、尺寸及精确集合，26源码快照与当前锁源逐字相等，
五个runtime sidecar同时对应原产物、编译或辅助源及完整SHA，runtime SUM精确五项。
包内kernel为新Image 34755072B/SHA48b9958d…048595；原header地址与metadata、九份preDT资源、
两个原logo及资源布局保持，实际结构与地址审核通过。输入闭合为public14+privateASoC1共15补丁，
89423完整tracked源及新codec的current2020 generated ABI/6360普通SOURCE+17typed source links。
SDK目录link只核有限文本、类型及内部目标目录，不递归内容。

作者真实build和audit均exit0/stderr空；主控另执行新CLI-r2成功，41候选+core/gate共43输入
前后字节与keyset相同。主控与作者receipt同为
`00f71bc17af5a8ff33a716aed739936ea0c0898e740824a08ee54093f465e5ab`，
两份audit报告也逐字相等；这是确定性内容相等，两套独立argv、进程结果及完整streams均保留。
首次root包装器absolute gate遭入口拒绝exit1，完整CLI-r1保留，未创建实际audit目录，不能计作成功审核。

新codec/helper执行前先核固定完整SHA；其窄修三个入口拒绝漂移且执行尝试0，actual codec28/28通过。
旧5/46/64仍是旧73cf源码基线，相关函数逐字未改；不冒称新版完整重跑。
新codec最终seal为90739568…60046e/9b0f774b…6bad2/bbf9cdb0…442b5，
主控实际审计与独立收口接受其离线build/import闭合；current ABI为Image完成后旁证，MODVERSIONS=n，
不能称编译当时签名或运行CRC强制校验。

接受状态为`RAM_ONLY_NOT_FLASH_READY`，用于生成新封存及随后由主控安排有限内存板验。
CPU v12、guard v4及双START拒绝保持；ASoC真实业务21/25通过，四项双START/共同STOP红例仍在。
第五sidecar `pcm-peer-idle`只做双打开、配置与逐个关闭，无PREPARE、START或声音I/O。
guard是状态采集与拒绝门，不单独授予START或reboot。

本接受不证明新内核已经上板、新module已加载或安全卸载、全双工、物理声音、屏幕、
新电池参数、USB恢复或正式flash；电池算法、USB peripheral和early eMMC候选未合入。
native PID1的旧RCU Image检查不构成本轮新Image身份，须另核新notes和实际完整live FDT。
TUN与网络配置不改，未flash/saveenv。

证据：[实际包](build/ram-audio-v5/manifest.json)、[主控新CLI](build/audit-root-cli-v5-r2/result.json)、
[首次拒绝](build/audit-root-cli-v5/result.json)、[最终工具审查](build/tool-preparation-v5-independent-review-v1.json)、
[codec主控接受](../rk3568-audio-runtime-20261005/REVIEW-CODEC-IMAGE-v4-20261006.md)。
