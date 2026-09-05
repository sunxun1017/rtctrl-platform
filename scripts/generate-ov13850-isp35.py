#!/usr/bin/env python3
"""Generate a LOCAL EXPERIMENT, never a calibrated/product IQ. No SDK writes."""
import argparse, copy, hashlib, json, subprocess
from pathlib import Path

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rev(p):
    return subprocess.check_output(["git", "-C", str(p), "rev-parse", "HEAD"], text=True).strip()
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdk-root", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--wb", choices=["unity", "borrowed-auto"], default="unity")
    a=ap.parse_args(); sdk=a.sdk_root.resolve(); out=a.out_dir.resolve()
    if out==sdk or sdk in out.parents: ap.error("output must be outside vendor SDK")
    iq=sdk/"external/camera_engine_rkaiq/rkaiq/iqfiles"
    old=iq/"isp21/ov13850_ZC-OV13850R2A-V1_Largan-50064B31.json"
    base=iq/"isp35/common/imx335_ATKMC_V1_3.json"
    o=json.loads(old.read_text()); d=json.loads(base.read_text()); s=d["sensor_calib"]
    assert o["sensor_calib"]["Gain2Reg"]["GainRange"]==[1,15.5,16,0,1,16,248]
    assert len(d["main_scene"])==1 and len(d["main_scene"][0]["sub_scene"])==1
    s["resolution"]={"width":2112,"height":1568}
    s["Gain2Reg"].update(copy.deepcopy(o["sensor_calib"]["Gain2Reg"]))
    s["Time2Reg"]={"fCoeff":[0,0,1,0.5]}
    s["CISGainSet"]=copy.deepcopy(o["sensor_calib"]["CISGainSet"])
    s["CISGainSet"]["CISIspDgainRange"]={"Min":1,"Max":1}
    s["CISTimeSet"]["Linear"]={"CISTimeRegMin":2,"CISLinTimeRegMaxFac":{"fCoeff":[1,16]},"CISTimeRegOdevity":{"fCoeff":[1,0]},"CISTimeLinePerReg":1}
    s["CISHdrSet"]["hdr_en"]=0
    for h in s["CISTimeSet"]["Hdr"]:
        h["CISTimeRegMin"]={"Coeff":[2,2,2]}
        h["CISTimeRegOdevity"]={"fCoeff":[1,0]}
    for v in s["CISDcgSet"].values(): v.update(support_en=0,dcg_ratio=1,sync_switch=0)
    s["CISExpUpdate"]["Linear"]={"time_update":2,"gain_update":2,"dcg_update":0}
    s["CISMinFps"]=30; s["CISFlip"]=0
    s["iso_list"]=[50*2**i for i in range(13)]
    scene=d["main_scene"][0]["sub_scene"][0]["scene_isp35"]
    reasons={}
    keep={"demosaic":"Borrowed demosaic; required Bayer reconstruction, not tuned", "gamma":"Borrowed display curve, not measured response", "gain":"ISP gain path retained; AE ISP gain bounded to unity", "csm":"Explicit BT.601 full-range matrix", "cgc":"Full-range conversion settings"}
    special={"ae_calib","wb","af_calib","colorAsGrey"}
    for k,v in scene.items():
        if k in special: continue
        ctrl=v if "en" in v else v.get("tunning",v)
        if "en" not in ctrl: raise ValueError("unreviewed module "+k)
        ctrl["en"]=int(k in keep); ctrl["bypass"]=0
        reasons[k]=keep.get(k,"Disabled: foreign sensor/lens or optional processing; retained payload for parser structure only")
    scene["csm"]["opMode"]="RK_AIQ_OP_MODE_MANUAL"
    scene["cgc"]["opMode"]="RK_AIQ_OP_MODE_MANUAL"
    wb=scene["wb"]["wbGainCtrl"]
    wb["opMode"]="RK_AIQ_OP_MODE_MANUAL" if a.wb=="unity" else "RK_AIQ_OP_MODE_AUTO"
    wb["manualPara"]["cfg"]["manual_wbgain"]=[1,1,1,1]
    scene["wb"]["awbStats"]["hw_awbCfg_lsc_en"]=0
    reasons["wb"]="Unity manual WB for isolation" if a.wb=="unity" else "UNVALIDATED IMX335 AWB regions/illuminants: functional experiment only"
    ae=scene["ae_calib"]
    ae["commCtrl"]["sw_aeT_opt_mode"]="RK_AIQ_OP_MODE_AUTO"
    ae["commCtrl"]["frmRate"]={"sw_aeT_frmRate_mode":"ae_frmRate_fix_mode","sw_aeT_frmRate_val":30}
    ae["commCtrl"]["envLvCalib"]["sw_aeT_envCalib_en"]=0
    ae["linAeCtrl"]["route"]={"sw_aeT_route_len":4,"sw_aeT_time_dot":[2/49920,0.01,0.03,0.03],"sw_aeT_gain_dot":[1,1,1,15.5],"sw_aeT_ispDGain_dot":[1]*4,"sw_aeT_pIrisGain_dot":[512]*4}
    ae["linAeCtrl"]["initExp"]={"sw_aeT_initTime_val":0.003,"sw_aeT_initGain_val":1,"sw_aeT_initIspDGain_val":1}
    reasons["ae_calib"]="Fixed 30fps, <=30ms route, 1..15.5 analog gain, sensor/ISP digital gain unity; borrowed AE targets/damping uncalibrated"
    reasons["af_calib"]="Disabled via sys_static_cfg; no verified actuator"
    reasons["colorAsGrey"]="Inherited off; color output"
    d["sys_static_cfg"]["algoSwitch"].update(enable=1,disable_algos=["DISABLE_AF"],disable_algos_len=1)
    out.mkdir(parents=True,exist_ok=True)
    target=out/"ov13850_ATK-MCOV13850_default.json"
    if target.exists(): raise FileExistsError(target)
    target.write_text(json.dumps(d,indent=2)+"\n")
    sources=[old,base,sdk/"external/camera_engine_rkaiq/rkaiq/include/iq_parser_v2/sensorinfo_head.h",sdk/"external/camera_engine_rkaiq/rkaiq/uAPI2/rk_aiq_user_api2_custom_ae.c",sdk/"external/camera_engine_rkaiq/rkaiq/hwi_c/aiq_sensorHw.c"]
    report={"status":"EXPERIMENTAL_NOT_CALIBRATED","wb":a.wb,"sdk_rkaiq_commit":rev(sdk/"external/camera_engine_rkaiq"),"inputs":[{"path":str(p),"sha256":sha(p)} for p in sources],"output_sha256":sha(target),"modules":reasons,"limitations":["module_calib lens values inherited placeholders, NOT physical lens identity; env calibration and AF disabled", "2-frame time/gain delays unmeasured", "HTS/PLL physical units not confirmed by datasheet; AIQ uses reported frame interval", "BLC disabled pending dark RAW measurement; black pedestal can bias AE/AWB", "JSON checks are NOT runtime parsing or image calibration"],"command":__import__("sys").argv}
    (out/"provenance.json").write_text(json.dumps(report,indent=2)+"\n")
    print(target); print("EXPERIMENT ONLY; runtime parser validation pending")
if __name__=="__main__": main()

