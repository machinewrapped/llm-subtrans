import logging
import time
from typing import cast

from GuiSubtrans.Command import Command
from PySubtrans.Helpers.ImportGuard import UsingOriginalImport
from PySubtrans.Helpers.Localization import _
from PySubtrans.Options import Options
from PySubtrans.TranslationProvider import TranslationProvider


class WarmupTranslationProvidersCommand(Command):
    """Warm the active and previously configured provider libraries in the background."""

    def __init__(self, options : Options, active_provider : TranslationProvider|None = None,
                 warm_configured_providers : bool = False):
        super().__init__()
        self.is_blocking = False
        self.skip_undo = True
        self.mark_project_dirty = False
        self.updates_datamodel = False
        self.warmed_providers : dict[str, TranslationProvider] = {}
        self.options = Options(options)
        self.active_provider = active_provider
        self.warm_configured_providers = warm_configured_providers

    def execute(self) -> bool:
        """Warm configured providers as a best-effort background task."""
        command_start = time.perf_counter()
        warmed_providers = 0
        provider_lookup_start = time.perf_counter()
        available_providers = TranslationProvider.get_providers()
        provider_lookup_elapsed = time.perf_counter() - provider_lookup_start
        logging.info(_("Warming up translation provider"))
        logging.debug("Located %d translation providers in %.3f seconds",
                      len(available_providers), provider_lookup_elapsed)

        active_provider_name = self.active_provider.name if self.active_provider else self.options.provider
        configured_provider_names = set(self.options.provider_settings) if self.warm_configured_providers else set()
        provider_names = [
            provider_name for provider_name in available_providers
            if provider_name in configured_provider_names or provider_name == active_provider_name
        ]
        if active_provider_name in provider_names:
            provider_names.remove(active_provider_name)
            provider_names.insert(0, active_provider_name)

        for provider_name in provider_names:
            if self.aborted:
                logging.info(_("Aborted translation provider warm-up"))
                return True

            try:
                provider_type = available_providers[provider_name]
                provider_class = cast(type[TranslationProvider], provider_type)

                warmup_start = time.perf_counter()
                with UsingOriginalImport():
                    provider_class.WarmUp()
                warmup_elapsed = time.perf_counter() - warmup_start
                logging.debug("Loaded %s provider dependencies in %.3f seconds",
                              provider_name, warmup_elapsed)

                if self.aborted:
                    logging.info(_("Aborted translation provider warm-up"))
                    return True

                construction_start = time.perf_counter()
                if provider_name == active_provider_name and self.active_provider:
                    provider = self.active_provider
                else:
                    provider_settings = self.options.GetProviderSettings(provider_name)
                    provider = TranslationProvider.create_provider(provider_name, provider_settings)
                construction_elapsed = time.perf_counter() - construction_start
                logging.debug("Constructed %s provider in %.3f seconds",
                              provider_name, construction_elapsed)

                self.warmed_providers[provider_name] = provider
                warmed_providers += 1
                provider_elapsed = time.perf_counter() - warmup_start
                logging.debug("Background-warmed provider: %s (%.3f seconds total)",
                              provider_name, provider_elapsed)
            except Exception as error:
                logging.warning("Unable to warm %s provider: %s", provider_name, error)

            if self.aborted:
                logging.info(_("Aborted translation provider warm-up"))
                return True

        command_elapsed = time.perf_counter() - command_start
        logging.info(_("Completed translation provider warm-up (%d providers)"), warmed_providers)
        logging.debug("Background translation provider warm-up took %.3f seconds", command_elapsed)
        return True
