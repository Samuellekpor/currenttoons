import os

from scripts.ai_client import ai_api_key, uses_aimlapi
from scripts.config import load_channel_config
from scripts.image_providers import _provider
from scripts.voiceover import resolve_tts


def test_aimlapi_key_preferred(monkeypatch):
    monkeypatch.setenv("AIMLAPI_KEY", "aiml-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ai_api_key() == "aiml-test"
    assert uses_aimlapi() is True


def test_openai_key_without_aimlapi(monkeypatch):
    monkeypatch.delenv("AIMLAPI_KEY", raising=False)
    monkeypatch.delenv("AIMLAPI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert ai_api_key() == "sk-test"
    assert uses_aimlapi() is False


def test_image_provider_defaults_to_aimlapi(monkeypatch):
    monkeypatch.setenv("AIMLAPI_KEY", "aiml-test")
    monkeypatch.delenv("IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    monkeypatch.delenv("FAL_KEY", raising=False)
    assert _provider() == "aimlapi"


def test_currenttoons_tts_falls_back_to_aimlapi(monkeypatch):
    monkeypatch.setenv("AIMLAPI_KEY", "aiml-test")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    config = load_channel_config("currenttoons")
    provider, voice, model = resolve_tts(config, "FR")
    assert provider == "openai"
    assert voice == "nova"
    assert model == "tts-1"
