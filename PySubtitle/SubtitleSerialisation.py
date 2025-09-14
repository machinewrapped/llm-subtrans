import json

from PySubtitle.Helpers.Color import Color
from PySubtitle.SettingsType import SettingsType
from PySubtitle.SubtitleLine import SubtitleLine
from PySubtitle.SubtitleBatch import SubtitleBatch
from PySubtitle.SubtitleError import TranslationError
from PySubtitle.Subtitles import Subtitles
from PySubtitle.SubtitleScene import SubtitleScene
from PySubtitle.Translation import Translation
from PySubtitle.TranslationPrompt import TranslationPrompt

# Serialisation helpers
def classname(obj):
    if isinstance(obj, type):
        return obj.__name__
    return type(obj).__name__

# Convert our custom types to JSON
class SubtitleEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, TranslationError):
            # Don't bother trying to serialise all the error types (why not?)
            return {
                "__class": classname(TranslationError),
                "type": classname(o),
                "problem": str(o)
            }

        _class = classname(o)
        properties = self.serialize_object(o)
        if isinstance(properties, dict):
            properties = {k: v for k, v in properties.items() if v is not None}
            return {**{ "_class": _class }, **properties}
        else:
            return properties

    def serialize_object(self, obj):
        if obj is None:
            return None

        if isinstance(obj, Subtitles):
            return {
                "sourcepath": obj.sourcepath,
                "outputpath": obj.outputpath,
                "scenecount": len(obj.scenes),
                "settings": getattr(obj, 'settings') or getattr(obj, 'context'),
                "metadata": getattr(obj, 'metadata', {}),
                "format": obj.file_format,
                "scenes": obj.scenes,
            }
        elif isinstance(obj, SubtitleScene):
            return {
                "scene": getattr(obj, 'number'),
                "batchcount": obj.size,
                "linecount": obj.linecount,
                "all_translated": obj.all_translated,
                "context": {
                    "summary": obj.context.get('summary'),
                    "history": obj.context.get('history') or obj.context.get('summaries')
                },
                "batches": obj._batches,
            }
        elif isinstance(obj, SubtitleBatch):
            return {
                "scene": getattr(obj, 'scene'),
                "batch": getattr(obj, 'number'),
                "size": obj.size,
                "all_translated": obj.all_translated,
                "errors": obj.errors if obj.errors else None,
                "summary": getattr(obj, 'summary'),
                "originals": obj._originals,
                "translated": obj._translated,
                "context": {
                    "summary": obj.context.get('summary'),
                    "history": obj.context.get('history') or obj.context.get('summaries')
                },
                "translation": obj.translation,
                "prompt": obj.prompt
            }
        elif isinstance(obj, SubtitleLine):
            return {
                "index": obj._index,
                "start": obj.start.total_seconds() if obj.start else None,
                "end": obj.end.total_seconds() if obj.end else None,
                "content": obj.content,
                "metadata": getattr(obj, 'metadata'),
                "translation": getattr(obj, 'translation'),
                "original": getattr(obj, 'original')
            }
        elif isinstance(obj, Translation):
            return {
                "content": obj.content
            }
        elif isinstance(obj, TranslationPrompt):
            return {
                "user_prompt": obj.user_prompt,
                "batch_prompt": obj.batch_prompt,
                "messages": obj.messages,
                "supports_system_messages": obj.supports_system_messages,
                "supports_system_prompt": obj.supports_system_prompt,
                "conversation": obj.conversation,
            }
        elif isinstance(obj, Color):
            return { "hex": obj.to_hex() }
        elif hasattr(obj, "name"):
            return obj.name

        return super().default(obj)

class SubtitleDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        super().__init__(object_hook=_object_hook, *args, **kwargs)

def _object_hook(dct):
    # Reconstruct our custom types from JSON
    if '_class' in dct:
        class_name = dct.pop('_class')
        if class_name in {classname(Subtitles), "SubtitleFile"}:      # Backward compatibility
            sourcepath = dct.get('sourcepath')
            outpath = dct.get('outputpath') or dct.get('filename')
            obj = Subtitles(sourcepath, outpath)
            obj.settings = SettingsType(dct.get('settings', {}) or dct.get('context', {}))
            obj.metadata = dct.get('metadata', {})
            obj.file_format = dct.get('format', '.srt')
            obj.scenes = dct.get('scenes', [])
            obj.UpdateProjectSettings(SettingsType()) # Force update for legacy files
            return obj
        elif class_name == classname(SubtitleScene):
            obj = SubtitleScene(dct)
            return obj
        elif class_name == classname(SubtitleBatch):
            obj = SubtitleBatch(dct)
            return obj
        elif class_name == classname(SubtitleLine) or class_name == "Subtitle": # TEMP backward compatibility
            return SubtitleLine(dct)
        elif class_name == classname(Translation) or class_name == "GPTTranslation":
            content = dct.get('content') or {
                'text' : dct.get('text'),
                'finish_reason' : dct.get('finish_reason'),
                'response_time' : dct.get('response_time'),
                'prompt_tokens' : dct.get('prompt_tokens'),
                'output_tokens' : dct.get('completion_tokens'),
                'reasoning_tokens' : dct.get('reasoning_tokens'),
                'accepted_prediction_tokens' : dct.get('accepted_prediction_tokens'),
                'rejected_prediction_tokens' : dct.get('rejected_prediction_tokens'),
                'total_tokens' : dct.get('total_tokens'),
                'summary': dct.get('summary'),
                'scene': dct.get('scene'),
                'synopsis': dct.get('synopsis'),
                'names': dct.get('names') or dct.get('characters')
                }

            if isinstance(content['text'], list):
                # This shouldn't happen, but try to recover if it does
                content['text'] = '\n'.join(content['text'])

            obj = Translation(content)
            return obj
        elif class_name == classname(TranslationPrompt):
            user_prompt = dct.get('user_prompt')
            conversation = dct.get('conversation')
            obj = TranslationPrompt(user_prompt, conversation)
            obj.supports_system_messages = dct.get('supports_system_messages')
            obj.supports_system_prompt = dct.get('supports_system_prompt')
            obj.batch_prompt = dct.get('batch_prompt')
            obj.messages = dct.get('messages')
            return obj
        elif class_name == classname(Color):
            return Color.from_hex(dct.get('hex', '#00000000'))
        elif class_name == classname(TranslationError):
            return TranslationError(dct.get('message'))

    return dct
