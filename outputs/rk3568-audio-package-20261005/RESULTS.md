# 当前验证结果

新音频 RAM 包的机械实现与 policy 验证已准备。生产 `integration-v1` Image/manifest 尚未到位，
因此没有生成或封存生产音频包，也没有板端执行。

已运行的红绿证据：

- `build/address-red-v1/result.json`：旧固定 Image 内存大小与缺失 gd 工作区两个用例失败。
- `build/tests-v1/result.json`：首轮 fixture 42/42；真实 AOSP 两函数构包，真实 libfdt 套原 DTBO。
- `build/manifest-red-v1/result.json`：自洽重算 inventory 后，四个虚假 manifest 声明被旧检查接受，按预期失败。
  当时 core 字节保存在 `build/tests-v1/fixture-candidate/source-inputs/outputs/rk3568-audio-package-20261005/audio-package.py`。
- `build/tests-v2/result.json`：补完整 manifest 语义与 Image metadata 绑定后 59/59。
- `build/base-bank-red-v1/result.json`：text_offset 为 4 MiB 时 aligned base 0 不在 usable bank，旧检查按预期暴露缺口。
  当时 core 字节保存在 `build/tests-v2/fixture-candidate/source-inputs/outputs/rk3568-audio-package-20261005/audio-package.py`。
- `build/tests-v3/result.json`：补 aligned base bank、正整数组件边界后 62/62，进程 exit 0。

负例先独立重算 boot header ID / RSCE payload SHA1，再证明通用 boot parser 接受格式，
最后严格内容 policy 拒绝 kernel、ramdisk、applied DT、logo、RSCE DT phandle、names/order、offset、cmdline 或 header metadata 变异。
另核自洽重算封存 inventory 不能让错误的部署、刷写、旧 RCU 身份、rootfs path/hash 或 source map 声明通过。
所有测试包都明确 `FIXTURE_ONLY_NOT_DEPLOYABLE`，生产 CLI 拒绝 `--fixture` 和 `--image` 覆盖。

生产命令与边界见 README。新 Image 的 SHA、大小、CRC、header 有效内存范围、
完整 C3 review gate、实际源/patch、compiler/config/symbol tables 都要重新绑定后生成包。
旧 native PID1 的 RCU 文件约束不等于新内核身份；actual 新内核还需主控现场 RAM CRC、地址与完整包输入核对。

没有修改旧 kernel、旧 boot-package 封存、公共 patch 或其他 agent 目录；未操作设备、UART、ADB、TUN 或分区。
正式 early DT、恢复入口、声音 START/STOP 实测与物理声音输出仍不属于本轮通过结论。
