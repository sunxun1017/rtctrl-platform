# OV13850 / ISP35 适配工作记录

## 已确认基线

用户板端：ISP35，AIQ v6.0x31.0；OV13850 revision 0xb2；CSI1；
2112×1568 NV12，60 帧序号连续，约 30.05 FPS，正常 STREAMOFF。
画面偏暗偏绿。RKAIQ 缺少
`ov13850_ATK-MCOV13850_default.json/.bin`，初始化失败后段错误。
厂家反馈没有配套适配。上述结果不等同于画质、长稳或自动曝光已验收。

## 本机 SDK 中的实际材料

SDK 根目录：`/home/sx/projects/atk_dlrv1126b_linux6.1_sdk`。

- 旧传感器参数：`external/camera_engine_rkaiq/rkaiq/iqfiles/isp21/ov13850_ZC-OV13850R2A-V1_Largan-50064B31.json`
- ISP35 结构参考：`external/camera_engine_rkaiq/rkaiq/iqfiles/isp35/common/imx335_ATKMC_V1_3.json`
- 官方开发指南：`docs/cn/RV1126B/RKIPC/Rockchip_Development_Guide_ISP35_CN.pdf`
- 官方调参指南：`docs/cn/RV1126B/RKIPC/Rockchip_Tuning_Guide_ISP35_CN.pdf`
- 色彩指南：`docs/cn/RV1126B/RKIPC/Rockchip_Color_Optimization_Guide_ISP39_ISP33_ISP35_CN.pdf`

IMX335 文件只用于识别目标结构，不是可直接部署的 OV13850 参数。
运行只读差异检查：

```sh
python3 scripts/audit-ov13850-iq.py \
  --sdk-root /home/sx/projects/atk_dlrv1126b_linux6.1_sdk
```

## 第一个适配关口：传感器曝光描述

旧 IQ 的模拟增益映射为 1～15.5 倍，对应寄存器 16～248；与当前
驱动增益范围吻合。数字增益范围为 1～1。旧 IQ 的更新延迟为两帧，
这只是参考值，当前模组仍需实测。

不能整体复制 `sensor_calib`：ISP35 参考新增了 `CISTimeLinePerReg`、
`iso_list` 等字段，HDR 的 `CISTimeRegMin` 从标量变成对象。
本次只适配线性模式，不启用 HDR、DCG 或翻转。

### 必须核实的时序差异

现有驱动/板端报告：宽 2112，hblank 2688，行长 4800；高 1568，
vblank 96，帧长 1664；pixel_rate 120000000。
由这些值计算 `120000000 / (4800 * 1664) ≈ 15.02 FPS`，
但采集实测约 30.05 FPS。这是时序描述不一致的线索，不是修改某个值的充分证据。
应核对传感器 HTS 寄存器单位、内部时钟和 RKAIQ 曝光换算实现后，
再决定是否调整 hblank/pixel_rate 或曝光映射，不能为了凑数直接乘除二。

## 实施顺序与验收

1. 阅读 ISP35 开发/调参指南，核对 AIQ 传感器时间、增益换算和帧延迟。
2. 板端固定场景、固定光源，对曝光与增益做受控阶梯采样，确定亮度响应与生效延迟。
   手动测试前确认没有 AIQ 进程并记录原值；测试后恢复原值。
3. 根据 ISP35 schema 建立实验 IQ，移植经核实的 OV13850 传感器参数。
   每个模块注明参数来源、保留/关闭原因和待标定项；不将其他镜头 LSC/CCM 当成标定结果。
4. 使用匹配 ISP35 的解析/运行库验证，再板端验证 AIQ 初始化和线性 AE。
5. 用均匀光照白纸/灰卡验证 AWB，再进行黑电平、色彩、gamma、LSC 和噪声标定。
6. 通过重复启停、不同光照和长稳测试后，才将配置纳入默认镜像。

## 当前交付边界

目前交付的是源码/IQ 审计入口和适配记录，尚未生成或部署可用 IQ。
阶段 2～6 必须有板端数据；文件解析成功本身不能证明曝光映射或画质正确。
公共内核子模块、板端 DTB、SDK 原始 IQ 均保持原样。


## 2026-09-05 后续实测

已实现实验IQ生成并完成板端解析/AE/采集测试；完整deinit发现MEMC线程挂起，AWB借用参数出现蓝偏，尚未完成标定。详见 [实验记录](ov13850-isp35-experiment-20260905.md)。本次新增/etc IQ已撤回，控件恢复。
