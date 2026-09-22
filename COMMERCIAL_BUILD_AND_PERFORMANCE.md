<!-- Copyright (c) 2026 Master11BR - GBOC System v14.6.0 Enterprise. Todos os direitos reservados. -->

# 🚀 GBOC System v14.6.0 — Roteiro de Desempenho, Qualidade Comercial e Compilação Standalone

[![GBOC Version](https://img.shields.io/badge/GBOC%20Version-14.6.0-blue.svg)](file:///d:/GBOC-New/GBOC-New/README.md)
[![Commercial Ready](https://img.shields.io/badge/commercial-ready-brightgreen.svg)]()

> **Roteiro Técnico para Transformar o GBOC em um Produto Comercial de Alta Performance, Protegido contra Engenharia Reversa e Compilável em Executáveis Standalone Autônomos (`.exe` / Binários Linux)**.

---

## 📌 Sumário
1. [Compilação Standalone sem Dependência de Python (PyInstaller & Nuitka)](#1-compilação-standalone-sem-dependência-de-python)
2. [Proteção de Código e Ofuscação (PyArmor / C-Extensions)](#2-proteção-de-código-e-ofuscação)
3. [Otimizações de Desempenho e Alta Escala (v14.6.0)](#3-otimizações-de-desempenho-e-alta-escala)
4. [Empacotamento Comercial Industrial (Inno Setup / MSI)](#4-empacotamento-comercial-industrial)

---

## 1. 📦 Compilação Standalone sem Dependência de Python

Para distribuição comercial corporativa, o **GBOC Agent** e o **GBOC Server** podem ser compilados diretamente em executáveis binários standalone que **não necessitam de Python instalado na máquina cliente**.

### 1.1 Compilação do GBOC Agent (`GBOCAgent.exe`) via PyInstaller

#### Instalação do PyInstaller:
```bash
pip install pyinstaller
```

#### Arquivo Especificador `GBOCAgent.spec`:
```python
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['agent_server.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('static', 'static'),
        ('engines', 'engines'),
        ('api', 'api'),
        ('utils', 'utils'),
        ('version_control.py', '.')
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'psutil',
        'httpx',
        'pydantic'
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'unittest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GBOCAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # Execução silenciosa como Serviço Windows
    icon='static/favicon.ico' if os.path.exists('static/favicon.ico') else None
)
```

#### Comando de Build:
```powershell
pyinstaller --clean GBOCAgent.spec
```
*O executável autônomo será gerado em `dist/GBOCAgent.exe`.*

---

## 2. 🛡️ Proteção de Código e Ofuscação (PyArmor / C-Extensions)

Para proteger a propriedade intelectual dos algoritmos do GBOC (FastCDC Native Engine, SureRestore Sandbox e Cyber Security Sentinel):

```bash
pip install pyarmor
pyarmor gen --recursive -O dist_protected GBOC-Agent/
```

---

## 3. ⚡ Otimizações de Desempenho e Alta Escala (v14.6.0)

1. **Cancelamento Real de Requisições via `gbocPerf.makeCancellable()`**:
   - Cada busca ativa, paginação ou troca de tela descarta requisições pendentes anteriores via `AbortController`, eliminando gargalos e *race conditions* no cliente.
2. **Algoritmo de Renderização Segura (`safeRender`)**:
   - Comparação estrita de string HTML completa (`_gbocLastHtml`) evitando renderizações desnecessárias do DOM e impedindo perda de foco ou piscamento em tabelas dinâmicas.
3. **Sincronização Automatizada com Gatekeeper de Build**:
   - O pipeline de distribuição executa `sync_css.py --verify` de modo determinístico antes de compilar os pacotes de instalação.
4. **Resiliência de Startup HTTP**:
   - Detecção dinâmica e fallback seguro para `httptools` e `uvloop` sem risco de falha em ambientes limpos.

---

## 4. 📦 Empacotamento Comercial Industrial

O pacote consolidado de instalação em `GBOC-Distribution/` fornece:
- `Setup.bat` / `Setup.ps1` com menu interativo e modo silencioso.
- Instalação e provisionamento automático do serviço Windows via NSSM.
- Suporte a silent install: `Setup.bat -Silent -Mode Agent -ServerUrl http://srv:8000`.
