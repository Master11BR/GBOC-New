"""Guia de uso do Copilot (gboc_help_kb): localização de funções e passos — sem rede/banco."""
import filecmp
from pathlib import Path

import pytest

from modules.ai_assistant import gboc_help_kb as kb

ROOT = Path(__file__).resolve().parents[1]


def test_kb_identical_between_server_and_agent():
    assert filecmp.cmp(ROOT / "GBOC-Server/modules/ai_assistant/gboc_help_kb.py",
                       ROOT / "GBOC-Agent/engines/gboc_help_kb.py", shallow=False)


@pytest.mark.parametrize("question,topic", [
    ("onde fica o restaurar arquivos e como usar?", "restore"),
    ("Como recuperar um arquivo apagado", "restore"),
    ("como crio uma tarefa de backup", "tasks"),
    ("onde vejo os logs", "logs"),
    ("como configurar o provedor de IA", "ai_config"),
    ("como parear um agente novo", "agents_pairing"),
])
def test_find_topics_ranks_expected_first(question, topic):
    found = kb.find_topics(question, "server")
    assert found and found[0]["id"] == topic


def test_answer_contains_location_and_steps_for_each_product():
    for product in ("server", "agent"):
        ans = kb.answer_from_kb("onde fica restaurar arquivos", product)
        assert "Onde fica" in ans and "1." in ans
    assert "(/restore.html)" in kb.answer_from_kb("onde fica restaurar arquivos", "agent")
    assert "(gboc:tab:" in kb.answer_from_kb("onde fica restaurar arquivos", "server")


def test_howto_detection_and_no_false_match():
    assert kb.is_howto_question("Onde fica a restauração?")
    assert not kb.is_howto_question("quantos jobs falharam hoje")
    assert kb.answer_from_kb("xyzzy plugh", "server") is None


def test_every_topic_has_location_and_steps():
    for t in kb.TOPICS:
        assert t.get("server") or t.get("agent"), t["id"]
        assert t["steps"], t["id"]
