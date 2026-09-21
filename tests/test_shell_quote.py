import subprocess
import sys
import unittest
from kratos_agent.utils.shell_quote import (
    quote_powershell,
    quote_powershell_dq,
    quote_cmd,
    quote_posix,
    quote_fish,
    powershell_encoded,
    argv_for,
)

CASES = [
    ("powershell", "God of War"),
    ("powershell", "god's war"),
    ("powershell", "it's a \"test\" with $vars and `ticks`"),
    ("powershell", "காட் ஆஃப் வார்"),
    ("powershell", "100% & <done> | pipe ^ caret"),
    ("cmd", "God of War"),
    ("bash", "god's war && $(rm -rf /)"),
    ("fish", "it's"),
]

class TestShellQuote(unittest.TestCase):
    def test_quoting_functions(self):
        import shlex
        self.assertEqual(quote_powershell("god's war"), "'god''s war'")
        self.assertEqual(quote_powershell("காட் ஆஃப் வார்"), "'காட் ஆஃப் வார்'")
        self.assertEqual(quote_posix("god's war"), shlex.quote("god's war"))
        self.assertEqual(quote_cmd("God of War"), '"God of War"')

    @unittest.skipUnless(sys.platform == "win32", "PowerShell roundtrip requires Windows")
    def test_powershell_encoded_roundtrip(self):
        for shell, payload in CASES:
            if shell != "powershell":
                continue
            # Use Write-Output with single-quoted string (escaped)
            script = f"Write-Output {quote_powershell(payload)}"
            argv = powershell_encoded(script)
            proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, f"Failed for {payload}: {proc.stderr}")
            self.assertEqual(proc.stdout.strip(), payload)

if __name__ == "__main__":
    unittest.main()
