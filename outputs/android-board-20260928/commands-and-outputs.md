# 串口命令与原始输出索引

COM6，1500000 baud，8N1，无流控，DTR/RTS=false。主机时间见 [session.log](session.log)。

每条命令保存 `.command.sh`；原始字节保存 `.raw.bin`；UTF-8可读副本保存 `.output.txt`。
输出保留终端回显、退格符、异步内核日志和失败信息，不能把夹杂的日志当作命令返回。

07/13为采集脚本分块上传，17为经过逐块SHA-256验证的数据回传。脚本内容见collector-used.sh和collect-extra.sh。

|步骤|命令|原始输出|
|---|---|---|
|01-identity|[命令](01-identity.command.sh)|[输出](01-identity.output.txt) / [字节](01-identity.raw.bin)|
|02-access|[命令](02-access.command.sh)|[输出](02-access.output.txt) / [字节](02-access.raw.bin)|
|03-root-tools|[命令](03-root-tools.command.sh)|[输出](03-root-tools.output.txt) / [字节](03-root-tools.raw.bin)|
|04-fdt|[命令](04-fdt.command.sh)|[输出](04-fdt.output.txt) / [字节](04-fdt.raw.bin)|
|05-fdt-retry|[命令](05-fdt-retry.command.sh)|[输出](05-fdt-retry.output.txt) / [字节](05-fdt-retry.raw.bin)|
|06-fdt-gzip|[命令](06-fdt-gzip.command.sh)|[输出](06-fdt-gzip.output.txt) / [字节](06-fdt-gzip.raw.bin)|
|07-upload-0|[命令](07-upload-0.command.sh)|[输出](07-upload-0.output.txt) / [字节](07-upload-0.raw.bin)|
|07-upload-10500|[命令](07-upload-10500.command.sh)|[输出](07-upload-10500.output.txt) / [字节](07-upload-10500.raw.bin)|
|07-upload-1500|[命令](07-upload-1500.command.sh)|[输出](07-upload-1500.output.txt) / [字节](07-upload-1500.raw.bin)|
|07-upload-3000|[命令](07-upload-3000.command.sh)|[输出](07-upload-3000.output.txt) / [字节](07-upload-3000.raw.bin)|
|07-upload-4500|[命令](07-upload-4500.command.sh)|[输出](07-upload-4500.output.txt) / [字节](07-upload-4500.raw.bin)|
|07-upload-6000|[命令](07-upload-6000.command.sh)|[输出](07-upload-6000.output.txt) / [字节](07-upload-6000.raw.bin)|
|07-upload-7500|[命令](07-upload-7500.command.sh)|[输出](07-upload-7500.output.txt) / [字节](07-upload-7500.raw.bin)|
|07-upload-9000|[命令](07-upload-9000.command.sh)|[输出](07-upload-9000.output.txt) / [字节](07-upload-9000.raw.bin)|
|07-upload-init|[命令](07-upload-init.command.sh)|[输出](07-upload-init.output.txt) / [字节](07-upload-init.raw.bin)|
|08-collect|[命令](08-collect.command.sh)|[输出](08-collect.output.txt) / [字节](08-collect.raw.bin)|
|09-collection-status|[命令](09-collection-status.command.sh)|[输出](09-collection-status.output.txt) / [字节](09-collection-status.raw.bin)|
|10-collection-wait|[命令](10-collection-wait.command.sh)|[输出](10-collection-wait.output.txt) / [字节](10-collection-wait.raw.bin)|
|11-stop-slow-collector|[命令](11-stop-slow-collector.command.sh)|[输出](11-stop-slow-collector.output.txt) / [字节](11-stop-slow-collector.raw.bin)|
|12-partial-status|[命令](12-partial-status.command.sh)|[输出](12-partial-status.output.txt) / [字节](12-partial-status.raw.bin)|
|13-extra-upload-0|[命令](13-extra-upload-0.command.sh)|[输出](13-extra-upload-0.output.txt) / [字节](13-extra-upload-0.raw.bin)|
|13-extra-upload-1500|[命令](13-extra-upload-1500.command.sh)|[输出](13-extra-upload-1500.output.txt) / [字节](13-extra-upload-1500.raw.bin)|
|14-extra-capture|[命令](14-extra-capture.command.sh)|[输出](14-extra-capture.output.txt) / [字节](14-extra-capture.raw.bin)|
|15-live-tree-archive|[命令](15-live-tree-archive.command.sh)|[输出](15-live-tree-archive.output.txt) / [字节](15-live-tree-archive.raw.bin)|
|16-bundle|[命令](16-bundle.command.sh)|[输出](16-bundle.output.txt) / [字节](16-bundle.raw.bin)|
|17-chunk-000-try1|[命令](17-chunk-000-try1.command.sh)|[输出](17-chunk-000-try1.output.txt) / [字节](17-chunk-000-try1.raw.bin)|
|17-chunk-001-try1|[命令](17-chunk-001-try1.command.sh)|[输出](17-chunk-001-try1.output.txt) / [字节](17-chunk-001-try1.raw.bin)|
|17-chunk-001-try2|[命令](17-chunk-001-try2.command.sh)|[输出](17-chunk-001-try2.output.txt) / [字节](17-chunk-001-try2.raw.bin)|
|17-chunk-002-try1|[命令](17-chunk-002-try1.command.sh)|[输出](17-chunk-002-try1.output.txt) / [字节](17-chunk-002-try1.raw.bin)|
|17-chunk-003-try1|[命令](17-chunk-003-try1.command.sh)|[输出](17-chunk-003-try1.output.txt) / [字节](17-chunk-003-try1.raw.bin)|
|17-chunk-003-try2|[命令](17-chunk-003-try2.command.sh)|[输出](17-chunk-003-try2.output.txt) / [字节](17-chunk-003-try2.raw.bin)|
|17-chunk-003-try3|[命令](17-chunk-003-try3.command.sh)|[输出](17-chunk-003-try3.output.txt) / [字节](17-chunk-003-try3.raw.bin)|
|17-chunk-004-try1|[命令](17-chunk-004-try1.command.sh)|[输出](17-chunk-004-try1.output.txt) / [字节](17-chunk-004-try1.raw.bin)|
|17-chunk-005-try1|[命令](17-chunk-005-try1.command.sh)|[输出](17-chunk-005-try1.output.txt) / [字节](17-chunk-005-try1.raw.bin)|
|17-chunk-006-try1|[命令](17-chunk-006-try1.command.sh)|[输出](17-chunk-006-try1.output.txt) / [字节](17-chunk-006-try1.raw.bin)|
|17-chunk-007-try1|[命令](17-chunk-007-try1.command.sh)|[输出](17-chunk-007-try1.output.txt) / [字节](17-chunk-007-try1.raw.bin)|
|17-chunk-008-try1|[命令](17-chunk-008-try1.command.sh)|[输出](17-chunk-008-try1.output.txt) / [字节](17-chunk-008-try1.raw.bin)|
|17-chunk-009-try1|[命令](17-chunk-009-try1.command.sh)|[输出](17-chunk-009-try1.output.txt) / [字节](17-chunk-009-try1.raw.bin)|
|17-chunk-010-try1|[命令](17-chunk-010-try1.command.sh)|[输出](17-chunk-010-try1.output.txt) / [字节](17-chunk-010-try1.raw.bin)|
|17-chunk-011-try1|[命令](17-chunk-011-try1.command.sh)|[输出](17-chunk-011-try1.output.txt) / [字节](17-chunk-011-try1.raw.bin)|
|17-chunk-012-try1|[命令](17-chunk-012-try1.command.sh)|[输出](17-chunk-012-try1.output.txt) / [字节](17-chunk-012-try1.raw.bin)|
|17-chunk-013-try1|[命令](17-chunk-013-try1.command.sh)|[输出](17-chunk-013-try1.output.txt) / [字节](17-chunk-013-try1.raw.bin)|
|17-chunk-014-try1|[命令](17-chunk-014-try1.command.sh)|[输出](17-chunk-014-try1.output.txt) / [字节](17-chunk-014-try1.raw.bin)|
|17-chunk-015-try1|[命令](17-chunk-015-try1.command.sh)|[输出](17-chunk-015-try1.output.txt) / [字节](17-chunk-015-try1.raw.bin)|
|17-chunk-016-try1|[命令](17-chunk-016-try1.command.sh)|[输出](17-chunk-016-try1.output.txt) / [字节](17-chunk-016-try1.raw.bin)|
|17-chunk-017-try1|[命令](17-chunk-017-try1.command.sh)|[输出](17-chunk-017-try1.output.txt) / [字节](17-chunk-017-try1.raw.bin)|
|17-chunk-018-try1|[命令](17-chunk-018-try1.command.sh)|[输出](17-chunk-018-try1.output.txt) / [字节](17-chunk-018-try1.raw.bin)|
|17-chunk-019-try1|[命令](17-chunk-019-try1.command.sh)|[输出](17-chunk-019-try1.output.txt) / [字节](17-chunk-019-try1.raw.bin)|
|17-chunk-020-try1|[命令](17-chunk-020-try1.command.sh)|[输出](17-chunk-020-try1.output.txt) / [字节](17-chunk-020-try1.raw.bin)|
|17-chunk-021-try1|[命令](17-chunk-021-try1.command.sh)|[输出](17-chunk-021-try1.output.txt) / [字节](17-chunk-021-try1.raw.bin)|
|17-chunk-022-try1|[命令](17-chunk-022-try1.command.sh)|[输出](17-chunk-022-try1.output.txt) / [字节](17-chunk-022-try1.raw.bin)|
|17-chunk-022-try2|[命令](17-chunk-022-try2.command.sh)|[输出](17-chunk-022-try2.output.txt) / [字节](17-chunk-022-try2.raw.bin)|
|17-chunk-022-try3|[命令](17-chunk-022-try3.command.sh)|[输出](17-chunk-022-try3.output.txt) / [字节](17-chunk-022-try3.raw.bin)|
|17-chunk-023-try1|[命令](17-chunk-023-try1.command.sh)|[输出](17-chunk-023-try1.output.txt) / [字节](17-chunk-023-try1.raw.bin)|
|17-chunk-024-try1|[命令](17-chunk-024-try1.command.sh)|[输出](17-chunk-024-try1.output.txt) / [字节](17-chunk-024-try1.raw.bin)|
|17-chunk-025-try1|[命令](17-chunk-025-try1.command.sh)|[输出](17-chunk-025-try1.output.txt) / [字节](17-chunk-025-try1.raw.bin)|
|17-chunk-026-try1|[命令](17-chunk-026-try1.command.sh)|[输出](17-chunk-026-try1.output.txt) / [字节](17-chunk-026-try1.raw.bin)|
|17-chunk-027-try1|[命令](17-chunk-027-try1.command.sh)|[输出](17-chunk-027-try1.output.txt) / [字节](17-chunk-027-try1.raw.bin)|
|17-chunk-028-try1|[命令](17-chunk-028-try1.command.sh)|[输出](17-chunk-028-try1.output.txt) / [字节](17-chunk-028-try1.raw.bin)|
|17-chunk-029-try1|[命令](17-chunk-029-try1.command.sh)|[输出](17-chunk-029-try1.output.txt) / [字节](17-chunk-029-try1.raw.bin)|
|17-chunk-030-try1|[命令](17-chunk-030-try1.command.sh)|[输出](17-chunk-030-try1.output.txt) / [字节](17-chunk-030-try1.raw.bin)|
|17-chunk-031-try1|[命令](17-chunk-031-try1.command.sh)|[输出](17-chunk-031-try1.output.txt) / [字节](17-chunk-031-try1.raw.bin)|
|17-chunk-032-try1|[命令](17-chunk-032-try1.command.sh)|[输出](17-chunk-032-try1.output.txt) / [字节](17-chunk-032-try1.raw.bin)|
|17-chunk-033-try1|[命令](17-chunk-033-try1.command.sh)|[输出](17-chunk-033-try1.output.txt) / [字节](17-chunk-033-try1.raw.bin)|
|17-chunk-034-try1|[命令](17-chunk-034-try1.command.sh)|[输出](17-chunk-034-try1.output.txt) / [字节](17-chunk-034-try1.raw.bin)|
|17-chunk-034-try2|[命令](17-chunk-034-try2.command.sh)|[输出](17-chunk-034-try2.output.txt) / [字节](17-chunk-034-try2.raw.bin)|
|17-chunk-034-try3|[命令](17-chunk-034-try3.command.sh)|[输出](17-chunk-034-try3.output.txt) / [字节](17-chunk-034-try3.raw.bin)|
|17-chunk-035-try1|[命令](17-chunk-035-try1.command.sh)|[输出](17-chunk-035-try1.output.txt) / [字节](17-chunk-035-try1.raw.bin)|
|17-chunk-036-try1|[命令](17-chunk-036-try1.command.sh)|[输出](17-chunk-036-try1.output.txt) / [字节](17-chunk-036-try1.raw.bin)|
|17-chunk-037-try1|[命令](17-chunk-037-try1.command.sh)|[输出](17-chunk-037-try1.output.txt) / [字节](17-chunk-037-try1.raw.bin)|
|17-chunk-038-try1|[命令](17-chunk-038-try1.command.sh)|[输出](17-chunk-038-try1.output.txt) / [字节](17-chunk-038-try1.raw.bin)|
|17-chunk-039-try1|[命令](17-chunk-039-try1.command.sh)|[输出](17-chunk-039-try1.output.txt) / [字节](17-chunk-039-try1.raw.bin)|
|17-chunk-040-try1|[命令](17-chunk-040-try1.command.sh)|[输出](17-chunk-040-try1.output.txt) / [字节](17-chunk-040-try1.raw.bin)|
|17-chunk-040-try2|[命令](17-chunk-040-try2.command.sh)|[输出](17-chunk-040-try2.output.txt) / [字节](17-chunk-040-try2.raw.bin)|
|17-chunk-041-try1|[命令](17-chunk-041-try1.command.sh)|[输出](17-chunk-041-try1.output.txt) / [字节](17-chunk-041-try1.raw.bin)|
|17-chunk-042-try1|[命令](17-chunk-042-try1.command.sh)|[输出](17-chunk-042-try1.output.txt) / [字节](17-chunk-042-try1.raw.bin)|
|17-chunk-043-try1|[命令](17-chunk-043-try1.command.sh)|[输出](17-chunk-043-try1.output.txt) / [字节](17-chunk-043-try1.raw.bin)|
|17-chunk-044-try1|[命令](17-chunk-044-try1.command.sh)|[输出](17-chunk-044-try1.output.txt) / [字节](17-chunk-044-try1.raw.bin)|
|18-usb-audio-details|[命令](18-usb-audio-details.command.sh)|[输出](18-usb-audio-details.output.txt) / [字节](18-usb-audio-details.raw.bin)|

