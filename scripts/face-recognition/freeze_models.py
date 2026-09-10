#!/usr/bin/env python3
"""Explicitly specialize local face ONNX models to batch 1 and observed output shapes."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('destination', type=Path)
    p.add_argument('--role', choices=['detector', 'recognizer'], required=True)
    a = p.parse_args()
    if a.destination.exists() or a.destination.with_suffix('.provenance.json').exists():
        p.error('Destination exists')
    model = onnx.load(str(a.source))
    if len(model.graph.input) != 1:
        p.error('Expected one input')
    dims = model.graph.input[0].type.tensor_type.shape.dim
    edge = 320 if a.role == 'detector' else 112
    if len(dims) != 4 or [d.dim_value for d in dims[1:]] != [3, edge, edge] or dims[0].dim_value not in (0, 1):
        p.error('Only batch dimension may be dynamic')
    dims[0].dim_value = 1
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(model.SerializeToString(), sess_options=options, providers=['CPUExecutionProvider'])
    outputs = session.run(None, {session.get_inputs()[0].name: np.zeros((1, 3, edge, edge), dtype=np.float32)})
    shapes = [list(o.shape) for o in outputs]
    expected = [[1, 4200, 2], [1, 4200, 4], [1, 4200, 10]] if a.role == 'detector' else [[1, 512]]
    if sorted(shapes) != expected:
        p.error(f'Unexpected actual output shapes: {shapes}')
    for value, shape in zip(model.graph.output, shapes):
        for dim, size in zip(value.type.tensor_type.shape.dim, shape):
            dim.dim_value = size
    onnx.checker.check_model(model)
    a.destination.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(a.destination))
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    a.destination.with_suffix('.provenance.json').write_text(json.dumps({
        'source': str(a.source), 'source_sha256': sha(a.source), 'derived_sha256': sha(a.destination),
        'operation': 'batch-one specialization and CPU-observed output shape annotation; no weights changed',
        'output_shapes': shapes, 'onnx_version': onnx.__version__, 'onnxruntime_version': ort.__version__}, indent=2)+'\n')


if __name__ == '__main__':
    main()
