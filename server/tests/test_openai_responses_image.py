"""Unit tests for image extraction in the Responses router (no models/network)."""
import base64

import pytest

from app.routers.openai_compat import PipelineError
from app.routers.openai_responses import _parse_data_url, _responses_request_to_messages
from app.schemas.openai_responses import OAIResponsesRequest


def _data_url(payload: bytes = b"hello", mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


def _req(content) -> OAIResponsesRequest:
    return OAIResponsesRequest(model="gpt-4o", input=[{"role": "user", "content": content}])


def test_parse_data_url_roundtrip():
    data, mime = _parse_data_url(_data_url(b"\x01\x02\x03", "image/jpeg"))
    assert data == b"\x01\x02\x03"
    assert mime == "image/jpeg"


def test_remote_url_rejected():
    with pytest.raises(PipelineError) as exc:
        _parse_data_url("https://example.com/cat.jpg")
    assert exc.value.status_code == 400


def test_malformed_data_url_rejected():
    with pytest.raises(PipelineError) as exc:
        _parse_data_url("data:image/png;base64,%%%not-base64%%%")
    assert exc.value.status_code == 400


def test_oversized_payload_rejected_before_decoding(monkeypatch):
    """The cap must be checked against the base64 string's length, not the
    decoded bytes — decoding first means buffering a payload we were always
    going to reject. Use a small override so the test doesn't need a
    multi-GB string to prove the bound is enforced before b64decode runs."""
    import app.routers.openai_responses as responses_router

    monkeypatch.setattr(responses_router, "MAX_ATTACHMENT_BYTES", 16)

    decode_calls = []
    real_b64decode = base64.b64decode

    def _tracking_b64decode(payload):
        decode_calls.append(payload)
        return real_b64decode(payload)

    monkeypatch.setattr(responses_router.base64, "b64decode", _tracking_b64decode)

    with pytest.raises(PipelineError) as exc:
        _parse_data_url(_data_url(b"x" * 1000, "image/png"))

    assert exc.value.status_code == 400
    assert decode_calls == [], "payload must be size-checked before it is decoded"


def test_payload_within_cap_still_decodes(monkeypatch):
    import app.routers.openai_responses as responses_router

    monkeypatch.setattr(responses_router, "MAX_ATTACHMENT_BYTES", 1_000_000)

    data, mime = _parse_data_url(_data_url(b"small enough", "image/png"))
    assert data == b"small enough"
    assert mime == "image/png"


def test_text_only_returns_no_image():
    msgs, image, _file = _responses_request_to_messages(_req("just text"))
    assert image is None
    assert [m.content for m in msgs] == ["just text"]


def test_single_image_extracted():
    content = [
        {"type": "input_text", "text": "what is this?"},
        {"type": "input_image", "image_url": _data_url(b"IMG", "image/webp")},
    ]
    msgs, image, _file = _responses_request_to_messages(_req(content))
    assert image == (b"IMG", "image/webp")
    assert msgs[0].content == "what is this?"  # image part stripped from text


def test_multiple_images_rejected():
    content = [
        {"type": "input_image", "image_url": _data_url(b"A")},
        {"type": "input_image", "image_url": _data_url(b"B")},
    ]
    with pytest.raises(PipelineError) as exc:
        _responses_request_to_messages(_req(content))
    assert exc.value.status_code == 400
