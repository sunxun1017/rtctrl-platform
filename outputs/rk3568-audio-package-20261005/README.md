# 音频 RAM bootm 包

builder 只接受固定 `audio-runtime/build/integration-v1/Image` 与 manifest，以及完成的独立 C3 gate。
它核对实际构建来源、完整 Image SHA/CRC/header、未改动的 native PID1 v3 initramfs/rootfs、
audio pre-overlay shim 和固定 AOSP/parser/libfdt。

RSCE 保留原 11 个名字及顺序、两份 logo 字节，九份 DT 都为同一 pre-overlay audio shim；header-v2 单 DT 同字节。
applied DT 仅供真实 libfdt 五属性转换审计。header 元数据地址保留，但不会当成 actual RAM 目的地。
新 Image 的有效内存范围、text_offset/2 MiB alignment 与 flags 每次从真实 header 读取。
静态检查暂定 kernel 4 MiB、FDT gd 0xa100000 的 256 KiB 工作区、initrd 64 MiB、package 512 MiB。
historical banks 只作为静态约束；主控必须重查本轮 gd、banks、env、relocation、reserved ranges 和传输 CRC。

生产命令（gate 路径由主控提供；目标目录必须全新）：

```sh
python3 -B outputs/rk3568-audio-package-20261005/build-audio-package.py \
    --review-gate outputs/rk3568-audio-runtime-20261005/build/REPLACE_WITH_REVIEW_GATE.json \
    --out outputs/rk3568-audio-package-20261005/build/ram-audio-v1

python3 -B outputs/rk3568-audio-package-20261005/audit-audio-package.py \
    --review-gate outputs/rk3568-audio-runtime-20261005/build/REPLACE_WITH_REVIEW_GATE.json \
    --candidate outputs/rk3568-audio-package-20261005/build/ram-audio-v1 \
    --out outputs/rk3568-audio-package-20261005/build/audit-production-v1
```

机械契约测试使用旧 RCU Image，全部标记 `FIXTURE_ONLY_NOT_DEPLOYABLE`，生产 CLI 没有 fixture 选项：

```sh
python3 -B outputs/rk3568-audio-package-20261005/test-audio-package.py \
    --out outputs/rk3568-audio-package-20261005/build/tests-v1
```

测试通过不证明新 Image 已构建、已部署或声音已传输。新内核身份需完整包的 Image SHA 与本轮 RAM CRC/实际地址核对；
native PID1 旧 RCU Image 文件检查只证明其自身旧输入约束，不能充当新 Image 身份。
module/helper 独立暂存，不进入本包。本目录没有硬件操作、刷写、保存环境或 TUN 修改。
所有产物都是 RAM_ONLY_NOT_FLASH_READY；正式 early DT 与 USB 恢复入口尚需另外验证。
