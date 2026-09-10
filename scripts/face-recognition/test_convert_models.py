import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as N
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('convert_models', Path(__file__).with_name('convert_models.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def value(name, shape):
    return N(name=name, type=N(tensor_type=N(elem_type=1, shape=N(dim=[N(dim_value=d) for d in shape]))))


def onnx(role='detector', arithmetic=False):
    dims = [[1, 4200, 10], [1, 4200, 4], [1, 4200, 2]] if role == 'detector' else [[1, 512]]
    nodes = [N(op_type='Sub', input=['in'], output=['normalized'])] if arithmetic else []
    graph = N(initializer=[], input=[value('in', [1, 3, 320, 320] if role == 'detector' else [1, 3, 112, 112])], output=[value(str(i), s) for i, s in enumerate(dims)], node=nodes)
    return N(load=lambda *a, **k: N(graph=graph), checker=N(check_model=lambda _: None))


class SDK:
    def __init__(self, fail=None):
        self.fail = fail
        self.released = False
    def config(self, **kw):
        return 1 if self.fail == 'config' else 0
    def load_onnx(self, **kw):
        return 1 if self.fail == 'load' else 0
    def build(self, **kw):
        return 1 if self.fail == 'build' else 0
    def export_rknn(self, path):
        Path(path).write_bytes(b'model')
        return 1 if self.fail == 'export' else 0
    def release(self):
        self.released = True


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'input.onnx'
        self.path.write_bytes(b'onnx')

    def test_detector_output_order_and_hash(self):
        r = m.inspect_model(self.path, 'detector', 'external', onnx())
        self.assertEqual(r['onnx_outputs'][0]['semantic'], 'five_landmark_offsets')
        self.assertEqual(r['source_sha256'], m.digest(self.path))

    def test_reject_duplicate_normalization(self):
        with self.assertRaises(m.ConversionError):
            m.inspect_model(self.path, 'recognizer', 'external', onnx('recognizer', True))
        r = m.inspect_model(self.path, 'recognizer', 'embedded', onnx('recognizer', True))
        self.assertEqual(r['mean_values'], [[0, 0, 0]])

    def test_bad_shape(self):
        fake = onnx()
        fake.load().graph.input[0].type.tensor_type.shape.dim[2].dim_value = 0
        with self.assertRaises(m.ConversionError):
            m.inspect_model(self.path, 'detector', 'external', fake)

    def test_release_every_sdk_error(self):
        r = m.inspect_model(self.path, 'detector', 'external', onnx())
        for step in ['config', 'load', 'build', 'export', None]:
            sdk = SDK(step)
            if step:
                with self.assertRaises(m.ConversionError):
                    m.convert_one(r, Path(self.tmp.name) / 'out', lambda **_: sdk)
            else:
                m.convert_one(r, Path(self.tmp.name) / 'out', lambda **_: sdk)
            self.assertTrue(sdk.released)

    def test_publish_manifest_only_after_both_succeed(self):
        args = N(detector=str(self.path), recognizer=str(self.path), recognizer_normalization='external', detector_dataset=None, plan=False, inspect=False, output_dir=str(Path(self.tmp.name) / 'published'))
        records = {r: m.inspect_model(self.path, r, 'external', onnx(r)) for r in ['detector', 'recognizer']}
        fake_api = N(RKNN=lambda **_: SDK())
        with patch.object(m, 'inspect_model', side_effect=lambda p, r, n: dict(records[r])), patch.dict('sys.modules', {'rknn': N(), 'rknn.api': fake_api}), patch.object(m.importlib.metadata, 'version', return_value='test'):
            with patch.object(m, 'convert_one', side_effect=m.ConversionError('failed')):
                with self.assertRaises(m.ConversionError):
                    m.run(args)
                self.assertFalse(Path(args.output_dir).exists())
            m.run(args)
            manifest = json.loads((Path(args.output_dir) / 'manifest.json').read_text())
            self.assertEqual(manifest['toolkit_version'], 'test')
            self.assertEqual(manifest['models'][0]['artifact_sha256'], m.digest(Path(args.output_dir) / 'detector.rknn'))
            with self.assertRaises(m.ConversionError):
                m.run(args)


if __name__ == '__main__':
    unittest.main()
