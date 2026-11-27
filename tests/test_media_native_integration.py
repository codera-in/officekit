import io
import wave

import pytest

from officekit.engines.engine_media_models import MediaOperation
from officekit.engines.engine_media_native import native_media_available
from officekit.engines.engine_media_optimizer import MediaOptimizerEngine


def make_pcm_wave():
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(44_100)
        stream.writeframes(b"\x00\x00" * 4_410)
    return output.getvalue()


@pytest.mark.skipif(not native_media_available("audio"), reason="macOS afconvert is not installed")
def test_system_audio_converter_creates_a_separate_m4a_copy():
    source = make_pcm_wave()
    operation = MediaOperation.model_validate({
        "operationId": "audio-convert",
        "options": {"targetFormat": "m4a", "bitrateKbps": 128},
    })
    result = MediaOptimizerEngine.execute(source, "recording.wav", [operation])
    assert result.extension == "m4a"
    assert result.media_type == "audio/mp4"
    assert result.data[4:8] == b"ftyp"
    assert len(result.data) <= 64 * 1024 * 1024
    assert source == make_pcm_wave()
