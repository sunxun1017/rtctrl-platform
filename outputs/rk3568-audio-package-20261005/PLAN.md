# 音频 RAM bootm 包

仅在本目录实现 builder、独立 policy auditor 和故障边界测试。
原 boot parser、AOSP mkbootimg 与真实 libfdt 固定 SHA 后复用；不修改旧封存目录。

1. 先保存动态 Image 内存范围与 gd FDT 地址测试的失败结果。
2. 实现严格输入来源核对、动态布局、原 RSCE names/logos 与九份 audio pre-overlay shim。
3. 用明确标记的旧 Image fixture 检查机械契约，重算 boot ID/resource SHA 后检查内容 policy 拒绝。
4. 新 integration-v1 Image/manifest 和独立 C3 gate 到位后才生成生产包；保存独立审计和完整封存清单。

范围：RAM_ONLY_NOT_FLASH_READY；不包含 module/helper，不操作设备、ADB、UART、TUN、分区、环境保存或发布。
暂定 actual RAM 目的地 kernel 4 MiB、FDT 0xa100000..0xa140000、initrd 64 MiB、package 0x20000000..0x22800000。
这些是静态候选，板端 fresh banks、gd、env、relocation 与 reserved ranges 必须由主控重新核实。
