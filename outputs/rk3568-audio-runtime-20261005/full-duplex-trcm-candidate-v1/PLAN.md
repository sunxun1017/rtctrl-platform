# 有限实现与验证

1. 锁定 params source-v4 CPU、model-v6 manifest 和 runner 身份，保留父目录字节。
2. 在新 CPU 副本增加 ticket/transport/per-dir quiet 状态、component admission、DAI
   commit、owner STOP、last/joint STOP、prepare/IRQ/PM/close guards。
3. 同一 caller harness 保存旧实现实际红例，再替换逐字提取 CPU body 作候选验证；
   params 八合同继续回归，不使用手写成功链代替 PCM/C3。
4. host、ASan+UBSan、AArch64 QEMU 保存每 argv/exit/stream/binarySHA，核固定有序
   labels、case 分组、计数与完整三 stdout 相等；任何失败留新 attempt，不覆原结果。
5. 给主控源码 patch/manifest、实际红绿和有限边界；真实 Kbuild/整体整合由主控负责。
