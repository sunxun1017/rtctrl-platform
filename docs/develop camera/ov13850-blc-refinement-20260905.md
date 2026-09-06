# OV13850 室内画质改进 — 2026-09-05

当前采用实测黑电平 BLC + 线性 AE 目标 ×1.5。保留自动白平衡，保留原 gamma；未采用测试过的 gamma 对比度和 CSM 饱和度增强。CCM、LSC、降噪仍未标定，不声称产品级全场景完成。

## 测量与依据

板端 Linux 6.1.141 / ISP35 / AIQ v6.0x31.0。SDK camera_engine_rkaiq 91dee445c13770279e3ee90cd82bd278c5306f85。板时钟为2021年，目录日期按PC2026-09-05记录。

2112×1568，BG10，compact=0，低位对齐16位容器，行长4224，帧6623232字节。曝光1498，增益寄存器16/32/64/128/248，各跳过30帧采3帧。当前温度下全画面16分区均值范围在 dark-measurements.json，未见此前的明显边角漏光。高增益仍有噪声与稀疏亮点。

BLC寄存器值0/17/34/67的固定曝光、unity WB暗场试验，输出Y均值26.233/19.736/12.991/0.514，支持10位RAW→12位ISP缩放4。SDK modules/rk_aiq_module_blc30.c 直接将 obcPreTnr 写入 fixed_val；include/isp/rk_aiq_isp_blc30.h 定义字段，algos/newStruct/blc/algo_blc.c 使用sensor iso_list插值。关闭自动BLC和postTNR额外偏置。

BLC各通道用实测均值×4取整，按iso_list插值；AE最大模拟增益15.5对应ISO775，超出测量范围的表项夹到末端，不代表高ISO标定。AE动态目标由[30,30,30,28,24,22,18]改为[45,45,45,42,36,33,27]；rk_aiq_isp_ae25.h范围0..255，倍数属于现场实验选择。

## 验证

三组BLC对比各451帧连续、正常停止。最终候选另做3×900帧：30.048FPS，每轮末尾10次AWB查询均收敛且轮内增益不变；轮间R约1.94–2.00、B约1.34–1.37，场景非完全静止，不能称零漂移。传感器曝光1498、增益100–104、VBLANK96，未越界。测试期间无新增内核timeout/stall/BUG/Oops关键词。见final-verification.json。

候选画面暗部明显不再灰白，AE提高恢复主体亮度。对比图有人物/椅子位置变化，不能把全图均值差全部归因参数。高光灯具仍会过曝。颜色准确性需灰卡/色卡、多灯光、温度及曝光范围继续验收，既往长时间系统卡死未因此宣称修复。

## 保存与回滚

板端正式配置 /etc/iqfiles/ov13850_ATK-MCOV13850_default.json。
安装SHA256 9e5b3ab9a28a02768043acaaaa8113b94e348fac6d82ba00332467cede705bf2。
原配置备份 /root/ov13850-refinement-20260905/pre-refinement.json。
全部实验留存在 /root/ov13850-refinement-20260905，未使用临时目录作为交付位置。

停止AIQ后，执行配套rollback.sh恢复旧配置。脚本校验当前与备份哈希，不覆盖后续未知改动。未修改开机启动项，配置保存不等于AIQ常驻运行。

## 本地重现

python generate-ov13850-measured-blc.py --iq <原认可IQ路径> --measurements dark-measurements.json --output <新目录>/ov13850_ATK-MCOV13850_default.json

脚本不附带厂商IQ到Git。重生成JSON参数与实测版一致；LF/CRLF序列化造成字节hash不同，已比较解析后的全部参数相同。原始测试版在 blc-bright/，重生成版在 repro/。归档记录包含输入/输出hash。

正式路径安装后复测：451帧采集及AIQ退出码0，AWB最终R=1.94438、B=1.37798且持续收敛。compact已恢复1，AIQ当前停止。板端回滚：sh /root/ov13850-refinement-20260905/rollback.sh。
