import logging
import sys

from argparse import ArgumentParser

from check_imports import check_required_imports
check_required_imports(['PySubtrans'])

from PySubtrans.Helpers import GetOutputPath
from PySubtrans.Options import Options
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleProject import SubtitleProject
from PySubtrans.Transcription.TranscriptionCoordinator import TranscriptionCoordinator
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from scripts.subtrans_common import InitLogger


def CreateTranscribeParser() -> ArgumentParser:
    """
    Command line arguments for media transcription.
    """
    parser = ArgumentParser(description="Transcribe audio/video to subtitles using a transcription provider")
    parser.add_argument('input', nargs='?', help="Path to media file (mp4, mkv, m4a, mp3, wav, ...)")
    parser.add_argument('-o', '--output', help="Output subtitle file path (SRT); defaults alongside the media file")
    parser.add_argument('--project', action='store_true', help="Also save a .subtrans project file for translation")
    parser.add_argument('--list-tracks', action='store_true', help="List audio tracks in the media file and exit")
    parser.add_argument('--list-providers', action='store_true', help="List available transcription providers and exit")
    parser.add_argument('--provider', type=str, default="Qwen Local", help="Transcription provider to use")
    parser.add_argument('-s', '--server', type=str, default=None, help="Server address (provider-specific, e.g. http://127.0.0.1:8888/v1)")
    parser.add_argument('-k', '--apikey', type=str, default=None, help="API key (provider-specific)")
    parser.add_argument('-m', '--model', type=str, default=None, help="Transcription model (e.g. qwen3-asr-1.7b)")
    parser.add_argument('--language', type=str, default=None, help="Spoken language hint (e.g. Chinese, English)")
    parser.add_argument('--track', type=int, default=0, help="Audio track index to transcribe (default 0)")
    parser.add_argument('--min-chunk', type=float, default=None, help="Minimum chunk length in seconds (default: provider recommendation)")
    parser.add_argument('--max-chunk', type=float, default=None, help="Maximum chunk length in seconds (default: provider recommendation)")
    parser.add_argument('--format', choices=('srt', 'ass', 'vtt'), default='vtt', help="Subtitle format for the transcribed output (default vtt; ass and vtt preserve speaker labels)")
    parser.add_argument('--rate-limit', type=float, default=None, help="Maximum backend requests per minute (0 for unlimited)")
    parser.add_argument('--align', action='store_true', default=True, help="Request word timestamps for timed lines (default on)")
    parser.add_argument('--no-align', dest='align', action='store_false', help="Disable word timestamps (chunk-level lines)")
    parser.add_argument('--postprocess', action='store_true', default=True, help="Clean transcribed lines with subtitle normalizations (default on)")
    parser.add_argument('--no-postprocess', dest='postprocess', action='store_false', help="Keep raw transcription text")
    parser.add_argument('-l', '--target-language', type=str, default=None, help="Target language recorded on the project")
    parser.add_argument('--debug', action='store_true', help="Run with DEBUG log level")
    parser.add_argument('--verbose', action='store_true', help="Log each transcribed chunk")
    return parser


def main() -> int:
    """Transcribe a media file to subtitles."""
    parser = CreateTranscribeParser()
    args = parser.parse_args()
    InitLogger("transcribe", args.debug)

    if args.list_providers:
        for name in sorted(TranscriptionProvider.get_providers()):
            print(name)
        return 0

    if not args.input:
        parser.error("the following arguments are required: input")

    provider_settings = SettingsType({
        'api_key': args.apikey,
        'server_address': args.server,
        'model': args.model,
        'language': args.language,
    })
    # Drop unset values so provider environment defaults apply
    provider_settings = SettingsType({k: v for k, v in provider_settings.items() if v is not None})

    try:
        provider = TranscriptionProvider.create_provider(args.provider, provider_settings)
    except ValueError as e:
        logging.error(str(e))
        return 1

    coordinator_settings = SettingsType({
        'audio_track': args.track,
        'language': args.language,
        'transcription_align': args.align,
    })
    # Drop unset values so provider recommendations apply
    if args.min_chunk is not None:
        coordinator_settings['min_chunk_seconds'] = args.min_chunk
    if args.max_chunk is not None:
        coordinator_settings['max_chunk_seconds'] = args.max_chunk
    if args.rate_limit is not None:
        coordinator_settings['rate_limit'] = args.rate_limit
    coordinator = TranscriptionCoordinator(provider, coordinator_settings)

    if args.list_tracks:
        try:
            for track in coordinator.CheckRequirements(args.input):
                print(track)
        except Exception as e:
            logging.error(f"Unable to list tracks: {e}")
            return 1
        return 0

    def progress(done : int, total : int, span : str) -> None:
        logging.info(f"Transcribing chunk {done + 1}/{total} [{span}]")
        if args.verbose:
            print(f"Transcribing chunk {done + 1}/{total} [{span}]", flush=True)

    try:
        options = Options()
        if args.target_language:
            options['target_language'] = args.target_language
        options['project_file'] = args.project
        options['postprocess_transcription'] = args.postprocess

        project : SubtitleProject = coordinator.CreateTranscriptionProject(args.input, options, progress)

        outputpath = args.output or GetOutputPath(args.input, args.target_language, f".{args.format}")
        if not outputpath:
            logging.error("Unable to determine output path")
            return 1

        project.subtitles.outputpath = outputpath
        # Call the lower-level writer so an unwritable destination reaches the
        # CLI error handler instead of being logged as a false success.
        project.subtitles.SaveOriginal(outputpath)
        logging.info(f"Saved subtitles to {outputpath} ({project.subtitles.linecount} lines)")

        if args.project:
            project.SaveProjectFile()
            logging.info(f"Saved project to {project.projectfile}")

    except KeyboardInterrupt:
        logging.warning("Transcription interrupted")
        coordinator.Abort()
        return 130
    except Exception as e:
        logging.error(f"Error during transcription: {e}")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
