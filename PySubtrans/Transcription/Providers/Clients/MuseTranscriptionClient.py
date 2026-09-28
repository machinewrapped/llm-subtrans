import json
from datetime import timedelta

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Parse import TryParseNonNegative
from PySubtrans.Helpers.Speech import (DEFAULT_ABBREVIATIONS, EstimateSpeechSeconds, ParseAbbreviations, SentenceEnds,
                                       SentenceRanges)
from PySubtrans.SettingsType import SettingsType
from PySubtrans.SubtitleError import SubtitleError
from PySubtrans.Transcription.TranscriptionClient import TranscriptionClient
from PySubtrans.Transcription.TranscriptionSegment import TranscriptionResult, TranscriptionSegment

# Longest a turn may last, as a multiple of the time its text takes to say.
# About the 95th percentile of measured speech against the estimate.
TURN_SPEECH_MULTIPLE = 2.0


class MuseTranscriptionClient(TranscriptionClient):
    """
    Speech-to-text via the Muse Voice Transcribe one-shot endpoint.

    Each chunk is POSTed as multipart (request JSON plus WAV audio) and the
    turns come back with start/end offsets and speaker labels. Turn-level
    timings only: no word timestamps.
    """
    def __init__(self, settings : SettingsType):
        super().__init__(settings)

    @property
    def server_address(self) -> str:
        """Base URL of the Meta Model API."""
        address = self.settings.get_str('server_address') or 'https://api.meta.ai/v1'
        return address.rstrip('/')

    @property
    def api_key(self) -> str|None:
        """Meta Model API key."""
        return self.settings.get_str('api_key')

    @property
    def model(self) -> str:
        """Transcription model id."""
        return self.settings.get_str('model') or 'muse-voice-transcribe-1.0'

    @property
    def diarize(self) -> bool:
        """Whether speaker diarization is requested (DIARIZATION mode)."""
        return self.settings.get_bool('diarize', False)

    @property
    def abbreviations(self) -> frozenset[str]:
        """Abbreviations whose full stop does not end a sentence, when a turn is divided into sentences."""
        return ParseAbbreviations(self.settings.get_list('abbreviations', sorted(DEFAULT_ABBREVIATIONS)))

    @property
    def supports_timestamps(self) -> bool:
        """Turns carry start and end offsets (DIARIZATION is always requested)."""
        return True

    @property
    def supports_diarization(self) -> bool:
        """Speaker labels are kept only when diarization is opted into."""
        return self.diarize

    def _transcribe_chunk(self, audio_bytes : bytes, audio_format : str) -> TranscriptionResult:
        payload = self._post(audio_bytes)

        text, parts = _parse_muse_payload(payload, include_speakers=self.diarize, abbreviations=self.abbreviations)

        result = TranscriptionResult(text=text, language=self.language, parts=parts)
        return self._attach_usage(result, payload)

    def _request_config(self) -> dict:
        """
        Request JSON part: DIARIZATION always, since PUSH_TO_TALK returns
        flat text with no turn timings to build subtitles from.
        """
        config : dict = {
            'mode': 'DIARIZATION',
            'model': self.model,
            'audioEncoding': 'WAV',
        }
        if self.language:
            config['languageBias'] = [self.language]

        return config

    def _attach_usage(self, result : TranscriptionResult, payload : dict) -> TranscriptionResult:
        """
        Attach duration when the response reports it.
        """
        duration_ms = TryParseNonNegative(payload.get('audioDurationMs'))
        if duration_ms is not None:
            result.duration = timedelta(seconds=duration_ms / 1000.0)

        return result

    def _post(self, audio_bytes : bytes) -> dict:
        url = f"{self.server_address}/asr/transcribe"
        headers = {'Authorization': f"Bearer {self.api_key}"} if self.api_key else {}
        fields = {
            'request': (None, json.dumps(self._request_config()), 'application/json'),
            'audio': ('chunk.wav', audio_bytes, 'audio/wav'),
        }

        response = self._PostRequestWithRetry(url, headers=headers, files=fields)

        # Intercept before the generic handler to provide Muse-specific
        # status-code hints from the cookbook.
        if response.is_error:
            raise SubtitleError(_("Transcription request failed: POST {} returned {}: {}").format(
                url, response.status_code, self._error_hint(response)))

        return self._ParseJsonResponse(url, response)

    def _error_hint(self, response) -> str:
        """Map cookbook-documented status codes to actionable hints."""
        reply = (response.text or '').strip()
        detail = reply[:500] if reply.startswith(('{', '[')) else (reply[:200] if reply else _("empty response body"))

        hints = {
            400: _("audio over the 10-minute cap, or a malformed request"),
            401: _("the credential was not accepted"),
            404: _("endpoint not found"),
            413: _("body over 32 MB"),
            429: _("rate limited"),
        }
        hint = hints.get(response.status_code)

        if hint is None:
            return detail
        return f"{hint}: {detail}"


