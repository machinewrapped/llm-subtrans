import logging
import os
from typing import Any

from PySubtrans.Helpers.Resources import GetResourcePath, config_dir

linesep = '\n'

DEFAULT_TASK_TYPE = "Translation"

default_user_prompt = "Translate these subtitles [ for movie][ to language]"

default_instructions = linesep.join([
	"Your task is to accurately translate subtitles into a target language.",
	"",
	"The user will provide a batch of lines for translation, you should respond with an ACCURATE, CONCISE, and NATURAL-SOUNDING translation for EACH LINE in the batch.",
	"The user may provide additional information, such as a list of names or a synopsis of earlier batches. Use this to improve your translation.",
	"Your response will be processed by an automated system, so it is ESSENTIAL that you respond using this format:",
	"",
	"Example input (English to German):",
	"",
	"#700",
	"Original>",
	"In the age of digital transformation,",
	"Translation>",
	"",
	"#701",
	"Original>",
	"those who resist change may find themselves left behind.",
	"Translation>",
	"",
	"You should respond with:",
	"",
	"#700",
	"Original>",
	"In the age of digital transformation,",
	"Translation>",
	"Im Zeitalter der digitalen Transformation,",
	"",
	"#701",
	"Original>",
	"those who resist change may find themselves left behind.",
	"Translation>",
	"diejenigen, die sich dem Wandel widersetzen,",
	"könnten sich zurückgelassen finden.",
    ])

default_retry_instructions = linesep.join([
	"There was an issue with the previous translation.",
	"",
	"Translate the subtitles again, paying careful attention to ensure that each line is translated SEPARATELY, and that EVERY line has a matching translation.",
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
        self.prompt = settings.get('prompt') or settings.get('gpt_prompt') or default_user_prompt
        self.instructions = settings.get('instructions') or default_instructions
        self.retry_instructions = settings.get('retry_instructions') or default_retry_instructions
        self.instruction_file = settings.get('instruction_file') or None
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

    def LoadInstructionsFile(self, filepath : str) -> None:
        """
        Try to load instructions from a text file.
        """
        if not os.path.exists(filepath):
            raise ValueError(f"Instruction file not found: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines()]

        if not lines:
            return

        if not lines[0].startswith('###'):
            logging.info(f"Loading legacy instruction file: {filepath}")
            file_instructions, file_retry_instructions = LoadLegacyInstructions(lines)
            if file_instructions:
                self.instructions = file_instructions
                self.retry_instructions = file_retry_instructions or default_retry_instructions
                self.instruction_file = os.path.basename(filepath)
            return

        sections : dict[str, list[str]] = {}
        section_name : str|None = None
        for line in lines:
            if line.startswith('###'):
                section_name = line[3:].strip()
                sections[section_name] = []
            elif section_name is not None and (line.strip() or sections[section_name]):
                sections[section_name].append(line)

        self.prompt = linesep.join(sections.get('prompt', []))
        self.instructions = linesep.join(sections.get('instructions', []))
        self.retry_instructions = linesep.join(sections.get('retry_instructions', [])) or default_retry_instructions
        self.instruction_file = os.path.basename(filepath)
        self.target_language = ''.join(sections.get('target_language', [])) if 'target_language' in sections else None
        self.task_type = ''.join(sections.get('task_type', [])) if 'task_type' in sections else DEFAULT_TASK_TYPE

        if not self.prompt or not self.instructions:
            raise ValueError("Invalid instruction file")

    def SaveInstructions(self, filepath : str) -> None:
        """
        Save instructions to a text file.
        """
        if filepath:
            # Make sure the file has a .txt extension
            if not filepath.endswith('.txt'):
                filepath += '.txt'

            # Write each section to the file with a header
            with open(filepath, "w", encoding="utf-8", newline='') as f:
                f.write("### prompt\n")
                f.write(self.prompt or default_instructions)
                if self.task_type != DEFAULT_TASK_TYPE:
                    f.write("\n\n### task_type\n{}".format(self.task_type))
                f.write("\n\n### instructions\n")
                f.write(self.instructions or default_instructions)
                f.write("\n\n### retry_instructions\n")
                f.write(self.retry_instructions or default_retry_instructions)
                f.write("\n")

            self.instruction_file = os.path.basename(filepath)

def GetInstructionsResourcePath(instructions_file : str|None = None) -> str:
    """
    Get the path for an instructions file (or the directory that contains them).
    """
    if not instructions_file:
        return GetResourcePath("instructions")

    return GetResourcePath("instructions", instructions_file)

def GetInstructionsResourceFiles() -> list[str]:
    """
    Get a list of instruction files in the instructions directory.
    """
    instruction_path = GetInstructionsResourcePath()
    logging.debug(f"Looking for instruction files in {instruction_path}")
    files = os.listdir(instruction_path)
    return [ file for file in files if file.lower().startswith("instructions") ]

def LoadInstructionsResource(resource_name : str) -> Instructions:
    """
    Load instructions from a file in the project/package.
    """
    filepath = GetInstructionsResourcePath(resource_name)
    logging.debug(f"Loading instructions from {filepath}")
    instructions = Instructions({})
    instructions.LoadInstructionsFile(filepath)
    return instructions

def GetInstructionsUserPath(instructions_file : str|None = None) -> str:
    """
    Get the path for an instructions file (or the directory that contains them).
    """
    instructions_dir = os.path.join(config_dir, "instructions")
    return os.path.join(instructions_dir, instructions_file) if instructions_file else instructions_dir

def GetInstructionsUserFiles() -> list[str]:
    """
    Get a list of instruction files in the user directory.
    """
    instructions_dir = GetInstructionsUserPath()
    logging.debug(f"Looking for instruction files in {instructions_dir}")
    if not os.path.exists(instructions_dir):
        os.makedirs(instructions_dir)

    files = os.listdir(instructions_dir)
    return [ file for file in files if file.lower().endswith(".txt") ]

def GetInstructionsFiles() -> list[str]:
    """
    Get a list of instruction files in the user and resource directories.
    """
    default_instructions = GetInstructionsResourceFiles()
    user_instructions = GetInstructionsUserFiles()

    instructions_map = { os.path.basename(file).lower(): file for file in default_instructions }
    instructions_map.update({ os.path.basename(file).lower(): file for file in user_instructions })

    # Sort 'instructions.txt' to the top of the list followed by other names case-insensitive
    return sorted(list(instructions_map.values()), key=lambda x: (x.lower() != 'instructions.txt', x.lower()))

def LoadInstructions(name : str) -> Instructions:
    """
    Load instructions from user directory if they exist, otherwise load from resources.
    """
    user_path = GetInstructionsUserPath(name)
    if os.path.exists(user_path):
        instructions = Instructions({})
        instructions.LoadInstructionsFile(user_path)
        return instructions

    return LoadInstructionsResource(name)

def LoadLegacyInstructions(lines : list[str]) -> tuple[str|None, str|None]:
    """
    Retry instructions can be added to the file after a line of at least 3 # characters.
    """
    if lines:
        for idx, item in enumerate(lines):
            if len(item) >= 3 and all(c == '#' for c in item):
                return linesep.join(lines[:idx]), linesep.join(lines[idx + 1:])

        return linesep.join(lines), None

    return None, None

def ReplaceTags(text : str, tags : dict[str, str]) -> str:
    """
    Replace option tags in a string with the value of the corresponding option.
    """
    if text:
        for name, value in tags.items():
            if value:
                text = text.replace(f"[{name}]", str(value))
    return text
