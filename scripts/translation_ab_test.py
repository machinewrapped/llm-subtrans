"""
Translate one subtitle file two ways and have a judge model compare the results blind.

Each arm is a provider and model, with optional setting overrides such as a different instruction file.
Arms can be set up in ARM_A_SETTINGS and ARM_B_SETTINGS below, on the command line, or both; the command line wins.
Where the two translations of a line differ, the judge sees the source line and both translations as X and Y, in random order per line.
The judge is any OpenAI-compatible chat endpoint, OpenRouter by default.
Verdicts are unblinded and summarised in report.md in the output directory.
Existing translations can be judged instead with --a-file and --b-file.

Example:
    translation_ab_test.py movie.ko.srt -l English --a Gemini:gemini-3.8-flash --b Gemini:gemini-3.8-flash
        --b-set instruction_file=my_instructions.txt --judge-model ~openai/gpt-luna-latest -o ab_results
"""
import html
import json
import logging
import math
import os
import random
import statistics
import sys
from argparse import ArgumentParser, ArgumentTypeError, Namespace
from dataclasses import dataclass

import httpx
import regex

from PySubtrans import init_options, init_project, init_translator
from PySubtrans.SettingsType import SettingsType, SettingType
from PySubtrans.SubtitleLine import SubtitleLine

# Settings for each arm, including 'provider' and 'model' if --a and --b are not given.
# Settings given on the command line are applied on top.
ARM_A_SETTINGS = SettingsType({
})

ARM_B_SETTINGS = SettingsType({
})

DEFAULT_JUDGE_SERVER = "https://openrouter.ai/api/v1"
JUDGE_TIMEOUT_SECONDS = 600.0

# A line is counted as shorter or longer in one arm when its length differs by at least this fraction
LENGTH_CHANGE_FRACTION = 0.2

# Setting values that are read as numbers, so that other strings such as version numbers stay strings
INTEGER_VALUE = regex.compile(r'^[+-]?\d+$')
FLOAT_VALUE = regex.compile(r'^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$')

# Settings whose values are credentials, which are left out of arm descriptions because reports are shared
SECRET_SETTING = regex.compile(r'key|token|secret|password', regex.IGNORECASE)

# A row starting with a dash marks a speaker turn in a dialogue cue
DIALOGUE_ROW = regex.compile(r'^\s*[-–—]\s', regex.MULTILINE)

VERDICT_LINE = regex.compile(r'^\s*(\d+)\s*\|\s*(X|Y|same)\s*\|\s*(high|medium|low)\s*\|\s*(.*)$', regex.IGNORECASE)

JUDGE_SYSTEM_PROMPT = "You compare two translations of the same subtitles. Answer only in the format requested."

JUDGEMENT_CAVEAT = "One model's line-by-line opinion. It can miss differences a viewer notices, so read the translations side by side before relying on it."

