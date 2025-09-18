#!/usr/bin/env python3
"""
Extract translatable strings from the source tree and write locales/gui-subtrans.pot.

This version can import provider classes to extract their settings as well.

Rules:
- _("text") → msgid "text"
- tr("context", "text") → msgctxt "context" ; msgid "text"
- Setting keys from Options.py → auto-generated English translations
- Provider setting keys → extracted from providers with descriptions

Only constant string literals are extracted from source code.
"""
import ast
import os
import re
from datetime import datetime, timezone

base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = base_path

LOCALES_DIR = os.path.join(REPO_ROOT, 'locales')
POT_PATH = os.path.join(LOCALES_DIR, 'gui-subtrans.pot')

INCLUDE_DIRS = (
    'GuiSubtrans',
    'PySubtrans',
    'scripts',
)
EXCLUDE_DIRS = (
    'locales',
    'PySubtrans/UnitTests',
    'GuiSubtrans/UnitTests',
    'tests',
    'assets',
    'theme',
    'hooks-subtrans',
)

# Global store of setting keys discovered during extraction
SETTING_KEYS: set[str] = set()


def ensure_parent(path: str):
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)

def escape_po(s: str) -> str:
    return s.replace('\\', r'\\').replace('"', r'\"').replace('\n', r'\n')

def generate_english_name(key: str) -> str:
    """Generate English display name from setting key using the same logic as OptionWidget.GenerateName"""
    # Guard: setting keys must not contain format placeholders
    if '{' in key or '}' in key:
        raise ValueError(f"Invalid setting key for English name generation (contains braces): {key}")
    name = key.replace('_', ' ').title()
    # Preserve common initialisms after title-casing
    replacements = {
        r"\bApi\b": "API",
        r"\bAws\b": "AWS",
        r"\bUrl\b": "URL",
        r"\bUri\b": "URI",
        r"\bUi\b": "UI",
    }
    for pattern, repl in replacements.items():
        name = re.sub(pattern, repl, name)
    return name


class SettingKeyExtractor:
    """Extracts setting keys from Options.py and provider classes"""
    
    def __init__(self):
        self.setting_keys: set[str] = set()
    
    def extract_to_entries(self, entries: dict[tuple[str|None, str], list[tuple[str, int]]]) -> set[str]:
        """Extract all setting keys and add them to entries dict, return the keys"""
        self.setting_keys.clear()
        self._extract_options_keys(entries)
        self._extract_provider_keys(entries)
        return self.setting_keys.copy()
    
    def _extract_options_keys(self, entries: dict[tuple[str|None, str], list[tuple[str, int]]]):
        """Extract setting keys from PySubtrans/Options.py default_settings dictionary"""
        options_path = os.path.join(REPO_ROOT, 'PySubtrans', 'Options.py')
        
        try:
            with open(options_path, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source, filename='PySubtrans/Options.py')
            
            found_default_settings = False
            for node in ast.walk(tree):
                # Handle both regular assignment and annotated assignment
                target_name = None
                value_node = None
                
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    target_name = node.targets[0].id
                    value_node = node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    target_name = node.target.id
                    value_node = node.value
                
                if target_name == 'default_settings' and isinstance(value_node, ast.Dict):
                    found_default_settings = True
                    print(f"Found default_settings dictionary with {len(value_node.keys)} keys")
                    
                    keys_extracted = 0
                    for key_node in value_node.keys:
                        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                            setting_key = key_node.value
                            self.setting_keys.add(setting_key)
                            key = (None, setting_key)
                            entries.setdefault(key, []).append(('PySubtrans/Options.py', key_node.lineno))
                            keys_extracted += 1
                    
                    print(f"Extracted {keys_extracted} setting keys from Options.py")
                    if keys_extracted == 0:
                        raise Exception("Found default_settings dictionary but no string keys could be extracted!")
                    if keys_extracted < 20:  # We expect at least 20 setting keys
                        raise Exception(f"Only extracted {keys_extracted} setting keys from Options.py - this seems too few! Expected at least 20.")
                    break
            
            if not found_default_settings:
                raise Exception("Could not find default_settings dictionary in Options.py! This will result in missing translations.")
                            
        except Exception as e:
            raise Exception(f"Could not extract setting keys from Options.py: {e}")
    
    def _extract_provider_keys(self, entries: dict[tuple[str|None, str], list[tuple[str, int]]]):
        """Extract setting keys from all translation providers"""
        providers_dir = os.path.join(REPO_ROOT, 'PySubtrans', 'Providers')
        provider_files = [f for f in os.listdir(providers_dir) if f.startswith('Provider_') and f.endswith('.py')]
        
        print(f"Found {len(provider_files)} provider files: {provider_files}")
        
        for provider_file in provider_files:
            provider_path = os.path.join(providers_dir, provider_file)
            
            try:
                static_keys = self._extract_provider_settings_static(provider_path)
                self.setting_keys.update(static_keys)
                
                for key in static_keys:
                    entry_key = (None, key)
                    entries.setdefault(entry_key, []).append((f'PySubtrans/Providers/{provider_file}', 0))
                    
            except Exception as e:
                raise Exception(f"Could not extract settings from {provider_file}: {e}")
    
    def _extract_provider_settings_static(self, provider_path: str) -> set[str]:
        """Statically parse provider __init__ method to extract setting keys"""
        keys = set()
        
        try:
            with open(provider_path, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source)
            
            for node in ast.walk(tree):
                if (isinstance(node, ast.FunctionDef) and 
                    node.name == '__init__'):
                    
                    for child in ast.walk(node):
                        if (isinstance(child, ast.Call) and
                            isinstance(child.func, ast.Attribute) and
                            child.func.attr == '__init__' and
                            len(child.args) >= 2):
                            
                            settings_arg = child.args[1]
                            # Handle direct dict literal: {...}
                            if isinstance(settings_arg, ast.Dict):
                                for key_node in settings_arg.keys:
                                    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                                        keys.add(key_node.value)
                            # Handle SettingsType({...}) constructor call
                            elif (isinstance(settings_arg, ast.Call) and
                                  isinstance(settings_arg.func, ast.Name) and
                                  settings_arg.func.id == 'SettingsType' and
                                  settings_arg.args and
                                  isinstance(settings_arg.args[0], ast.Dict)):
                                dict_arg = settings_arg.args[0]
                                for key_node in dict_arg.keys:
                                    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                                        keys.add(key_node.value)
                            
        except Exception as e:
            raise Exception(f"Static analysis failed for {provider_path}: {e}")

        return keys


