# RK3568 软件适配：2026-10-06

本轮声音驱动整合、完整内核与匹配模块构建已完成。外设由用户明天连接，新候选尚未上板；
完整迁移仍需声音、显示、关机、正式启动及恢复验收。TUN保持原样，新电池参数待补，
电量/充电算法未用猜测参数启用。

共享参数事务保留另一方向的请求和缓存。CPU增加启动预约/提交、本向停止与最后共同停止；
健康单向IRQ保留peer。DMA首错经借用的每通道回调传入CPU，保持首次错误，撤销启动许可，
借用仍等真实C3清理。codec关机先走实际声卡文件排空，再清理组件和归还实际时钟引用。
helper的5000ms仅约束文件等待，原断卡、工作排空和释放仍有框架等待边界。

| 实际离线检查 | 结果 | 证据 |
| --- | --- | --- |
| CPU、参数与DMA接缝 | 三环境12/12合同、100/100有序观察，19场景 | [TRCM结果](full-duplex-trcm-candidate-v1/RESULTS-v3.md) |
| DMA故障与排空 | 三环境37/37有序观察 | [DMA结果](full-duplex-dma-fault-candidate-v1/MODEL-REVIEW-v1.md) |
| 控件、PM与终端清理 | 三环境1471/1471观察；同一旧模型211红；有限PM_SLEEP=n通过 | [终端设计](full-duplex-shared-io-candidate-v1/TERMINAL-DESIGN-v5.md) |
| 实际合PM owner门的CPU回归 | 新编译三环境12/12、100/100 | [主控合并回归](root-cpu-pm-merge-v1/runs-merged2/receipt.json) |
| 完整Image/modules | 实际编译退出0；89423 tracked输入前后同 | [完整构建](build/root-audio-integration-v5/full-build-v1/receipt.json) |
| canonical codec | 实际编译退出0；37 imports对两份实际symvers闭合；2020 generated前后同 | [新模块](build/root-audio-integration-v5/canonical-codec-v1/receipt.json) |

Image为34755072B，SHA `e2a5590fbde0a431a1a900c5fc9789d1e607af71a5300010e5431a2927ae3f61`。
最终模块是 `canonical-codec-v1/modules/snd-soc-rk817.ko`，606536B，SHA
`c43e470ccf7219bd344ba9d7315b38599f6b0eafb8a2ea6700eee34de9e13d85`，内部名 `snd_soc_rk817`。
首次完整构建的 `rk817_codec.ko` 为中间模块，交付使用canonical版本。
实际60B kernel notes已提取，供后续运行身份比较；当前没有板上新身份结果。

完整源库存对已接受audio-v4只有11个明确文件差异；私有增量在11份独立基线副本实际
check/apply后逐字等于本次Image输入。配置完整SHA与原板配置相同。
[最终软件绑定](build/root-audio-integration-v5/final-software-v1/receipt.json)和
[补丁实际重放](build/root-audio-integration-v5/final-software-v1/patch-replay-receipt.json)。
直接pcm_params include、新可选DAI hook、关机helper及CPU PM首错门已统一。
独立只读源码审查未发现具体阻塞问题；有限模型的MMIO、锁与部分框架仍是显式API边界。
MODVERSIONS=n，模块imports/vermagic不等于运行CRC或安全卸载证明。

新离线启动候选已构建，使用CPU/codec配对checked-shared-params DT。主控新CLI已完整
回读36普通包文件，39有限输入前后保持，并重新核对真实完整overlay、raw/零padding。
40MiB padded SHA `90e663bc12d33026764bf7b95ac6beede816801c6f7c2fb537615f28059dc0b1`，CRC `4427a536`。
[离线交付入口](offline-next-delivery-v1/README.md)、[主控实际回读](build/root-offline-next-audit-v1/receipt.json)。
新板端双START、声学效果、FIFO重启样本质量、显示与全平台关机需另外实测。最新硬件证据仍是第五轮
有限RAM回归后正常返回原Android，下一次操作前重核。
[已有实机结果](build/board-results-20261006-v5-r3/result.json)。
