# ATK-DLRV1126B + OV13850：ISP35 / RKAIQ 适配复现手册

日期：2026-09-05。本文是当前实测配置的操作入口；历史探索见 [适配记录](ov13850-isp35-adaptation.md)、[实验记录](ov13850-isp35-experiment-20260905.md) 和 [黑电平改进记录](ov13850-blc-refinement-20260905.md)。

## 1. 复现范围与结果层级

适用于本次 ATK-DLRV1126B、ATK-MCOV13850 V1.3 实物，2112×1568、线性非 HDR、约30FPS。镜头型号未确认。已验证 IQ 找到并初始化、AE/AWB 收敛、连续采集和重复启停；这不等于完成产品标定。

最终采用：ISP35 结构 + OV13850 传感器描述 + 全像素自动白平衡实验模式 + 本模组实测黑电平 + AE 目标×1.5。未采用试验过的额外 gamma 对比度或 CSM 饱和度增强。未把其他传感器的 CCM、LSC、噪声参数当成标定结果。

普通场景颜色比例会影响全像素AWB；灯具高光可能饱和，暗部仍有噪声。未验收多光源、全温度、全曝光范围、镜头阴影及色卡准确性。既往长时间系统卡死不是本 IQ 修复范围。

## 2. 环境与不可跳过的检查

以下主机命令均在 **WSL Ubuntu/Linux** 执行。SDK 的 repo/Git 元数据依赖 Linux，不要用 Windows Git 直接操作 UNC 形式的 SDK。Windows PC 的预览和归档不是必需的生成输入。

```sh
cd /home/sx/projects/rtctrl-platform
# 先阅读当前工作区适用的 AGENTS.md；保留已有修改。
git status --short
export SDK=/home/sx/projects/atk_dlrv1126b_linux6.1_sdk
export RUN="$PWD/work/ov13850-reproduce-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN"
git -C "$SDK/external/camera_engine_rkaiq" rev-parse HEAD
```

实测版本：SDK RKAIQ `91dee445c13770279e3ee90cd82bd278c5306f85`；板端 Linux 6.1.141 / ARM64，ISP HW35，AIQ v6.0x31.0（2025-08-01），OV13850 ID 0xd850 / revision0xb2。SDK 源码版本和板上二进制版本分别记录，不能假定完全相同。

输入文件：

- `$SDK/external/camera_engine_rkaiq/rkaiq/iqfiles/isp21/ov13850_ZC-OV13850R2A-V1_Largan-50064B31.json`：旧传感器描述参考。
- `$SDK/external/camera_engine_rkaiq/rkaiq/iqfiles/isp35/common/imx335_ATKMC_V1_3.json`：ISP35结构和部分未标定基础处理参考。
- [暗场测量表](ov13850-dark-measurements-20260905.json)：当前模组、曝光1498、五档模拟增益下实测值。

生成器记录输入文件hash与SDK提交。历史输入清单见 [source manifest](ov13850-source-manifest-20260905.json)。供应商IQ只在本地生成，不提交到Git。

板端连接地址可能随链路变化；用当前可达地址，不把历史169.254地址当成固定配置。连接后先核对：

```sh
uname -a
tr '\000' '\n' < /proc/device-tree/model
for n in /sys/class/video4linux/v4l-subdev*/name; do printf '%s: ' "$n"; cat "$n"; done
for m in /dev/media*; do echo "$m"; media-ctl -d "$m" -p; done
ps | grep -E 'rkaiq|ov13850-aiq|v4l2'
```

已验证链路：I2C4/0x10 → D-PHY3 → MIPI2 → rkcif-mipi-lvds2 → rkisp-vir1。历史sensor=/dev/v4l-subdev5、CIF=/dev/media2、ISP=/dev/media4；每次重启重新发现。不要因色偏擅改lane、GPIO或镜像。

## 3. 源码与资料支持的关键结论

