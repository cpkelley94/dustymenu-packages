from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GameYobBatteryTests(unittest.TestCase):
    def test_display_queue_and_console_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "display-test"
            subprocess.run([
                "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-I" + str(ROOT / "packages/v3/compat/gameyob"),
                str(ROOT / "tests/gameyob_display_test.cpp"), "-o", str(binary),
            ], check=True, capture_output=True)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
            self.assertIn("Foreground frame callbacks", result.stdout)

    def test_battery_save_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            binary = work / "battery-test"
            subprocess.run([
                "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-I" + str(ROOT / "packages/v3/compat/gameyob"),
                str(ROOT / "tests/gameyob_battery_test.cpp"),
                "-Wl,--wrap=fopen,--wrap=fclose,--wrap=fwrite,--wrap=fread,--wrap=fsync",
                "-o", str(binary),
            ], check=True, capture_output=True)
            result = subprocess.run([str(binary), str(work)], check=True, capture_output=True, text=True)
            self.assertIn("Battery save creation", result.stdout)
