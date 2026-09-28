# Android 运行设备树初读

依据：经板端 SHA-256 验证的 `fdt.dtb`，由 DTC 1.6.1 生成 `android-running.dts`。
下列行号指该 DTS。此表描述配置，不能单独证明驱动绑定、实装型号或功能通过。

|部分|设备树证据|移植关注点|
|---|---|---|
|屏幕|DSI0 panel@0，2785；native 720×720、35.5MHz，2807；4 lane；完整 init 序列2800|HBP/HSYNC/HFP=30/2/24，VBP/VSYNC/VFP=8/2/16；另一个800×1280模式不是native；不能由simple-panel-dsi推断屏IC型号|
|屏幕电源|reset GPIO0_A5低有效，enable GPIO0_C5高有效；3.3V供电|复用时须核对新内核panel绑定与电源顺序|
|背光|6009；PWM fe6e0000，4514；周期25000ns|40kHz，有亮度表|
|屏触摸|I2C1 gt1x@14，3993；goodix,gt9xx；reset GPIO0_B6、touch GPIO0_B5|坐标1920×1080与屏分辨率不同；reset与CAP1188重复，需要运行时证据|
|摄像头|I2C2 ov5695@36，4096；TongJu/CHT842-MD；2 lane|power GPIO0_D5，reset GPIO3_D4，pwdn GPIO3_D5；MCLK GPIO4_C0；vm149c@0c lens-focus引用|
|摄像头链路|OV5695→csi2-dphy0→rkisp-vir0|CIF disabled；其他disabled传感器不能当实装；需匹配原IQ文件|
|板载音频|rk809-sound，6044；simple-audio-card；i2s@fe410000与RK809/RK817 codec|mclk-fs=256，指定12.288MHz；spk GPIO4_C4低有效；差分mic；不能代替USB声卡证据|
|Wi-Fi|wireless-wlan，6238；wifi_chip_type=ap6398s；SDIO fe2c0000|与旧框图AP6256不一致；reset GPIO2_B1低有效，host wake GPIO2_B2；实装需SDIO ID及固件佐证|
|蓝牙|wireless-bluetooth，6246；bluetooth-platdata；旧参数bt_uart=ttyS1|reset GPIO2_B7，wake GPIO2_C1，host IRQ GPIO2_C0，RTS GPIO2_B5；不是标准serdev描述|
|IMU|I2C3 unjet,rjgt102@68，4145；I2C5 gs_mxc6655xa@15，4234|未见SH3001；不可直接将RJGT102等同SH3001；MXC节点30ms轮询、layout=1|
|身体触摸|SPI3 cap1188@0，4360；microchip,cap1188；100kHz、mode3|reset GPIO0_B6；无IRQ/键值映射；原厂SPI驱动需源码；不能直接使用I2C CAP11xx替代|
|SPI3引脚|SPI3 M1，5654|GPIO4_C2/C5/C3，CS0 GPIO4_C6，另配CS1 GPIO4_D1|
|UART0|serial@fdd50000，1688；alias serial0|GPIO0_C0/C1 mux3、pull-up；没有GD32子节点，不能证明连接GD32或协议含义|
|其他MCU|I2C5 mcuinf@62，4249；smdtmcu,STM8S00K3|含skip-mcu/powerkey-controller，不与GD32混同|
|调试口|fiq-debugger，6446|serial-id=2，1500000，与UART0分开|

GPIO phandle 0x37/0xea/0xbb/0x83/0x40 分别对应GPIO0/1/2/3/4（4943–5005）。
电平和非标准属性的实际解释仍应与厂商对应版本驱动核对。

树中还有不一致或备用描述：DSI1父节点disabled但panel子节点okay；HDMI/UART9有`status="dsiabled"`；旧参数`disp_dsi0="lvds"`。
DTC的26条警告保存在`dtc-warnings.txt`。反编译得到的是运行时扁平设备树内容，不会还原原厂DTS include、宏和注释结构。
