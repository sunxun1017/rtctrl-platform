"""RV1126B Melo hybrid synthesis; graph-specific 44.1 kHz decoder contract."""
import ctypes
from pathlib import Path

RATE = 44100
HOP = 512
BUCKET = 256
HALO = 16
CORE = BUCKET - 2 * HALO


def scale_silence(samples, sample_rate=RATE):
    """Match sherpa 1.13.8 ScaleSilence(.2), once per complete generated batch."""
    import numpy as np
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    quiet = np.abs(x) <= np.float32(.01)
    edges = np.diff(np.concatenate(([False], quiet, [False])).astype(np.int8))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    threshold = int(sample_rate * .2)
    parts = []
    cursor = 0
    for start, end in zip(starts, ends):
        length = int(end - start)
        if length < threshold or (end == len(x) and length == threshold):
            continue
        count = int(np.float32(length) * np.float32(.2))
        parts.extend((x[cursor:start], x[start:start + count]))
        cursor = end
    parts.append(x[cursor:])
    return np.concatenate(parts)


def decode_chunks(latent, decoder):
    import numpy as np
    z = np.asarray(latent, dtype=np.float32)
    if z.ndim != 3 or z.shape[:2] != (1, 192) or not 0 < z.shape[2] <= 4000 or not np.isfinite(z).all():
        raise ValueError("Invalid Melo latent")
    length = z.shape[2]
    parts = []
    for start in range(0, length, CORE):
        end = min(length, start + CORE)
        left, right = max(0, start - HALO), min(length, end + HALO)
        count = right - left
        padded = np.zeros((1, 192, BUCKET), np.float32)
        padded[:, :, :count] = z[:, :, left:right]
        wave = np.asarray(decoder(padded, count), dtype=np.float32).reshape(-1)
        if len(wave) != BUCKET * HOP or not np.isfinite(wave).all():
            raise ValueError("Invalid Melo decoder output")
        parts.append(wave[(start - left) * HOP:(end - left) * HOP].copy())
    return np.concatenate(parts)


class MeloNpu:
    def __init__(self, root, sherpa, threads=2):
        root = Path(root)
        model = root / "vits-melo-tts-zh_en"
        hybrid = root / "melo-npu"
        self.decoder = NativeDecoder(hybrid)
        self.prefix = sherpa.OfflineTts(sherpa.OfflineTtsConfig(
            model=sherpa.OfflineTtsModelConfig(vits=sherpa.OfflineTtsVitsModelConfig(
                model=str(hybrid / "prefix.onnx"), tokens=str(model / "tokens.txt"),
                lexicon=str(model / "lexicon.txt"), dict_dir=str(model / "dict")), num_threads=threads),
            rule_fsts=",".join(str(model / name) for name in ("date.fst", "number.fst", "phone.fst")),
            max_num_sentences=1, silence_scale=1.0))

    def synthesize(self, text):
        import numpy as np
        parts, failures = [], []
        total = 0
        def callback(samples, progress):
            nonlocal total
            try:
                z = np.asarray(samples, dtype=np.float32)
                if z.size % 192:
                    raise ValueError("Invalid Melo prefix output")
                wave = decode_chunks(z.reshape(1, 192, -1), self.decoder)
                wave = scale_silence(wave)
                total += len(wave)
                if total > RATE * 45:
                    raise ValueError("Synthesized reply too long")
                parts.append(wave)
                return 1
            except Exception as error:
                failures.append(error)
                return 0
        self.prefix.generate(text, sid=0, speed=1.0, callback=callback)
        if failures:
            raise RuntimeError("Melo synthesis failed") from failures[0]
        if not parts:
            raise ValueError("Empty Melo synthesis")
        return np.concatenate(parts), RATE


class NativeDecoder:
    """Native ABI definition is paired with scripts/speech-npu/melo_decoder.cc."""
    def __init__(self, root):
        self.context = None
        self.library = ctypes.CDLL(str(Path(root) / "libmelo_decoder.so"))
        lib = self.library
        pointer = ctypes.POINTER(ctypes.c_float)
        lib.melo_decoder_create.argtypes = [ctypes.c_char_p]
        lib.melo_decoder_create.restype = ctypes.c_void_p
        lib.melo_decoder_run.argtypes = [ctypes.c_void_p, pointer, ctypes.c_uint, pointer]
        lib.melo_decoder_run.restype = ctypes.c_int
        lib.melo_decoder_destroy.argtypes = [ctypes.c_void_p]
        lib.melo_decoder_destroy.restype = ctypes.c_int
        lib.melo_decoder_error.argtypes = []
        lib.melo_decoder_error.restype = ctypes.c_char_p
        self.context = lib.melo_decoder_create(str(Path(root) / "decoder-masked-256.rknn").encode())
        if not self.context:
            raise RuntimeError("Melo decoder initialization failed")

    def __call__(self, latent, valid_length):
        import numpy as np
        data = np.ascontiguousarray(latent, dtype=np.float32)
        if data.shape != (1, 192, BUCKET) or not 0 < valid_length <= BUCKET or not self.context:
            raise ValueError("Invalid decoder input")
        output = np.empty(BUCKET * HOP, np.float32)
        pointer = ctypes.POINTER(ctypes.c_float)
        code = self.library.melo_decoder_run(self.context, data.ctypes.data_as(pointer),
                                            valid_length, output.ctypes.data_as(pointer))
        if code:
            raise RuntimeError("Melo NPU inference failed")
        return output

    def close(self):
        if self.context:
            self.library.melo_decoder_destroy(self.context)
            self.context = None

    def __del__(self):
        self.close()
