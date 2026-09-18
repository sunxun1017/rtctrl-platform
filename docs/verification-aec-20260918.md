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

## 真人双讲补测（2026-09-18）

用户准备确认后完成两轮，要求听到固定Melo播放时重复指定测试短句。
原始、纯AEC、AEC+AES来自同一次采集；录音和识别全文只在内存，不保存、不上传，结束后关闭采集。
第一轮20秒全段：原始最佳距离11/12且完整匹配0，纯AEC距离0且匹配1，AES距离2且匹配0。
这轮含播放尾部单讲窗口，只作探索，不作为严格重叠验收。
第二轮17秒采集，仅评分首个播放write后2–14秒，共192000样点（12秒）。
固定素材本地识别与目标句最小距离10/12，未命中目标；播放约15.79秒，覆盖评分窗口。

| 同步音频路 | 固定12字短句最佳子串编辑距离 | 完整匹配次数 | RMS / peak |
|---|---:|---:|---:|
| 原始麦克风 | 8 | 0 | 332 / 3395 |
| 纯AEC | 0 | 1 | 120 / 1013 |
| AEC+AES | 0 | 2 | 76 / 597 |

无处理错误，capture_discontinuities=0。全段missing_reference_samples含播放前后静音时间，不能当作重叠窗口缺失率。
观察：本次真实重叠说话有完整测试短句穿过AEC且可被本地ASR识别；原始混音未完整命中。
不证明每个音节、每次重复都完整保留，不给出召回率/整段CER，也不能用双讲RMS差当回声ERLE或近端衰减量。
未保存录音，因此未进行回放听感评审；不同距离、音量、长时漂移仍未覆盖。
AES两轮结果不同，仍保持板端纯AEC配置；自动插话检测及打断回答仍未开启。
脚本：scripts/audio-aec/double_talk_probe.py，重跑须先协调用户说话时机。
