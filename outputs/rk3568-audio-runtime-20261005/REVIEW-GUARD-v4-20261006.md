# guard v4 独立只读审查与主控复跑

独立 reviewer `/root/audio_guard_v2_review_1006` 审查结论：未发现新增正确性阻断，可用于本次
native3 PID1/BusyBox shell/单线程 helper、无服务的人工独占域只读 collector；不单独许可 START/解绑/reboot。

v3 实机合法 codec probe 持有一个 MCLK 基础引用，六TX父链各enable/prepare1，CPU自身MCLK已归零。
v3漏算codec基础引用而误拒，首次rc2/raw保持。原驱动与实际模块冻结源字节相同，probe:1330获取，
component remove:1372释放；正常card cleanup确实进入remove，平台driver仍绑定不能推定基础引用仍有。
v4精确要求bound六TX+HCLK各1、card-unbound仅HCLK1、cpu-unbound全0，全部protect0。
CCF没有per-consumer计数；这里是固定源码/module/DT/三OFF/单线程域下的归属推论，不是直接owner测量。

TX六cached parent严格固定到本次mclkout→mclkout_tx→mclk_tx→clk_tx→frac→src→gpll。
实际clk.c current_parent_show只core->parent->name，不调provider/PM/MMIO；不核闲置RX/IOE父链或共享PLL引用数。
独立读核main两次collect真实stage、read/open/close/容量/文本失败拒绝、第二次parent再采集比较，完成后才输出。
源码diff与冻结production-v3-v4.diff逐字节同SHA93e105cc0862089cf967f0a9ac70b02eabceeba5251ae1e0de10bece3b1e3143；
CPU/DMA/STOP/控件/FD/UIO其余生产门槛保持。

独立核685/685SHA、55当前输入与冻结副本，静态AArch64无INTERP/动态节，未新增硬件控制接口。
ELF741560B/SHA8740384398313be87a13245e854d6fc5a17a10f3794bdd83966e933c894c6f69；
manifest15a24232ebaab58a5642aba2d8b92e66216208480fc7decae5ea776f6b8dbb18，
inventoryb45792270eda2881b3d5de06406bd42df0c6b34d80fc46505ffde42a31efc4dd。
两份documentation-addendum SHA另核通过，澄清PLAN旧零引用句和历史证据路径，原685文件字节未变。

作者501+288+13模型各三环境由独立reviewer只读核ELF/SHA/输出；reviewer没有执行或编译模型。
288模型确实调用实际main→第一collect，在新增clock/parent门槛后故意于proc/devices失败，
不覆盖完整collector成功、第二快照运行或板端行为。v3两个实红保存。

主控新鲜实际调用冻结288模型ELF，host/ASan+UBSan/QEMU各288/288，完整stdout/stderr SHA等作者证据，
再核685SHA，`build/guard-v4-root-recheck-v1/result.json`。这是冻结binary复跑，没有重编译、没有板测。
板端新RAM文件的完整v4 SHA及完整collector仍须现场另核。
