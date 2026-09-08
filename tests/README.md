# Test suites

Activate the project virtual environment before running tests.

- `python tests/unit_tests.py`: fast checks using test-double providers, fake media metadata, and simulated clocks. Includes GUI commands, subtitle file round trips, and core translation/transcription logic.
- `python tests/integration_tests.py`: all concrete-provider tests, provider registration/import checks, real FFmpeg/ffprobe chunking, and Qt worker/dialog lifecycle checks in `tests/GuiIntegrationTests/`. API responses are mocked; no live API requests or model-weight loading are performed.

The unit runner rejects imports of `PySubtrans.Providers` and `PySubtrans.Transcription.Providers`, including modules already loaded before the runner. This guard remains active for the unit-test process. Test doubles register through the existing subclass registries; production registration is unchanged. Run integration tests in a separate process.

Integration tests report skips when optional SDKs, FFmpeg/ffprobe, or PySide6 GUI dependencies are absent. Install the relevant dependencies to exercise those checks; a successful run with skips does not validate those integrations. SDK import errors when installed fail the suite.

All `scripts/makedistro*` scripts and `scripts/publish_package.py` run both suites before building. A failing suite stops the release workflow, including publishing with `--skip-upload`. Optional dependency skips remain allowed so platform-specific builds do not require every optional backend.

Keep concrete-provider imports and subprocess checks in `tests/IntegrationTests/`. Transcription unit fixtures bypass executable availability checks and supply fake media metadata. Pure helpers may remain in unit coverage when they do not import concrete providers.
