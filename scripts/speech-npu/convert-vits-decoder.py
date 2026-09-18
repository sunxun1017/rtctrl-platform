#!/usr/bin/env python3
"""Extract a fixed-length AISHELL3 decoder for isolated RV1126B validation.

This does not convert the text frontend or dynamic duration/flow graph.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

SOURCE_SHA256 = "5511d651b7840c0a93a6bbfd4afd070a2c7f39ca1ec3ff2ecd73191519bbb852"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--length", type=int, default=int(os.environ.get("LATENT_LENGTH", "16")))
    args = parser.parse_args()
    if not 1 <= args.length <= 2048:
        parser.error("latent length must be between 1 and 2048")
    if digest(args.source) != SOURCE_SHA256:
        parser.error("source is not the audited AISHELL3 VITS model")
    import onnx
    from onnx import helper, TensorProto
    from rknn.api import RKNN

    args.output.mkdir(parents=True, exist_ok=True)
    source = onnx.load(args.source)
    nodes = [node for node in source.graph.node if node.name.startswith("/decoder/")]
    if len(nodes) != 114:
        raise ValueError("Unexpected decoder graph")
    used = {name for node in nodes for name in node.input}
    initializers = [item for item in source.graph.initializer if item.name in used]
    shapes = [[1, 96, args.length], [1, 256, 1]]
    names = ["/Mul_8_output_0", "/Unsqueeze_output_0"]
    inputs = [helper.make_tensor_value_info(name, TensorProto.FLOAT, shape)
              for name, shape in zip(names, shapes)]
    output_shape = [1, 1, args.length * 256]
    outputs = [helper.make_tensor_value_info(
        "/decoder/output_conv/output_conv.2/Tanh_output_0", TensorProto.FLOAT, output_shape)]
    graph = helper.make_graph(nodes, "aishell3_vits_decoder", inputs, outputs, initializers)
    model = helper.make_model(graph, opset_imports=list(source.opset_import))
    model.ir_version = source.ir_version
    onnx.checker.check_model(model)
    prefix = args.output / ("decoder-l%d" % args.length)
    onnx_path, rknn_path = prefix.with_suffix(".onnx"), prefix.with_suffix(".rknn")
    if rknn_path.exists():
        raise ValueError("Output RKNN already exists; choose a fresh output directory")
    onnx.save(model, onnx_path)
    sdk = RKNN(verbose=False)
    def check(stage, result):
        print(stage, result, flush=True)
        if result != 0:
            raise RuntimeError("%s failed: %s" % (stage, result))
    try:
        check("config", sdk.config(target_platform="rv1126b"))
        check("load", sdk.load_onnx(model=str(onnx_path)))
        check("build", sdk.build(do_quantization=False))
        check("export", sdk.export_rknn(str(rknn_path)))
    finally:
        sdk.release()
    report = {"latent_length": args.length, "input_shapes": shapes,
              "output_shape": output_shape, "source_sha256": SOURCE_SHA256,
              "onnx_sha256": digest(onnx_path), "rknn_sha256": digest(rknn_path),
              "nodes": len(nodes), "target": "rv1126b", "quantized": False,
              "status": "converted_not_board_validated"}
    prefix.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
