# PROJECT_CONTEXT - GBOC System v14.6.0 Enterprise

## 🎯 OBJETIVO
Sistema corporativo de gerenciamento de backups, monitoramento e diagnóstico preemptivo. O projeto garante alta performance utilizando sempre as tecnologias em suas últimas versões.

## 🏗️ ARQUITETURA E STACK
Duas frentes independentes integradas via WebSocket/REST:

### 1. Agente (`\GBOC-Agent` - Porta 9200)
- **Stack**: FastAPI (Python 3.11+ | 3.14).
- **Responsabilidade**: Roda os motores de backup (Duplicati, Kopia, Restic, Native FastCDC v4), Ransomware Shield e coletores.

### 2. Servidor (`\GBOC-Server` - Porta 8000)
- **Stack**: FastAPI (Python 3.11+ | 3.14).
- **Banco de Dados**: PostgreSQL (com índices otimizados e Connection Pooling). Consultas booleanas devem obrigatoriamente usar `= true` ou `= false` (nunca `1` ou `0`).
- **Cache**: Redis Assíncrono (aioredis).
- **Segurança**: Autenticação JWT (Access/Refresh Tokens), hash de senha via PBKDF2 (100k iterações), Rate Limiting.
- **Confiabilidade**: Implementa Dead Letter Queue (DLQ) para mensagens falhadas e Retry Logic com backoff exponencial. Webhooks existem na estrutura, mas estão desabilitados (`WEBHOOKS_ENABLED = False`).

## 📁 ESTRUTURA DE FRONTEND & UNIVERSAL CSS ARCHITECTURE
- **Arquitetura Universal de CSS**: 100% compartilhada e sincronizada entre Servidor e Agente via 5 arquivos canônicos:
  1. `style.css`: Framework base de componentes universais.
  2. `gboc-themes.css`: Design Tokens, 8 Estilos de UI (`minimal`, `neumorphism`, `claymorphism`, `fluent`, `nexus-widgets`, `nexus-glass`, `command-sentinel`, `cyber-3d`) e 6 Temas de Iluminação (`dark`, `light`, `amber`, `purple`, `ocean`, `red`).
  3. `gboc-layout.css`: Layout responsivo universal (Sidebar Vertical + Topbar Horizontal).
  4. `gboc-hardware-hud.css`: HUD de telemetria de hardware em tempo real.
  5. `gboc-file-picker.css`: Explorador universal de arquivos e diretórios.
- **Enterprise Modal & Dialog System (`gboc-modal.js`)**: Interceptador global transparente para `alert()`, `confirm()` e `prompt()` nativos com micro-animações, detecção semântica de ícones/cores e atalhos de teclado (`Enter` / `Escape`).
- **Compatibilidade**: HTML5 semântico, CSS3 / CSS Living Standard, JavaScript ES6+ assíncrono. A interface não deve quebrar o `auth_interceptor.js`.

## 📌 REGRAS DE ESTADO ZERO MOCKS
- Todo o ecossistema já está integrado. Interfaces e serviços devem consumir dados reais (PostgreSQL, APIs ou motores).
- É ESTRITAMENTE PROIBIDO gerar código com dados mockados (falsos, estáticos ou arrays hardcoded) para simular entregas.