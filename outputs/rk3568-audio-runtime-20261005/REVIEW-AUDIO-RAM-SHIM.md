# 音频 RAM DT shim 独立复核

display_next_steps独立全树与fresh真实libfdt三次apply均通过，由主控保存。
原audio DT163161B/SHA `9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478`；
shim163204B/SHA `c36b140c0ad18b79c3976f64239ef02251fc6986893afad7c474126725eb1e8b`；
applied-audit-only163285B/SHA `4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f`。
962节点无增删，761既有phandle保持。原codec占2f9，所以chosen用2fa；旧UART allocator实际拒绝。

shim只加chosen symbol/phandle两属性，原dtbo单entry559B/offset64、SHA acf746c…dfec3。
套entry0后全树仅五属性差异，normal5242c300、两reservation保持。
独立fresh apply三次逐字节等于审计DT。包必须放pre-overlay shim，applied仅审计。
完整[清单和diff](build/audio-ram-shim-v1/manifest.json)与[旧allocator拒绝](build/audio-ram-shim-v1/old-uart-shim-rejected.json)保留。

该结论只核RAM shim。新Image/header占用范围、完整boot包绑定与板端最终树仍待核，
不是声音传输、正式flash或早期DM通过。
