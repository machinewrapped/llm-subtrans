import os
import subprocess
import sys

import PySubtrans
from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestProviderImportCost(LoggedTestCase):
    def test_provider_imports_stay_light(self):
        """Registering providers must not pull heavy optional SDKs."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(PySubtrans.__file__)))
        script = (
            "import sys; "
            "from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider; "
            "names = sorted(TranscriptionProvider.get_providers()); "
            "heavy = [m for m in ('torch', 'qwen_asr', 'google', 'google.genai') if m in sys.modules]; "
            "assert not heavy, heavy; "
            "print('light ok: ' + ','.join(names))"
        )
        result = subprocess.run([sys.executable, '-c', script], cwd=repo_root,
                                capture_output=True, text=True, timeout=180)

        self.assertLoggedEqual("light imports", 0, result.returncode,
                               input_value=(result.stderr or "")[-2000:])