class TranslatableStringExtractor:
    """Extracts translatable strings wrapped in _() and tr() from source code"""
    
    def extract_from_codebase(self) -> dict[tuple[str|None, str], list[tuple[str, int]]]:
        """Extract all translatable strings from the codebase"""
        entries: dict[tuple[str|None, str], list[tuple[str, int]]] = {}
        
        for root, _, files in os.walk(REPO_ROOT):
            for name in files:
                path = os.path.join(root, name)
                if not self._should_include(path):
                    continue
                rel = os.path.relpath(path, REPO_ROOT).replace('\\', '/')
                
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        source = f.read()
                    tree = ast.parse(source, filename=rel)

                    for node in ast.walk(tree):
                        if not isinstance(node, ast.Call):
                            continue
                        
                        func = node.func
                        func_name = None
                        if isinstance(func, ast.Name):
                            func_name = func.id
                        elif isinstance(func, ast.Attribute):
                            func_name = func.attr
                        
                        if func_name not in ('_', 'tr'):
                            continue

                        key = self._extract_string_from_call(node, func_name)
                        if key:
                            entries.setdefault(key, []).append((rel, node.lineno))

                except Exception as e:
                    raise Exception(f"Failed to parse {rel} for translatable strings: {str(e)}")

        return entries
    
    def _should_include(self, path: str) -> bool:
        """Check if file should be included in string extraction"""
        rel = os.path.relpath(path, REPO_ROOT).replace('\\', '/')
        if not rel.endswith('.py'):
            return False
        for ex in EXCLUDE_DIRS:
            if rel.startswith(ex.rstrip('/') + '/') or rel == ex:
                return False
        return any(rel.startswith(d.rstrip('/') + '/') or rel == d for d in INCLUDE_DIRS)
    
    def _extract_string_from_call(self, node: ast.Call, func_name: str) -> tuple[str|None, str]|None:
        """Extract string from _() or tr() call"""
        if func_name == '_' and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return (None, arg.value)
        elif func_name == 'tr' and len(node.args) >= 2:
            ctx_arg, txt_arg = node.args[0], node.args[1]
            if (isinstance(ctx_arg, ast.Constant) and isinstance(ctx_arg.value, str)
                and isinstance(txt_arg, ast.Constant) and isinstance(txt_arg.value, str)):
                return (ctx_arg.value, txt_arg.value)
        return None

############################################################################

