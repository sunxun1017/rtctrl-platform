# 下一阶段：RK809板载音频

本文件保留2026-10-04的基线与计划。2026-10-05已完成源码Linux声卡/控件接口测试，
最新结果见[RK809接口实测](../rk3568-audio-20261005/README.md)；实际播放/采集仍未验收。

触摸身份拒绝后，继续做了Android只读音频基线和锁定5.10源码分析。
[audio-baseline-result.json](audio-baseline-result.json) 单列本次元数据证据；没有播放、录音、改path control或GPIO。
最新实测电量25%；CAP返回时的30%保留为上一阶段历史值。

## 原Android的新快照

| 项目 | 本次实际输出 |
| --- | --- |
| 声卡0 | Bothlent UAC Dongle，USB Audio capture 1 |
| 声卡1 | rockchip,rk809-codec，machine `/sys/devices/platform/rk809-sound` |
| 板载PCM | fe410000.i2s ↔ rk817-hifi，playback 1、capture 1 |
| codec driver | `/sys/bus/platform/drivers/rk817-codec` |
| ALSA controls | 两个ENUM；Playback Path=HP_NO_MIC、Capture MIC Path=MIC OFF |
| 功放GPIO软件占用 | GPIO4_C4/pin148为GPIO owned，MUX unclaimed；没有测实际电平 |

卡号只适用于本次快照，不能写死“card0就是板载音频”。以卡名、ID、sysfs父设备匹配，再核对PCM。
注册PCM/读到controls不等于已经能发声或采到有效音频。
原Android已有标准tinymix/tinyplay/tinycap。本次仅执行 `tinymix -D 1` 的列表读取。

可信私有记录为 android-audio-baseline-v2.json 和 android-audio-details-v3.json。
首个复合shell命令未正确整体引用，参数没有按预期送入sh -c，采集无效且不参与任何结论。
修正后逐项保存返回码；v2的探查同时试了两个DT节点名，其中一个不存在，整项exit1，
所以节点存在/status/DAI结论使用v3对确切 `/rk809-sound` 路径的成功读取。

## 原板设备树与源码Linux的差异

原Android运行树的CPU DAI是I2S1 `fe410000`，codec是I²C0/PMIC@20下的codec child，
compatible包含rk809-codec及rk817-codec fallback。speaker control GPIO4_C4 ACTIVE_LOW，
hp-volume30、spk-volume12、mic-in-differential；原卡为simple-audio-card，使用I²S格式。
这些是原配置事实，GPIO极性与参数值尚未做实际声音、功放或电气验收。
原引脚为MCLK GPIO1_A2、BCLK A3、LRCK A5、输入B3、输出A7；`mclk-fs=256`、初始MCLK12.288MHz。
板级power.dtsi已保留LDO4 `vccio_acodec=3.1V` always-on及vccio1连接，这是配置事实而非电压测量。
codec没有额外regulator consumer；原DT未描述独立功放芯片/供电或hp-ctl-gpios，不猜测新增电源。

本轮已测UART基线DTB没有codec child或RK809声卡，I2S1仍disabled。
现Image配置只有 `CONFIG_SND_SOC_RK817=n` 是此基本链的缺项；
ASoC、simple-card、I2S_TDM、MFD_RK808、REGMAP_I2C以及DMA基础已有y。
不需要先写新machine驱动或移植完整Android音频HAL才能尝试基础PCM。

锁定源码存在codec实现及构建入口：

- `sound/soc/codecs/Kconfig:1114`：RK817依赖MFD_RK808并选择REGMAP_I2C。
- `sound/soc/codecs/Makefile:501`：snd-soc-rk817.o。
- `drivers/mfd/rk808.c:247`、`:1230`：RK809映射到rk817 cells，codec child有匹配compatible。
- `sound/soc/codecs/rk817_codec.c`：Playback Path、Capture MIC Path及Resume Path controls。
- `sound/soc/rockchip/rockchip_i2s_tdm.c`：当前I2S/DMA时钟与数据通路。

同现Image ABI单独构建codec模块存在源码路径，相关ASoC/regmap API已导出；
本轮没有构建该模块、检查最终导入闭包或证明可加载。也可评估新Image，须单独绑定新配置/产物并板测。
基础Linux用户态可按标准ALSA接口及开源工具推进；厂家HAL `.so` 的全部路由、效果或业务策略仍未复现，
不能从PCM注册和两个controls推断全部厂商行为都已替换。

## 一个会阻止声卡注册的路由差异

原Android的simple-audio-card,routing引用MICBIAS1/IN1P/HPOL/HPOR，
锁定5.10 `rk817_codec.c` 没有这些DAPM widgets。源码对缺失source/sink返回-ENODEV：
`sound/soc/soc-dapm.c:3000`、`:3005`，`sound/soc/soc-core.c:1922`～`:1925`
会把DT routes错误送到probe失败路径。因此原routing不能机械照搬到这份驱动。

最小候选先依据实际的path controls整理声卡，不带这组不匹配的routing/widgets。
若后续要完善DAPM，就单独实现与寄存器、功放、时钟一致的电源语义；不要增加空widget掩盖缺项。
这里是源码路径结论，尚未生成或上板验证新音频DTB。

## Probe也会改变硬件

没有播放不代表没有配置写。后续候选须把以下实际路径列入实验边界：

- `rk817_codec.c:1376`、`:1383`：请求hp/spk GPIO为GPIOD_OUT_LOW；ACTIVE_LOW时逻辑0对应物理高，
  对本板功放的电气效果仍需确认。
- `rk817_codec.c:1313`、`:1314`：component probe启用MCLK并写codec reset/寄存器序列。
- `rockchip_i2s_tdm.c:2802`、`:2884`：probe启HCLK并写DMA/CKR，`:2257` 的common_soc_init写GRF。
- `drivers/base/dd.c:534`：driver probe之前就会选择pinctrl。

PCM open的 `sound/soc/generic/simple-card-utils.c:194` startup还会启用时钟。
这份codec还吞掉部分GPIO、时钟与寄存器写入失败；后续真实probe诊断前须审查并修正错误传播，
不能让模块加载或声卡链接掩盖硬件配置失败。音质、麦克风实际通路及厂家HAL中的AEC/降噪/唤醒等算法另行验收。

应先构建匹配模块和独立音频DTB，核验GPIO/时钟/供电与副作用，再在RAM系统验收声卡身份和controls；
播放、采集、路径切换、退出与正常电源生命周期分别验证。
本次仅完成Android元数据和源码依赖分析，音频Linux功能仍未验收。
