# 本地识别与合成，千帆文字回答

本方案适配实测ALIENTEK RV1126B aarch64 / Python3.11 / glibc2.41。
音频只在板端私有临时目录处理，发送给千帆的是识别文字。应用没有把人脸信息送往千帆。
不是完全离线聊天：没有外网或千帆权限时不能生成回答。

## 选择与资源

- sherpa-onnx 1.13.8官方aarch64 wheels，复用板系统numpy1.25.0。
- Zipformer CTC small中文INT8：2025-07-16版本。
- AISHELL-3 VITS low：原生8000Hz、174音色；默认sid0，配置local_tts_speaker可调整。
- 神经语音有韵律，但8kHz限制声音带宽；转换16kHz播放不会恢复高频。试听不是主观自然度验收。
- 作者模型卡和AISHELL-3源数据标Apache2；保留上游许可。模型及数据许可见下方来源。

实测模型常驻后5.61秒语音识别约1.85–1.88秒；生成3.13–3.38秒声音约1.96–2.15秒。
初次启动两模型合计约34秒，后续不重复加载。两轮交错处理峰值RSS约350.4MiB；
这不是长时间峰值保证。当前模型/绑定目录约142MiB，实物仅1GB内存，非预算2GB版本。
没有使用未经验证的RK3588 NPU模型；当前推理为CPU双线程。

Kokoro INT8测试生成2.93秒声音需约38.55秒，故未选。Matcha Baker速度可用但标非商用，未作为本产品默认。
Melo尚未板测，未假称已验证。Piper Huayan音色卡数据许可Unknown，未作为商用许可明确的候选。

## 安装及配置

模型不进入Git或普通应用tar包。固定官方下载地址、归档/模型SHA256见local-speech-manifest.json。
下载至主机后核对SHA256，解包保留：

    /userdata/rtctrl-speech/python/                 # 解包两个固定aarch64 wheels的模块
    /userdata/rtctrl-speech/sherpa-onnx-zipformer-ctc-small-zh-int8-2025-07-16/
      model.int8.onnx, tokens.txt
    /userdata/rtctrl-speech/vits-icefall-zh-aishell3/
      model.onnx, tokens.txt, lexicon.txt, date.fst, number.fst, phone.fst, new_heteronym.fst

不要把所有候选模型或归档一起放在板端，userdata分区约936MiB，不能按8GB整盘估算可用空间。
Python绑定必须和CPython/架构匹配；本次无需重新安装系统numpy。
复制config/companion/rv1126b-local.json，按实际bundle绝对路径修改两条speech-client命令。
在权限0600、归服务用户的service.env中设置BAIDU_QIANFAN_API_KEY，不写入JSON/浏览器/Git。
同时保留ALSA_CONFIG_PATH专用48kHz双声道plug配置。不要把千帆Key交给旧Android服务器。

使用既有service-control.py启动/重启。主服务管理warm worker生命周期，启动不采集麦克风。
点击“准备语音”会检查worker ready/busy和密钥存在；不等同千帆在线验证。模型未就绪时提示稍后重试。
准备成功后开启麦克风、按住说话，松开完成本地识别。每次最多15秒，当前为单轮短回答，无长期记忆。

## 直连开发板时的云网络

生产设备需要可用的DNS、HTTPS互联网和正确系统时间。不要关闭TLS校验。
本次开发板仅网线直连电脑，未连接Wi-Fi；采用临时SSH反向转发HTTP CONNECT代理：

    # 电脑/WSL运行，固定只允许qianfan.baidubce.com:443，无请求内容日志
    python3 deploy/companion/qianfan-connect-proxy.py
    # 电脑SSH；控制台端口可继续使用已有转发
    ssh -N -R 127.0.0.1:18080:127.0.0.1:18080 root@192.168.50.2

板配置qianfan_proxy_url=http://127.0.0.1:18080。TLS仍由板卡直接校验百度证书和域名。
拥有直连互联网时清空该配置。关闭电脑/隧道后云回答会失败，本次没有设置自动联网或开机隧道。
板原时间2021年不满足当前证书，已按主机时间校正；重启时间同步仍待整机验收。

## 取消与边界

停止会立即停止录音/播放、隔离旧轮结果、终止临时客户端；正在执行的native模型推理不能立即抢占。
worker仍忙时拒绝新一轮准备，待推理完成可重试，不串播旧语音。服务关闭时会回收worker。
每轮临时目录0700、Unixsocket0600，输入输出有界，模型进程不继承云密钥。
返回文字最多120字符，音频最多45秒；暂不支持离线唤醒、AEC、连续全双工打断或多轮会话记忆。

## 上游资料

- https://github.com/k2-fsa/sherpa-onnx
- https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html
- https://huggingface.co/csukuangfj/icefall-tts-aishell3-vits-low-2024-04-06
- https://www.openslr.org/93/
- https://cloud.baidu.com/doc/qianfan-docs/s/qm8qxemze
