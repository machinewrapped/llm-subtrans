#!/usr/bin/env python3
"""
One-stop localization workflow for LLM-Subtrans.

Runs the end-to-end flow:
    1) Extract translatable strings -> locales/gui-subtrans.pot
    2) Merge POT into every locale's PO and compile MO catalogs
    3) Integrate any manual translations from untranslated_msgids_<lang>.txt
    4) Re-compile changed POs
    5) Regenerate untranslated_msgids_<lang>.txt (remaining blanks only)

Also normalizes msgid wrapping inside PO files to single-line form so
seeding/matching works reliably.
# """
import argparse
import os
import json
import re
import sys
import ast
import subprocess
import time
import httpx
from datetime import datetime, timezone

# Load environment variables from .env file
try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    print("Warning: python-dotenv not available; environment variables from .env file will not be loaded.")

# Model to use for auto-translation
free_translation_model = os.getenv('FREE_TRANSLATION_MODEL', 'moonshotai/kimi-k2:free')     # Free but may be rate-limited
paid_translation_model = os.getenv('PAID_TRANSLATION_MODEL', 'google/gemini-2.5-flash')              # Fast and reliable but not free

base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from PySubtrans.Helpers.Localization import get_available_locales

# Optional: use Babel to determine plural forms for locales
try:
    from babel.messages.catalog import Catalog as _BabelCatalog
    from babel.core import Locale as _BabelLocale
except Exception:
    _BabelCatalog = None
    _BabelLocale = None
    print("Warning: Babel not available; plural forms will not be detected.")

LOCALES_DIR = os.path.join(base_path, 'locales')
POT_PATH = os.path.join(LOCALES_DIR, 'gui-subtrans.pot')


def get_locale_english_name(lang: str) -> str:
    """Get the English display name for a language code."""
    if _BabelLocale is None:
        return lang
    try:
        locale = _BabelLocale.parse(lang)
        return locale.english_name or lang
    except Exception:
        return lang


def auto_translate_strings(untranslated: dict[str,str], target_language: str, paid: bool = False) -> dict[str,str]:
    """Call OpenRouter API to translate untranslated strings."""
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        print("Warning: OPENROUTER_API_KEY not found in environment variables")
        return {}
    
    if not untranslated:
        return {}
    
    language_name = get_locale_english_name(target_language)
    
    # Prepare request
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://github.com/machinewrapped/llm-subtrans',
        'X-Title': 'LLM-Subtrans'
    }
    
    # Create the prompt
    prompt = '\n'.join([
        f"Populate translations in {language_name} for these UI strings and messages.",
        "String formatting tags in curly braces must be preserved.",
        "Settings keys such as `api_key` or `server_address` should be given human-readable translations like `API Key` and `Server Address`.",
        "Return only a valid JSON dictionary with the same keys with the translations as values:\n\n",
        json.dumps(untranslated, ensure_ascii=False, indent=2)
    ])

    model = paid_translation_model if paid else free_translation_model
    
    request_body = {
        'model': model,
        'messages': [
            {
                'role': 'user',
                'content': prompt
            }
        ],
        'temperature': 0.3
    }
    
    try:
        print(f"Calling OpenRouter API to translate {len(untranslated)} strings to {language_name}...")
        
        with httpx.Client(timeout=300) as client:
            response = client.post(
                'https://openrouter.ai/api/v1/chat/completions',
                headers=headers,
                json=request_body
            )
            
            if response.is_error:
                print(f"OpenRouter API error: {response.status_code} - {response.text}")
                return {}
            
            result = response.json()
            
            if 'choices' not in result or not result['choices']:
                print("No choices returned from OpenRouter API")
                return {}
            
            content = result['choices'][0]['message']['content']
            
            # Extract JSON from response (model might add prologue/epilogue)
            try:
                # Try to find JSON in the response
                json_start = content.find('{')
                json_end = content.rfind('}') + 1
                
                if json_start != -1 and json_end > json_start:
                    json_content = content[json_start:json_end]
                    translations = json.loads(json_content)
                    
                    if isinstance(translations, dict):
                        # Filter out empty translations
                        valid_translations = {k: v for k, v in translations.items() if v and v.strip()}
                        print(f"Successfully translated {len(valid_translations)} strings")
                        return valid_translations
                    
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON from OpenRouter response: {e}")
                print(f"Response content: {content[:500]}...")
            
            return {}
            
    except httpx.RequestError as e:
        print(f"Request error calling OpenRouter API: {e}")
        return {}
    except Exception as e:
        print(f"Unexpected error calling OpenRouter API: {e}")
        return {}