def collect_entries() -> tuple[dict[tuple[str|None, str], list[tuple[str, int]]], set[str]]:
    """Collect all translatable entries (both strings and setting keys)"""
    entries: dict[tuple[str|None, str], list[tuple[str, int]]] = {}
    
    # Extract setting keys first
    setting_extractor = SettingKeyExtractor()
    setting_keys = setting_extractor.extract_to_entries(entries)
    
    print(f"Total setting keys extracted: {len(setting_keys)}")
    if len(setting_keys) == 0:
        raise Exception("CRITICAL ERROR: No setting keys were extracted! This will result in missing translations.")
    
    # Extract translatable strings from source code
    string_extractor = TranslatableStringExtractor()
    string_entries = string_extractor.extract_from_codebase()
    
    # Merge string entries with setting entries
    for key, refs in string_entries.items():
        entries.setdefault(key, []).extend(refs)
    
    print(f"Total entries to be written: {len(entries)} (includes {len(setting_keys)} setting keys + {len(string_entries)} translatable strings)")
    
    return entries, setting_keys


def write_pot(entries: dict[tuple[str|None, str], list[tuple[str, int]]], timestamp: str):
    ensure_parent(POT_PATH)

    lines: list[str] = []
    # Header
    lines.append('msgid ""')
    lines.append('msgstr ""')
    lines.append(f'"Project-Id-Version: LLM-Subtrans\\n"')
    lines.append(f'"POT-Creation-Date: {timestamp}\\n"')
    lines.append(f'"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"')
    lines.append(f'"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"')
    lines.append(f'"MIME-Version: 1.0\\n"')
    lines.append(f'"Content-Type: text/plain; charset=UTF-8\\n"')
    lines.append(f'"Content-Transfer-Encoding: 8bit\\n"')
    lines.append(f'"Language: en\\n"')
    lines.append('')

    for key, refs in sorted(entries.items(), key=lambda k: (k[0][0] or '', k[0][1]) if isinstance(k[0], tuple) else ('', '')):
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        context, msgid = key
        # References
        ref_chunks = [f"{f}:{n}" for f, n in sorted(refs)]
        if ref_chunks:
            lines.append(f"#: {' '.join(ref_chunks)}")
        if context:
            lines.append(f"msgctxt \"{escape_po(context)}\"")
        lines.append(f"msgid \"{escape_po(msgid)}\"")
        lines.append("msgstr \"\"")
        lines.append("")

    with open(POT_PATH, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"Wrote {POT_PATH} with {len(entries)} entries")
    
    # Return setting_keys for English PO generation


def write_english_po(entries: dict[tuple[str|None, str], list[tuple[str, int]]], timestamp: str, setting_keys: set[str]):
    """Write English PO file with auto-generated translations for setting keys"""
    en_po_path = os.path.join(LOCALES_DIR, 'en', 'LC_MESSAGES', 'gui-subtrans.po')
    ensure_parent(en_po_path)
    
    # Only auto-generate msgstr for setting keys (Options.py or Providers), all others blank
    lines: list[str] = []

    # Header
    lines.append('msgid ""')
    lines.append('msgstr ""')
    lines.append(f'"Project-Id-Version: LLM-Subtrans\\n"')
    lines.append(f'"POT-Creation-Date: {timestamp}\\n"')
    lines.append(f'"PO-Revision-Date: {timestamp}\\n"')
    lines.append(f'"Last-Translator: Auto-generated\\n"')
    lines.append(f'"MIME-Version: 1.0\\n"')
    lines.append(f'"Content-Type: text/plain; charset=UTF-8\\n"')
    lines.append(f'"Content-Transfer-Encoding: 8bit\\n"')
    lines.append(f'"Language: en\\n"')
    lines.append('')


    for key, refs in sorted(entries.items(), key=lambda k: (k[0][0] or '', k[0][1]) if isinstance(k[0], tuple) else ('', '')):
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        context, msgid = key
        # References
        ref_chunks = [f"{f}:{n}" for f, n in sorted(refs)]
        if ref_chunks:
            lines.append(f"#: {' '.join(ref_chunks)}")
        if context:
            lines.append(f"msgctxt \"{escape_po(context)}\"")
        lines.append(f"msgid \"{escape_po(msgid)}\"")

        # Only auto-generate for actual setting keys (context must be None, msgid in setting_keys, and msgid looks like a key)
        if context is None and msgid in setting_keys and msgid.isidentifier():
            msgstr = generate_english_name(msgid)
        else:
            msgstr = ""

        lines.append(f"msgstr \"{escape_po(msgstr)}\"")
        lines.append("")

    with open(en_po_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"Wrote {en_po_path} with auto-generated setting translations (sanitized)")

#############################################################

def main():
    entries, setting_keys = collect_entries()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M+0000')
    write_pot(entries, now)
    write_english_po(entries, now, setting_keys)

if __name__ == '__main__':
    main()