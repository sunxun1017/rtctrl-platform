# 统一设备入口

应用可作为8080局域网入口，人脸预览内部运行于127.0.0.1:8081；不改变模型与摄像头配置。
部署配置在原本地语音配置上加入：

```json
{"bind":"0.0.0.0","port":8080,"lan_access":true,"standalone_voice":true,
 "vision_url":"http://127.0.0.1:8081","face_url":"http://127.0.0.1:8081/status.json"}
```

`standalone_voice`不依赖浏览器租约，切换或关闭网页继续听取。新进程默认静音；网络/模型错误停止采音，
不会因网页重新打开而自动开麦。各页面顶部可立即静音。没有唤醒词，不支持自动打断播放。
本模式不安装系统自启动，也不改变云端网络代理；如现有语音使用电脑CONNECT代理，仍需该网络通路。

## 手机访问

同网段打开设备8080端口，首次输入8位配对码。可信本机/SSH回环入口的设置页可显示配对码，
也可由设备管理员读取配置的pairing_file（默认/run/rtctrl-companion/pairing-code，0600）。
二维码只包含设备HTTP地址，不包含配对码、Wi-Fi口令或会话凭据。HTTP适用于可信局域网，不发布到公网。
远端配对后使用HttpOnly/SameSite=Strict cookie，24小时过期；服务重启重新配对。最多16会话，5次/分钟限制。
不要在本入口前添加一个把任意远端请求转换成可信回环的反向代理；回环访问默认信任本机用户。
本次二维码用于访问已有网络；未实现自动AP热点配网，也不会开启热点、自动扫描或替用户切换网络。

## 人脸迁移与回退

迁移前记录运行程序/proc/PID/cmdline、cwd和必要LD_LIBRARY_PATH，保存仅管理员可读的JSON。
必须沿用正在运行的二进制和全部参数，仅替换--bind、--port，不使用启动脚本的默认值覆盖性能参数。
禁止携带--enroll-name（避免迁移时修改图库）。先停止旧进程，再从同cwd启动新端口，更新video.pid。
此次板端保留before-portal-launch.json（原参数）、portal-launch.json（内部端口）和原应用打包备份。
回退：先停止统一服务，恢复应用/配置备份，停止内部人脸进程，以原JSON中的args/cwd/env重启并更新video.pid。
需要重新启动内部预览时，在其部署目录执行（确认video.pid没有仍在运行的进程）：

```python
import json, subprocess
from pathlib import Path
c = json.loads(Path("portal-launch.json").read_text())
p = subprocess.Popen(c["args"], cwd=c["cwd"], env=c["env"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
Path("video.pid").write_text(str(p.pid) + "\n")
```

## 日志与资源

应用固定结构事件最多256条，包含启动、状态、静音、连续对话、错误、回声隔离，不存录音、完整文本或凭据。
内核仅提取音频/NPU/内存/网络/温度固定摘要，不提供任意日志文件读取；0.8秒/128KiB有界、5秒缓存。
支持来源/级别筛选及JSON导出，应用日志重启清空；完整底层排错仍需本地SSH工具。
摄像头默认不开网页流；选中首页摄像头才连接，切页/隐藏断开。最多两条转发流，不占满全部HTTP连接。
CPU、内存、NPU和最高thermal_zone温度集中在状态页。

参考：[Home Assistant诊断](https://www.home-assistant.io/integrations/diagnostics)、
[Home Assistant系统日志](https://www.home-assistant.io/integrations/system_log/)、
[ESPHome本地Web](https://esphome.io/components/web_server/)。借鉴页面分层与诊断边界，不在1GB板上部署完整HA。
二维码使用qrcode8.2（BSD，vendor dist-info保留LICENSE），SVG后端无需Pillow或外部CDN。