def _parse_muse_payload(payload : dict, chunk_seconds : float|None = None, include_speakers : bool = True,
                        abbreviations : frozenset[str] = DEFAULT_ABBREVIATIONS) -> tuple[str, list[TranscriptionSegment]]:
    """
    Extract (text, parts) from a Muse Voice Transcribe response.

    Pure function over the one-shot shape so it is unit-testable without
    network access. Turns carry start and end offsets with speaker labels
    (bare letters in DIARIZATION); a turn missing its end runs until the
    next turn starts, the last one until the reported audio duration.

    Each turn becomes a part per sentence (see _place_sentences), since
    a long turn often holds several utterances with silence between them.
    A turn reported with no length is given the time its text takes to say.
    """
    text = str(payload.get('transcript') or payload.get('text') or '').strip()

    duration_ms = TryParseNonNegative(payload.get('audioDurationMs'))
    audio_seconds = (duration_ms / 1000.0) if duration_ms is not None else chunk_seconds

    turns = [entry for entry in payload.get('turns') or [] if isinstance(entry, dict)]

    starts : list[float|None] = []
    for entry in turns:
        start_ms = TryParseNonNegative(entry.get('startMs'))
        starts.append(start_ms / 1000.0 if start_ms is not None else None)

    parts : list[TranscriptionSegment] = []
    for index, entry in enumerate(turns):
        entry_text = str(entry.get('transcript') or entry.get('text') or '').strip()
        start = starts[index]

        if not entry_text or start is None:
            continue

        end_ms = TryParseNonNegative(entry.get('endMs'))
        end = end_ms / 1000.0 if end_ms is not None else None

        following = next((s for s in starts[index + 1:] if s is not None and s > start), None)
        if end is None:
            end = following if following is not None else audio_seconds

        if end is None or end <= start:
            speech = TURN_SPEECH_MULTIPLE * EstimateSpeechSeconds(entry_text)
            end = start + speech if following is None else min(start + speech, following)

        speaker = entry.get('speaker') if include_speakers else None
        sentences = [entry_text[first:last].strip() for first, last in SentenceRanges(entry_text, SentenceEnds.ALL, abbreviations)]
        sentences = [sentence for sentence in sentences if sentence]
        for sentence, (sentence_start, sentence_end) in _place_sentences(sentences, start, end):
            parts.append(TranscriptionSegment(
                start=timedelta(seconds=sentence_start), end=timedelta(seconds=sentence_end),
                text=sentence,
                speaker=str(speaker) if speaker is not None else None))

    return text, parts


def _place_sentences(sentences : list[str], start : float, end : float) -> list[tuple[str, tuple[float, float]]]:
    """
    Place a turn's sentences within its span, each lasting at most a multiple of the time it takes to say.

    Turn starts are reliable, but a turn's reported end often runs on over silence.
    Measured against another engine, the speech in a long turn begins at its start,
    and, when the turn holds several sentences, the last one ends close to its end.
    So the first sentence starts with the turn, the last ends with it, and any
    between are spread by their share of characters.
    A turn too short to hold its sentences shares its span out by characters.
    """
    limits = [TURN_SPEECH_MULTIPLE * EstimateSpeechSeconds(sentence) for sentence in sentences]

    if len(sentences) == 1:
        return [(sentences[0], (start, min(end, start + limits[0])))]

    if end - start <= sum(limits):
        total = sum(len(sentence) for sentence in sentences)
        placed : list[tuple[str, tuple[float, float]]] = []
        position = start
        for sentence in sentences:
            length = (end - start) * len(sentence) / total
            placed.append((sentence, (position, position + length)))
            position += length
        return placed

    first_end = start + limits[0]
    last_start = end - limits[-1]
    middle = sentences[1:-1]
    total = sum(len(sentence) for sentence in middle) or 1
    gap = last_start - first_end

    placed = [(sentences[0], (start, first_end))]
    position = 0
    for offset, sentence in enumerate(middle):
        sentence_start = first_end + gap * position / total
        position += len(sentence)
        room = first_end + gap * position / total - sentence_start
        placed.append((sentence, (sentence_start, sentence_start + min(limits[offset + 1], room))))

    placed.append((sentences[-1], (last_start, end)))
    return placed