## 前置探测

- `00-probe-command.sh` / `00-probe.txt`：按历史2500000配置发送，收到乱码，不能判定命令成功。
- `passive-*.bin`与`passive-long-*.bin`：不同波特率下仅接收；1500000长窗口得到可读内核日志。
- 首次探测的本机保存路径因PowerShell Provider前缀失败，未保留那一窗口；随后重跑并保存为00。
- 直接调用UNC上的ps1曾被主机签名策略拒绝；之后在当前PowerShell内读取所写脚本为scriptblock执行，没有更改全局执行策略。
- `su -c id`在该Android上不支持；使用`su 0 id`成功。
- 04、05的未压缩FDT回传损坏；06 gzip压缩传输后解码，通过原始FDT的板端SHA-256。
- 08逐文件采集未完成；11发送Ctrl-C终止，12记录其1960行进度。保留的snapshot/devicetree是不完整副本。
- 15完整运行设备树tar成功，最终完整副本为live-tree/；主机校验见verification.json。

## 主机处理

DTC来自Ubuntu包`device-tree-compiler`，只下载解包在host-tools/，未全局安装。
下载输出见host-tools/download.log；校验与解包逻辑见verify-artifacts.py；DTC命令及输出见host-verification.log。
最初反编译命令：`host-tools/extracted/usr/bin/dtc -I dtb -O dts -o android-running.dts fdt.dtb 2> dtc-warnings.txt`。
gzip校验：`gzip -t fdt.dtb.gz`；解压：`gzip -dc fdt.dtb.gz > fdt.dtb`；哈希：`sha256sum fdt.dtb`。
