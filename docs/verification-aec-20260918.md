# RV1126B 软件参考 AEC 验证（2026-09-18）

## 实现与范围

普通 Rockchip VQE CPU AEC，16kHz、256点/16ms，单麦+软件播放参考；不使用AINR/NPU。
原播放PCM不变，只有参考副本持续重采样到16kHz。时间戳有界队列最多5秒；采集使用连续样点时钟，显著断流重锚定。Python输出固定增加256样点（16ms）缓存延迟。
AEC原生错误停止音频，不静默回退原始麦克风。显式关闭麦克风、断开、连续对话租约到期仍停止物理采集。
回答期间保持本地AEC滤波，但不将这些帧送入ASR或云端。自动插话检测/取消回答尚未实现，能力字段仍为false。

默认配置关闭，板端实验配置启用纯AEC（AES=false）。需绝对aec_library路径、live/local/RKNN streaming ASR。
私有目录同时放librtctrl_aec.so、普通librkaudio_vqe.so、librkaudio_common.so与SDK LICENSE；不修改系统库。
构建、ABI和许可见 [原生说明](../scripts/audio-aec/README.md)。此SDK rkaudio_preprocess_short 返回字节数512，非样点数；反汇编及尾部canary已核实。

## 实际板端结果

合成探针12秒信号（非麦克风）：

| 模式 | synthetic ERLE | 双讲近端347Hz音调幅度比 |
|---|---:|---:|
| 纯AEC | 13.553dB | 0.8557 |
| AEC+AES | 23.766dB | 0.7479 |

用户明确授权后，进行一次10秒本地固定Melo语音播放+板载麦克风安静测试。
只在内存处理，未保存或上传麦克风PCM。两种模式处理同一次采集。
窗口3.026–7.536秒，72000采集样点，无参考缺失、无采集断流，无处理错误。

| 模式 | 麦克风能量 | 输出能量 | 回声主导窗口能量降低 |
|---|---:|---:|---:|
| 纯AEC | 41286620160 | 322671360 | 21.07dB |
| AEC+AES | 41286620160 | 125914560 | 25.16dB |

总时长10.161s，Python进程CPU0.946s（同时跑两套AEC），峰值RSS19452KiB。
CPU数不含arecord/aplay，RSS包含Python和两个算法实例，不是单套AEC独立成本。
终止arecord时Interrupted system call为正常结束；应用错误列表为空。
实测窗口能量降低不等于真人双讲可懂度；尚未验收真人同时说话、远场、不同音量/摆位或长期时钟漂移。
因此采用较保守纯AEC，不宣称已实现免按键打断。

## 重测与回退

脚本 scripts/audio-aec/acoustic_probe.py 必须显式传 --run-local-acoustic-test、固定--wav及--library，
并设置板端ALSA_CONFIG_PATH。脚本会开启麦克风和播放音频，运行前须取得当前用户授权并提示保持安静。
只打印聚合指标，不写音频。每次新录音需符合用户授权范围。
回退：板端配置aec_enabled=false后重启companion；备份board-test-before-aec.json及rtctrl-companion-before-aec.tar.gz。
不需要替换固件/系统RKNN库。

## 回归与交付

release/asan各17个companion测试组通过；AEC11项、AudioIO27项及core静音回归通过。原生host stub通过，ARM交叉编译和真实库合成探针通过。板端部署后准备语音验证单独进行，保持麦克风关闭。
