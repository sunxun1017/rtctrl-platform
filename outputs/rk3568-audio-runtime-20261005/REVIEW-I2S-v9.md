# I2S v9 独立审查与阻断

主控已读完整报告、实际独立模型结果，并将130个文件逐项完整SHA核对后保存：
[完整报告](build/i2s-v9-independent-review/REVIEW.md)、
[拷贝校验](build/i2s-v9-independent-review/copy-verification.json)。
inventory SHA `0d081a6917de127bffc2468e1812df860933e9a716683f59881791642bfa7d2c`。
冻结源 `5a04c4697c4db7f90f961767b1a454388e99fc170047571af5b4d818950cd357`。

v8旧UAF注册顺序和checked controls撤除已在真实路径修复；六套原回归三环境各658/658
独立复跑，完整C使用实际Kbuild参数重新编译通过、4220个ABI文件核对通过。
仍有两项真实错误路径阻断，并发现现有PM模型不完整：

- 完整probe→inactive set_fmt→runtime_resume，STOP写入/读回未确认时直接释放MCLK。
  真实模型输出stop_proven0/XFER3/TX RX引用0；运行exit1为行为断言，ASan/UBSan stderr空。
- 早期probe失败和正常remove→devres都多调用一次pm_runtime_disable，真实计数深度留2。
  相同device经真实reinit后再次probe只降至1，绑定-EACCES、退出无法完成；准确计数模型已复现。
- 真PM core锁存callback errno，resume -EIO后再次get是-EINVAL。旧shim只清注入便重试成功，
  不能作真实正常退出证据。模型必须保留这一语义；受控内部STOP不能假设普通get可恢复。

以上均为实际生产函数与明确API/MMIO模型的离线回归，没有板端触发证据。
下一版按持有clock与PM enable所有权配对修正，旧v9/sealed-v2保持。当前不放行START/完整Image/部署。