JUDGE_PROMPT = """Each item below is one subtitle line from {movie}, translated into {language} in two ways, X and Y.
The line being judged is marked >>, with the lines around it in the source and in each translation for context.

For each item, judge which translation of the marked line makes the better subtitle for someone watching the film: X, Y or same.
Give your confidence (high, medium or low) and a reason of at most 15 words.

Answer with one line per item, for all {count} items, in exactly this format and nothing else:
<item id>|<X, Y or same>|<high, medium or low>|<reason>

{items}"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg: #ffffff; --fg: #1d1d1f; --muted: #6e6e73; --line: #e2e2e6; --panel: #f5f5f7;
         --changed: #fff8e6; --preferred: #e3f4e8; --long: #b54708; --accent: #2f5bd3; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #161618; --fg: #ececf0; --muted: #9a9aa2; --line: #2e2e33; --panel: #1f1f23;
           --changed: #2c2716; --preferred: #17301f; --long: #f5a35c; --accent: #8aa8ff; }}
}}
body {{ margin: 0; padding: 24px; background: var(--bg); color: var(--fg); font: 14px/1.45 system-ui, sans-serif; }}
h1 {{ font-size: 20px; margin: 0 0 8px; }}
p, li {{ color: var(--muted); }}
table {{ border-collapse: collapse; }}
.stats {{ display: flex; flex-wrap: wrap; gap: 24px; margin: 16px 0 24px; }}
.stats table td, .stats table th {{ padding: 4px 12px; border-bottom: 1px solid var(--line); text-align: right; }}
.stats table td:first-child, .stats table th:first-child {{ text-align: left; }}
.filters {{ position: sticky; top: 0; background: var(--bg); padding: 8px 0; z-index: 2; }}
.filters button {{ font: inherit; margin-right: 6px; padding: 4px 12px; border: 1px solid var(--line); border-radius: 14px;
                   background: var(--panel); color: var(--fg); cursor: pointer; }}
.filters button.active {{ border-color: var(--accent); color: var(--accent); }}
.lines {{ width: 100%; table-layout: fixed; }}
.lines th {{ position: sticky; top: 46px; background: var(--panel); text-align: left; padding: 6px 8px; z-index: 1; }}
.lines td {{ padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; white-space: pre-wrap; word-wrap: break-word; }}
.lines col.num {{ width: 56px; }} .lines col.time {{ width: 96px; }} .lines col.verdict {{ width: 20%; }}
tr.different td.a, tr.different td.b, tr.layout td.a, tr.layout td.b {{ background: var(--changed); }}
td.preferred {{ background: var(--preferred) !important; }}
.count {{ display: block; font-size: 11px; color: var(--muted); }}
.count.long {{ color: var(--long); font-weight: 600; }}
.meta {{ color: var(--muted); font-size: 12px; }}
body.only-different tbody tr.identical, body.only-different tbody tr.missing {{ display: none; }}
body.only-judged tbody tr:not([data-verdict]) {{ display: none; }}
body.only-a tbody tr:not([data-verdict="A"]) {{ display: none; }}
body.only-b tbody tr:not([data-verdict="B"]) {{ display: none; }}
body.only-long tbody tr:not(.has-long) {{ display: none; }}
</style>
</head>
<body>
<h1>{title}</h1>
<ul>{arms}</ul>
<p>{summary}</p>
<div class="stats">{stats}</div>
{caveat}
<div class="filters">
<button class="active" data-filter="">All lines</button>
<button data-filter="only-different">Different</button>
<button data-filter="only-long">Long</button>
{judge_filters}
</div>
<table class="lines">
<colgroup><col class="num"><col class="time"><col><col><col>{verdict_col}</colgroup>
<thead><tr><th>#</th><th>Time</th><th>Source</th><th>A</th><th>B</th>{verdict_head}</tr></thead>
<tbody>
{rows}
</tbody>
</table>
<script>
document.querySelectorAll('.filters button').forEach(button => button.addEventListener('click', () => {{
  document.body.className = button.dataset.filter;
  document.querySelectorAll('.filters button').forEach(other => other.classList.toggle('active', other === button));
}}));
</script>
</body>
</html>
"""


@dataclass
class Arm:
    """One way of translating the file: a provider, a model and any other settings."""
    label : str
    provider : str
    model : str
    settings : SettingsType
    file : str|None = None

    @property
    def description(self) -> str:
        if self.file:
            return f"existing translation {self.file}"

        settings = ', '.join(f"{key}={value}" for key, value in self.settings.items()
                             if key not in ('provider', 'model') and not SECRET_SETTING.search(key))
        return f"{self.provider}:{self.model}" + (f" ({settings})" if settings else "")


@dataclass
class Site:
    """A line whose two translations differ, with the lines around it in the source and in each translation."""
    number : int
    start : str
    end : str
    duration : float
    source : str
    translations : dict[str, str]
    source_before : list[str]
    source_after : list[str]
    translations_before : dict[str, list[str]]
    translations_after : dict[str, list[str]]


@dataclass
class ArmStats:
    """Measures of one arm's translation, and how its lines compare in length with the other arm's."""
    lines : int
    characters : int
    mean_length : float
    p90_length : int
    long_lines : int
    multi_row : int
    dialogue : int
    longer : int
    shorter : int


@dataclass
class PairStats:
    """How the two arms' translations of the same lines compare."""
    both : int
    identical : int
    layout_only : int
    different : int