- 驱动：`third_party/linux-rv1126b/drivers/media/i2c/ov13850.c`；设备树：`platforms/rv1126b/boards/atk-dlrv1126b/bsp/kernel/arch/arm64/boot/dts/rockchip/rv1126b-alientek-ov13850-csi1.dtsi`。
- 控件HTS=4800、VTS=1664、pixel_rate=120MHz用简单公式得到约15FPS；AIQ路径使用帧间隔推算pclk，实测报告239.616MHz、HTS4800、VTS1664，对应30FPS。该现象不是已经证明的驱动bug，未为凑帧率盲改时钟。
- 旧GainRange `[1,15.5,16,0,1,16,248]` 的映射在当前脚本中检查：1/2/4/8/15.5倍对应寄存器16/32/64/128/248。传感器数字增益、ISP数字增益限定unity。两帧生效延迟仍是待全量验证参考。
- 不能把ISP21 JSON改名当ISP35适配。生成脚本显式处理CISTimeLinePerReg、HDR字段形状、iso_list等；实际板端初始化验证是独立步骤。
- 缺IQ时server将NULL上下文传给setListenStrmStatus的崩溃属于SDK用户态错误处理。维护补丁在独立分支 `fix/rkaiq-error-handling`（提交5e7bedd），见 https://github.com/sunxun1017/rtctrl-platform/pull/1 。当前工作分支可能尚未包含它们；本文不会自动应用补丁或替换板端库。
- BLC类型：SDK `rkaiq/include/isp/rk_aiq_isp_blc30.h`；转换：`rkaiq/modules/rk_aiq_module_blc30.c`，obcPreTnr直接写fixed_val；算法：`rkaiq/algos/newStruct/blc/algo_blc.c`，使用sensor iso_list插值。
- AE目标范围：`rkaiq/include/isp/rk_aiq_isp_ae25.h` 的 ae_dynSetpoint_t，0..255。

应阅读SDK `docs/cn/RV1126B/RKIPC/` 中 Development_Guide_ISP35、Tuning_Guide_ISP35、Color_Optimization_Guide_ISP39_ISP33_ISP35 三份官方中文PDF。全像素AWB依据色彩指南2.2.2.9.1诊断方法；AWB/CCM正式标定另需相应RAW、光源及色卡。解析PDF可用 `pdftotext -layout` 或 Python pypdf，不能把JSON例子比较当完整schema验证。

## 4. 从原始 SDK 生成最终 IQ（已实际重跑）

```sh
python3 scripts/generate-ov13850-isp35.py \
  --sdk-root "$SDK" --out-dir "$RUN/base" --wb unity
python3 scripts/make-ov13850-awb-diagnostic.py \
  --base "$RUN/base/ov13850_ATK-MCOV13850_default.json" \
  --output "$RUN/awb.json" --all-pixels
python3 scripts/generate-ov13850-measured-blc.py \
  --iq "$RUN/awb.json" \
  --measurements 'docs/develop camera/ov13850-dark-measurements-20260905.json' \
  --output "$RUN/final/ov13850_ATK-MCOV13850_default.json" --ae-factor 1.5
sha256sum "$RUN/awb.json" "$RUN/final/ov13850_ATK-MCOV13850_default.json"
```

在上述SDK上重跑得到：

- 全像素AWB中间文件：`af7ef73c59746fabf51f8fe4395a996e1e46f999b3bd148b18c0bc31e0cbdf2b`。
- 最终Linux/LF文件：`ae957a5472806fc828578f882e53e1990ed887f3910a228e4d22ad6b995217a4`。
- 当日板端实测并安装的Windows/CRLF序列化文件：`9e5b3ab9a28a02768043acaaaa8113b94e348fac6d82ba00332467cede705bf2`。已逐项比较JSON，参数完全相同；字节hash不同不能省略解释。

脚本拒绝覆盖已有输出。SDK或输入变化导致hash变化时，应查看provenance和参数差异，不要继续宣称同版复现。不手工生成BIN，本次直接使用JSON。

模块处理：

