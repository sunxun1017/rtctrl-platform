# 静态图片人脸身份匹配

此应用运行在非实时域。它把图像预处理、人脸框/关键点解码、五点对齐和本地身份匹配与通用 inference 后端分开。算法库可以注入任意符合契约的 `Backend`，无需 RKNN SDK。

## 模型契约

- 检测：RetinaFace MobileNet，固定 320×320，RGB 连续 Float32 提交，值域 0–255；模型转换内置 mean `[104,117,123]`，应用不重复减均值。单输入 NHWC 或 NCHW。输出恰好三项，形状 `[1,4200,4]`、`[1,4200,2]`、`[1,4200,10]`（也接受省略 batch 的二维形状），分别是偏移、二类概率和关键点偏移。通道在前、logits、不同 anchor 数的模型明确拒绝。
- 识别：w600k_mbf 对应的 112×112 RGB Float32 输入，值域 0–255；ONNX 未内置归一化时，转换使用 mean/std 127.5；已内置且接受原始 RGB 时，转换使用 mean 0/std 1，避免重复归一化。应用始终提交原始 RGB。输出单个 512 元素向量。按标准五点模板估计相似变换，输出向量做 L2 归一化。
- 不会仅凭模型形状推断语义。使用其它权重必须先确认输出与预处理契约。

检测使用居中 letterbox 和实际整数 resize 比例反映射；默认置信度 0.8、NMS IoU 0.4、最多保留 1000 个候选和 32 张脸。候选和人脸上限可能截断密集场景结果。

每人可以录入多个样本，匹配使用同一人的最大余弦相似度。低于显式提供的 `--threshold` 或不同人员前两名分差小于 `--gap` 则输出 `unknown`；不同人员最佳得分完全并列时，即使 gap 为零也拒识。阈值没有通用安全默认值，应使用目标摄像头的独立验证数据标定。录入要求恰好一张检测到的人脸。

当前仅静态图片、CPU OpenCV 预处理和复制式输入，不宣称摄像头或端到端零拷贝。模型转换、板端执行与身份识别精度均需要实际模型/板卡验证。人员库包含生物特征数据，应由部署方限制访问和管理删除。

## 验证

`rtctrl_face_tests` 不依赖 RKNN runtime：用合成输出验证解码、NMS、非方图逆映射、多脸录入拒绝、退化对齐、特征归一化、未知与分差规则、人员库维度/模型不匹配和 JSON 转义。它不能替代真实 RKNN 模型的转换、输出排列和板端精度验证。

## 构建和运行

宿主需要 CMake、Ninja、C++17 编译器、OpenCV 开发包（core/imgproc/imgcodecs）和 OpenSSL Crypto 开发包：

```bash
cmake --preset face-host
cmake --build --preset face-host
ctest --preset face-host
```

宿主可运行替身算法测试、SHA256 测试和 CLI 参数解析；真实 RKNN 推理需要兼容的板端 runtime。当前宿主整合测试 13 项通过，RV1126B AArch64 CLI 已交叉编译成功，尚未上板运行。

使用提供的 ATK RV1126B SDK 交叉构建（参数换成自己的 SDK 路径）：

```bash
scripts/face-recognition/build_rv1126b.sh /path/to/atk_dlrv1126b_linux6.1_sdk
```

脚本使用 SDK 的 GCC 10.3 AArch64 工具链、OpenCV 3.4.5 和 OpenSSL 静态 Crypto 库；缺少指定 SDK 布局下的依赖会明确失败。可传第二个参数指定独立构建目录，切换工具链不要复用旧缓存。产物是 `build/face-rv1126b/rtctrl_face`，链接成功不代表与任意根文件系统的 glibc/libstdc++ ABI 都兼容；部署到对应 SDK 的系统，并检查动态依赖。

先按 [模型准备说明](../../scripts/face-recognition/README.md) 转换有权使用的本地模型，再在板端执行：

```bash
export RTCTRL_RKNN_RUNTIME=/usr/lib/librknnrt.so
./rtctrl_face enroll \
  --detector detector.rknn --recognizer recognizer.rknn \
  --image alice.jpg --gallery gallery.json --name Alice

./rtctrl_face recognize \
  --detector detector.rknn --recognizer recognizer.rknn \
  --image group.jpg --gallery gallery.json --threshold "$VALIDATED_THRESHOLD"
```

`VALIDATED_THRESHOLD` 必须设为你用独立验证集标定的余弦阈值（范围 -1 到 1），不是通用默认常数。可加 `--gap` 指定不同人员前两名分差，范围 0 到 2。未设置 runtime 环境变量时默认加载 `librknnrt.so`。模型指纹由识别模型文件 SHA256 和预处理契约版本自动计算，不能通过姓名或参数绕过模型一致性检查。

人员库只支持单写者：请串行执行 enroll。临时文件和原子 rename 避免发布半个 JSON，但不提供多进程写锁；并发录入可能丢失另一进程的更新。损坏或模型不匹配的已有人员库会拒绝载入，不能当成空库覆盖。

模型文件在程序运行期间必须保持不变；模型哈希检查与 SDK 加载分别读取文件，不支持在线替换权重。

## 当前验证状态（2026-09-11）

- `build/face-host` 和 `build/face-asan` 各 15 项测试通过；默认 release 13 项通过。
- 本次功能目录 C++ 格式检查通过；全仓库 format-check 仍报告其他既有文件的格式差异。
- 使用 SDK 的 GCC 10.3、OpenCV 3.4.5、OpenSSL 1.0.2o 成功交叉编译 ARM64 CLI。
- 两个官方权重已用 Toolkit2 2.3.2 转换为 RV1126B 非量化模型，产物在 `.deps/models/rv1126b`。
- 部署包：`build/face-rv1126b/rtctrl-face-rv1126b.tar.gz`，含程序、两个模型及 manifest；板端 runtime 使用板卡匹配版本。
- 宿主模拟器与 ONNX 的零输入对照：所有输出有限且形状相同；检测各输出余弦相似度最低 0.999627，识别 0.999968。此检查不代表实际人脸精度。
- 未完成：真实板端推理、已登记人员识别精度、摄像头接入和端到端零拷贝。当前等待 SSH 认证配置。
