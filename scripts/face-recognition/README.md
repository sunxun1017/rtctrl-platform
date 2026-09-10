# RV1126B 模型准备

工具只转换用户有权使用的本地权重，不下载权重。需要 Python3、onnx；实际转换需要支持 RV1126B 的 RKNN Toolkit2。

```bash
python3 scripts/face-recognition/convert_models.py \
  --detector /path/to/RetinaFace_mobile320.onnx \
  --recognizer /path/to/w600k_mbf.onnx \
  --recognizer-normalization external --plan
```

`--plan`/`--inspect` 只检查 ONNX，不加载 Toolkit 或写文件。确认识别模型是否内置 `(pixel-127.5)/127.5`：未内置选 external；已内置且接受 RGB 0..255 选 embedded。工具保守检查输入附近算术，不能证明预处理语义。

转换时去掉 --plan，加 `--output-dir models/face-rv1126b`。输出目录必须不存在，两个模型都成功才发布 detector.rknn、recognizer.rknn 和 manifest.json。manifest 记录源和产物 SHA256、版本、形状及配置；转换不代表板端精度或零拷贝已验证。

固定单输入 NCHW ONNX：检测 [1,3,320,320]、识别 [1,3,112,112]；检测输出要求 [1,4200,4]、[1,4200,2]、[1,4200,10]（顺序不限），识别 [1,512]。拒绝动态维度和外置权重。运行时查询 RKNN 输出属性匹配语义，不能假设编译后顺序不变。形状检查不证明算法语义。

运行时输入为 RGB 原始 0..255，布局必须查询 backend.input_spec，按返回的 NCHW 或 NHWC 填充。检测 mean104,117,123/std1 来自 [Rockchip 官方转换示例](https://github.com/airockchip/rknn_model_zoo/blob/main/examples/RetinaFace/python/convert.py)。识别 external 使用 mean/std127.5，须与具体权重契约核对。预处理已包含在转换配置，不要重复归一化。

默认不量化。仅检测可添加 `--detector-dataset /absolute/path/dataset.txt` 启用 INT8。采用 Toolkit 图像路径清单，建议绝对路径；校准输入是 RGB 原始0..255，不提前归一化。需要代表实际场景并对比浮点精度。识别特征需后续 L2 归一化和验证拒识阈值。

离线替身测试无需 ONNX、Toolkit 或网络：

```bash
python3 -m unittest discover -s scripts/face-recognition -p 'test_*.py'
```

## 官方模型的符号维度

实际官方权重的 RetinaFace 输出 anchor 维度是符号，w600k_mbf 输入 batch 是符号。
严格转换器不会猜测它们。可显式用 `freeze_models.py` 固定 batch=1，通过本机
ONNX Runtime 的一次推理确认输出尺寸，再写派生模型和原始/派生 SHA256 记录；不改权重。
需要 numpy、onnx、onnxruntime：

```bash
python3 scripts/face-recognition/freeze_models.py \
  /path/to/RetinaFace_mobile320.onnx /path/to/static/RetinaFace_mobile320.onnx --role detector
python3 scripts/face-recognition/freeze_models.py \
  /path/to/w600k_mbf.onnx /path/to/static/w600k_mbf.onnx --role recognizer
```

随后将派生模型传给转换器，并保留相邻 provenance.json。固定尺寸只覆盖当前 batch=1
用法；零输入输出尺寸检查不代表识别精度验证。

2026-09-11 在用户确认个人学习用途后取得的原始文件（保存在 git 忽略的 `.deps/models`）：

| 文件 | 官方来源 | SHA256 |
|---|---|---|
| RetinaFace_mobile320.onnx | [Rockchip 下载入口](https://github.com/airockchip/rknn_model_zoo/blob/main/examples/RetinaFace/model/download_model.sh) | `1061ac88e7c833cf058c3e8eb50367dc5e3daadcc14967b5dede8ac4409b86fa` |
| buffalo_sc.zip | [InsightFace release](https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_sc.zip) | `57d31b56b6ffa911c8a73cfc1707c73cab76efe7f13b675a05223bf42de47c72` |
| w600k_mbf.onnx | 上述压缩包内同名文件 | `9cc6e4a75f0e2bf0b1aed94578f144d15175f357bdc05e815e5c4a02b319eb4f` |

识别图以 Conv 开始，没有输入归一化算子，因此此文件使用 external 配置。

## 本次实测

2026-09-11 使用 RKNN Toolkit2 2.3.2 成功将上述静态派生模型转换为 RV1126B 非量化模型，
产物在 `.deps/models/rv1126b/`。隔离依赖目录 `.deps/face-toolkit/python`，使用 numpy1.26.4、
onnx1.16.1、opencv4.10.0.84、torch2.4.0+cpu，未改系统包。

可复现零输入数值对照（从源 ONNX 重新非量化构建模拟器模型）：

```bash
PYTHONPATH="$PWD/.deps/face-toolkit/python" python3 scripts/face-recognition/check_simulator.py \
  .deps/models/rv1126b/manifest.json --output .deps/models/rv1126b/simulator-comparison.json
```

原始 RGB 全零输入经 manifest 的 mean/std 后送 ONNX Runtime CPU，与 RKNN 宿主模拟器比较：

| 输出 | shape | 最大绝对差 | cosine |
|---|---|---|---|
| boxes | [1,4200,4] | 0.134307 | 0.999627 |
| scores | [1,4200,2] | 0.000472 | 0.99999999 |
| landmarks | [1,4200,10] | 0.224048 | 0.999771 |
| embedding | [1,512] | 0.004639 | 0.999968 |

所有值有限，形状匹配。以上仅为一次全零输入的转换数值检查，不能证明真实人脸精度、拒识阈值
或板端表现；box/landmark 差异仍需用真实图像验证。未在 RV1126B 板端执行。
