"""
Testes unitários da camada de IA (funções puras — sem rede, sem banco e sem respostas simuladas).
Cobre: normalização de provedor, resolução de chave/modelo por provedor, proteção de chaves
mascaradas, validação de URL e os modelos estatísticos do REP-F6.
"""
import filecmp
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from modules.ai_assistant import ai_providers as aip
from modules.reports import ai_predictive as pred

ROOT = Path(__file__).resolve().parents[1]


def test_shared_files_are_identical_between_server_and_agent():
    assert filecmp.cmp(ROOT / "GBOC-Server/modules/ai_assistant/ai_providers.py",
                       ROOT / "GBOC-Agent/engines/ai_providers.py", shallow=False)
    assert filecmp.cmp(ROOT / "GBOC-Server/modules/reports/ai_predictive.py",
                       ROOT / "GBOC-Agent/engines/ai_predictive.py", shallow=False)
    assert filecmp.cmp(ROOT / "GBOC-Server/ai_assistant.js",
                       ROOT / "GBOC-Agent/static/ai_assistant.js", shallow=False)


@pytest.mark.parametrize("raw,expected", [
    ("ollama_local", "ollama"), ("", "ollama"), ("groq_free", "groq"), ("grok", "grok"),
    ("gemini_free", "gemini"), ("anthropic", "claude"), ("deepseek", "deepseek"),
    ("qwen", "ollama"), ("llama3", "ollama"), ("cohere", "cohere"), ("kimi", "kimi"),
])
def test_normalize_provider(raw, expected):
    assert aip.normalize_provider(raw) == expected


def test_key_is_never_sent_to_another_provider():
    cfg = {"provider": "openai", "openai_api_key": "sk-openai", "groq_api_key": ""}
    assert aip.resolve_api_key(cfg, "openai") == "sk-openai"
    assert aip.resolve_api_key(cfg, "groq") == ""


def test_legacy_generic_key_only_for_active_provider():
    cfg = {"provider": "gemini", "api_key": "AIza-legacy"}
    assert aip.resolve_api_key(cfg, "gemini") == "AIza-legacy"
    assert aip.resolve_api_key(cfg, "openai") == ""


def test_ollama_model_is_not_sent_to_cloud_provider():
    cfg = {"provider": "openai", "model": "llama3:latest", "openai_model": "llama3:latest"}
    assert aip.resolve_model(cfg, "openai") == aip.DEFAULT_MODELS["openai"]
    assert aip.resolve_model({"provider": "ollama", "model": "llama3:latest"}, "ollama") == "llama3:latest"


def test_masked_key_does_not_overwrite_saved_key():
    clean = aip.sanitize_config_update({"provider": "groq", "groq_api_key": "gsk_...7890", "api_key": "***"})
    assert "groq_api_key" not in clean and "api_key" not in clean


def test_generic_key_is_mapped_to_selected_provider_and_unknown_fields_dropped():
    clean = aip.sanitize_config_update({"provider": "claude", "api_key": "sk-ant-123456789", "evil": 1})
    assert clean["claude_api_key"] == "sk-ant-123456789"
    assert "evil" not in clean and "api_key" not in clean


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "ftp://host", "http://user:pw@host"])
def test_invalid_ollama_urls_are_rejected(url):
    with pytest.raises(ValueError):
        aip.validate_http_url(url)


def test_mask_config_hides_all_secrets():
    masked = aip.mask_config({"openai_api_key": "sk-1234567890abcd", "api_key": "abc"})
    assert masked["openai_api_key"] == "sk-1...abcd"
    assert masked["api_key"] == "***"
    assert masked["configured_keys"] == ["openai"]


def test_missing_key_returns_explicit_error_without_network():
    result = aip.chat({"provider": "openai"}, "sys", "hi")
    assert result.ok is False and "chave de API" in result.error


def test_parse_json_object_from_llm_text():
    assert aip.parse_json_object('texto ```json {"cause": "x"} ```') == {"cause": "x"}
    assert aip.parse_json_object("sem json") is None


def _execs(n, gb_per_day=2, start_hour=2):
    now = datetime.now()
    return [{"start": now - timedelta(days=i, hours=-start_hour), "bytes": gb_per_day * 1024 ** 3, "status": "completed"}
            for i in range(n)]


def test_predictive_models_unavailable_without_samples():
    suite = pred.build_predictive_suite([], [], {"available": False})
    assert suite["score"] is None
    assert all(m["status"] == "UNAVAILABLE" for m in suite["models"])


def test_capacity_regression_uses_real_growth():
    cap = pred.capacity_model(_execs(10, gb_per_day=2), [{"total_gb": 1000, "used_gb": 900}])
    assert cap["status"] == "ALERTA"            # 100 GB livres / 2 GB por dia = 50 dias (< 60)
    assert cap["growth_gb_day"] == pytest.approx(2.0, rel=0.01)
    assert cap["days_to_exhaustion"] == 50


def test_zscore_detects_outlier():
    execs = _execs(10, gb_per_day=1) + [{"start": datetime.now(), "bytes": 500 * 1024 ** 3, "status": "completed"}]
    assert pred.anomaly_model(execs)["anomalies"] == 1


def test_ransomware_without_canaries_or_incidents_is_unavailable():
    assert pred.ransomware_model({"available": True, "canaries_total": 0, "canaries_compromised": 0,
                                  "incidents_30d": None})["status"] == "UNAVAILABLE"
