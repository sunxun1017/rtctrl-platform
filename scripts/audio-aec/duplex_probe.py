"""Explicit local full-duplex probe: fixed reply, real listener, no cloud/audio files."""
import argparse
import json
import sys
import time
import wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from apps.companion.audio import AudioIO, OpusCodec, PcmAudio
from apps.companion.core import Companion
from apps.companion.config import validate
from apps.companion.local_voice import LocalVoiceTransport
from apps.companion.streaming_asr import StreamingAsr
TARGET="今天天气不错我想出去散步"


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-local-test",action="store_true",required=True)
    ap.add_argument("--aes",action="store_true")
    ap.add_argument("--duration",type=int,choices=(10,15),default=10)
    ap.add_argument("--config",required=True)
    ap.add_argument("--wav",required=True)
    args=ap.parse_args()
    cfg=json.loads(Path(args.config).read_text());cfg["full_duplex"]=True;cfg["aec_enable_aes"]=args.aes
    config=validate(cfg)
    with wave.open(args.wav) as w:
        if w.getnchannels()!=1 or w.getsampwidth()!=2:raise ValueError("Invalid fixture")
        rate=w.getframerate();pcm=w.readframes(min(w.getnframes(),rate*8))
    report=dict(onset_events=0,partial_events=0,partial_while_playing=0,best_target_distance=len(TARGET),first_partial_after_play_s=None,final_events=0,final_while_playing=0,target_exact_matches=0,
                reply_requests=0,input_seen_while_speaking=False,errors=[])
    core=None
    class LocalOnly(LocalVoiceTransport):
        def connect(self):
            self._asr_stream=StreamingAsr(self.config["local_speech_root"])
            self._codec=OpusCodec();self._closed=False
        def _emit(self,generation,value):
            if self._active(generation) and isinstance(value,dict):
                kind=value.get("type")
                if kind=="duplex_started":report["onset_events"]+=1
                if kind=="duplex_partial":
                    report["partial_events"]+=1
                    if core and core.audio and core.audio.playback_busy():
                        report["partial_while_playing"]+=1
                    if report["first_partial_after_play_s"] is None and core and core.audio:
                        report["first_partial_after_play_s"]=round(time.monotonic()-core.audio.first_write_monotonic,3)
                if kind in ("duplex_partial","duplex_final"):
                    recognized="".join(c for c in value.get("text","") if c.isalnum())
                    previous=[0]*(len(recognized)+1)
                    for i,wanted in enumerate(TARGET,1):
                        current=[i]
                        for j,got in enumerate(recognized,1):
                            current.append(min(previous[j]+1,current[j-1]+1,previous[j-1]+(wanted!=got)))
                        previous=current
                    report["best_target_distance"]=min(report["best_target_distance"],min(previous))
                if kind=="duplex_final":
                    report["final_events"]+=1
                    if core and core.audio and core.audio.playback_busy():report["final_while_playing"]+=1
                    text="".join(c for c in value.get("text","") if c.isalnum())
                    report["target_exact_matches"]+=text.count(TARGET)
            super()._emit(generation,value)
        def _run(self,generation,unused,recognized_text=None):
            report["reply_requests"]+=1
            if report["reply_requests"]!=1:return
            self._emit(generation,dict(type="tts",state="start"))
            self._emit(generation,PcmAudio(pcm,rate))
            self._emit(generation,dict(type="tts",state="stop"))
    core=Companion(config,AudioIO,OpusCodec,LocalOnly)
    core.start()
    try:
        core.action("connect")
        deadline=time.monotonic()+12
        while not core.snapshot()["connected"]:
            if time.monotonic()>deadline:raise RuntimeError("Connect timeout")
            time.sleep(.05)
        core.action("unmute");core.action("continuous")
        started=time.monotonic()
        core.post("message",dict(type="duplex_final",text="固定本地测试"),core.generation)
        while time.monotonic()-started<args.duration:
            core.action("keep_listening")
            state=core.snapshot()
            if state["state"]=="error":raise RuntimeError(state["error"])
            if state["state"]=="speaking" and state["input_state"] in ("waiting_speech","recognizing"):
                report["input_seen_while_speaking"]=True
            time.sleep(.05)
    finally:
        report["capture_peak"]=core.snapshot()["metrics"]["capture_peak_amplitude"]
        core.close()
    report["capture_stopped"]=True
    print(json.dumps(report),flush=True)

if __name__=="__main__":main()
