#!/usr/bin/env python3
"""Load the frozen exact-context replay helper without executing its main."""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("frozen_c1_replay",Path(__file__).with_name("freeze-c1.py"))
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
strict_replay=module.replay
