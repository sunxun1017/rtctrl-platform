# RV1126B 交互终端实现与验证记录

日期：2026-09-18。

## 实现

新增 apps/companion 独立非实时应用，复用现有人脸 /status.json，提供中文浏览器控制台、
二维表情、按住说话、Opus/ALSA音频、云端WebSocket会话、手动打断、静音、超时、错误恢复、
资源状态、依赖检查与部署打包。默认演示、静音，声卡仅在用户开始说话时打开。
Python事件队列48项、输出队列16包、文本64KiB/音频4KiB/人脸响应64KiB限制。
网络适配器锁定websocket-client 1.8.0，校验版本、TLS、帧长度、分片累计和ping/pong。
打断通过新连接隔离旧回复；capture_epoch隔离前一轮录音回调。
未修改现有人脸算法、模型、人员库或实时控制核心。

原Android C工程后端 ws://118.196.28.154:8060/ 返回24kHz输出；上传保持16kHz。
配置保留此地址，测试令牌通过环境变量传入，不保存真实凭据。
旧地址 ws://118.31.173.231:8260 本次未连通。

## 实际验证

- 完整新增测试：56/56通过（core/config/monitor/HTTP/打包21，audio15，transport20）。
- 使用本地安装的固定网络依赖运行全部测试，无依赖跳过：
  PYTHONPATH=work/companion-python python3 -m unittest discover -s tests -p 'test_companion*.py' -q
- release、asan配置/构建通过，CTest各16/16通过。transport在显式绝对PYTHONPATH下额外复验通过，
  确保没有将缺依赖时的skip当成完整网络验证。Python测试本身不被C++ ASan插桩。
- 真实libopus16k编码→16/24/48k解码往返通过；不使用真实声卡。
- 真实127.0.0.1 WebSocket Upgrade、masked消息、二进制、ping/pong、黑洞连接、
  错误pong与超大帧头拒绝通过。
- 外部后端probe握手通过；完整core静音连接20秒后仍connected=true、muted=true，
  audio_frames_sent=0，正常释放。该WSL进程peak RSS 20584KiB，仅为空闲短测。
- 浏览器手动走通演示连接、启用、按住/松开及回复；PC和800×480截图检查，
  小屏主控按钮均首屏可见。
- python打包生成自包含tar.gz；解包后demo doctor测试通过；含固定Python依赖，
  不含模型、人脸库、录音、环境令牌。
- check-architecture.py通过；git diff --check通过。
- 全仓format-check仍失败于既有C++格式差异，例如products/yidong23/.../topology.hpp、
  tests/test_main.cpp等，本次无C++源码修改，未全仓重排。

## 尚未验证或实现

尚未部署或运行于目标板；WSL缺arecord/aplay，板端须doctor后配置声卡。
真实语音识别/回复内容、实物扬声器、长时间稳定性、与人脸并发资源/温升尚未验收。
离线唤醒词、AEC/全双工自动打断、本地LCD渲染、云端语音到运动意图映射没有实现。
界面展示这些边界；现有控制产品继续独立工作，云端消息不会直接武装执行器。
本次是可测试和打包的交互功能集成，不是整机量产验收完成。

使用步骤见[应用说明](../apps/companion/README.md)，架构见[ADR0009](adr/0009-companion-nonrealtime-service.md)。