def ParseArm(label : str, spec : str|None, base : SettingsType, overrides : list[str], file : str|None = None) -> Arm:
    """
    Build an arm from its settings, KEY=VALUE overrides, and an optional PROVIDER:MODEL spec, which take precedence in that order.
    An arm read from an existing translation file needs no provider or model.
    """
    settings = SettingsType(base)
    settings.update(ParseOverride(override) for override in overrides)

    if spec:
        provider, separator, model = spec.partition(':')
        if not separator or not provider or not model:
            raise ValueError(f"Arm {label} must be given as PROVIDER:MODEL, not '{spec}'")
        settings.update({'provider': provider, 'model': model})

    provider, model = settings.get_str('provider') or "", settings.get_str('model') or ""
    if not file and (not provider or not model):
        raise ValueError(f"Arm {label} needs a provider and model, from --{label.lower()} or its settings")

    return Arm(label, provider, model, settings, file)


def ParseOverride(override : str) -> tuple[str, SettingType]:
    """Parse a KEY=VALUE setting, reading booleans and numbers as such."""
    key, separator, value = override.partition('=')
    if not separator or not key:
        raise ValueError(f"Setting overrides must be given as KEY=VALUE, not '{override}'")

    if value.lower() in ('true', 'false'):
        return key, value.lower() == 'true'

    if INTEGER_VALUE.match(value):
        return key, int(value)

    if FLOAT_VALUE.match(value):
        return key, float(value)

    return key, value


def PositiveInt(value : str) -> int:
    """An argument that must be a whole number above zero."""
    number = int(value)
    if number <= 0:
        raise ArgumentTypeError(f"must be above zero, not {value}")
    return number


def NonNegativeInt(value : str) -> int:
    """An argument that must be a whole number, zero or above."""
    number = int(value)
    if number < 0:
        raise ArgumentTypeError(f"must be zero or above, not {value}")
    return number


def NonNegativeFloat(value : str) -> float:
    """An argument that must be a number, zero or above."""
    number = float(value)
    if number < 0.0:
        raise ArgumentTypeError(f"must be zero or above, not {value}")
    return number


def TranslateArm(arm : Arm, args : Namespace, run : int) -> dict[int, str]:
    """Translate the input file with an arm's settings, save it, and return its translations by line number."""
    settings = SettingsType({
        'target_language': args.target_language,
        'movie_name': args.movie or os.path.splitext(os.path.basename(args.input))[0],
    })
    settings.update(arm.settings)

    options = init_options(**settings)
    project = init_project(options, filepath=args.input)
    translator = init_translator(options)

    # Each run saves to its own file in the output directory, not beside the input where the arms would overwrite each other
    project.UpdateOutputPath(os.path.join(args.output_dir, f"{arm.label}{run}.srt"))

    logging.info(f"Translating arm {arm.label} run {run}: {arm.description}")
    project.TranslateSubtitles(translator)

    return {line.number: line.text or "" for line in project.subtitles.translated or []}


def LoadTranslation(path : str, originals : list[SubtitleLine]) -> dict[int, str]:
    """Read an existing translation, matched to the source lines by start time."""
    numbers = {line.start: line.number for line in originals}
    translated = init_project(filepath=path, auto_batch=False).subtitles.originals or []
    return {numbers[line.start]: line.text or "" for line in translated if line.start in numbers}


def FindSites(originals : list[SubtitleLine], first : dict[int, str], second : dict[int, str],
              min_change : float, context : int = 2) -> list[Site]:
    """
    The lines both arms translated differently, with up to `context` lines either side in the source and in each translation.
    With min_change, only lines whose length changed by at least that fraction of the longer translation.
    """
    arms = {'A': first, 'B': second}
    sites : list[Site] = []
    for index, line in enumerate(originals):
        if line.number not in first or line.number not in second:
            continue

        a, b = Normalise(first[line.number]), Normalise(second[line.number])
        if a == b or abs(len(a) - len(b)) < min_change * max(len(a), len(b)):
            continue

        before = originals[max(0, index - context):index]
        after = originals[index + 1:index + 1 + context]
        sites.append(Site(
            line.number, line.srt_start, line.srt_end, line.duration.total_seconds(), line.text or "",
            {label: texts[line.number] for label, texts in arms.items()},
            [other.text or "" for other in before], [other.text or "" for other in after],
            {label: [texts.get(other.number, "") for other in before] for label, texts in arms.items()},
            {label: [texts.get(other.number, "") for other in after] for label, texts in arms.items()},
        ))

    return sites


