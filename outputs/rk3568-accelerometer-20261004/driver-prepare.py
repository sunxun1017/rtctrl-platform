#!/usr/bin/env python3
"""Prepare bounded sensor fixes from the locked clean source without editing it."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KERNEL = ROOT / "third_party/linux-rk3588"
COMMIT = "9f9e9d18574d0914c0d192a90c3babfe1fd63c95"
PATCH = ROOT / "platforms/rk3568/boards/aiot-3568pq/patches/0005-sensor-error-propagation.patch"
FILES = ["drivers/input/sensors/sensor-i2c.c", "drivers/input/sensors/sensor-dev.c",
         "drivers/input/sensors/accel/mxc6655xa.c"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError("Source pattern count changed: " + repr(old))
    return text.replace(old, new)


def run(argv):
    return subprocess.check_output(argv, text=True).strip()


def check_boundary(path):
    for parent in path.parents:
        if parent == ROOT:
            break
        if parent.is_symlink():
            raise ValueError("Refuse symlink output parent: " + str(parent))
    else:
        raise ValueError("Output outside repository")
    try:
        path.resolve().relative_to(ROOT)
    except ValueError:
        raise ValueError("Output outside repository") from None


def check_new(path):
    if path.exists() or path.is_symlink():
        raise ValueError("Refuse existing output: " + str(path))
    check_boundary(path)


def check_patch(path, generated):
    if path.is_symlink():
        raise ValueError("Refuse symlink patch: " + str(path))
    check_boundary(path)
    if not path.exists():
        return False
    if not path.is_file():
        raise ValueError("Existing patch must be an ordinary file: " + str(path))
    if path.read_bytes() != generated:
        raise ValueError("Existing patch differs from generated patch: " + str(path))
    return True


def fix_bus(text):
    text = replace(text, "\telse if(res == 0)\n\t\treturn -EBUSY;\n\telse\n\t\treturn res;",
                   "\treturn res < 0 ? res : -EIO;", 2)
    text = replace(text, "\treturn tmp[0];", "\tif (ret < 0)\n\t\treturn ret;\n\n\treturn (unsigned char)tmp[0];", 2)
    text = replace(text, "return (ret == 1) ? count : ret;",
                   "return ret == 1 ? count : (ret < 0 ? ret : -EIO);", 2)
    text = replace(text, "return (ret == num) ? 0 : ret;",
                   "return ret == num ? 0 : (ret < 0 ? ret : -EIO);", 2)
    return text


def fix_core(text):
    text = replace(text, "#include <linux/module.h>\n", "#include <linux/module.h>\n#include <linux/err.h>\n")
    text = replace(text, '\tsensor_class = class_create(THIS_MODULE, "sensor_class");\n',
                   '\tsensor_class = class_create(THIS_MODULE, "sensor_class");\n'
                   '\tif (IS_ERR(sensor_class)) {\n\t\tret = PTR_ERR(sensor_class);\n'
                   '\t\tsensor_class = NULL;\n\t\treturn ret;\n\t}\n')
    text = replace(text, '\t\tprintk(KERN_ERR "%s:Fail to creat accel class file\\n", __func__);\n\t\treturn ret;',
                   '\t\tprintk(KERN_ERR "%s:Fail to creat accel class file\\n", __func__);\n\t\tgoto err_destroy;')
    text = replace(text, '\t\tprintk(KERN_ERR "%s:Fail to creat gyro class file\\n", __func__);\n\t\treturn ret;\n\t}\n\n\treturn 0;\n}',
                   '\t\tprintk(KERN_ERR "%s:Fail to creat gyro class file\\n", __func__);\n\t\tgoto err_remove_accel;\n\t}\n\n\treturn 0;\n'
                   '\nerr_remove_accel:\n\tclass_remove_file(sensor_class, &class_attr_accel_calibration);\n'
                   'err_destroy:\n\tclass_destroy(sensor_class);\n\tsensor_class = NULL;\n\treturn ret;\n}')
    text = replace(text, '\t\tfor (i = 0; i < 3; i++) {\n\t\t\tresult = sensor_rx_data(client, &temp, 1);\n\t\t\t*value = temp;\n\t\t\tif (!result)\n\t\t\t\tbreak;',
                   '\t\tfor (i = 0; i < 3; i++) {\n\t\t\ttemp = sensor->ops->id_reg;\n'
                   '\t\t\tresult = sensor_rx_data(client, &temp, 1);\n\t\t\tif (!result) {\n'
                   '\t\t\t\t*value = (unsigned char)temp;\n\t\t\t\tbreak;\n\t\t\t}')
    text = replace(text, 'sensor->ops->id_data);\n\t\t\tresult = -1;',
                   'sensor->ops->id_data);\n\t\t\tresult = -ENODEV;')
    text = replace(text, '\t\tresult = -2;\n\t\tgoto error;', '\t\tgoto error;', 2)
    text = replace(text, '\tsensor_probe(client, devid);\n',
                   '\tresult = sensor_probe(client, devid);\n\tif (result) {\n'
                   '\t\tsensor_ops[ops->id_i2c] = NULL;\n\t\ti2c_set_clientdata(client, NULL);\n\t}\n')
    text = replace(text, '\tsensor_class_init();\n\n\treturn 0;', '\treturn sensor_class_init();')
    return text


def fix_mxc(text):
    text = replace(text, '\tint result = 0;\n\n\tsensor->ops->ctrl_data = sensor_read_reg(client, sensor->ops->ctrl_reg);\n',
                   '\tint result = 0;\n\tint ctrl_data;\n\n'
                   '\tctrl_data = sensor_read_reg(client, sensor->ops->ctrl_reg);\n'
                   '\tif (ctrl_data < 0)\n\t\treturn ctrl_data;\n')
    text = replace(text, '\t\tsensor->ops->ctrl_data &= ~MXC6655_POWER_DOWN;', '\t\tctrl_data &= ~MXC6655_POWER_DOWN;')
    text = replace(text, '\t\tsensor->ops->ctrl_data |= MXC6655_POWER_DOWN;', '\t\tctrl_data |= MXC6655_POWER_DOWN;')
    text = replace(text, '\t\t\t\t  sensor->ops->ctrl_data);', '\t\t\t\t  ctrl_data);')
    text = replace(text, '\t\tdev_err(&client->dev, "%s:fail to active sensor\\n", __func__);\n',
                   '\t\tdev_err(&client->dev, "%s:fail to active sensor\\n", __func__);\n'
                   '\telse\n\t\tsensor->ops->ctrl_data = ctrl_data;\n')
    text = replace(text, '\tstatus = sensor_read_reg(client, MXC6655_INT_MASK1);\n',
                   '\tstatus = sensor_read_reg(client, MXC6655_INT_MASK1);\n\tif (status < 0)\n\t\treturn status;\n')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        parser.error("version must be vN")
    if run(["git", "-C", str(KERNEL), "rev-parse", "HEAD"]) != COMMIT:
        raise ValueError("Unexpected kernel source commit")
    if run(["git", "-C", str(KERNEL), "status", "--porcelain"]):
        raise ValueError("Kernel source must be clean")
    destination = HERE / ("driver-source-" + args.version)
    check_new(destination)
    source = [KERNEL / relative for relative in FILES]
    original = [path.read_text() for path in source]
    candidate = [fix_bus(original[0]), fix_core(original[1]), fix_mxc(original[2])]
    patch = ""
    for relative, before, after in zip(FILES, original, candidate):
        patch += "diff --git a/" + relative + " b/" + relative + "\n"
        patch += "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                             fromfile="a/" + relative, tofile="b/" + relative))
    patch_bytes = patch.encode("utf-8")
    reused_patch = check_patch(PATCH, patch_bytes)
    destination.mkdir()
    for relative, text in zip(FILES, candidate):
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    if not reused_patch:
        with PATCH.open("xb") as stream:
            stream.write(patch_bytes)
    record = {"source_commit": COMMIT, "source_clean": True,
              "sources": {relative: {"original_sha256": sha(path), "candidate_sha256": sha(destination / relative)}
                          for relative, path in zip(FILES, source)},
              "patch_path": str(PATCH.relative_to(ROOT)), "patch_sha256": sha(PATCH),
              "existing_identical_patch_reused": reused_patch,
              "board_tested": False, "unload_lifecycle_fixed": False,
              "bounded_scope": "I2C errors, ID/init/probe propagation, class creation failure cleanup; default OFF unchanged"}
    (destination / "driver-source-manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
