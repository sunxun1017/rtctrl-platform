# 音频 RAM 包 v2

v2 仅修复生产输入校验的两项错误。普通文件读取允许合法零字节，仍核对普通文件类型、
路径、大小上限和读取前后 identity；JSON、Image、boot 格式各自拒绝无效空输入。
Image release 固定为本次真实 Linux 构建的 `5.10.160-rt89-g9f9e9d18574d-dirty`。
旧工具、prepared-v1 和全部旧 fixture 结果保留，旧 62/62 只证明当时的机械 fixture 契约。

生产输入固定为 `audio-runtime/build/integration-v1/Image`、完整 manifest 与 review-gate-v2。
构包继续绑定固定 AOSP/parser/libfdt、native PID1 v3 initramfs/rootfs、audio pre-overlay shim；
RSCE 九份 DT、header-v2 单 DT、两份原 logo、地址静态边界和真实 overlay 语义保持。

```sh
python3 -B outputs/rk3568-audio-package-20261005/build-audio-package-v2.py \
    --review-gate outputs/rk3568-audio-runtime-20261005/build/review-gate-v2.json \
    --out outputs/rk3568-audio-package-20261005/build/ram-audio-v2

python3 -B outputs/rk3568-audio-package-20261005/audit-audio-package-v2.py \
    --review-gate outputs/rk3568-audio-runtime-20261005/build/review-gate-v2.json \
    --candidate outputs/rk3568-audio-package-20261005/build/ram-audio-v2 \
    --out outputs/rk3568-audio-package-20261005/build/audit-production-v2
```

```sh
python3 -B outputs/rk3568-audio-package-20261005/test-audio-package-v2.py \
    --out outputs/rk3568-audio-package-20261005/build/tests-v4

python3 -B outputs/rk3568-audio-package-20261005/test-production-inputs-v2.py \
    --out outputs/rk3568-audio-package-20261005/build/production-bug-green-v2
```

机械测试仍为 `FIXTURE_ONLY_NOT_DEPLOYABLE`，旧 RCU Image release 从其冻结构建记录和真实
Image banner 独立确认。生产包为 `RAM_ONLY_NOT_FLASH_READY`；没有板端执行、部署、刷写或
声音结论。实际执行前仍需主控核实 fresh banks/gd/env/relocation/reserved ranges、完整传输
SHA/CRC 与实际地址。native PID1 旧 RCU 文件检查不代替新 Image 身份。module/helper 独立准备。
