import logging

from GuiSubtrans.Command import Command
from PySubtrans.Options import Options
from PySubtrans.TranslationProvider import TranslationProvider
from PySubtrans.Helpers.Localization import _

class ExitProgramCommand(Command):
    """
    Exit the program.
    """
    def __init__(self):
        super().__init__()
        self.is_blocking = True
        self.can_undo = False

    def execute(self) -> bool:
        logging.info(_("Exiting Program"))
        return True

class CheckProviderSettings(Command):
    """
    Check if the translation provider is configured correctly.
    """
    def __init__(self, options : Options):
        super().__init__()
        self.is_blocking = True
        self.skip_undo = True
        self.options = options
        self.show_provider_settings = False

    def execute(self) -> bool:
        try:
            if not self.datamodel:
                logging.warning(_("No datamodel available to check provider settings"))
                self.show_provider_settings = True
                return True

            translation_provider : TranslationProvider|None = self.datamodel.translation_provider
            if not translation_provider:
                logging.warning(_("Invalid translation provider"))
                self.show_provider_settings = True

            elif not translation_provider.ValidateSettings():
                logging.warning(_("Provider {provider} needs configuring: {message}").format(provider=translation_provider.name, message=translation_provider.validation_message))
                self.show_provider_settings = True

        except Exception as e:
            logging.error(_("CheckProviderSettings: {error}").format(error=e))

        finally:
            return True

