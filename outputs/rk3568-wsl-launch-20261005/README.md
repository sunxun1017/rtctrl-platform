# WSL 新进程启动边界调查（2026-10-05）

只读检查并写本目录证据；未重启 WSL/服务/系统，未结束进程，未改 TUN、路由、防火墙或板卡。

主控实际从 Windows C:\ 工作目录、显式 Linux --cd、--exec /usr/bin/python3 完成包 SHA/header 只读检查：chunk 3452d8，exit 0，0.7153171 秒；独立 OF 源码测试也由主控报告成功。当前构建可以沿用这个已成功入口，每次仍应核对退出码。此成功来自主控证据，本审计没有再次启动复跑。

审计唯一探测也从 C:\ 启动并显式 --cd，但形式为 -- /bin/true。2026-10-05T21:42:32+08:00，30116 毫秒后返回 Wsl/Service/0x8007274c、内层 exit -1。外层 PowerShell 为打印 receipt 正常结束，其 exit 0 不能作 WSL 成功。故“仅改 UNC cwd 就稳定恢复”尚未成立；命令形式、控制台/会话或瞬态差异尚未隔离。

21:41:30 的 UNC /proc 与 Windows 快照：
- WSLService PID 6952、vmcompute PID 9848、HNS PID 4380 均 Running。
- 内核 6.18.33.2-microsoft-standard-WSL2，uptime 190985.20 秒；loadavg 0.35/0.46/0.52。
- Linux MemAvailable 3798868 KiB（约 3.62 GiB）、SwapFree 2096748 KiB；Windows FreePhysicalMemory 2166476 KiB（约 2.07 GiB）。此时没有物理内存耗尽证据，不排除此前压力。
- 21:43:06 发行版 /proc 93 个进程；loadavg 线程数 920，threads-max 62136；file-nr 2567。未接近这些限制。
- 21:43:44 PID 2 init-systemd(Ub…) 两个线程等待 poll/socket packet，PID 7 init 等待 Unix stream，PID 1 systemd 等待 epoll。瞬时 wchan 不能单独证明死锁。
- 现存 bash、VS Code/Codex、SessionLeader/Relay 和多个 /run/WSL/*_interop 端点仍在；未见 sshd/tmux/screen、TCP22 监听或 make/ninja/cc1/gcc。既有 shell 是潜在入口，但本审计没有已证实的可执行控制通道，未接管其 FD/私有 IPC 或读取凭据。
- /proc/net 的 self 相对入口经 UNC 失败，/proc/1/net/unix 与 tcp 可读；第一种路径失败不代表网络栈不可用。
- Windows 相关日志目录查询未取得通道；没有 ETW 或完整调用栈。

0x8007274c 的低位错误为 10060/WSAETIMEDOUT，只说明连接超时，不指出 TUN/外网/路由。微软文档说明 WSLService 经 hvsocket 与 init 交互，创建 SessionLeader/Relay，再启动用户进程。故现有 UNC/进程可用与某次新会话超时可以同时存在。

公开源码把“经默认 shell 执行”和“提供文件名直接 exec”分为不同路径；这说明形式可能影响调用路径，不能证明当前版本故障发生在哪个 transaction。在线 master 与本机安装版本也可能不同。

来源：
- [Winsock 错误码](https://learn.microsoft.com/en-us/windows/win32/winsock/windows-sockets-error-codes-2)
- [微软 WSL 启动过程](https://github.com/microsoft/WSL/blob/master/doc/docs/technical-documentation/boot-process.md)
- [WSLService 职责](https://github.com/microsoft/WSL/blob/master/doc/docs/technical-documentation/wslservice.exe.md)
- [CreateLxProcess 调用形态源码](https://github.com/microsoft/WSL/blob/master/src/windows/service/exe/LxssUserSession.cpp)
- [会话创建事务源码](https://github.com/microsoft/WSL/blob/master/src/windows/service/exe/WslCoreInstance.cpp)

证据：
- probe-c-drive-shell-form.json：唯一探测精确命令、耗时、内层退出码和工具原输出（UTF 解码损坏显式标明）。
- observations.json：状态指标与主控成功的来源，区分独立核实和传入事实。
- init-process-snapshot.json：完整 init、线程等待点和全部进程名称。
- linux-processes-and-endpoints-truncated.txt：21:43:06 原工具输出被工具预算截断，保留标记，不能当作完整 JSON/完整端点列表。

当前只有部分新进程调用失败证据；现存 Linux VM、会话和源码/产物未由此证明损坏。无须为本调查执行系统恢复或改网络。
