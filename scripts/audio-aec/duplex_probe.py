"""Explicit local full-duplex probe: fixed reply, real listener, no cloud/audio files."""
import argparse
import audioop
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
    ap.add_argument("--digital-loopback",action="store_true",help="No microphone or speaker; inject fixed playback PCM into ASR")
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
    # Derive playback text locally from the public fixture, before recording.
    # This is a fixture transcript only; no microphone audio is retained here.
    reference_asr=StreamingAsr(config["local_speech_root"])
    try:
        reference_asr.exchange(3)
        reference_pcm,_=audioop.ratecv(pcm,2,1,rate,16000,None)
        for pos in range(0,len(reference_pcm),1920):
            reference_asr.exchange(1,reference_pcm[pos:pos+1920])
        reference_text=reference_asr.exchange(2).get("text","")
        if not reference_text:raise RuntimeError("Fixture transcript unavailable")
    finally:
        reference_asr.close()
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
            self._emit(generation,dict(type="llm",text=reference_text))
            self._emit(generation,dict(type="tts",state="start"))
            self._emit(generation,dict(type="tts",state="sentence_start",text=reference_text))
            self._emit(generation,PcmAudio(pcm,rate))
            self._emit(generation,dict(type="tts",state="stop"))
    class MemoryAudio:
        """Deliberately simulate AEC failure, without opening audio devices."""
        def __init__(self,*args,**kwargs):
            self.callback=None;self.until=0.;self.first_write_monotonic=0.;self.pending=bytearray();self.due=0.
        def configure_output(self,rate):pass
        def start(self,callback):self.callback=callback
        def stop_capture(self):self.callback=None
        def pause_capture(self):self.callback=None
        def interrupt(self):self.until=0.;self.pending.clear()
        def stop(self):self.stop_capture();self.interrupt()
        def playback_busy(self):return time.monotonic()<self.until
        def play_pcm(self,audio):
            data,_=audioop.ratecv(audio.data,2,1,audio.sample_rate,16000,None)
            self.pending.extend(data);self.first_write_monotonic=time.monotonic()
            self.until=self.first_write_monotonic+len(data)/32000
        def feed(self):
            if self.callback and time.monotonic()>=self.due:
                data=bytes(self.pending[:1920]);del self.pending[:1920]
                self.callback(data.ljust(1920,b"\x00"));self.due=time.monotonic()+.06
    core=Companion(config,MemoryAudio if args.digital_loopback else AudioIO,OpusCodec,LocalOnly)
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
            if args.digital_loopback:core.audio.feed()
            state=core.snapshot()
            if state["state"]=="error":raise RuntimeError(state["error"])
            if state["state"]=="speaking" and state["input_state"] in ("waiting_speech","recognizing"):
                report["input_seen_while_speaking"]=True
            time.sleep(.01 if args.digital_loopback else .05)
    finally:
        report["capture_peak"]=core.snapshot()["metrics"]["capture_peak_amplitude"]
        report["echo_suspicions"]=core.snapshot()["metrics"].get("echo_suspicions",0)
        report["pending_utterances"]=core.snapshot()["pending_utterances"]
        core.close()
    report["capture_stopped"]=True
    report["digital_loopback"]=args.digital_loopback
    print(json.dumps(report),flush=True)

if __name__=="__main__":main()
