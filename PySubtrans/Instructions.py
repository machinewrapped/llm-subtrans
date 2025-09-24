DEFAULT_TASK_TYPE = "Translation"

default_user_prompt = "Translate these subtitles [ for movie][ to language]"

linesep = '\n'

default_instructions = linesep.join([
    "The goal is to accurately translate subtitles into a target language.",
    "",
    "You will receive a batch of lines for translation. Carefully read through the lines, along with any additional context provided.",
    "Translate each line accurately, concisely, and separately into the target language, with appropriate punctuation.",
    "",
    "The translation must have the same number of lines as the original, but you can adapt the content to fit the grammar of the target language.",
    "Make sure to translate all provided lines and do not ask whether to continue.",
    "",
    "Use any provided context to enhance your translations. If a name list is provided, ensure names are spelled according to the user's preference.",
    "If you detect obvious errors in the input, correct them in the translation using the available context, but do not improvise.",
    "If the input contains profanity, use equivalent profanity in the translation.",
    "",
    "At the end you should add <summary> and <scene> tags with information about the translation:",
    "<summary>A one or two line synopsis of the current batch.</summary>",
    "<scene>This should be a short summary of the current scene, including any previous batches.</scene>",
    "If the context is unclear, just summarize the dialogue.",
    "",
    "Your response will be processed by an automated system, so you MUST respond using the required format:",
    "",
    "Example (translating to English):",
    "",
    "#200",
    "Original>",
    "変わりゆく時代において、",
    "Translation>",
    "In an ever-changing era,",
    "",
    "#501",
    "Original>",
    "進化し続けることが生き残る秘訣です。",
    "Translation>",
    "continuing to evolve is the key to survival.",
    ])

default_retry_instructions = linesep.join([
	"There was an issue with the previous translation.",
	"",
	"Translate the subtitles again, ensuring each line is translated SEPARATELY, and EVERY line has a corresponding translation.",
	"",
	"Do NOT merge lines together in the translation, it leads to incorrect timings and confusion for the reader."
    ])

class Instructions:
    def __init__(self, settings : dict) -> None:
        self.prompt : str|None = None
        self.instructions : str|None = None
        self.retry_instructions : str|None = None
        self.instruction_file : str|None = None
        self.target_language : str|None = None
        self.task_type : str|None = DEFAULT_TASK_TYPE
        self.InitialiseInstructions(settings)

    def GetSettings(self) -> dict[str, str|None]:
        """ Generate the settings for these instructions """
        settings = {
            'prompt': self.prompt,
            'instructions': self.instructions,
            'retry_instructions': self.retry_instructions,
            'instruction_file': self.instruction_file,
            'task_type' : self.task_type
        }

        if self.target_language:
            settings['target_language'] = self.target_language

        return settings

    def InitialiseInstructions(self, settings : dict[str, str|None]) -> None:
        self.prompt = settings.get('prompt') or default_user_prompt
        self.instructions = settings.get('instructions') or default_instructions
        self.retry_instructions = settings.get('retry_instructions') or default_retry_instructions
        self.instruction_file = settings.get('instruction_file')
        self.target_language = None
        self.task_type = settings.get('task_type') or DEFAULT_TASK_TYPE

        # Add any additional instructions from the command line
        if settings.get('instruction_args') and isinstance(settings['instruction_args'], list):
            additional_instructions = linesep.join(settings['instruction_args'])
            if additional_instructions:
                self.instructions = linesep.join([self.instructions, additional_instructions])

        tags = {
            "[ for movie]": f" for {settings.get('movie_name')}" if settings.get('movie_name') else "",
            "[ to language]": f" to {settings.get('to_language')}" if settings.get('to_language') else "",
        }

        tags.update({ f"[{k}]": v for k, v in settings.items() if v })

        self.prompt = ReplaceTags(self.prompt, tags)
        self.instructions = ReplaceTags(self.instructions, tags)
        self.retry_instructions = ReplaceTags(self.retry_instructions, tags)

def ReplaceTags(text : str, tags : dict[str, str]) -> str:
    """
    Replace option tags in a string with the value of the corresponding option.
    """
    if text:
        for name, value in tags.items():
            if value:
                text = text.replace(f"[{name}]", str(value))
    return text
