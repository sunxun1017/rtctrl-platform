# 音频 RAM 包 v3

新版本将 CPU v11 的完整 Image、针对该 Image ABI 新建的 codec，以及冻结 guard v4、PCM transfer
和 inspector 一起核验。新工具和输出均另立，旧 v1/v2 全部保留。

boot-padded.img 仍为 40 MiB Android header-v2 RAM 试验包；native3 initramfs/rootfs、audio pre-overlay
DT、header 元数据、RSCE 九份 DT 和原 logo 保持旧冻结字节。codec/helper/guard 不注入旧 rootfs，
而是另存 `runtime/` 四个普通文件和完整 SHA 清单；builder 与独立 auditor 检查完全相同的真实来源。

CPU v11 只修正合法 shutdown 的请求缓存清理与下一轮参数配置准入，guard v4 的 CPU sysfs 协议
保持。guard v4 自身原 v10 输入、来源声明和封存不改，本包分别绑定新 CPU 源码与原 guard。
guard 是限定域的只读收集器，本包的离线完成不授予 START，也不证明新 Image 已实机运行。

```sh
python3 -B outputs/rk3568-audio-package-20261005/run-production-v3.py
```

该入口使用 `audio-runtime/build/review-gate-v3.json` 与 `integration-v2`，新包为
`build/ram-audio-v3`、新审计为 `build/audit-production-v3`。review gate、13 项实际补丁、CPU
source/manifest/inventory、完整 Image/header/config/symvers/compiler、codec source/ABI/vermagic/
imports、guard v4 的完整 frozen inventory 和四个 sidecar 内容都须通过，不能以旧包替代。

封存目录保存工具及输入清单副本，并以完整 SHA 引用实际包、sidecar 和执行旁证；这些大文件
保留在各自新输出目录，封存脚本逐引用重新读取核验，不声称已把整包复制进封存目录。
沿用的 v2 auditor 尚不逐项重验 manifest 的两份执行要求文字列表；主控须保留本 README 和
原 builder 生成的要求，不能凭离线 audit 推导 START、地址有效或实机验证完成。

结果为 RAM_ONLY_NOT_FLASH_READY。真实执行前，主控仍须重新确认当前 banks/gd/env、保留和
重定位区域、实际传输地址、全包 SHA/CRC、新 Image 身份、整棵 live DT、pre/post guard、诊断
和正常返回。没有物理声音或正式 flash 结论；旧 native3 RCU 文件检查不代替新 Image 身份。