def Normalise(text : str) -> str:
    """Text with its line breaks and spacing collapsed, so layout alone does not make a difference."""
    return ' '.join(text.split())


def BuildItems(sites : list[Site], key : dict[int, dict[str, str]]) -> str:
    """The blind items for the judge, with each site's arms shown as X and Y in its own random order."""
    def passage(label : str, before : list[str], line : str, after : list[str]) -> list[str]:
        return ([f"{label}:"] + [f"   {Flatten(text)}" for text in before] + [f">> {Flatten(line)}"]
                + [f"   {Flatten(text)}" for text in after])

    items : list[str] = []
    for site in sites:
        order = key[site.number]
        lines = [f"## Item {site.number} ({site.start} --> {site.end}, shown for {site.duration:.1f}s)"]
        lines += passage("Source", site.source_before, site.source, site.source_after)
        for label in ('X', 'Y'):
            arm = order[label]
            lines += passage(label, site.translations_before[arm], site.translations[arm], site.translations_after[arm])
        items.append('\n'.join(lines))

    return '\n\n'.join(items)


def Flatten(text : str) -> str:
    """Show a multi-row subtitle on one line, with its rows separated by a slash."""
    return ' / '.join(row.strip() for row in text.splitlines() if row.strip())


def AskJudge(prompt : str, args : Namespace) -> str:
    """Send one request to the judge's chat completions endpoint and return its reply."""
    response = httpx.post(
        f"{args.judge_server.rstrip('/')}/chat/completions",
        headers={'Authorization': f"Bearer {args.judge_key}"},
        json={'model': args.judge_model, 'messages': [
            {'role': 'system', 'content': JUDGE_SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt},
        ]},
        timeout=JUDGE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content'] or ""


def ParseVerdicts(reply : str, key : dict[int, dict[str, str]]) -> dict[int, tuple[str, str, str]]:
    """Read the judge's verdict lines, unblinded to the arm each preferred."""
    verdicts : dict[int, tuple[str, str, str]] = {}
    for line in reply.splitlines():
        match = VERDICT_LINE.match(line)
        if not match:
            continue

        number, pick, confidence, reason = int(match[1]), match[2], match[3].lower(), match[4].strip()
        if number not in key:
            continue

        winner = 'same' if pick.lower() == 'same' else key[number][pick.upper()]
        verdicts[number] = (winner, confidence, reason)

    return verdicts


def Judge(sites : list[Site], args : Namespace) -> tuple[dict[int, dict[str, str]], dict[int, tuple[str, str, str]]]:
    """Have the judge compare every site blind, in batches, and return the key and the unblinded verdicts."""
    rng = random.Random(args.seed)
    key : dict[int, dict[str, str]] = {}
    for site in sites:
        arms = ['A', 'B']
        rng.shuffle(arms)
        key[site.number] = {'X': arms[0], 'Y': arms[1]}

    movie = args.movie or os.path.splitext(os.path.basename(args.input))[0]
    verdicts : dict[int, tuple[str, str, str]] = {}
    blind : list[str] = []
    replies : list[str] = []

    for first in range(0, len(sites), args.judge_batch):
        batch = sites[first:first + args.judge_batch]
        items = BuildItems(batch, key)
        blind.append(items)

        logging.info(f"Judging sites {first + 1}-{first + len(batch)} of {len(sites)}")
        try:
            reply = AskJudge(JUDGE_PROMPT.format(movie=movie, language=args.target_language, count=len(batch), items=items), args)
        except httpx.HTTPError as e:
            logging.error(f"Judge request failed for sites {first + 1}-{first + len(batch)}: {e}")
            continue

        replies.append(reply)
        batch_verdicts = ParseVerdicts(reply, key)
        if len(batch_verdicts) < len(batch):
            logging.warning(f"Judge returned {len(batch_verdicts)} verdicts for {len(batch)} sites")

        verdicts.update(batch_verdicts)

    WriteText(args, 'sites_blind.md', '\n\n'.join(blind))
    WriteText(args, 'judge_replies.txt', '\n\n'.join(replies))
    with open(os.path.join(args.output_dir, 'key.json'), 'w', encoding='utf-8') as file:
        json.dump(key, file, indent=1)

    return key, verdicts


def MeasureArm(texts : dict[int, str], other : dict[int, str], long_line : int) -> ArmStats:
    """Line counts and lengths for one arm, and how many of its lines are longer or shorter than the other arm's."""
    lengths = sorted(len(Normalise(text)) for text in texts.values())
    shared = [number for number in texts if number in other]
    return ArmStats(
        lines=len(texts),
        characters=sum(lengths),
        mean_length=statistics.mean(lengths) if lengths else 0.0,
        p90_length=lengths[int(0.9 * (len(lengths) - 1))] if lengths else 0,
        long_lines=sum(1 for length in lengths if length > long_line),
        multi_row=sum(1 for text in texts.values() if '\n' in text.strip()),
        dialogue=sum(1 for text in texts.values() if len(DIALOGUE_ROW.findall(text)) > 1),
        longer=sum(1 for number in shared if len(Normalise(texts[number])) > len(Normalise(other[number]))),
        shorter=sum(1 for number in shared if len(Normalise(texts[number])) < len(Normalise(other[number]))),
    )


def ComparePair(first : dict[int, str], second : dict[int, str]) -> PairStats:
    """Count the lines both arms translated identically, identically but for layout, and differently."""
    shared = [number for number in first if number in second]
    identical = sum(1 for number in shared if first[number].strip() == second[number].strip())
    same_words = sum(1 for number in shared if Normalise(first[number]) == Normalise(second[number]))
    return PairStats(both=len(shared), identical=identical, layout_only=same_words - identical, different=len(shared) - same_words)


def StatsRows(stats : dict[str, ArmStats], long_line : int) -> list[tuple[str, str, str]]:
    """The per-arm statistics as table rows of (measure, A, B)."""
    measures : list[tuple[str, str]] = [
        ("Lines translated", 'lines'), ("Characters", 'characters'), ("Mean line length", 'mean_length'),
        ("90th percentile line length", 'p90_length'), (f"Lines over {long_line} characters", 'long_lines'),
        ("Lines with more than one row", 'multi_row'), ("Dialogue lines", 'dialogue'),
        ("Longer than the other arm", 'longer'), ("Shorter than the other arm", 'shorter'),
    ]

    def show(value : int|float) -> str:
        return f"{value:.1f}" if isinstance(value, float) else str(value)

    return [(label, show(getattr(stats['A'], field)), show(getattr(stats['B'], field))) for label, field in measures]


def Tally(verdicts : dict[int, tuple[str, str, str]]) -> tuple[dict[str, int], dict[str, int]]:
    """Verdicts for each arm and 'same', and the high-confidence ones for each arm."""
    tally = {winner: sum(1 for verdict in verdicts.values() if verdict[0] == winner) for winner in ('A', 'B', 'same')}
    confident = {winner: sum(1 for verdict in verdicts.values() if verdict[0] == winner and verdict[1] == 'high') for winner in ('A', 'B')}
    return tally, confident


def RunDifferences(runs : dict[str, list[dict[int, str]]]) -> list[str]:
    """A sentence for each repeat run, saying on how many lines it is worded differently from the first."""
    sentences : list[str] = []
    for label, (base, *repeats) in runs.items():
        for number, repeat in enumerate(repeats, start=2):
            changed = sum(1 for line, text in base.items() if Normalise(text) != Normalise(repeat.get(line, "")))
            sentences.append(f"Run {number} of {label} is worded differently from run 1 on {changed} lines.")

    return sentences


def Report(arms : list[Arm], runs : dict[str, list[dict[int, str]]], originals : list[SubtitleLine],
           sites : list[Site], verdicts : dict[int, tuple[str, str, str]], args : Namespace) -> str:
    """Summarise the statistics, verdicts and run-to-run differences as markdown."""
    first, second = runs['A'][0], runs['B'][0]
    stats = {'A': MeasureArm(first, second, args.long_line), 'B': MeasureArm(second, first, args.long_line)}
    pair = ComparePair(first, second)

    lines : list[str] = [f"# Translation A/B test: {os.path.basename(args.input)} into {args.target_language}", ""]
    for arm in arms:
        lines.append(f"- **{arm.label}:** {arm.description}")
    if args.judge_model:
        lines.append(f"- **Judge:** {args.judge_model} at {args.judge_server}")

    lines += ["", f"{len(originals)} source lines. Of the {pair.both} both arms translated, {pair.identical} are identical, "
              f"{pair.layout_only} differ only in layout, and {pair.different} are worded differently.", "",
              "| | A | B |", "|---|---|---|"]
    lines += [f"| {label} | {a} | {b} |" for label, a, b in StatsRows(stats, args.long_line)]
    lines += [f"\n{sentence}" for sentence in RunDifferences(runs)]

    if verdicts:
        tally, confident = Tally(verdicts)
        lines += ["", "## Model judgement", "", f"{JUDGEMENT_CAVEAT} Judged by {args.judge_model}.", "",
                  f"{len(sites)} lines judged, {len(verdicts)} verdicts.", "",
                  "| Preferred | Lines | High confidence |", "|---|---|---|",
                  f"| A | {tally['A']} | {confident['A']} |",
                  f"| B | {tally['B']} | {confident['B']} |",
                  f"| Same | {tally['same']} | |", "",
                  f"Sign test, ignoring 'same': p = {SignTestPValue(tally['A'], tally['B']):.3g}", "",
                  f"| Length (differing by {LENGTH_CHANGE_FRACTION:.0%} or more) | Lines | A preferred | B preferred | p |",
                  "|---|---|---|---|---|"]
        for group, count, a_wins, b_wins in LengthBreakdown(sites, verdicts):
            lines.append(f"| {group} | {count} | {a_wins} | {b_wins} | {SignTestPValue(a_wins, b_wins):.3g} |")

        lines += ["", "## Verdicts", ""]
        by_number = {site.number: site for site in sites}
        for number, (winner, confidence, reason) in sorted(verdicts.items()):
            site = by_number[number]
            lines += [f"**{number}** ({site.start}) {winner}, {confidence}: {reason}",
                      f"- Source: {Flatten(site.source)}",
                      f"- A: {Flatten(site.translations['A'])}",
                      f"- B: {Flatten(site.translations['B'])}", ""]

    return '\n'.join(lines)


def BuildHtml(arms : list[Arm], runs : dict[str, list[dict[int, str]]], originals : list[SubtitleLine],
              sites : list[Site], verdicts : dict[int, tuple[str, str, str]], args : Namespace) -> str:
    """A page with the statistics and every line side by side, with any verdicts, to read the two translations together."""
    first, second = runs['A'][0], runs['B'][0]
    stats = {'A': MeasureArm(first, second, args.long_line), 'B': MeasureArm(second, first, args.long_line)}
    pair = ComparePair(first, second)
    escape = html.escape

    tables = ['<table><tr><th></th><th>A</th><th>B</th></tr>'
              + ''.join(f"<tr><td>{escape(label)}</td><td>{a}</td><td>{b}</td></tr>" for label, a, b in StatsRows(stats, args.long_line))
              + '</table>']

    if verdicts:
        tally, confident = Tally(verdicts)
        tables.append('<table><tr><th>Judge preferred</th><th>Lines</th><th>High confidence</th></tr>'
                      f"<tr><td>A</td><td>{tally['A']}</td><td>{confident['A']}</td></tr>"
                      f"<tr><td>B</td><td>{tally['B']}</td><td>{confident['B']}</td></tr>"
                      f"<tr><td>Same</td><td>{tally['same']}</td><td></td></tr>"
                      f"<tr><td>Sign test</td><td colspan=\"2\">p = {SignTestPValue(tally['A'], tally['B']):.3g}</td></tr></table>")
        tables.append(f'<table><tr><th>Length (&ge;{LENGTH_CHANGE_FRACTION:.0%} apart)</th><th>Lines</th><th>A</th><th>B</th><th>p</th></tr>'
                      + ''.join(f"<tr><td>{group}</td><td>{count}</td><td>{a}</td><td>{b}</td><td>{SignTestPValue(a, b):.3g}</td></tr>"
                                for group, count, a, b in LengthBreakdown(sites, verdicts))
                      + '</table>')

    def cell(label : str, text : str|None, verdict : tuple[str, str, str]|None) -> str:
        if text is None:
            return f'<td class="{label.lower()}"><span class="meta">not translated</span></td>'

        length = len(Normalise(text))
        preferred = ' preferred' if verdict and verdict[0] == label else ''
        long = ' long' if length > args.long_line else ''
        return f'<td class="{label.lower()}{preferred}">{escape(text.strip())}<span class="count{long}">{length}</span></td>'

    rows : list[str] = []
    for line in originals:
        a, b = first.get(line.number), second.get(line.number)
        if a is None or b is None:
            status = 'missing'
        elif a.strip() == b.strip():
            status = 'identical'
        else:
            status = 'layout' if Normalise(a) == Normalise(b) else 'different'

        verdict = verdicts.get(line.number)
        has_long = any(text is not None and len(Normalise(text)) > args.long_line for text in (a, b))
        classes = status + (' has-long' if has_long else '')
        attribute = f' data-verdict="{verdict[0]}"' if verdict else ''
        verdict_cell = ''
        if verdicts:
            verdict_cell = (f'<td><strong>{escape(verdict[0])}</strong> <span class="meta">{escape(verdict[1])}</span><br>{escape(verdict[2])}</td>'
                            if verdict else '<td></td>')

        rows.append(f'<tr class="{classes}"{attribute}><td class="meta">{line.number}</td><td class="meta">{escape(line.srt_start)}</td>'
                    f'<td>{escape((line.text or "").strip())}</td>{cell("A", a, verdict)}{cell("B", b, verdict)}{verdict_cell}</tr>')

    title = f"Translation A/B test: {os.path.basename(args.input)} into {args.target_language}"
    arm_items = ''.join(f"<li><strong>{arm.label}:</strong> {escape(arm.description)}</li>" for arm in arms)
    if args.judge_model:
        arm_items += f"<li><strong>Judge:</strong> {escape(args.judge_model)}</li>"

    summary = (f"{len(originals)} source lines. Of the {pair.both} both arms translated, {pair.identical} are identical, "
               f"{pair.layout_only} differ only in layout, and {pair.different} are worded differently. "
               + ' '.join(RunDifferences(runs)))

    judge_filters = ('<button data-filter="only-judged">Judged</button><button data-filter="only-a">Judge preferred A</button>'
                     '<button data-filter="only-b">Judge preferred B</button>') if verdicts else ''

    caveat = f'<p><strong>Model judgement:</strong> {escape(JUDGEMENT_CAVEAT)}</p>' if verdicts else ''
    return HTML_TEMPLATE.format(title=escape(title), arms=arm_items, summary=escape(summary), stats=''.join(tables), caveat=caveat,
                                judge_filters=judge_filters, verdict_col='<col class="verdict">' if verdicts else '',
                                verdict_head='<th>Model verdict</th>' if verdicts else '', rows='\n'.join(rows))


def LengthBreakdown(sites : list[Site], verdicts : dict[int, tuple[str, str, str]]) -> list[tuple[str, int, int, int]]:
    """Verdicts grouped by whether A's or B's translation of the line is noticeably longer: (group, sites, A wins, B wins)."""
    groups : dict[str, list[str]] = {'A longer': [], 'B longer': [], 'Similar length': []}
    for site in sites:
        if site.number not in verdicts:
            continue

        a, b = len(Normalise(site.translations['A'])), len(Normalise(site.translations['B']))
        if abs(a - b) < LENGTH_CHANGE_FRACTION * max(a, b):
            group = 'Similar length'
        else:
            group = 'A longer' if a > b else 'B longer'
        groups[group].append(verdicts[site.number][0])

    return [(group, len(winners), winners.count('A'), winners.count('B')) for group, winners in groups.items()]


def SignTestPValue(wins : int, losses : int) -> float:
    """Two-sided sign test: the chance of a split at least this uneven if neither arm were better."""
    total = wins + losses
    if total == 0:
        return 1.0

    extreme = max(wins, losses)
    tail = sum(math.comb(total, k) for k in range(extreme, total + 1)) / 2 ** total
    return min(1.0, 2 * tail)


def WriteText(args : Namespace, filename : str, text : str) -> None:
    """Write a text file to the output directory."""
    with open(os.path.join(args.output_dir, filename), 'w', encoding='utf-8') as file:
        file.write(text)


def CreateParser() -> ArgumentParser:
    """Command line arguments for the A/B test."""
    parser = ArgumentParser(description="Translate a subtitle file two ways and have a judge model compare them blind")
    parser.add_argument('input', help="Subtitle file to translate")
    parser.add_argument('-l', '--target-language', required=True, help="Language to translate into")
    parser.add_argument('-o', '--output-dir', required=True, help="Directory for the translations, judge sheets and report")
    parser.add_argument('--a', help="Arm A as PROVIDER:MODEL, e.g. Gemini:gemini-3.8-flash (default: from ARM_A_SETTINGS)")
    parser.add_argument('--b', help="Arm B as PROVIDER:MODEL (default: from ARM_B_SETTINGS)")
    parser.add_argument('--set', action='append', default=[], metavar='KEY=VALUE', help="Setting override for both arms")
    parser.add_argument('--a-set', action='append', default=[], metavar='KEY=VALUE', help="Setting override for arm A")
    parser.add_argument('--b-set', action='append', default=[], metavar='KEY=VALUE', help="Setting override for arm B")
    parser.add_argument('--a-file', help="Judge this existing translation as arm A instead of translating")
    parser.add_argument('--b-file', help="Judge this existing translation as arm B instead of translating")
    parser.add_argument('--min-change', type=NonNegativeFloat, default=0.0, help="Only judge lines whose length changed by at least this fraction, e.g. 0.15")
    parser.add_argument('--runs', type=PositiveInt, default=1, help="Translations per arm; runs after the first only measure run-to-run differences")
    parser.add_argument('--movie', help="Film name for the translator and judge (default: the file name)")
    parser.add_argument('--judge-model', help="Model for the judge, e.g. ~openai/gpt-luna-latest (default: no judging, statistics and side-by-side only)")
    parser.add_argument('--judge-server', default=DEFAULT_JUDGE_SERVER, help="OpenAI-compatible API base URL for the judge (default: OpenRouter)")
    parser.add_argument('--judge-key', default=None, help="API key for the judge (default: OPENROUTER_API_KEY)")
    parser.add_argument('--judge-batch', type=PositiveInt, default=25, help="Sites per judge request")
    parser.add_argument('--judge-context', type=NonNegativeInt, default=2, help="Lines shown either side of each judged line, in the source and each translation")
    parser.add_argument('--max-sites', type=NonNegativeInt, default=0, help="Judge a random sample of at most this many sites (default: all)")
    parser.add_argument('--long-line', type=PositiveInt, default=70, help="Lines over this many characters count as long in the statistics")
    parser.add_argument('--seed', type=int, default=0, help="Seed for sampling sites and assigning X and Y")
    return parser


def main() -> int:
    parser = CreateParser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    args.judge_key = args.judge_key or os.getenv('OPENROUTER_API_KEY')
    if args.judge_model and not args.judge_key:
        parser.error("a judge API key is required (--judge-key or OPENROUTER_API_KEY)")

    os.makedirs(args.output_dir, exist_ok=True)
    try:
        arms = [ParseArm('A', args.a, ARM_A_SETTINGS, args.set + args.a_set, args.a_file),
                ParseArm('B', args.b, ARM_B_SETTINGS, args.set + args.b_set, args.b_file)]
    except ValueError as e:
        parser.error(str(e))

    originals = init_project(filepath=args.input, auto_batch=False).subtitles.originals or []

    runs : dict[str, list[dict[int, str]]] = {}
    for arm in arms:
        runs[arm.label] = [LoadTranslation(arm.file, originals)] if arm.file else [TranslateArm(arm, args, run) for run in range(1, args.runs + 1)]

    sites : list[Site] = []
    verdicts : dict[int, tuple[str, str, str]] = {}
    if args.judge_model:
        sites = FindSites(originals, runs['A'][0], runs['B'][0], args.min_change, args.judge_context)
        if args.max_sites and len(sites) > args.max_sites:
            sites = sorted(random.Random(args.seed).sample(sites, args.max_sites), key=lambda site: site.number)

        if sites:
            _key, verdicts = Judge(sites, args)
        else:
            logging.info("The two arms translated every line the same way, so there is nothing to judge")

    report = Report(arms, runs, originals, sites, verdicts, args)
    WriteText(args, 'report.md', report)
    WriteText(args, 'report.html', BuildHtml(arms, runs, originals, sites, verdicts, args))

    print(report.split("\n## Verdicts")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
