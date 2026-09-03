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