| 模块 | 最终处理及原因 |
|---|---|
| Sensor/AE | OV13850描述，线性2112×1568；固定30FPS，曝光路线≤30ms、模拟增益≤15.5；AE目标[45,45,45,42,36,33,27]为现场偏好调整 |
| AWB | 自动；关闭外借色度白点筛选和增益调整；全像素估计可受场景颜色影响 |
| BLC | 启用实测前级扣除；关闭自动BLC与postTNR额外偏置；只验证当前温度/模式 |
| Gamma/demosaic/gain | 保留ISP35参考基础处理，未宣称传感器专项调优 |
| CSM/CGC | BT.601 full-range，正常范围转换；未采用饱和度增强 |
| CCM/LSC/降噪/锐化/其他可选模块 | 保持禁用，未复用别的模组标定；残留payload仅供解析结构 |
| AF/HDR | 本阶段不支持；禁用AF算法，线性模式运行 |

## 5. 新模组怎样重新测暗场

复现本次参数可使用已存测量表；换传感器、镜头、增益映射、工作模式或温度条件不能直接称复用标定。不要把白场拟合截距当黑场。

先停止当前已知AIQ/采集进程并确认结束。用不透光物体完整遮光，不触碰镜头或接线；检查全部边角，白纸倒下/场景移动后重新采白场。设置下列节点为本次拓扑确认值，再执行（建议保存为独立sh脚本运行，以便EXIT trap生效）：

```sh
# 板端：下面三项必须先从media-ctl/sysfs确认
SENSOR=/dev/v4l-subdev5
RAW=/dev/video12
COMPACT=/sys/devices/platform/rkcif-mipi-lvds2/compact_test
D=/root/ov13850-dark-new
mkdir -p "$D"
cat "$COMPACT" > "$D/compact-before.txt"
v4l2-ctl -d "$SENSOR" --get-ctrl=exposure,analogue_gain,vertical_blanking > "$D/controls-before.txt"
# 本次原值为compact的四路全1；不是全1时不要套用下方恢复命令
[ "$(cat "$D/compact-before.txt")" = "1 1 1 1" ] || exit 1
old_exp=$(sed -n 's/^exposure: //p' "$D/controls-before.txt")
old_gain=$(sed -n 's/^analogue_gain: //p' "$D/controls-before.txt")
case "$old_exp:$old_gain" in *[!0-9:]*|:*|*:) echo '原控件读取失败'; exit 1;; esac
restore_raw() {
  echo 1 > "$COMPACT"
  v4l2-ctl -d "$RAW" --set-fmt-video=width=2112,height=1568,pixelformat=BG10
  v4l2-ctl -d "$SENSOR" --set-ctrl="exposure=$old_exp,analogue_gain=$old_gain"
}
trap restore_raw EXIT
trap 'exit 130' INT TERM
echo 0 > "$COMPACT"
v4l2-ctl -d "$RAW" --set-fmt-video=width=2112,height=1568,pixelformat=BG10
v4l2-ctl -d "$RAW" --get-fmt-video
# 必须为BG10、Bytes per Line4224、Size Image6623232，才能按<uint16低10位解析
for g in 16 32 64 128 248; do
  v4l2-ctl -d "$SENSOR" --set-ctrl="exposure=1498,analogue_gain=$g" || break
  timeout 8 v4l2-ctl -d "$RAW" --stream-mmap=4 --stream-skip=30 \
    --stream-count=3 --stream-to="$D/dark$g.raw" > "$D/dark$g.log" 2>&1 || break
done
restore_raw
trap - EXIT INT TERM
```

把RAW复制到主机，用NumPy按 `dtype='<u2'`、`reshape(3,1568,2112)` 读取。BG10四通道顺序：R=`[:,1::2,1::2]`，Gr=`[:,1::2,0::2]`，Gb=`[:,0::2,1::2]`，B=`[:,0::2,0::2]`。逐通道求均值，另分4×4区域检查漏光、时序稳定和异常像素，不只看中央。每档文件应19869696字节，像素不得超1023。

