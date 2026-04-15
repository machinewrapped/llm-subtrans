"""
Terminology map test script.

Translates a subtitle file with use_terminology_map=True and collects per-batch
data about which terms are extracted, which are genuinely new, and whether the
model ever tries to override an existing translation.  Use this to evaluate and
iterate on the terminology prompt.

Usage:
    ./envsubtrans/Scripts/python.exe scripts/test_terminology.py subtitles.srt \\
        --provider Gemini --model gemini-2.5-flash --language Japanese

    # Save a full JSON report for later analysis:
    ./envsubtrans/Scripts/python.exe scripts/test_terminology.py subtitles.srt \\
        --provider OpenRouter --language French --output report.json

The API key and any other provider-specific settings are read from .env when
not supplied on the command line.
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
import time
from dataclasses import dataclass, field

from PySubtrans import (
    SubtitleError,
    SubtitleTranslator,
    init_options,
    init_subtitles,
    init_translation_provider,
    init_translator,
)
from PySubtrans.SubtitleBatch import SubtitleBatch

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class BatchRecord:
    """Data captured for one translated batch."""
    scene          : int
    batch          : int
    lines          : int
    injected_terms : dict[str, str]              # terminology map injected into the prompt
    returned_terms : dict[str, str]              # all terms the model emitted
    new_terms      : dict[str, str]              # terms added to the map for the first time
    conflict_terms : dict[str, tuple[str, str]]  # existing terms the model tried to retranslate
    response_text  : str|None = None             # exact model response text for this batch
    errors         : list[str] = field(default_factory=list)


@dataclass
class TermProvenance:
    """How and when a term was first observed during this run."""
    initial_value  : str|None = None
    first_injected : tuple[int, int]|None = None
    first_returned : tuple[int, int]|None = None
    first_added    : tuple[int, int]|None = None
    first_conflict : tuple[int, int]|None = None
    conflict_count : int = 0


@dataclass
class RunState:
    """Mutable run counters and per-term provenance."""
    total_lines      : int
    total_batches    : int
    start_time       : float = field(default_factory=time.perf_counter)
    processed_lines  : int = 0
    processed_batches: int = 0
    terms            : dict[str, TermProvenance] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def _ensure_term(state : RunState, term : str) -> TermProvenance:
    """Get or create term provenance entry."""
    if term not in state.terms:
        state.terms[term] = TermProvenance()
    return state.terms[term]


def _set_first(spot : tuple[int, int]|None, scene : int, batch : int) -> tuple[int, int]:
    """Set first-observed tuple only once."""
    return spot if spot is not None else (scene, batch)


def _format_sb(value : tuple[int, int]|None) -> str:
    """Render a scene/batch tuple for human-readable reports."""
    if value is None:
        return "-"
    scene, batch = value
    return f"{scene}.{batch}"

def _parse_terminology_context(raw : str|None) -> dict[str, str]:
    """Parse the pipe-delimited terminology stored in batch.context into a dict."""
    if not raw or not isinstance(raw, str):
        return {}
    result : dict[str, str] = {}
    for line in raw.splitlines():
        if '|' in line:
            k, _, v = line.partition('|')
            k, v = k.strip(), v.strip()
            if k and v:
                result[k] = v
    return result


def _make_batch_handler(records : list[BatchRecord], state : RunState):
    """Return a batch_translated handler that records per-batch context data."""

    def on_batch_translated(sender, batch : SubtitleBatch|None = None, **_):
        if batch is None:
            return

        # batch.context['terminology'] was stored before translation; it holds
        # exactly what was injected into the prompt for this batch.
        injected = _parse_terminology_context(batch.context.get('terminology'))  # type: ignore[arg-type]

        record = BatchRecord(
            scene=batch.scene,
            batch=batch.number,
            lines=batch.size,
            injected_terms=injected,
            returned_terms={},   # filled in by terminology_updated if the model returned terms
            new_terms={},
            conflict_terms={},
            response_text=batch.translation.full_text if batch.translation else None,
            errors=batch.error_messages,
        )
        records.append(record)

        state.processed_batches += 1
        state.processed_lines += batch.size

        for term in injected:
            info = _ensure_term(state, term)
            info.first_injected = _set_first(info.first_injected, batch.scene, batch.number)

        progress = (
            f"[{state.processed_batches}/{state.total_batches} batches | "
            f"{state.processed_lines}/{state.total_lines} lines]"
        )
        error_note = f" [errors: {len(record.errors)}]" if record.errors else ""
        print(
            f"  {progress} Scene {batch.scene} Batch {batch.number}: "
            f"translated, context terms={len(injected)}{error_note}"
        )

    return on_batch_translated


def _make_terminology_handler(records : list[BatchRecord], state : RunState):
    """Return a terminology_updated handler that enriches the latest batch record."""

    def on_terminology_updated(
        sender,
        returned_terms : dict[str, str]|None = None,
        new_terms : dict[str, str]|None = None,
        conflict_terms : dict[str, tuple[str, str]]|None = None,
        terminology_map : dict[str, str]|None = None,
        **_,
    ):
        if not records:
            return

        # terminology_updated always fires after batch_translated for the same batch
        rec = records[-1]
        rec.returned_terms = dict(returned_terms or {})
        rec.new_terms      = dict(new_terms or {})
        rec.conflict_terms = dict(conflict_terms or {})

        for term in rec.returned_terms:
            info = _ensure_term(state, term)
            info.first_returned = _set_first(info.first_returned, rec.scene, rec.batch)

        for term in rec.new_terms:
            info = _ensure_term(state, term)
            info.first_added = _set_first(info.first_added, rec.scene, rec.batch)

        for term in rec.conflict_terms:
            info = _ensure_term(state, term)
            info.first_conflict = _set_first(info.first_conflict, rec.scene, rec.batch)
            info.conflict_count += 1

        tag = f"Scene {rec.scene:>2} Batch {rec.batch:>2}"

        if rec.new_terms:
            pairs = ', '.join(f"{k}={v}" for k, v in rec.new_terms.items())
            print(f"  {tag}: +{len(rec.new_terms)} new  [{pairs}]")

        if rec.conflict_terms:
            for orig, (existing, proposed) in rec.conflict_terms.items():
                print(f"  {tag}: CONFLICT  '{orig}': kept '{existing}', model proposed '{proposed}'")

        if rec.returned_terms and not rec.new_terms and not rec.conflict_terms:
            print(f"  {tag}: {len(rec.returned_terms)} term(s) returned (all already known)")

    return on_terminology_updated


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def run(args : argparse.Namespace) -> int:
    options = init_options(
        provider=args.provider,
        model=args.model or None,
        api_key=args.api_key or None,
        target_language=args.language,
        instruction_file=args.instruction_file or 'instructions.txt',
        use_terminology_map=True,
        max_batch_size=args.max_batch_size,
        scene_threshold=args.scene_threshold,
        preprocess_subtitles=True,
        postprocess_translation=False,
    )

    source = pathlib.Path(args.subtitle_file)
    if not source.exists():
        print(f"Error: file not found: {source}", file=sys.stderr)
        return 1

    print(f"Loading: {source}")
    subtitles = init_subtitles(filepath=str(source), options=options)
    total_lines   = subtitles.linecount
    total_scenes  = subtitles.scenecount
    total_batches = sum(len(scene.batches) for scene in subtitles.scenes)
    print(f"Loaded {total_lines} lines in {total_scenes} scene(s), {total_batches} batch(es)")
    print(f"Provider: {args.provider}  Model: {args.model or 'default'}  Language: {args.language}")
    print(f"Max batch size: {args.max_batch_size}  Scene threshold: {args.scene_threshold}s")
    print()

    provider   = init_translation_provider(args.provider, options)
    translator : SubtitleTranslator = init_translator(options, translation_provider=provider)

    initial_map : dict[str, str] = {k: str(v) for k, v in subtitles.settings.get_dict('terminology_map').items()}

    state = RunState(total_lines=total_lines, total_batches=total_batches)
    for term, value in initial_map.items():
        state.terms[term] = TermProvenance(initial_value=value)

    records : list[BatchRecord] = []
    batch_handler = _make_batch_handler(records, state)
    terminology_handler = _make_terminology_handler(records, state)
    translator.events.batch_translated.connect(batch_handler, weak=False)
    translator.events.terminology_updated.connect(terminology_handler, weak=False)

    print("Translating ...\n")
    try:
        translator.TranslateSubtitles(subtitles)
    except SubtitleError as exc:
        logging.error("Translation failed: %s", exc)
        return 1

    final_map : dict[str, str] = {k: str(v) for k, v in subtitles.settings.get_dict('terminology_map').items()}

    _print_report(args, source, total_lines, total_scenes, records, initial_map, final_map, state)

    if args.output:
        _write_json(args, source, records, initial_map, final_map, state, args.output)

    return 0


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_report(
    args        : argparse.Namespace,
    source      : pathlib.Path,
    total_lines : int,
    total_scenes: int,
    records     : list[BatchRecord],
    initial_map : dict[str, str],
    final_map   : dict[str, str],
    state       : RunState,
) -> None:
    sep  = "=" * 72
    thin = "-" * 72

    print(f"\n{sep}")
    print("TERMINOLOGY MAP TEST REPORT")
    print(sep)
    print(f"File     : {source.name}")
    print(f"Provider : {args.provider}   Model: {args.model or 'default'}")
    print(f"Language : {args.language}")
    print(f"Lines    : {total_lines}   Scenes: {total_scenes}   Batches: {len(records)}")

    returning   = [r for r in records if r.returned_terms]
    adding      = [r for r in records if r.new_terms]
    conflicting = [r for r in records if r.conflict_terms]
    errored     = [r for r in records if r.errors]
    conflict_total = sum(len(r.conflict_terms) for r in conflicting)
    elapsed = time.perf_counter() - state.start_time
    added_terms = [k for k in final_map if k not in initial_map]

    print(f"Batches returning any terms    : {len(returning)}/{len(records)}")
    print(f"Batches adding new terms       : {len(adding)}/{len(records)}")
    print(f"Terms in initial map           : {len(initial_map)}")
    print(f"Terms added this run           : {len(added_terms)}")
    print(f"Total conflict attempts        : {conflict_total}")
    print(f"Run time                       : {elapsed:.1f}s")
    if conflicting:
        print(f"Batches with conflicts         : {len(conflicting)}/{len(records)}")
    if errored:
        print(f"Batches with errors            : {len(errored)}/{len(records)}")

    if state.total_batches and not records:
        print("WARNING: No batch events were captured although batches existed.")
        print("This usually indicates callbacks were not attached correctly.")

    # Per-batch table
    print(f"\nPER-BATCH BREAKDOWN")
    print(thin)
    print(f"{'Batch':<10} {'Lines':>5}  {'In ctx':>6}  {'Returned':>8}  {'New':>4}  {'Conf':>4}  New terms")
    print(thin)

    prev_scene = None
    for r in records:
        if r.scene != prev_scene:
            if prev_scene is not None:
                print()
            prev_scene = r.scene

        flags    = ' [ERROR]' if r.errors else ''
        new_str  = ', '.join(r.new_terms.keys()) if r.new_terms else ''
        conf_str = f" CONFLICT({', '.join(r.conflict_terms.keys())})" if r.conflict_terms else ''
        print(
            f"{r.scene}.{r.batch:<5}    {r.lines:>5}  {len(r.injected_terms):>6}  "
            f"{len(r.returned_terms):>8}  {len(r.new_terms):>4}  {len(r.conflict_terms):>4}  "
            f"{new_str}{conf_str}{flags}"
        )

    print(f"\nTERM ENTRY TIMELINE")
    print(thin)
    print(f"{'Term':<32} {'Value':<32} {'Entry':<10} {'Entered@':<10} {'Returned@':<10} {'Conf@':<10} {'#Conf':>5}")
    print(thin)

    def _entry_sort_key(term : str) -> tuple[int, int, int, str]:
        info = state.terms.get(term, TermProvenance())
        if info.initial_value is not None:
            return (0, 0, 0, term)
        if info.first_added is not None:
            return (1, info.first_added[0], info.first_added[1], term)
        # Term seen in events but not known to be added/initial; push to end.
        return (2, 999999, 999999, term)

    for term in sorted(final_map.keys(), key=_entry_sort_key):
        info = state.terms.get(term, TermProvenance())
        entry = 'initial' if info.initial_value is not None else 'added'
        entered_at = 'initial' if info.initial_value is not None else _format_sb(info.first_added)
        print(
            f"{term:<32.32} {final_map[term]:<32.32} {entry:<10} {entered_at:<10} "
            f"{_format_sb(info.first_returned):<10} {_format_sb(info.first_conflict):<10} {info.conflict_count:>5}"
        )

    added_records = [r for r in records if r.new_terms]
    if added_records:
        print(f"\nMODEL RESPONSES FOR TERM ENTRIES")
        print(thin)
        for r in added_records:
            term_list = ', '.join(f"{k}={v}" for k, v in r.new_terms.items())
            print(f"Scene {r.scene} Batch {r.batch}  Added: {term_list}")
            print("Model response:")
            if r.response_text:
                print(r.response_text)
            else:
                print("(no response text captured)")
            print(thin)

    if conflicting:
        print(f"\nMODEL RESPONSES FOR CONFLICTS")
        print(thin)
        for r in conflicting:
            print(f"Scene {r.scene} Batch {r.batch}  Conflicts: {', '.join(r.conflict_terms.keys())}")
            print("Model response:")
            if r.response_text:
                print(r.response_text)
            else:
                print("(no response text captured)")
            print(thin)

    # Conflict details
    if conflicting:
        print(f"\nCONFLICTS  (model tried to change an existing term)")
        print(thin)
        for r in conflicting:
            for orig, (kept, proposed) in r.conflict_terms.items():
                print(f"  Scene {r.scene} Batch {r.batch}: '{orig}'  kept='{kept}'  proposed='{proposed}'")

    # Final map
    print(f"\n{thin}")
    print(f"FINAL TERMINOLOGY MAP  ({len(final_map)} term(s))")
    print(thin)
    if final_map:
        max_key = max((len(k) for k in final_map), default=0)
        for orig, trans in final_map.items():
            print(f"  {orig:<{max_key}}  |  {trans}")
    else:
        print("  (empty - no terms were accumulated)")
    print()


def _write_json(
    args        : argparse.Namespace,
    source      : pathlib.Path,
    records     : list[BatchRecord],
    initial_map : dict[str, str],
    final_map   : dict[str, str],
    state       : RunState,
    output_path : str,
) -> None:
    adding      = [r for r in records if r.new_terms]
    conflicting = [r for r in records if r.conflict_terms]
    conflict_total = sum(len(r.conflict_terms) for r in conflicting)

    provenance = {
        term: {
            'initial_value': info.initial_value,
            'first_injected': {'scene': info.first_injected[0], 'batch': info.first_injected[1]} if info.first_injected else None,
            'first_returned': {'scene': info.first_returned[0], 'batch': info.first_returned[1]} if info.first_returned else None,
            'first_added': {'scene': info.first_added[0], 'batch': info.first_added[1]} if info.first_added else None,
            'first_conflict': {'scene': info.first_conflict[0], 'batch': info.first_conflict[1]} if info.first_conflict else None,
            'conflict_count': info.conflict_count,
            'entry_type': 'initial' if info.initial_value is not None else 'added',
            'entered_at': {'scene': info.first_added[0], 'batch': info.first_added[1]} if info.initial_value is None and info.first_added else None,
        }
        for term, info in state.terms.items()
    }

    report = {
        'file'               : str(source),
        'provider'           : args.provider,
        'model'              : args.model,
        'language'           : args.language,
        'max_batch_size'     : args.max_batch_size,
        'scene_threshold'    : args.scene_threshold,
        'total_batches'      : len(records),
        'adding_batches'     : len(adding),
        'conflicting_batches': len(conflicting),
        'conflict_count'     : conflict_total,
        'initial_map'        : initial_map,
        'final_map'          : final_map,
        'term_provenance'    : provenance,
        'batches'            : [
            {
                'scene'         : r.scene,
                'batch'         : r.batch,
                'lines'         : r.lines,
                'injected_terms': r.injected_terms,
                'returned_terms': r.returned_terms,
                'new_terms'     : r.new_terms,
                'conflict_terms': {k: list(v) for k, v in r.conflict_terms.items()},
                'response_text' : r.response_text,
                'errors'        : r.errors,
            }
            for r in records
        ],
    }
    out = pathlib.Path(output_path)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Full report saved to: {out}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args(argv : list[str]|None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test the terminology map feature with a real subtitle file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('subtitle_file',
                        help="Path to the subtitle file to translate")
    parser.add_argument('--provider', default='OpenRouter',
                        help="Translation provider (default: OpenRouter)")
    parser.add_argument('--model', default=None,
                        help="Model identifier (uses provider default if omitted)")
    parser.add_argument('--apikey', dest='api_key', default=None,
                        help="API key (reads from .env if omitted)")
    parser.add_argument('--language', default='English',
                        help="Target language (default: English)")
    parser.add_argument('--instructions', dest='instruction_file', default=None,
                        help="Path to an instructions file (default: instructions.txt)")
    parser.add_argument('--max-batch-size', dest='max_batch_size', type=int, default=50,
                        help="Max lines per batch (default: 50)")
    parser.add_argument('--scene-threshold', dest='scene_threshold', type=float, default=60.0,
                        help="Scene gap threshold in seconds (default: 60)")
    parser.add_argument('--output', default=None,
                        help="Write a full JSON report to this path")
    parser.add_argument('--verbose', action='store_true',
                        help="Show DEBUG-level logging from PySubtrans internals")
    return parser.parse_args(argv)


def configure_logging(verbose : bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format='%(levelname)s %(name)s: %(message)s',
        stream=sys.stderr,
    )


if __name__ == '__main__':
    args = parse_args()
    configure_logging(args.verbose)
    raise SystemExit(run(args))
