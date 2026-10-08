# actual Image-v4 RK817 模块离线接受

2026-10-06。主控接受当前模块进入新RAM包离线整合；不表示已经加载、上板、可安全卸载、
真实声学效果或全双工通过。最终封存仍须准确覆盖普通文件与单列SDK链接并核回。

实际Image：`48b9958d36e2b4821235520360530faac38c9f2dae072c2a2602dbda7e048595`。
实际codec manifest：[build-v2/manifest.json](codec-image-v4-v1/build-v2/manifest.json)，
SHA `32241d1dfe9f2cbf17bae023065d87ee436173ba319a9f40b81ad5c7b1eb8e3c`。
实际模块519072B，SHA `aa594a46d660c929cdae71f81024659cf9f4beca032baf9a193ad6ded3476171`。
最后编译工具SHA `ac8e0fabbb5ee9dee12b136e576560c98e2efe9484727db1227338507a5c1fee`。

作者实际五条命令均exit0、stderr空。冻结C/H实际参与外部obj-m Kbuild，primary .cmd与stdout同一命令。
新模块直接解析为AArch64 ET_REL/42节、32个undefined U符号；这些imports同时匹配实际Module及vmlinux symvers。
模块自身无exports，name/GPLv2/vermagic/alias及init/cleanup符号符合冻结源。
MODVERSIONS=n，实际无__versions；不声明运行时CRC版本校验。

主控 [fresh audit](build/root-codec-image-v4-audit-v1/receipt.json) SHA
`bfbba6268dc8934a3b59585983c554f076cc7252dd5d62566fbc9216a148a518`：
重新核五条实际命令/log和28输入锁，实际源码/header/.cmd，现行SOURCE/ABI与before/after，
并新执行三条只读ELF/nm命令，结果与作者实际模块记录完全相同；没有重复编译或加载模块。
独立reviewer `/root/battery_dt_audit_1006` 另直接解析ELF与全部imports，并核实际命令、完整有限库存接受。

生成ABI为2020普通文件；actual BUILD、私有影子及root文件快照的键、mode、尺寸和SHA匹配。
root复制的是文件；未复制空scripts/kconfig/lxdialog目录，不将空目录差异当文件缺失。
root快照是Image完成后、codec前current actual BUILD旁证，不是编译当时签名全ABI。
SOURCE6360普通+4文件链接+13DTC目录链接与Image完整89423库存的固定选集精确匹配。
四文件链接只接受明确内部普通target；13目录链接只接受固定SDK文本、内部普通目录及祖先，不递归target内容。
未知链接、外逃、错type、missing/extra源输入或锁覆盖仍拒绝；未把它们混称普通文件。

初次actual build-v1因未登记DTC目录链接在inventory阶段拒绝，steps为空，未开始compiler/make；失败保留。
最终30项preflight是有限真实helper/fixture证据，不当模块或板上测试；早期红例只执行旧helper表达式，
不能称旧完整builder运行。原Image、原generated ABI和SOURCE有限选集均保持。

原codec源码/header不改，COMPRESS、电池算法和双START准入保持原配置与限制。
板加载、实际PM/时钟/传输、最终引用归还与正常卸载由下一轮有限实机独立验证。