def get_plural_forms(lang: str) -> str|None:
    """Return the Plural-Forms header value for a given language code.
    Prefer Babel (CLDR) rules; fallback to the common English rule if Babel is unavailable.
    """
    lang = (lang or '').lower()
    if _BabelCatalog is not None:
        try:
            cat = _BabelCatalog(locale=lang)
            plural_expr = getattr(cat, 'plural_expr', None)
            num_plurals = getattr(cat, 'num_plurals', None)
            if plural_expr and num_plurals:
                return f"nplurals={num_plurals}; plural={plural_expr};"
        except Exception:
            print(f"Warning: could not get plural forms for {lang} using Babel")
    # Fallback: English-style plural rule
    return 'nplurals=2; plural=(n != 1);'


def ensure_header_fields(po_path: str, lang: str) -> bool:
    """Ensure important header fields (e.g., Plural-Forms) exist. Returns True if file changed."""
    try:
        with open(po_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return False

    if not lines:
        return False

    # Header is at file start until first blank line after the header msgid/msgstr block.
    # We assume standard format produced by gettext tools.
    header_start = 0
    i = 0
    # Find end of header (first completely blank line after the quoted header lines)
    while i < len(lines):
        if lines[i].strip() == '':
            break
        i += 1
    header_end = i  # exclusive

    if header_end <= header_start:
        return False

    header_lines = lines[header_start:header_end]
    has_plural = any(l.strip().startswith('"Plural-Forms:') for l in header_lines)
    desired_plural = get_plural_forms(lang)

    changed = False
    if desired_plural:
        if not has_plural:
            # Insert after Language line if present, else at end of header block
            insert_idx = None
            for idx, l in enumerate(header_lines):
                if l.strip().startswith('"Language:'):
                    insert_idx = idx + 1
                    break
            if insert_idx is None:
                insert_idx = len(header_lines)
            header_lines.insert(insert_idx, f'"Plural-Forms: {desired_plural}\\n"\n')
            changed = True
        else:
            # Update existing Plural-Forms if different
            for idx, l in enumerate(header_lines):
                if l.strip().startswith('"Plural-Forms:'):
                    desired_line = f'"Plural-Forms: {desired_plural}\\n"\n'
                    if l != desired_line:
                        header_lines[idx] = desired_line
                        changed = True
                    break

    if changed:
        lines[header_start:header_end] = header_lines
        with open(po_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
    return changed


# --- PO cleaner helpers: collapse wrapped msgid lines into a single line ---
def _is_quoted_line(s: str) -> bool:
    s = s.lstrip()
    return s.startswith('"') and s.rstrip().endswith('"')


def _extract_quoted(s: str) -> str:
    s = s.strip()
    try:
        first = s.index('"')
        last = s.rindex('"')
    except ValueError:
        return s
    return s[first + 1:last]


def clean_po_file(path: str) -> bool:
    """Clean a single PO file in-place. Returns True if file changed."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return False

    out = []
    i = 0
    changed = False

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        if stripped.startswith('msgid '):
            indent_len = len(line) - len(stripped)
            indent = line[:indent_len]

            if '"' not in stripped:
                out.append(line)
                i += 1
                continue

            first_content = _extract_quoted(stripped)

            j = i + 1
            parts = [first_content]
            while j < len(lines) and _is_quoted_line(lines[j]):
                parts.append(_extract_quoted(lines[j]))
                j += 1

            if len(parts) > 1 or (first_content == '' and j > i + 1):
                combined = ''.join(parts)
                out.append(f"{indent}msgid \"{combined}\"\n")
                changed = True
                i = j
                continue
            else:
                out.append(line)
                i += 1
                continue

        out.append(line)
        i += 1

    if changed:
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(out)
    return changed


def _escape_po(s: str) -> str:
    """Escape a Python string for inclusion inside a PO msgstr quoted string."""
    # Normalize line endings
    s = s.replace('\r\n', '\n')
    # Protect existing literal \n sequences so we don't double-escape them
    sentinel = '\x00'
    s = s.replace('\\n', sentinel)
    # Escape remaining backslashes
    s = s.replace('\\', r'\\')
    # Convert actual newline characters to literal \n
    s = s.replace('\n', r'\n')
    # Escape quotes
    s = s.replace('"', r'\"')
    # Restore protected \n sequences
    s = s.replace(sentinel, r'\n')
    return s


def ensure_dirs(language_code: str) -> str:
    lang_dir = os.path.join(LOCALES_DIR, language_code, 'LC_MESSAGES')
    os.makedirs(lang_dir, exist_ok=True)
    return lang_dir


def ensure_po(language_code: str) -> str:
    lang_dir = ensure_dirs(language_code)
    po_path = os.path.join(lang_dir, 'gui-subtrans.po')
    if not os.path.exists(po_path):
        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M+0000')
        header = (
            'msgid ""\n'
            'msgstr ""\n'
            f'"Project-Id-Version: LLM-Subtrans\\n"\n'
            f'"POT-Creation-Date: {now}\\n"\n'
            f'"PO-Revision-Date: {now}\\n"\n'
            '"MIME-Version: 1.0\\n"\n'
            '"Content-Type: text/plain; charset=UTF-8\\n"\n'
            '"Content-Transfer-Encoding: 8bit\\n"\n'
            f'"Language: {language_code}\\n"\n'
        )
        with open(po_path, 'w', encoding='utf-8') as f:
            f.write(header)
    # Ensure header fields (even if file already existed)
    ensure_header_fields(po_path, language_code)
    return po_path


def run_cmd(cmd: list[str]) -> None:
    try:
        subprocess.check_call(cmd)
    except FileNotFoundError:
        # gettext utils may be missing; skip gracefully
        print(f"Skipping: {' '.join(cmd)} (tool not found)")
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {' '.join(cmd)} -> {e}")


def run_extract_strings() -> None:
    """Run scripts/extract_strings.py to refresh POT (and English PO)."""
    script = os.path.join(base_path, 'scripts', 'extract_strings.py')
    if not os.path.exists(script):
        print(f"extract_strings.py not found at {script}")
        return
    try:
        subprocess.check_call([sys.executable, script])
    except subprocess.CalledProcessError as e:
        raise Exception(f"extract_strings.py failed: {e}")


def merge_and_compile(languages: list[str]|None = None):
    if not os.path.exists(POT_PATH):
        print(f"POT not found at {POT_PATH}. Run extract_strings.py first.")
        return

    # Get available languages dynamically
    languages = languages or get_available_locales()
    if not languages:
        print("No locales found. Please ensure locale directories exist in the locales folder.")
        return

    for lang in languages:
        po_path = ensure_po(lang)
        mo_path = os.path.splitext(po_path)[0] + '.mo'

        # Merge POT into PO (msgmerge)
        # Use --no-wrap to keep long msgid/msgstr on single lines so our
        # seeding/cleaning tools can operate reliably.
        run_cmd(['msgmerge', '--update', '--no-fuzzy-matching', '--backup=none', '--no-wrap', po_path, POT_PATH])

        # Post-merge normalization: collapse wrapped msgid lines in-place.
        try:
            if clean_po_file(po_path):
                print(f"Normalized msgid wrapping: {po_path}")
        except Exception as e:
            print(f"Warning: could not clean {po_path}: {e}")

        # Ensure header completeness (Plural-Forms, etc.)
        try:
            if ensure_header_fields(po_path, lang):
                print(f"Updated header fields: {po_path}")
        except Exception as e:
            print(f"Warning: could not ensure header fields for {po_path}: {e}")

        # Fix any msgid/msgstr trailing \n parity issues that cause msgfmt fatal errors
        try:
            if fix_newline_parity(po_path):
                print(f"Fixed newline parity: {po_path}")
        except Exception as e:
            print(f"Warning: could not fix newline parity for {po_path}: {e}")

        # Compile MO (msgfmt)
        run_cmd(['msgfmt', '-o', mo_path, po_path])

        print(f"Updated {po_path} and {mo_path}")


def _collect_untranslated_msgids(po_file_path: str) -> dict[str,str]:
    """Parse a .po file and return a dict of msgid -> '' for empty msgstr entries."""
    untranslated: dict[str,str] = {}
    try:
        with open(po_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return untranslated

    current_msgid: str|None = None
    current_msgstr: str|None = None
    in_msgid = False
    in_msgstr = False

    for raw in lines:
        line = raw.strip()

        if line.startswith('msgid '):
            # finalize previous
            if current_msgid is not None and current_msgstr == "":
                untranslated[current_msgid] = ""

            current_msgid = line[len('msgid '):].strip('"')
            current_msgstr = None
            in_msgid = True
            in_msgstr = False
            continue

        if line.startswith('msgstr '):
            current_msgstr = line[len('msgstr '):].strip('"')
            in_msgstr = True
            in_msgid = False
            continue

        if line.startswith('"') and (in_msgid or in_msgstr):
            content = line.strip('"')
            if in_msgid and current_msgid is not None:
                current_msgid += content
            elif in_msgstr and current_msgstr is not None:
                current_msgstr += content
            continue

        if not line:
            if current_msgid is not None and current_msgstr == "":
                untranslated[current_msgid] = ""
            current_msgid = None
            current_msgstr = None
            in_msgid = in_msgstr = False
            continue

        if line.startswith('#~'):
            current_msgid = None
            current_msgstr = None
            in_msgid = in_msgstr = False

    if current_msgid is not None and current_msgstr == "":
        untranslated[current_msgid] = ""

    return untranslated


def fix_newline_parity(po_path: str) -> bool:
    """Ensure that if a msgid ends with literal \n, the corresponding msgstr ends with literal \n too.
    Returns True if the file was modified.
    """
    try:
        with open(po_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return False

    out: list[str] = []
    i = 0
    changed = False
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if stripped.startswith('msgid '):
            # capture full msgid
            j = i + 1
            parts = [_extract_quoted(stripped) if '"' in stripped else '']
            while j < len(lines) and _is_quoted_line(lines[j]):
                parts.append(_extract_quoted(lines[j]))
                j += 1
            msgid_full = ''.join(parts)
            out.extend(lines[i:j])
            i = j
            # expect msgstr next
            if i < len(lines) and lines[i].lstrip().startswith('msgstr '):
                msgstr_line = lines[i]
                k = i + 1
                # collect continuation lines to know block end
                while k < len(lines) and _is_quoted_line(lines[k]):
                    k += 1
                # Only adjust simple single-line msgstr blocks (common case)
                # We will reconstruct first line if needed to add trailing \n
                # Extract first msgstr content
                nstrip = msgstr_line.lstrip()
                msgstr_first = _extract_quoted(nstrip) if '"' in nstrip else ''
                ends_id = msgid_full.endswith(r'\n')
                ends_str_nl = msgstr_first.endswith(r'\n')
                ends_str_backslash_n = msgstr_first.endswith(r'\\n')
                if ends_id and msgstr_first != '' and (not ends_str_nl or ends_str_backslash_n):
                    # Ensure msgstr ends with literal \n (single backslash n)
                    indent_len = len(msgstr_line) - len(nstrip)
                    indent = msgstr_line[:indent_len]
                    if ends_str_backslash_n:
                        new_first = msgstr_first[:-2] + r'\n'
                    else:
                        new_first = msgstr_first + r'\n'
                    out.append(f"{indent}msgstr \"{new_first}\"\n")
                    # keep following continuation lines (if any)
                    out.extend(lines[i+1:k])
                    changed = True
                    i = k
                    continue
                else:
                    out.extend(lines[i:k])
                    i = k
                    continue
            else:
                # no msgstr line; just continue
                continue
        # default
        out.append(line)
        i += 1

    if changed:
        with open(po_path, 'w', encoding='utf-8') as f:
            f.writelines(out)
    return changed


def write_untranslated_dict_file(lang: str, untranslated: dict[str,str]) -> str:
    out_path = os.path.join(base_path, f'untranslated_msgids_{lang}.txt')
    # Write as JSON for robust escaping
    data = {key: '' for key in untranslated.keys()}
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')
    return out_path


def write_autotranslated_dict_file(lang: str, translations: dict[str,str]) -> str:
    """Write auto-translated strings to autotranslated_msgids_<lang>.txt for review."""
    out_path = os.path.join(base_path, f'autotranslated_msgids_{lang}.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(translations, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')
    return out_path


def auto_translate_untranslated(untranslated_map: dict[str, dict[str,str]], paid: bool = False) -> None:
    """Auto-translate untranslated strings in the untranslated map (lang -> untranslated dict)."""
    for lang, untranslated in untranslated_map.items():
        if lang == 'en':
            continue

        if not untranslated:
            print(f"No untranslated strings found for {lang}")
            continue

        print(f"Auto-translating {len(untranslated)} strings for {lang}...")
        translations = auto_translate_strings(untranslated, lang, paid)
        if translations:
            out_path = write_autotranslated_dict_file(lang, translations)
            print(f"Saved {len(translations)} auto-translations to '{out_path}' for review.")
        else:
            print(f"No translations returned for {lang}")

        if not paid:
            time.sleep(3)  # Avoid hitting rate limits on free model


def generate_untranslated_files(languages: list[str]) -> dict[str, dict[str,str]]:
    """Generate untranslated_msgids_<lang>.txt files for all languages.

    Returns a map of language -> untranslated dict (msgid -> '') pairs.
    """
    result: dict[str, dict[str,str]] = {}
    for lang in languages:
        po_file = os.path.join(LOCALES_DIR, lang, 'LC_MESSAGES', 'gui-subtrans.po')
        untranslated = _collect_untranslated_msgids(po_file)
        out_path = write_untranslated_dict_file(lang, untranslated)
        result[lang] = untranslated
        print(f"Extracted {len(untranslated)} untranslated msgids to '{out_path}'.")
    return result


def integrate_autotranslations(languages: list[str]) -> None:
    """Integrate auto-translated files if they exist."""
    for lang in languages:
        if lang == 'en':
            continue
        auto_dict_path = os.path.join(base_path, f'autotranslated_msgids_{lang}.txt')
        if os.path.exists(auto_dict_path):
            po_file = os.path.join(LOCALES_DIR, lang, 'LC_MESSAGES', 'gui-subtrans.po')
            translations = _parse_translations_file(auto_dict_path)
            if translations:
                updated = _update_po_with_translations(po_file, translations)
                if updated:
                    print(f"Integrated {updated} auto-translations into {po_file}")
                    # Compile after updates
                    mo_path = os.path.splitext(po_file)[0] + '.mo'
                    run_cmd(['msgfmt', '-o', mo_path, po_file])

def _parse_translations_file(path: str) -> dict[str,str]:
    """Safely parse a dict-like file produced by write_untranslated_dict_file, returning only non-empty translations."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Prefer JSON (new format)
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Fallback to legacy Python dict literal
            data = ast.literal_eval(content)
        if not isinstance(data, dict):
            return {}

        # Normalize keys to match PO msgids by converting Python string escaping to PO file format escaping.
        # Transform manual keys into the PO-escaped form: backslashes (\\), quotes (\"), newlines (\n).
        def _norm_key_po(k: str) -> str:
            s = str(k)
            # Normalize Windows newlines to LF first
            s = s.replace('\r\n', '\n')
            # Convert actual newlines to literal \n; leave existing \n sequences as-is
            s = s.replace('\n', r'\n')
            # Escape only unescaped double quotes to match PO msgid encoding
            s = re.sub(r'(?<!\\)"', r'\\"', s)
            return s
        # Keep only entries with non-empty translations
        return {_norm_key_po(k): str(v) for k, v in data.items() if isinstance(v, str) and v != ''}

    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"Warning: could not parse manual translations in {path}: {e}")
        return {}


def _update_po_with_translations(po_path: str, translations: dict[str,str]) -> int:
    """Update msgstr for matching msgid entries. Returns count of updated entries."""
    if not translations:
        return 0

    try:
        with open(po_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return 0

    out: list[str] = []
    i = 0
    updated = 0
    current_msgid: str|None = None
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        if stripped.startswith('msgid '):
            # capture full msgid possibly spanning quoted lines
            first_content = _extract_quoted(stripped) if '"' in stripped else ''
            j = i + 1
            parts = [first_content]
            while j < len(lines) and _is_quoted_line(lines[j]):
                parts.append(_extract_quoted(lines[j]))
                j += 1
            current_msgid = ''.join(parts)
            # write original msgid lines as-is (we don't rewrap here)
            out.extend(lines[i:j])
            i = j
            # next should be msgstr or comments/blank
            if i < len(lines):
                next_line = lines[i]
                nstrip = next_line.lstrip()
                if nstrip.startswith('msgstr '):
                    # collect existing msgstr continuation to know the block
                    msgstr_indent_len = len(next_line) - len(nstrip)
                    msgstr_indent = next_line[:msgstr_indent_len]
                    msgstr_first = _extract_quoted(nstrip) if '"' in nstrip else ''
                    k = i + 1
                    while k < len(lines) and _is_quoted_line(lines[k]):
                        k += 1

                    if current_msgid in translations and msgstr_first == '':
                        # Replace msgstr block with our translation (single line)
                        value = _escape_po(translations[current_msgid])
                        # If msgid ends with literal \n, ensure msgstr also ends with literal \n to satisfy msgfmt
                        ends_with_nl = current_msgid.endswith(r'\n')
                        if ends_with_nl and not value.endswith(r'\n'):
                            value = value + r'\n'
                        out.append(f"{msgstr_indent}msgstr \"{value}\"\n")
                        updated += 1
                        i = k
                        continue
                    else:
                        # keep original msgstr block untouched
                        out.extend(lines[i:k])
                        i = k
                        continue
                else:
                    # not a msgstr line; just continue
                    continue
            continue

        # default fall-through
        out.append(line)
        i += 1

    if updated:
        with open(po_path, 'w', encoding='utf-8') as f:
            f.writelines(out)
    return updated


def integrate_manual_translations(languages: list[str]) -> None:
    total_updated = 0
    for lang in languages:
        po_path = os.path.join(LOCALES_DIR, lang, 'LC_MESSAGES', 'gui-subtrans.po')
        dict_path = os.path.join(base_path, f'untranslated_msgids_{lang}.txt')
        translations = _parse_translations_file(dict_path)
        if not translations:
            print(f"No manual translations found for {lang} (or none filled). Skipping.")
            continue
        updated = _update_po_with_translations(po_path, translations)
        if updated:
            total_updated += updated
            print(f"Integrated {updated} translations into {po_path}")
            # Compile after updates
            mo_path = os.path.splitext(po_path)[0] + '.mo'
            run_cmd(['msgfmt', '-o', mo_path, po_path])
        else:
            print(f"No matching empty entries updated for {lang}.")
    if total_updated:
        print(f"Integrated total {total_updated} translations across locales.")


def main():
    parser = argparse.ArgumentParser(description='One-stop localization workflow for LLM-Subtrans')
    parser.add_argument('--auto', action='store_true', 
                       help='Automatically translate untranslated strings using OpenRouter API (requires OPENROUTER_API_KEY environment variable)')
    parser.add_argument('--paid', action='store_true',
                       help='Use paid translation model for auto-translation (default is free model)')
    args = parser.parse_args()

    auto_translate = args.auto
    paid_translation = args.paid

    if auto_translate:
        api_key = os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            print("Error: --auto requires OPENROUTER_API_KEY environment variable to be set")
            sys.exit(1)
        print("Auto-translation mode enabled")

    steps = "{num}/7" if auto_translate else "{num}/5"

    # 1) Extract strings -> POT
    print(f"{steps.format(num=1)} Extracting strings…")
    run_extract_strings()

    # discover locales
    languages = get_available_locales()
    print(f"Locales: {languages}")

    # 2) Merge & compile
    print(f"{steps.format(num=2)} Merging POT into PO and compiling…")
    merge_and_compile(languages)

    # 3) Integrate manual translations if present
    print(f"{steps.format(num=3)} Integrating any manual translations from untranslated_msgids_*.txt…")
    integrate_manual_translations(languages)

    # 4) Generate untranslated lists
    print(f"{steps.format(num=4)} Generating untranslated lists…")
    untranslated_map = generate_untranslated_files(languages)

    # 5) Auto-translate if requested
    if auto_translate:
        print(f"{steps.format(num=5)} Auto-translating untranslated strings…")
        auto_translate_untranslated(untranslated_map, paid=paid_translation)

        print(f"{steps.format(num=6)} Integrating auto-translations from autotranslated files…")
        integrate_autotranslations(languages)

        print(f"{steps.format(num=7)} Final untranslated lists generation…")
        generate_untranslated_files(languages)

    print("Done.")

if __name__ == '__main__':
    main()