本次1倍增益R/Gr/Gb/B均值16.8034/16.5485/16.8161/16.8606，全幅16分区均值16.7320～16.7827；15.5倍增益空间差异仍低于1个RAW码值。测量表字段为gain_reg、R_Gr_Gb_B、percentiles、tile_mean_range。

单位验证：固定曝光30ms、模拟增益1、手动unity WB，仅改变BLC0=0/17/34/67，暗场NV12平均Y=26.233/19.736/12.991/0.514，支持10位RAW到ISP扣除值×4。不是根据显示变黑就允许任意大扣除；需同时结合RAW测量及源码。最终前五档BLC(R/Gr/Gb/B)：67/66/67/67，67/66/66/68，68/67/66/68，68/66/66/69，70/65/66/72。超过实测ISO的表项夹到末端，AE路线必须继续限制可达ISO≤775。

## 6. 构建并部署到独立测试目录

```sh
# 主机，仍在项目根目录
mkdir -p work
sh scripts/build-ov13850-aiq-lifecycle.sh "$SDK"
# 用当前板端IP，首次连接核对主机身份，不关闭HostKeyChecking
export BOARD=root@<当前板端IP>
ssh "$BOARD" 'mkdir -p /root/ov13850-repro/iq'
scp work/ov13850-aiq-lifecycle "$BOARD":/root/ov13850-repro/
scp "$RUN/final/ov13850_ATK-MCOV13850_default.json" "$BOARD":/root/ov13850-repro/iq/
```

测试程序使用板上原有librkaiq.so；没有偷偷替换库。它检查init返回、prepare/start结果，使用setListenStrmStatus(ctx,true)监听流事件，输出AE/WB，stop/deinit有超时保护。文件权限需要可执行：`chmod +x /root/ov13850-repro/ov13850-aiq-lifecycle`。

板端再次发现ISP统计/参数/视频节点：

```sh
ISP=/dev/media4  # 替换为拓扑确认的rkisp-vir1
VIDEO=$(media-ctl -d "$ISP" -e rkisp_mainpath)
media-ctl -d "$ISP" -e rkisp-statistics
media-ctl -d "$ISP" -e rkisp-input-params
v4l2-ctl -d "$VIDEO" --get-fmt-video
# 必须2112×1568 NV12，Size Image4967424，full-range
```

## 7. 初始化、稳定帧与重复启停验收

仅在没有其他AIQ/摄像头消费者时运行。保持场景和灯光稳定；采样期间不要提前遮光。

```sh
# 板端；VIDEO来自上一节，SENSOR_NAME来自本次sysfs
SENSOR_NAME='m01_b_ov13850 4-0010'
T=/root/ov13850-repro
for i in 1 2 3; do
  "$T/ov13850-aiq-lifecycle" "$SENSOR_NAME" "$T/iq" 50 > "$T/aiq-$i.log" 2>&1 &
  p=$!
  sleep 2
  if ! grep -q '^START=0' "$T/aiq-$i.log"; then
    kill -TERM "$p" 2>/dev/null; wait "$p"; echo 'AIQ未成功启动'; break
  fi
  timeout 40 v4l2-ctl -d "$VIDEO" --stream-mmap=4 --stream-count=900 \
    --stream-to=/dev/null --verbose > "$T/capture-$i.log" 2>&1
  cap_rc=$?
  kill -TERM "$p" 2>/dev/null
  wait "$p"; aiq_rc=$?
  printf 'cycle=%s CAP=%s AIQ=%s\n' "$i" "$cap_rc" "$aiq_rc"
  grep -E 'STOP=|DEINIT_DONE|WB_QUERY=' "$T/aiq-$i.log" | tail -12
  [ "$cap_rc" = 0 ] && [ "$aiq_rc" = 0 ] || break
done
```

验收条件：PREPARE=0/START=0；无IQ找不到或解析错误；每轮sequence0..899连续、约30.05FPS；AE控制不越界；末尾10次WB_QUERY=0且converged=1；STOP=0/DEINIT_DONE；无新内核timeout/stall/Oops。收敛标志不是颜色准确性证明。看到LIFECYCLE_TIMEOUT后停止继续循环，先保留日志和回溯，不反复启动叠加进程。

