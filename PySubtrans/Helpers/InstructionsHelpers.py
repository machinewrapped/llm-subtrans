import logging
import os

from PySubtrans.Instructions import Instructions, DEFAULT_TASK_TYPE, default_instructions, default_retry_instructions
from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Resources import GetResourcePath, config_dir

linesep = '\n'

def LoadInstructions(instruction_file : str) -> Instructions:
    """
    Load instruction file with flexible path resolution:
    1. Check if it's an absolute path and exists
    2. Check if it's relative to current directory
    3. Check LLM-Subtrans user directory if exists, otherwise load from resources
    """
    # Check absolute path
    if os.path.isabs(instruction_file) and os.path.exists(instruction_file):
        return LoadInstructionsFile(instruction_file)

    # Check relative to current directory
    if os.path.exists(instruction_file):
        return LoadInstructionsFile(os.path.abspath(instruction_file))

    # Check whether the file exists in the LLM-Subtrans user directory
    user_path = GetInstructionsUserPath(instruction_file)
    if os.path.exists(user_path):
        return LoadInstructionsFile(user_path)

    # Finally, try loading from package resources
    return LoadInstructionsResource(instruction_file)

def LoadInstructionsFile(filepath : str) -> Instructions:
    """
    Load instructions from a text file.
    """
    if not os.path.exists(filepath):
        raise ValueError(f"Instruction file not found: {filepath}")

    instructions = Instructions({})

    with open(filepath, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f.readlines()]

    if not lines:
        return instructions

    if not lines[0].startswith('###'):
        logging.info(f"Loading legacy instruction file: {filepath}")
        file_instructions, file_retry_instructions = LoadLegacyInstructions(lines)
        if file_instructions:
            instructions.instructions = file_instructions
            instructions.retry_instructions = file_retry_instructions or default_retry_instructions
            instructions.instruction_file = os.path.basename(filepath)
        return instructions

    sections : dict[str, list[str]] = {}
    section_name : str|None = None
    for line in lines:
        if line.startswith('###'):
            section_name = line[3:].strip()
            sections[section_name] = []
        elif section_name is not None and (line.strip() or sections[section_name]):
            sections[section_name].append(line)

    instructions.prompt = linesep.join(sections.get('prompt', [])).strip()
    instructions.instructions = linesep.join(sections.get('instructions', [])).strip()
    instructions.retry_instructions = linesep.join(sections.get('retry_instructions', [])).strip() or default_retry_instructions
    instructions.instruction_file = os.path.basename(filepath)
    instructions.target_language = ''.join(sections.get('target_language', [])) if 'target_language' in sections else None
    instructions.task_type = ''.join(sections.get('task_type', [])) if 'task_type' in sections else DEFAULT_TASK_TYPE

    if not instructions.prompt or not instructions.instructions:
        raise ValueError("Invalid instruction file")

    return instructions


def SaveInstructions(instructions : Instructions, filepath : str) -> None:
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
            f.write(instructions.prompt or default_instructions)
            if instructions.task_type != DEFAULT_TASK_TYPE:
                f.write("\n\n### task_type\n{}".format(instructions.task_type))
            f.write("\n\n### instructions\n")
            f.write(instructions.instructions or default_instructions)
            f.write("\n\n### retry_instructions\n")
            f.write(instructions.retry_instructions or default_retry_instructions)
            f.write("\n")

        instructions.instruction_file = os.path.basename(filepath)


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
    return LoadInstructionsFile(filepath)


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
