import logging
import pathlib
import runpy
import tempfile

from PySubtrans.Helpers.TestCases import LoggedTestCase


class TestBatchTranslateTerminologyPersistence(LoggedTestCase):
    """Regression tests for terminology map persistence in batch-translate."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        script_path = repo_root / 'scripts' / 'batch-translate.py'
        script_globals = runpy.run_path(str(script_path))
        cls.batch_processor_class = script_globals['BatchProcessor']

    def test_save_terminology_file_creates_missing_parent_directories(self):
        """Saving to a nested terminology path should create missing parent directories."""
        processor = self.batch_processor_class.__new__(self.batch_processor_class)
        processor.logger = logging.getLogger(__name__)

        with tempfile.TemporaryDirectory() as temp_dir:
            nested_path = pathlib.Path(temp_dir) / 'state' / 'terms' / 'map.txt'
            terminology_map = {
                'Dragon': 'Drache',
                'Hero': 'Held',
            }

            processor._save_terminology_file(str(nested_path), terminology_map)

            self.assertLoggedTrue("nested terminology file exists", nested_path.exists())
            saved_content = nested_path.read_text(encoding='utf-8')
            self.assertLoggedEqual(
                "saved terminology content",
                "Dragon::Drache\nHero::Held",
                saved_content,
            )
