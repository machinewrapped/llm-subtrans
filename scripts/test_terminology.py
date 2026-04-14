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
from PySubtrans.Subtitles import Subtitles


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
    errors         : list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

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


def _make_batch_handler(records : list[BatchRecord]):
    """Return a batch_translated handler that records per-batch context data."""

    def on_batch_translated(sender, batch : SubtitleBatch|None = None, **_):
        if batch is None:
            return

        # batch.context['terminology'] was stored before translation; it holds
        # exactly what was injected into the prompt for this batch.
        injected = _parse_terminology_context(batch.context.get('terminology'))  # type: ignore[arg-type]

        records.append(BatchRecord(
            scene=batch.scene,
            batch=batch.number,
            lines=batch.size,
            injected_terms=injected,
            returned_terms={},   # filled in by terminology_updated if the model returned terms
            new_terms={},
            conflict_terms={},
            errors=batch.error_messages,
        ))

    return on_batch_translated


def _make_terminology_handler(records : list[BatchRecord]):
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

    records : list[BatchRecord] = []
    translator.events.batch_translated.connect(_make_batch_handler(records))
    translator.events.terminology_updated.connect(_make_terminology_handler(records))

    print("Translating ...\n")
    try:
        translator.TranslateSubtitles(subtitles)
    except SubtitleError as exc:
        logging.error("Translation failed: %s", exc)
        return 1

    final_map : dict[str, str] = {k: str(v) for k, v in subtitles.settings.get_dict('terminology_map').items()}

    _print_report(args, source, total_lines, total_scenes, records, final_map)

    if args.output:
        _write_json(args, source, records, final_map, args.output)

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
    final_map   : dict[str, str],
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

    print(f"Batches returning any terms    : {len(returning)}/{len(records)}")
    print(f"Batches adding new terms       : {len(adding)}/{len(records)}")
    if conflicting:
        print(f"Batches with conflicts         : {len(conflicting)}/{len(records)}")
    if errored:
        print(f"Batches with errors            : {len(errored)}/{len(records)}")

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
    final_map   : dict[str, str],
    output_path : str,
) -> None:
    adding      = [r for r in records if r.new_terms]
    conflicting = [r for r in records if r.conflict_terms]

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
        'final_map'          : final_map,
        'batches'            : [
            {
                'scene'         : r.scene,
                'batch'         : r.batch,
                'lines'         : r.lines,
                'injected_terms': r.injected_terms,
                'returned_terms': r.returned_terms,
                'new_terms'     : r.new_terms,
                'conflict_terms': {k: list(v) for k, v in r.conflict_terms.items()},
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
