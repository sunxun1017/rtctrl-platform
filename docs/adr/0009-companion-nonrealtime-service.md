# ADR 0009：独立语音与表情交互服务

状态：2026-09-18 接受。

RV1126B 的云端语音、HTTP控制台和表情生命周期不能进入1kHz I/O或200Hz控制循环。
新增 apps/companion Python3 叶子应用，使用标准库编排、固定版本websocket-client网络适配、
ctypes libopus编码和ALSA子进程。小块音频有界队列与会话线程独占状态，原有C++实时核心和端口不变。
这扩展了语言边界文档中Python的用途，但只限非实时产品交互层；不将Python用于运动控制。

视觉通过已有本地/status.json读取，冻结帧标记不可用；不另开摄像头、不载入模型、不修改人员库。
云端事件只可更新对话与表情，不能直达执行器。后续语音动作需通过明确的意图白名单、
现有bridge安全门控、反馈和租约，另行定义契约，不能将未经验证的文字转为串口指令。

默认演示且静音。真实录音需要用户操作。协议缺少turn ID，打断时重建连接以隔离旧回复。
网络/设备错误、队列溢出和超时关闭音频；不自动恢复采集。
浏览器是当前显示端，无本地LCD适配；离线唤醒和AEC是独立的待实现能力。
不引入原Android二进制库、Java运行时或Unity依赖。

参考：[应用说明](../../apps/companion/README.md)。

## ConnMan 配网扩展（2026-09-18）

网络管理作为独立非实时NetworkManager接入HTTP服务，不进入Companion语音事件队列。
默认配置wifi_enabled=false；启用后仍仅显式用户操作才调用ConnMan。
GET /api/network读取缓存，POST /api/network提交单后台任务；沿用同源/Host/请求大小约束。
radio enable与scan分离。只允许扫描结果中的wifi服务，不管理有线网卡、热点共享或全局离线模式。
认证通过本机ConnMan交互代理，应用不存凭据；系统ConnMan可以保存成功认证信息。
应用退出回收CLI子进程，但不撤销ConnMan守护进程已接受的网络操作，也不主动断开已有连接。
此版支持可见开放/个人密码网络，隐藏SSID和企业认证留待独立适配。
