import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ConfigEncodingTests(unittest.TestCase):
    def test_loads_utf8_config_when_process_locale_is_ascii(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_bytes(
                bytes.fromhex(
                    "7b2273797374656d5f70726f6d7074223a202246697820e2809420"
                    "70756e6374756174696f6e227d"
                )
            )
            script = """
import sys
from pathlib import Path
from cmdc import config

config.CONFIG_DIR = Path(sys.argv[1]).parent
config.CONFIG_PATH = Path(sys.argv[1])
loaded = config.load()
assert loaded["system_prompt"].encode("utf-8").hex() == "46697820e280942070756e6374756174696f6e"
"""
            environment = os.environ.copy()
            environment.update(PYTHONUTF8="0", LC_ALL="C", LANG="C")
            result = subprocess.run(
                [sys.executable, "-c", script, str(config_path)],
                capture_output=True,
                env=environment,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_saves_utf8_config_privately_when_process_locale_is_ascii(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            script = """
import json
import stat
import sys
from pathlib import Path
from cmdc import config

config.CONFIG_DIR = Path(sys.argv[1]).parent
config.CONFIG_PATH = Path(sys.argv[1])
saved = {"system_prompt": "Fix — punctuation", "api_keys": {"test": "secret"}}
config.save(saved)
raw = config.CONFIG_PATH.read_bytes()
assert json.loads(raw.decode("utf-8")) == saved
assert stat.S_IMODE(config.CONFIG_PATH.stat().st_mode) == 0o600
"""
            environment = os.environ.copy()
            environment.update(PYTHONUTF8="0", LC_ALL="C", LANG="C")
            result = subprocess.run(
                [sys.executable, "-c", script, str(config_path)],
                capture_output=True,
                env=environment,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
