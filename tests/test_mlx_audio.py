import video2knowledge.adapters.mlx_audio as mlx_audio_module
from video2knowledge.adapters.mlx_audio import MlxAudioClient, _normalize_transcript_segments


def test_mlx_segments_repair_invalid_and_missing_timestamps():
    segments = _normalize_transcript_segments(
        {
            "duration": 8,
            "segments": [
                {"start": -2, "end": 1, "text": " First "},
                {"start": 3, "end": 2, "text": "Second", "speaker_id": "S1"},
                {"start": 5, "end": None, "text": "Third"},
                {"start": 6, "end": 7, "text": "   "},
                "invalid segment",
            ],
        }
    )

    assert [(segment.start, segment.end, segment.text) for segment in segments] == [
        (0, 1, "First"),
        (3, 5, "Second"),
        (5, 8, "Third"),
    ]
    assert segments[1].speaker == "S1"


def test_mlx_segments_keep_start_times_monotonic():
    segments = _normalize_transcript_segments(
        {
            "segments": [
                {"start": 4, "end": 5, "text": "First"},
                {"start": 2, "end": 4.5, "text": "Second"},
                {"start": "invalid", "end": "invalid", "text": "Third"},
            ]
        }
    )

    assert [(segment.start, segment.end) for segment in segments] == [
        (4, 5),
        (4, 4.5),
        (4, 4),
    ]


def test_mlx_transcript_text_is_preserved_when_segments_are_unusable():
    segments = _normalize_transcript_segments(
        {
            "duration": 12.5,
            "segments": [{"start": 2, "end": 1, "text": " "}],
            "text": "Full text",
        }
    )

    assert len(segments) == 1
    assert (segments[0].start, segments[0].end, segments[0].text) == (0, 12.5, "Full text")


def test_mlx_client_uses_timestamp_normalization(tmp_path, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "duration": 7,
                "segments": [{"start": 4, "end": 1, "text": "Recovered segment"}],
            }

    monkeypatch.setattr(mlx_audio_module.httpx, "post", lambda *args, **kwargs: FakeResponse())
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"test")

    segments = MlxAudioClient().transcribe(audio, "zh-CN")

    assert [(segment.start, segment.end, segment.text) for segment in segments] == [
        (4, 7, "Recovered segment")
    ]


def test_synthesis_options_and_variable_duration_timing(tmp_path, monkeypatch):
    import io
    import wave

    from video2knowledge.models import TranscriptSegment

    requests = []

    def post(url, *, json, timeout):
        requests.append((url, json, timeout))
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * (8000 * len(requests)))

        class Response:
            content = buffer.getvalue()

            def raise_for_status(self):
                pass

        return Response()

    monkeypatch.setattr(mlx_audio_module.httpx, "post", post)
    client = MlxAudioClient(
        tts_model="synthetic-model", voice="SyntheticVoice", speed=1.5, timeout_seconds=30
    )
    segments = [TranscriptSegment(0, 0, "First"), TranscriptSegment(0, 0, "Second")]
    output = client.synthesize(segments, tmp_path / "speech.wav", "en")
    assert requests[0][1] == {
        "model": "synthetic-model",
        "input": "First",
        "voice": "SyntheticVoice",
        "speed": 1.5,
        "response_format": "wav",
    }
    assert all(timeout == 30 for _, _, timeout in requests)
    assert [(s.start, s.end) for s in segments] == [(0, 1), (1, 3)]
    with wave.open(str(output), "rb") as audio:
        assert audio.getnframes() == 24000
