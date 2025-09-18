from events import Events # type: ignore

class TranslationEvents(Events):
    __events__ = ( "preprocessed", "batch_translated", "scene_translated" )

