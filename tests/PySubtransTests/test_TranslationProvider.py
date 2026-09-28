from PySubtrans.Helpers.TestCases import DummyProvider, LoggedTestCase
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.ModelList import ModelList, ModelListState
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.TranslationProvider import TranslationProvider


class CountingProvider(TranslationProvider):
    """Provider that counts model lookups so caching can be observed."""
    name = "Counting Provider"

    def __init__(self):
        super().__init__(self.name, SettingsType({'model': 'model-a'}))
        self.lookup_count = 0

    def GetAvailableModels(self) -> list[str]:
        self.lookup_count += 1
        return ['model-a', 'model-b']


class RaisingProvider(TranslationProvider):
    """Provider whose model lookup raises, to check failures become state."""
    name = "Raising Provider"

    def __init__(self):
        super().__init__(self.name, SettingsType({'model': 'model-a'}))
        self.lookup_count = 0

    def GetAvailableModels(self) -> list[str]:
        self.lookup_count += 1
        raise RuntimeError("lookup failed")


class TranslationProviderTests(LoggedTestCase):

    def test_create_provider_case_insensitive(self):
        """create_provider accepts a non-canonical provider name casing"""
        provider = TranslationProvider.create_provider("dummy provider", SettingsType())
        self.assertLoggedIsInstance("case-insensitive lookup returns DummyProvider", provider, DummyProvider)

    @skip_if_debugger_attached
    def test_create_provider_unknown_raises(self):
        """create_provider raises ValueError for an unregistered provider name"""
        with self.assertRaises(ValueError) as context:
            TranslationProvider.create_provider("no such provider", SettingsType())
        log_input_expected_error("no such provider", ValueError, context.exception)

    def test_get_provider_normalizes_name(self):
        """get_provider normalizes options.provider to the canonical registered name and applies settings"""
        options = Options({
            'provider': 'dummy provider',
            'provider_settings': {
                'Dummy Provider': SettingsType({'model': 'test-model-xyz'})
            },
            'target_language': 'French',
        })

        provider = TranslationProvider.get_provider(options)

        self.assertLoggedIsInstance("get_provider returns DummyProvider", provider, DummyProvider)
        self.assertLoggedEqual("options.provider normalized to canonical name", "Dummy Provider", options.provider)
        self.assertLoggedEqual("provider received settings from options", "test-model-xyz", provider.settings.get_str('model'))

    def test_eager_lookup_resolves_and_caches(self):
        """The first eager access resolves the list, and it is not fetched again."""
        provider = CountingProvider()

        self.assertLoggedEqual("state before lookup", ModelListState.Unloaded, provider.model_list.state)
        self.assertLoggedEqual("models fetched on demand", ['model-a', 'model-b'], provider.available_models)
        self.assertLoggedEqual("lookup performed", 1, provider.lookup_count)
        self.assertLoggedEqual("state after lookup", ModelListState.Loaded, provider.model_list.state)

        self.assertLoggedEqual("second access returns cached models", ['model-a', 'model-b'], provider.available_models)
        self.assertLoggedEqual("lookup count unchanged", 1, provider.lookup_count)

    def test_reset_returns_to_unloaded(self):
        """Resetting discards the list and allows another lookup."""
        provider = CountingProvider()
        provider.available_models

        provider.ResetAvailableModels()

        self.assertLoggedEqual("state after reset", ModelListState.Unloaded, provider.model_list.state)
        self.assertLoggedEqual("lookup after reset refetches", ['model-a', 'model-b'], provider.available_models)
        self.assertLoggedEqual("lookup count after reset", 2, provider.lookup_count)

    def test_begin_load_defers_eager_fetch(self):
        """While a load is in progress the known models are returned without fetching."""
        provider = CountingProvider()

        provider.model_list.BeginLoad()

        self.assertLoggedEqual("state while loading", ModelListState.Loading, provider.model_list.state)
        self.assertLoggedEqual("no models known yet", [], provider.available_models)
        self.assertLoggedEqual("provider did not fetch", 0, provider.lookup_count)

    def test_resolve_records_loaded_state(self):
        """Resolving runs the lookup and records the loaded state."""
        provider = CountingProvider()
        provider.model_list.BeginLoad()

        provider.model_list.Resolve()

        self.assertLoggedEqual("state after resolve", ModelListState.Loaded, provider.model_list.state)
        self.assertLoggedEqual("models available", ['model-a', 'model-b'], provider.available_models)
        self.assertLoggedEqual("lookup performed", 1, provider.lookup_count)

    def test_cancel_returns_to_unloaded(self):
        """Cancelling an in-progress load returns to unloaded so it can be retried."""
        provider = CountingProvider()
        provider.model_list.BeginLoad()

        provider.model_list.Cancel()

        self.assertLoggedEqual("state after cancel", ModelListState.Unloaded, provider.model_list.state)
        self.assertLoggedEqual("eager access fetches again", ['model-a', 'model-b'], provider.available_models)
        self.assertLoggedEqual("lookup performed after cancel", 1, provider.lookup_count)

    def test_failed_lookup_is_recorded_as_state(self):
        """A failed lookup is recorded as state rather than raised, and stays retryable."""
        provider = RaisingProvider()

        models = provider.available_models

        self.assertLoggedEqual("failed lookup returns no models", [], models)
        self.assertLoggedEqual("state after failure", ModelListState.Failed, provider.model_list.state)
        self.assertLoggedIsNotNone("error recorded", provider.model_list.error)

        provider.available_models
        self.assertLoggedEqual("lookup retried", 2, provider.lookup_count)

    def test_superseded_request_is_not_recorded(self):
        """A lookup that has been superseded cannot record its result over a newer one."""
        models = ['new']
        model_list = ModelList(lambda: list(models))

        stale_request = model_list.BeginLoad()
        current_request = model_list.BeginLoad()

        self.assertLoggedTrue("newer request recorded", model_list.Resolve(current_request))
        self.assertLoggedEqual("newer models recorded", ['new'], model_list.models)

        models = ['stale']
        self.assertLoggedFalse("stale request discarded", model_list.Resolve(stale_request))
        self.assertLoggedEqual("newer result retained", ['new'], model_list.models)

    def test_cancelled_request_is_not_recorded(self):
        """A cancelled lookup cannot record its result, and the list stays retryable."""
        model_list = ModelList(lambda: ['late'])

        request = model_list.BeginLoad()
        model_list.Cancel()

        self.assertLoggedFalse("cancelled request discarded", model_list.Resolve(request))
        self.assertLoggedEqual("state after cancel", ModelListState.Unloaded, model_list.state)
        self.assertLoggedEqual("no models recorded", [], model_list.known)
