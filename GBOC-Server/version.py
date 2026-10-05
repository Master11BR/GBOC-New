"""
GBOC Server — Version Module
Fonte única de verdade para versão do sistema.
"""
GBOC_VERSION = "14.8.1"
GBOC_BUILD = "stable"
GBOC_EDITION = "Enterprise"
GBOC_RELEASE_DATE = "2026-10-05"
GBOC_PLATFORM = "Server"

def version_string() -> str:
    return f"GBOC {GBOC_PLATFORM} v{GBOC_VERSION} {GBOC_EDITION}"
