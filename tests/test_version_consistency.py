"""Nenhum arquivo do produto pode exibir uma versão diferente da oficial (version.py)."""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _unifier():
    # carregado pelo caminho: pôr GBOC-Agent no sys.path esconderia os "modules" do Server em outros testes
    spec = importlib.util.spec_from_file_location("gboc_version_unifier", ROOT / "GBOC-Agent/utils/version_unifier.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.VersionUnifier


def _official():
    src = (ROOT / "GBOC-Server/version.py").read_text(encoding="utf-8")
    return re.search(r'GBOC_VERSION\s*=\s*"([^"]+)"', src).group(1)


def test_server_and_agent_share_version():
    agent = (ROOT / "GBOC-Agent/version.py").read_text(encoding="utf-8")
    assert f'GBOC_VERSION = "{_official()}"' in agent


def test_no_stale_version_strings():
    VersionUnifier = _unifier()
    u = VersionUnifier(ROOT, target=_official())
    assert u.unify_versions()
    assert not u.findings, "Versões divergentes (corrija com: python GBOC-Agent/utils/version_unifier.py --apply):\n" + \
        "\n".join(f"{f['file']}:{f['line']}: {f['text']}" for f in u.findings[:50])


def test_unifier_fixes_only_product_version(tmp_path):
    VersionUnifier = _unifier()
    (tmp_path / "GBOC-Agent").mkdir()
    f = tmp_path / "GBOC-Agent" / "page.html"
    f.write_bytes(b'<title>GBOC Agent 14.6.0</title>\r\n"min_server_version": "14.6.0",\r\n'
                  b"<span>GBOC System v14.4 Enterprise</span>\r\nAgente 14.7.7+\r\nlib 2.14.6.0\r\n")
    dry = VersionUnifier(tmp_path, target="14.8.1")
    dry.unify_versions()
    assert len(dry.findings) == 2 and b"14.6.0</title>" in f.read_bytes()       # dry-run não altera
    VersionUnifier(tmp_path, target="14.8.1", apply=True).unify_versions()
    assert f.read_bytes() == (b'<title>GBOC Agent 14.8.1</title>\r\n"min_server_version": "14.6.0",\r\n'
                              b"<span>GBOC System v14.8.1 Enterprise</span>\r\nAgente 14.7.7+\r\nlib 2.14.6.0\r\n")
