from __future__ import annotations

import wave
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from ..models import TranscriptSegment


class MlxAudioClient:
    """Client for mlx-audio's local OpenAI-compatible HTTP server."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        stt_model: str = "mlx-community/whisper-large-v3-turbo-asr-fp16",
        tts_model: str = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit",
        voice: str = "Vivian",
    ):
        self.base_url = base_url.rstrip("/")
        self.stt_model, self.tts_model, self.voice = stt_model, tts_model, voice

    def transcribe(self, audio_path: Path, language: str | None = None) -> list[TranscriptSegment]:
        data = {"model": self.stt_model, "response_format": "verbose_json"}
        if language:
            data["language"] = language
        # mlx-audio delegates compressed formats to an external ffmpeg binary.
        # Decode locally with PyAV so a stock macOS setup only needs this project's
        # Python dependencies.
        with _server_ready_audio(audio_path) as upload_path, upload_path.open("rb") as handle:
            try:
                response = httpx.post(
                    f"{self.base_url}/v1/audio/transcriptions",
                    data=data,
                    files={"file": (upload_path.name, handle, "audio/wav")},
                    timeout=None,
                )
            except httpx.ConnectError as exc:
                raise RuntimeError(self._connection_error_message()) from exc
        response.raise_for_status()
        payload = response.json()
        raw_segments = payload.get("segments") or []
        if raw_segments:
            return [
                TranscriptSegment(
                    float(s.get("start", s.get("start_time", 0))),
                    float(s.get("end", s.get("end_time", 0))),
                    str(s.get("text", "")),
                    str(s.get("speaker", s.get("speaker_id", ""))) or None,
                )
                for s in raw_segments
            ]
        text = str(payload.get("text", "")).strip()
        return [TranscriptSegment(0, 0, text)] if text else []

    def synthesize(
        self, segments: list[TranscriptSegment], output_path: Path, language: str
    ) -> Path:
        """Generate one WAV per segment and concatenate, preserving lyric boundaries."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="v2k-tts-") as tmp:
            parts: list[Path] = []
            for index, segment in enumerate(segments):
                try:
                    response = httpx.post(
                        f"{self.base_url}/v1/audio/speech",
                        json={
                            "model": self.tts_model,
                            "input": segment.text,
                            "voice": self.voice,
                            "response_format": "wav",
                        },
                        timeout=None,
                    )
                except httpx.ConnectError as exc:
                    raise RuntimeError(self._connection_error_message()) from exc
                response.raise_for_status()
                part = Path(tmp) / f"{index:05d}.wav"
                part.write_bytes(response.content)
                parts.append(part)
            cursor = 0.0
            for segment, part in zip(segments, parts, strict=True):
                with wave.open(str(part), "rb") as audio:
                    duration = audio.getnframes() / audio.getframerate()
                segment.start, segment.end = cursor, cursor + duration
                cursor += duration
            _concat_wav(parts, output_path)
        return output_path

    def _connection_error_message(self) -> str:
        return (
            f"MLX Audio is not reachable at {self.base_url}. "
            "Start it from Runtime Settings in the GUI and wait until its status is running."
        )


@contextmanager
def _server_ready_audio(audio_path: Path) -> Iterator[Path]:
    if audio_path.suffix.lower() == ".wav":
        yield audio_path
        return

    with TemporaryDirectory(prefix="v2k-stt-") as tmp:
        output = Path(tmp) / f"{audio_path.stem}.wav"
        _decode_to_pcm_wav(audio_path, output)
        yield output


def _decode_to_pcm_wav(source: Path, output: Path) -> None:
    """Decode any PyAV-supported audio to mono 16 kHz PCM for Whisper."""
    try:
        import av
    except ImportError as exc:
        raise RuntimeError(
            "Compressed-audio decoding requires the 'audio' extra: "
            "pip install 'video2knowledge[audio]'"
        ) from exc

    with av.open(str(source)) as container, wave.open(str(output), "wb") as target:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16_000)
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16_000)

        for frame in container.decode(stream):
            for converted in resampler.resample(frame):
                target.writeframes(bytes(converted.planes[0]))
        for converted in resampler.resample(None):
            target.writeframes(bytes(converted.planes[0]))


def _concat_wav(parts: list[Path], output: Path) -> None:
    if not parts:
        raise ValueError("There are no text segments to synthesize")
    with wave.open(str(parts[0]), "rb") as first:
        params = first.getparams()
        frames = [first.readframes(first.getnframes())]
    for part in parts[1:]:
        with wave.open(str(part), "rb") as current:
            if current.getparams()[:4] != params[:4]:
                raise ValueError("MLX Audio returned inconsistent WAV parameters")
            frames.append(current.readframes(current.getnframes()))
    with wave.open(str(output), "wb") as target:
        target.setparams(params)
        for chunk in frames:
            target.writeframes(chunk)
