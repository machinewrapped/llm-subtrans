import logging
import sys

from argparse import ArgumentParser

from check_imports import check_required_imports
check_required_imports(['PySubtrans'])

from PySubtrans import init_transcription, transcribe_media
from PySubtrans.Helpers import GetOutputPath
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.AudioExtractor import AudioExtractor
from PySubtrans.Transcription.TranscriptionProvider import TranscriptionProvider
from scripts.subtrans_common import InitLogger


def CreateTranscribeParser() -> ArgumentParser:
    """
    Command line arguments for media transcription.
    """
    parser = ArgumentParser(description="Transcribe audio/video to subtitles using a transcription provider")
    parser.add_argument('input', nargs='?', help="Path to media file (mp4, mkv, m4a, mp3, wav, ...)")
    parser.add_argument('-o', '--output', help="Output subtitle file path (SRT); defaults alongside the media file")
    parser.add_argument('--list-tracks', action='store_true', help="List audio tracks in the media file and exit")
    parser.add_argument('--list-providers', action='store_true', help="List available transcription providers and exit")
    parser.add_argument('--provider', type=str, default="OpenRouter", help="Transcription provider to use (default OpenRouter)")
    parser.add_argument('-s', '--server', type=str, default=None, help="Server address (provider-specific, e.g. http://127.0.0.1:8888/v1)")
    parser.add_argument('-k', '--apikey', type=str, default=None, help="API key (provider-specific)")
    parser.add_argument('-m', '--model', type=str, default=None, help="Transcription model (default: the provider's recommended model, e.g. microsoft/mai-transcribe-2)")
    parser.add_argument('--language', type=str, default=None, help="Spoken language hint (e.g. Chinese, English)")
    parser.add_argument('--diarize', dest='diarize', action='store_true', default=None, help="Identify speakers (default on; model-dependent)")
    parser.add_argument('--no-diarize', dest='diarize', action='store_false', help="Turn off speaker identification")
    parser.add_argument('--audio-events', action='store_true', default=None, help="Tag sound effects and music, e.g. [laughter], for closed captions (model-dependent)")
    parser.add_argument('--track', type=int, default=0, help="Audio track index to transcribe (default 0)")
    parser.add_argument('--ffmpeg-path', type=str, default=None,
                        help="Path to the ffmpeg executable (default: use ffmpeg and ffprobe from PATH)")
    parser.add_argument('--min-chunk', type=float, default=None, help="Minimum chunk length in seconds (default: provider recommendation)")
    parser.add_argument('--max-chunk', type=float, default=None, help="Maximum chunk length in seconds (default: provider recommendation). 0 sends the whole clip in one request, for providers that support it (ElevenLabs)")
    parser.add_argument('--format', choices=('srt', 'ass', 'vtt'), default='vtt', help="Subtitle format for the transcribed output (default vtt; ass and vtt preserve speaker labels)")
    parser.add_argument('--rate-limit', type=float, default=None, help="Maximum backend requests per minute (0 for unlimited)")
    parser.add_argument('--align', action='store_true', default=True, help="Request word timestamps for timed lines (default on)")
    parser.add_argument('--no-align', dest='align', action='store_false', help="Disable word timestamps (chunk-level lines)")
    parser.add_argument('--postprocess', action='store_true', default=True, help="Clean transcribed lines with subtitle normalizations (default on)")
    parser.add_argument('--no-postprocess', dest='postprocess', action='store_false', help="Keep raw transcription text")
    parser.add_argument('--capture', type=str, default=None,
                        help="Also write the provider's raw segments to this .json file, or into this folder as <media>_<provider>.json, for replay with scripts/replay_transcription.py")
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

    # Listing tracks only probes the media with ffmpeg, so it needs no provider or credentials
    if args.list_tracks:
        try:
            extractor = AudioExtractor(SettingsType({'ffmpeg_path': args.ffmpeg_path}))
            for track in extractor.ListAudioTracks(args.input):
                print(track)
        except Exception as e:
            logging.error(f"Unable to list tracks: {e}")
            return 1
        return 0

    try:
        transcriber = init_transcription(
            args.provider,
            model=args.model,
            api_key=args.apikey,
            language=args.language,
            server_address=args.server,
            diarize=args.diarize,
            audio_events=args.audio_events,
            audio_track=args.track,
            ffmpeg_path=args.ffmpeg_path,
            min_chunk_seconds=args.min_chunk,
            max_chunk_seconds=args.max_chunk,
            rate_limit=args.rate_limit,
            transcription_align=args.align,
            postprocess_transcription=args.postprocess,
            transcription_capture_path=args.capture,
        )
    except SubtitleError as e:
        logging.error(f"Unable to initialise transcription: {e}")
        return 1

    def progress(sender, done : int, span : str) -> None:
        label = f"Transcribing chunk {done + 1}"
        logging.info(f"{label} [{span}]")
        if args.verbose:
            print(f"{label} [{span}]", flush=True)

    try:
        transcriber.events.progress.connect(progress)
        subtitles, error = transcribe_media(transcriber, args.input, auto_batch=False)

        outputpath = args.output or GetOutputPath(args.input, args.language, f".{args.format}")
        if not outputpath:
            logging.error("Unable to determine output path")
            return 1

        subtitles.outputpath = outputpath
        # Call the lower-level writer so an unwritable destination reaches the
        # CLI error handler instead of being logged as a false success.
        subtitles.SaveOriginal(outputpath)
        logging.info(f"Saved subtitles to {outputpath} ({subtitles.linecount} lines)")

        if error is not None:
            logging.error(f"Transcription incomplete: {error}")
            return 1

    except KeyboardInterrupt:
        logging.warning("Transcription interrupted")
        transcriber.Abort()
        return 130
    except Exception as e:
        logging.error(f"Error during transcription: {e}")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
