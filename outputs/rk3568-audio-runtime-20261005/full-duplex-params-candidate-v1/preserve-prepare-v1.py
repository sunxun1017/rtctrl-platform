import hashlib, json
from pathlib import Path
here=Path(__file__).resolve().parent
out=here/'prepare-attempt-v1'; out.mkdir()
p=here/'prepare-model.py'; (out/'prepare-snapshot.py').write_bytes(p.read_bytes())
record={'argv':['/usr/bin/python3','-B','outputs/rk3568-audio-runtime-20261005/full-duplex-params-candidate-v1/prepare-model.py'],
 'exit':1,'phase':'PREPARATION_NOT_COMPILER_OR_MODEL',
 'error':'ValueError: Expected one replacement: (void)caller; then asoc_simple_hw_params. Actual instrumentation entry and exit both matched.',
 'recording':'Original traceback observed in tool output; not captured into a direct stderr file.',
 'snapshot_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'partial_model_preserved':'model-v1'}
(out/'failure.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
