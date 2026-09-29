#!/usr/bin/env python3
"""Render the reviewed Android DT overview; no device access or external packages."""
from html import escape
from pathlib import Path

cards = [
    ('I²C0 · 电源管理', 'fdd40000', [
        ('● 0x1c  TCS452x → CPU 供电', 'bound'),
        ('● 0x20  RK809 → 多路 regulator / codec', 'bound'),
        ('● 0x22  FUSB302 · Type-C', 'bound'),
        ('● 0x6b  BQ25703 · 充电', 'bound')]),
    ('I²C1 / I²C2 · 触摸与相机控制', 'fe5a0000 / fe5b0000', [
        ('○ I²C1: 0x14 Goodix GT9xx；0x30 XRM117x', 'declared'),
        ('○ I²C2: 0x36 OV5695 图像传感器', 'declared'),
        ('● I²C2: 0x0c VM149C 对焦', 'bound'),
        ('数据链路：OV5695 → DPHY0 → ISP vir0', 'normal')]),
    ('I²C3 / I²C5 · 传感器与板控', 'fe5c0000 / fe5e0000', [
        ('○ I²C3: 0x68 RJGT102；0x50 AT88 节点', 'declared'),
        ('● I²C5: 0x15 MXC6655 加速度传感器', 'bound'),
        ('● I²C5: 0x62 STM8S00K3 → McuCom', 'bound'),
        ('○ I²C5: 0x50 AT24C16；0x51 PCF8563', 'declared')]),
    ('SPI3 · 身体触摸', 'fe640000 · CS0', [
        ('● CAP1188 → input/event0', 'bound'),
        ('100 kHz · mode 3 · SPI3 M1 引脚组', 'normal'),
        ('reset: GPIO0_B6', 'normal'),
        ('注意：与 Goodix reset 声明重复', 'declared')]),
    ('UART · 调试与外部控制', 'fdd50000 / fe660000', [
        ('UART0 → Android /dev/ttySMT0', 'normal'),
        ('外部 GD32 连接及协议实测仍待核对', 'declared'),
        ('UART2 → FIQ debugger → 调试串口', 'normal'),
        ('调试口：1500000 baud；不同于 UART0', 'normal')]),
    ('存储与无线', 'SDHCI / SDIO', [
        ('SDHCI fe310000 → eMMC · 8 bit', 'normal'),
        ('原树 max-frequency=200 MHz', 'normal'),
        ('● SDIO fe2c0000 → bcmsdh_sdmmc', 'bound'),
        ('DT Wi-Fi: ap6398s；BT 为厂商平台节点', 'normal')]),
    ('显示与背光', 'VOP2 → DSI0 → panel@0', [
        ('原机 DSI connected · 720 × 720', 'normal'),
        ('4 lanes · pixel clock 35.5 MHz', 'normal'),
        ('panel reset GPIO0_A5 / enable GPIO0_C5', 'normal'),
        ('PWM fe6e0000 → 背光 · 40 kHz', 'normal')]),
    ('音频与 USB', 'I²S fe410000 / USB host', [
        ('I²S → RK809/RK817 codec → 板载声卡', 'normal'),
        ('RK809 codec 控制来自 I²C0', 'normal'),
        ('运行时补充：USB Bothlent UAC 声卡', 'bound'),
        ('8 通道 / 16 kHz / S16_LE；非 DT 固定子节点', 'normal')]),
    ('供电关系与系统资源', '原树逻辑描述，不是电路原理图', [
        ('dc_12v → vcc3v3_sys / vcc5v0_sys / USB', 'normal'),
        ('RK809 → CPU 以外的多路电源与 IO 域', 'normal'),
        ('vccio4 / vccio6 = 1.8 V；LDO4 = 3.1 V', 'normal'),
        ('4 个 CPU 节点；3 段 RAM；2 项 memreserve', 'normal')]),
]
colors = {'bound': '#087a60', 'declared': '#965c0a', 'normal': '#334155'}
svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1680" height="1160" viewBox="0 0 1680 1160">',
       '<rect width="1680" height="1160" fill="#f1f5f9"/>',
       '<g font-family="Microsoft YaHei,Noto Sans CJK SC,sans-serif">']
def text(x, y, value, size=18, color='#0f172a', weight='normal'):
    svg.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(value)}</text>')
text(50, 53, '3568A · Android 原机设备树框图', 32, weight='bold')
text(50, 88, '依据 2026-09-28 原始 FDT 与运行记录整理 · Linux 4.19.232 · 主要板级外设视图', 19)
svg.append('<rect x="555" y="115" width="570" height="72" rx="15" fill="#16324f"/>')
text(614, 145, 'Rockchip RK3568 / board: 3568A', 25, '#ffffff', 'bold')
text(611, 172, '总线连接、功能链路与供电引用的分组概览', 18, '#d9e9f8')
svg.append('<path d="M840 187 V209 H28 V958 M840 209 H578 V958 M840 209 H1128 V958" fill="none" stroke="#94a3b8" stroke-width="2"/>')
for i, (title, addr, rows) in enumerate(cards):
    x, y = 50 + (i % 3) * 550, 234 + (i // 3) * 248
    svg.append(f'<path d="M{x-22} {y+34} H{x}" stroke="#94a3b8" stroke-width="2"/>')
    svg.append(f'<rect x="{x}" y="{y}" width="510" height="222" rx="12" fill="white" stroke="#cbd5e1"/>')
    text(x+20, y+35, title, 23, weight='bold')
    text(x+20, y+62, addr, 16, '#64748b')
    for j, (label, kind) in enumerate(rows):
        text(x+20, y+98+j*31, label, 17, colors[kind])
text(50, 1020, '● 采集时已有 driver 绑定（不等于功能验收）    ○ DT 声明 / 已枚举，但采集时未见 driver 绑定', 20)
text(50, 1060, 'I²C5 的 STM8 板控节点不能直接等同 UART0 的 GD32；关机协议与 ACK 仍待核对。', 20, '#965c0a')
text(50, 1096, '图中省略 SoC 内部时钟、复位、IOMMU 及大量备用/禁用节点；不代表新 Linux 已启用这些设备。', 18, '#64748b')
text(50, 1130, '原始 FDT SHA-256: a028987f730f3c8e4be9cb6e771b91a5665932712c51e1e540b96654de4dd28b', 16, '#64748b')
svg.append('</g></svg>')
Path(__file__).with_name('android-device-tree.svg').write_text('\n'.join(svg)+'\n', encoding='utf-8')