保存稳定画面时，在同样的AIQ启动/停止流程内将采集命令换为：

```sh
timeout 25 v4l2-ctl -d "$VIDEO" --stream-mmap=4 --stream-skip=450 \
  --stream-count=1 --stream-to="$T/stable.nv12" --verbose > "$T/stable-capture.log" 2>&1
```

一帧4967424字节。NV12是Y平面后交错UV，不是NV21；本IQ采用BT.601 full-range，Y不减16。解码R=Y+1.402(V−128)，G=Y−0.344136(U−128)−0.714136(V−128)，B=Y+1.772(U−128)。不要用错误range或后期滤镜掩盖问题。

更换光照验收需要用户配合：稳定白纸/灰卡 → 原光照收敛取图 → 遮暗并保持 → 记录曝光和增益 → 恢复 → 等待重新收敛。再移出大白纸测试普通场景漂移。当前新BLC版已做稳定场景复测，不能沿用旧版光照响应测试来宣称新版全光源通过。

## 8. 验证通过后安装、重启行为与回滚

先停AIQ。以下通用命令同时备份JSON/BIN；只将匹配BIN移入备份，避免旧BIN抢先被加载。不得删除其他传感器文件。

```sh
# 板端，确认测试目录中的IQ就是待安装版本
F=/etc/iqfiles/ov13850_ATK-MCOV13850_default
B=/root/ov13850-backup-$(date +%Y%m%d-%H%M%S)
mkdir "$B" || exit 1
for ext in json bin; do
  if [ -e "$F.$ext" ]; then cp -p "$F.$ext" "$B/original.$ext" || exit 1; fi
done
printf '%s\n' "$B"  # 记下此路径，板时钟可能不正确
if [ -e "$F.bin" ]; then mv "$F.bin" "$B/disabled.bin" || exit 1; fi
cp /root/ov13850-repro/iq/ov13850_ATK-MCOV13850_default.json "$F.json.new" || exit 1
mv "$F.json.new" "$F.json"
sync
sha256sum "$F.json"
```

将第7节IQ目录改成 `/etc/iqfiles` 再完成一次初始化、稳定帧与退出，确认正式路径。配置位于持久存储，重启不会丢；但本流程**不配置开机自启动**。每次采集仍需正确启动AIQ。直接运行rkaiq_3A_server时也要避免与测试程序并存。

本次已安装版的专用回滚命令（板端，先停止AIQ）：

```sh
sh /root/ov13850-refinement-20260905/rollback.sh
```

该脚本校验当前实测版与旧版备份hash，恢复 `/root/ov13850-refinement-20260905/pre-refinement.json`。对后续重新部署版，应使用该次记录的B路径恢复original.json/original.bin：先校验备份和当前文件，再复制到临时同目录文件并mv；不要拿本次专用hash脚本恢复不同版本。

## 9. 本次验证摘要与交付边界

3×900帧均连续，FPS30.04804/30.04804/30.04808；曝光1498、增益103/100/104、VBLANK96。每轮最后10次AWB增益固定且收敛；轮间R约1.94～2.00、B约1.34～1.37，场景非完全静止。正式路径复测451帧成功，最终R1.94438/B1.37798收敛，STOP/DEINIT正常。内核日志比对未发现新增timeout/stall/BUG/Oops。它不代表无限时长压力测试。

主机端完整原始RAW、NV12、截图及日志留存于PC `Documents/Codex/2026-09-05/root-atk-dlrv1126b-media-ctl-d/outputs/OV13850-image-refinement-20260905`；板端 `/root/ov13850-refinement-20260905`。仓库只保存可复现脚本、小型测量表及说明，避免提交供应商IQ和大量帧文件。

后续优先级：多灯光AWB/色卡CCM → 全温度/多曝光黑电平 → 镜头LSC → 噪声/锐化 → 长时间稳定性。没有新的测量证据时不盲改驱动，不执行自动刷机、OTP写入或带电插拔。