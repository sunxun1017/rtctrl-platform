#!/usr/bin/env python3
"""Rebuild manifest ONNX inputs and compare zero-input RKNN simulation to ONNX CPU."""
import argparse
import json
from pathlib import Path
import numpy as np
import onnxruntime as ort
from rknn.api import RKNN


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    manifest = json.loads(args.manifest.read_text())
    results = []
    for record in manifest['models']:
        sdk = RKNN(verbose=False)
        try:
            def check(ret):
                if ret != 0:
                    raise RuntimeError(f'RKNN operation failed: {ret}')
            check(sdk.config(mean_values=record['mean_values'], std_values=record['std_values'], target_platform=manifest['target']))
            check(sdk.load_onnx(model=record['source']))
            check(sdk.build(do_quantization=False))
            check(sdk.init_runtime())
            shape = record['onnx_inputs'][0]['shape']
            raw = np.zeros((1, shape[2], shape[3], 3), dtype=np.uint8)
            actual = sdk.inference(inputs=[raw], data_format=['nhwc'])
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            session = ort.InferenceSession(record['source'], sess_options=options, providers=['CPUExecutionProvider'])
            mean = np.array(record['mean_values'][0], dtype=np.float32).reshape(1, 1, 1, 3)
            std = np.array(record['std_values'][0], dtype=np.float32).reshape(1, 1, 1, 3)
            normalized = ((raw.astype(np.float32) - mean) / std).transpose(0, 3, 1, 2)
            expected = session.run(None, {session.get_inputs()[0].name: normalized})
            if actual is None or len(actual) != len(expected):
                raise RuntimeError('Missing simulator outputs')
            outputs = []
            for reference in expected:
                matches = [x for x in actual if x.shape == reference.shape]
                if len(matches) != 1:
                    raise RuntimeError('Ambiguous output shape mapping')
                a, b = matches[0].astype(np.float64).ravel(), reference.astype(np.float64).ravel()
                if not (np.isfinite(a).all() and np.isfinite(b).all()):
                    raise RuntimeError('Non-finite outputs')
                denominator = np.linalg.norm(a) * np.linalg.norm(b)
                outputs.append({'shape': list(reference.shape), 'max_abs_error': float(np.max(np.abs(a-b))),
                                'cosine': float(np.dot(a, b)/denominator) if denominator else None,
                                'all_finite': True})
            results.append({'role': record['role'], 'outputs': outputs})
        finally:
            sdk.release()
    args.output.write_text(json.dumps({'scope': 'zero input host simulator vs ONNX CPU, rebuilt unquantized; not recognition accuracy or board validation', 'results': results}, indent=2)+'\n')


if __name__ == '__main__':
    main()
