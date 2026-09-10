#!/usr/bin/env python3
"""Audit local ONNX contracts and explicitly convert them with RKNN Toolkit2."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile


class ConversionError(RuntimeError):
    pass


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def inspect_model(path, role, normalization, onnx_module=None):
    if onnx_module is None:
        try:
            import onnx as onnx_module
        except ImportError as exc:
            raise ConversionError('ONNX inspection requires the onnx Python package') from exc
    model = onnx_module.load(str(path), load_external_data=False)
    if any(t.data_location == 1 for t in model.graph.initializer):
        raise ConversionError('External ONNX tensor data is not supported; use a self-contained ONNX')
    onnx_module.checker.check_model(model)
    initializers = {t.name for t in model.graph.initializer}
    inputs = [v for v in model.graph.input if v.name not in initializers]

    def info(value):
        tt = value.type.tensor_type
        dims = [d.dim_value for d in tt.shape.dim]
        if not dims or any(d <= 0 for d in dims):
            raise ConversionError('Only static positive tensor dimensions are supported')
        if tt.elem_type != 1:
            raise ConversionError('ONNX tensors must use float32')
        return {'name': value.name, 'shape': dims}

    ins = [info(v) for v in inputs]
    outs = [info(v) for v in model.graph.output]
    edge = 320 if role == 'detector' else 112
    if len(ins) != 1 or ins[0]['shape'] != [1, 3, edge, edge]:
        raise ConversionError(f'{role} requires one NCHW input [1,3,{edge},{edge}]')
    if role == 'detector':
        semantics = {4: 'box_offsets', 2: 'background_face_scores', 10: 'five_landmark_offsets'}
        if sorted(o['shape'] for o in outs) != [[1, 4200, 2], [1, 4200, 4], [1, 4200, 10]]:
            raise ConversionError('Detector requires [1,4200,4], [1,4200,2], [1,4200,10] outputs')
        for o in outs:
            o['semantic'] = semantics[o['shape'][-1]]
        mean, std = [104, 117, 123], [1, 1, 1]
    else:
        if len(outs) != 1 or outs[0]['shape'] != [1, 512]:
            raise ConversionError('Recognizer requires one [1,512] embedding output')
        # Conservatively flag arithmetic before the first learned layer. This is
        # an audit aid, not a proof of a graph's preprocessing semantics.
        reachable = {ins[0]['name']}
        arithmetic = []
        for node in model.graph.node:
            if any(i in reachable for i in node.input):
                if node.op_type in ('Sub', 'Mul', 'Div', 'Add'):
                    arithmetic.append(node.op_type)
                if node.op_type not in ('Conv', 'Gemm', 'MatMul'):
                    reachable.update(node.output)
        if normalization == 'external' and arithmetic:
            raise ConversionError('Input arithmetic found; external normalization could duplicate it. Audit graph and select embedded only if it accepts raw RGB 0..255')
        outs[0]['semantic'] = 'embedding_requires_l2_normalization'
        mean, std = ([0, 0, 0], [1, 1, 1]) if normalization == 'embedded' else ([127.5] * 3, [127.5] * 3)
    return {'role': role, 'source': str(Path(path).resolve()), 'source_sha256': digest(path),
            'onnx_inputs': ins, 'onnx_outputs': outs, 'mean_values': [mean], 'std_values': [std],
            'input_contract': {'color': 'RGB', 'range': [0, 255], 'runtime_layout': 'query_backend_input_spec_NCHW_or_NHWC',
                               'normalization': normalization if role == 'recognizer' else 'external'},
            'semantic_validation': 'shape checked; numerical equivalence and accuracy require validation'}


def convert_one(record, output, factory, dataset=None):
    sdk = factory(verbose=False)
    try:
        def check(step, ret):
            if ret != 0:
                raise ConversionError(f'{step} failed: {ret}')
        check('config', sdk.config(mean_values=record['mean_values'], std_values=record['std_values'], target_platform='rv1126b'))
        check('load_onnx', sdk.load_onnx(model=record['source']))
        args = {'do_quantization': dataset is not None}
        if dataset is not None:
            args['dataset'] = str(dataset)
        check('build', sdk.build(**args))
        check('export_rknn', sdk.export_rknn(str(output)))
        if not output.is_file() or output.stat().st_size == 0:
            raise ConversionError('SDK reported success but exported no model')
    finally:
        sdk.release()


def run(args):
    paths = [Path(args.detector), Path(args.recognizer)]
    for p in paths:
        if not p.is_file():
            raise ConversionError(f'Model does not exist: {p}')
    records = [inspect_model(paths[0], 'detector', 'external'),
               inspect_model(paths[1], 'recognizer', args.recognizer_normalization)]
    dataset = Path(args.detector_dataset).resolve() if args.detector_dataset else None
    if dataset and (not dataset.is_file() or not dataset.read_text().strip()):
        raise ConversionError('Calibration dataset list must exist and be nonempty')
    manifest = {'schema_version': 1, 'target': 'rv1126b', 'status': 'plan', 'models': records,
                'detector_quantized': dataset is not None, 'recognizer_quantized': False}
    if dataset:
        manifest['calibration'] = {'list': str(dataset), 'sha256': digest(dataset), 'color': 'RGB', 'range': [0, 255]}
    if args.plan or args.inspect:
        print(json.dumps(manifest, indent=2))
        return
    try:
        from rknn.api import RKNN
        sdk_version = importlib.metadata.version('rknn-toolkit2')
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        raise ConversionError('Conversion requires a local RKNN Toolkit2 installation supporting RV1126B; --plan only requires onnx') from exc
    destination = Path(args.output_dir).resolve()
    if destination.exists():
        raise ConversionError('Output directory already exists; choose a new directory to avoid stale or overwritten artifacts')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.rknn-convert-', dir=destination.parent) as tmp:
        stage = Path(tmp) / 'models'
        stage.mkdir()
        for record in records:
            filename = record['role'] + '.rknn'
            output = stage / filename
            convert_one(record, output, RKNN, dataset if record['role'] == 'detector' else None)
            record['artifact'] = filename
            record['artifact_sha256'] = digest(output)
        manifest.update(status='converted_not_board_validated', toolkit_version=sdk_version)
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        os.rename(stage, destination)
    print(f'Created {destination / "manifest.json"}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--detector', required=True, help='Local RetinaFace_mobile320.onnx')
    p.add_argument('--recognizer', required=True, help='Local w600k_mbf.onnx')
    p.add_argument('--recognizer-normalization', choices=['embedded', 'external'], required=True,
                   help='Explicitly declare whether ONNX already normalizes raw RGB pixels')
    p.add_argument('--detector-dataset', help='Explicit RKNN calibration list; enables detector INT8 only')
    p.add_argument('--output-dir', default='models/face-rv1126b')
    p.add_argument('--plan', action='store_true')
    p.add_argument('--inspect', action='store_true')
    args = p.parse_args()
    try:
        run(args)
    except Exception as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
