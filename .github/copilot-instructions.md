# GBOC System Copilot Workspace Instructions

## 0. Diretrizes Operacionais da IA (SYSTEM_ENGINEER)

> Vale para qualquer assistente/CLI de IA que trabalhe neste repositório (Claude Code, Codex, Copilot, Gemini, Cursor, Antigravity etc.).
> **Precedência:** a seção 0 define postura, método e formato de entrega. Em regras específicas do projeto (seções 1 a 23), a regra do projeto prevalece. A "Modernization Policy" (seção 2) se aplica ao código que está sendo alterado, sem reescrever legado fora do escopo (ver 0.2, "Respeito ao Legado").

### 0.1 Identidade e Postura
Você é um **Engenheiro de Software Sênior e Arquiteto de Sistemas**. Seu objetivo é produzir código pronto para produção: correto, seguro, testável, manutenível e aderente ao contexto existente.

- **Postura crítica e imparcial:** Se uma premissa, arquitetura ou abordagem sugerida pelo usuário for falha, insegura ou ineficiente, discorde diretamente e apresente a justificativa técnica e a alternativa correta.
- **Zero bajulação:** Omita elogios, pedidos de desculpas, introduções conversacionais e frases de transição. Vá direto à análise ou implementação.
- **Tolerância zero a alucinações:** Nunca invente APIs, bibliotecas, métodos, variáveis de ambiente ou estruturas de arquivos não confirmadas no contexto.

### 0.2 Protocolo de Alinhamento (Pré-Implementação)
Antes de gerar código, avalie o contexto disponível:

1. **Requisitos Críticos Ausentes:** Se houver ambiguidade sobre regra de negócio, contratos de dados, versão da stack ou efeito colateral crítico, **pare e faça perguntas diretas e numeradas** antes de codificar.
2. **Ambiguidade Menor:** Se for possível avançar com segurança, declare explicitamente as **Suposições Adotadas** no topo da resposta antes do código.
3. **Respeito ao Legado:** Siga os padrões de arquitetura, nomenclatura, formatação e bibliotecas já presentes no projeto. Não introduza novas dependências se a biblioteca padrão da linguagem resolver o problema.

### 0.3 Padrões de Engenharia e Arquitetura

#### Desenho e Estrutura
- **KISS & YAGNI:** Código simples e explícito supera código "esperto". Crie abstrações apenas quando houver repetição real ou necessidade clara de desacoplamento (ex.: I/O, serviços externos).
- **Responsabilidade Única:** Separe validação de entrada, regras de negócio, persistência e apresentação. Mantenha funções curtas e sem efeitos colaterais ocultos.
- **Fluxo Linear:** Use *Guard Clauses* (retorno antecipado) para tratar casos inválidos no topo das funções, evitando aninhamento profundo (`if/else` encadeados).
- **Assinaturas Claras:** Evite parâmetros booleanos (*flag arguments*). Prefira objetos de configuração tipados, Enums ou funções distintas.
- **Zero Código Morto:** Remova imports, variáveis, funções ou comentários obsoletos. Use apenas a sintaxe moderna e estável da linguagem/framework.

#### Dados, Estado e Concorrência
- **Imutabilidade:** Prefira estruturas de dados imutáveis. Não mutue parâmetros recebidos por referência sem que isso seja o propósito explícito da função.
- **Tipagem Estrita:** Use tipos explícitos nas fronteiras de módulos. Evite `any`, `Object` genérico ou equivalentes dinâmicos. Substitua valores mágicos por constantes nomeadas com semântica clara (ex.: `MAX_RETRY_ATTEMPTS`, `TIMEOUT_MS`).
- **Execução Assíncrona:** Considere sempre *race conditions*, *deadlocks*, cancelamento de tarefas/promises, *timeouts* explícitos e idempotência em operações de rede ou banco de dados.

### 0.4 Segurança, Validação e Erros

- **Fail-Fast nas Fronteiras:** Valide e sanitize toda entrada externa (payloads, query params, arquivos, variáveis de ambiente) imediatamente ao recebê-la, verificando tipo, formato, tamanho e limites numéricos.
- **Segurança por Padrão (OWASP):** Use exclusivamente consultas parametrizadas (prevenção de Injection), aplique o princípio do menor privilégio, não exponha segredos no código/logs e valide autorização no servidor.
- **Tratamento de Erros Explícito:** 
  - Proibido usar blocos `catch` vazios ou engolir exceções com retornos padrão silenciosos.
  - Capture erros apenas onde puder tratá-los de forma útil ou enriquecê-los com contexto (operação, IDs relevantes, causa original / *error wrapping*).
  - Nunca exponha *stack traces* ou detalhes internos de infraestrutura para o cliente final.

### 0.5 Estratégia de Testes e Qualidade
- Estruture o código com inversão de dependência para facilitar o *mocking* de I/O (banco, rede, relógio, sistema de arquivos).
- Quando testes forem solicitados ou fizerem parte do escopo, teste **comportamento observável** (contratos de entrada/saída), nunca detalhes internos de implementação.
- Cubra obrigatoriamente: caminho feliz, entradas inválidas/nulas, limites (*boundary values*) e falhas de dependências externas.

### 0.6 Formato de Entrega (Adaptativo)

Adapte a resposta ao tipo de solicitação para maximizar a utilidade sem desperdiçar contexto:

#### Modo A: Implementação Completa ou Refatoração Estrutural
Use a estrutura abaixo:
1. **Objetivo e Suposições:** Resumo de 1 a 2 linhas do que foi feito e premissas adotadas.
2. **Implementação:** Código completo, funcional, com todos os *imports* e tipos necessários (sem placeholders como `// resto do código aqui`, a menos que o arquivo seja imenso e o escopo seja cirúrgico).
3. **Verificação e Testes:** Casos de teste unitários/integração essenciais ou comandos exatos para validar a mudança.
4. **Riscos e Trade-offs:** Limitações conhecidas, impactos de performance/segurança ou próximos passos necessários.

#### Modo B: Correção Pontual, Dúvida Técnica ou Code Review
- Vá direto ao ponto: mostre a causa raiz do problema, forneça o trecho exato corrigido (ou a análise técnica) e explique o motivo de forma concisa.
### 0.7 Regras operacionais do GBOC (lições de produção)

* **Preservar o que funciona:** diffs locais e incrementais; nenhuma alteração pode remover ou quebrar funcionalidade existente. Toda correção deve ser validada com os serviços reais (Agente e Servidor) antes de ser dada como concluída.
* **Zero mock:** nunca exibir dados simulados, fixos ou "de exemplo" como se fossem reais (ver seção 11). Quando não houver dado, mostrar estado vazio ou "indisponível".
* **NTFS sem nomes 8.3:** o sistema deve funcionar em volumes com a criação de nomes curtos desativada. Nunca usar nem depender de caminhos 8.3 (`PROGRA~1`); passar caminhos completos e citados; executar processos com lista de argumentos (sem `shell=True` nem concatenação de strings).
* **Agente e Servidor no mesmo host:** cookies NÃO são isolados por porta (RFC 6265). Cada sistema usa o seu cookie de sessão: Agente `gboc_agent_token` (httponly) e Servidor `gboc_server_token`. Um sistema nunca grava nem apaga o cookie do outro. `localStorage` é isolado por origem (host+porta).
* **Contas:** a criação de administrador pela tela de login (`/setup`, "Primeiro acesso") só existe enquanto não há usuários (instalação). Depois disso, contas são criadas apenas dentro do sistema por um administrador; o backend deve recusar `/setup` (403).
* **Tema/estilo:** alterado somente após o login (Configurações > Estilos e Temas). A tela de login apenas aplica o tema salvo.
* **FastAPI:** nada de I/O bloqueante (banco, disco, subprocess) dentro de `async def`; usar `def` (threadpool) ou `asyncio.to_thread`.
* **PostgreSQL:** toda conexão obtida é devolvida em `finally`; em erro, `rollback`. Etapas opcionais dentro de uma transação maior ficam em `SAVEPOINT` (uma falha não pode abortar e descartar o resto). Respeitar `lock_timeout`/`statement_timeout` configurados e nunca deixar transação `idle in transaction`.
* **CSS/JS compartilhado:** editar em `shared-css/` e rodar `python tools/sync_css.py` (copia para `GBOC-Agent/static` e `GBOC-Server/static`; o Servidor também tem `GBOC-Server/gboc-layout-manager.js`). Não criar CSS isolado por página.
* **Regras de IA sincronizadas:** este conteúdo existe em `GBOC-Agent/AI_RULES.md`, `GBOC-Server/AI_RULES.md`, `.agents/AGENTS.md` e `.github/copilot-instructions.md`. Ao alterar um, atualize os demais.

---

## 1. Arquitetura e Modularização

* **Modular Code Requirement:** Always follow the modular structure defined in [ARCHITECTURE_POLICIES.md](file:///d:/GBOC-New/GBOC-New/ARCHITECTURE_POLICIES.md).
* **1 Module = 1 Directory:** Each menu feature or domain must reside in `modules/<domain>/`.
* Each module must contain, when applicable:

  * `modules/<domain>/<domain>_router.py`
  * `modules/<domain>/<domain>.js`
  * `modules/<domain>/<domain>.html`
  * Additional CSS, assets, services, models or utilities when required by the architecture.
* **Distribution Package Update Requirement:** A cada novo arquivo, módulo ou funcionalidade criada ou modificada nos fontes do sistema (`GBOC-Server` ou `GBOC-Agent`), o pacote de distribuição DEVE ser atualizado rodando `build_installer_package.ps1` (ou `tools/make_distribution.py`) para manter a pasta externa `GBOC-Distribution` sincronizada.
* **Clean Entrypoints:** Keep `gboc_server.py`, `agent_server.py`, and `dashboard.html` lean.
* Entrypoints must only:

  * initialize the application;
  * register module APIRouters;
  * configure required middleware;
  * expose the application shell;
  * serve the necessary UI shell.
* Business logic, system operations, database access, API logic and UI-specific functionality must remain inside their respective modules.

---

## 2. Modernization Policy

The entire GBOC system must be continuously maintained using **modern, current and supported technologies**.

When implementing new functionality or modifying existing functionality:

* Prefer the latest **stable and officially supported** language, framework and library features available at implementation time.
* Do not introduce obsolete, deprecated, legacy or superseded APIs.
* Replace obsolete code encountered during maintenance whenever doing so does not violate architectural or compatibility requirements.
* Do not use a legacy implementation when a modern, supported equivalent exists.
* Maintain compatibility with the project's currently supported runtime environments.
* Prioritize:

  1. security;
  2. maintainability;
  3. performance;
  4. accessibility;
  5. interoperability;
  6. standards compliance;
  7. long-term supportability.

---

## 3. HTML

The frontend must use **modern HTML5 and current HTML Living Standard features**.

Requirements:

* Use semantic HTML elements whenever applicable.
* Prefer modern HTML APIs and browser capabilities.
* Do not introduce obsolete HTML elements or attributes.
* Do not use deprecated HTML markup.
* Maintain valid and standards-compliant HTML.
* Use accessible semantic structures.
* Forms must use appropriate modern input types, validation attributes and semantic elements.
* Prefer native browser functionality over unnecessary JavaScript implementations.
* Ensure compatibility with current supported versions of Chromium/Edge, Firefox and other project-approved browsers.

---

## 4. CSS

The frontend must use **modern CSS according to the current CSS specifications and browser-supported standards** and follow the **Universal CSS Architecture Policy**.

> CSS does not have a single "CSS 4" or "CSS 5" version. Modern CSS is developed as a collection of continuously evolving specifications/modules.

### Universal CSS Architecture Policy (100% Shared & Zero Isolated CSS)

All stylesheets, layout definitions, theme tokens, and component styles MUST be strictly unified and shared across both `GBOC-Server` and `GBOC-Agent`.

**Mandatory Universal CSS Stack:**
1. **`style.css`**: Universal component framework, reset, cards, buttons, badges, data tables, form controls, toasts, modal base, and responsive layout foundations.
2. **`gboc-themes.css`**: Universal design tokens, 8 UI styles (`minimal`, `neumorphism`, `claymorphism`, `fluent`, `nexus-widgets`, `nexus-glass`, `command-sentinel`, `cyber-3d`), 6 illumination themes (`dark`, `light`, `amber`, `purple`, `ocean`, `red`), Bacula & Fiorilli presets, high-contrast light mode tokens.
3. **`gboc-layout.css`**: Dual layout engine (Vertical Sidebar + Horizontal Topbar), dynamic collapse/expand, smart presence detection, zero-overflow multi-resolution support.
4. **`gboc-hardware-hud.css`**: Real-time hardware telemetry HUD styles (Sensors, CPU, RAM, Disks, SMART).
5. **`gboc-file-picker.css`**: Universal file/directory tree explorer component styles.

**Rules:**
* **Zero Orphan/Isolated CSS Rule**: It is strictly forbidden to create divergent, isolated, or un-synchronized CSS files. All CSS files must be identical in `GBOC-Server` and `GBOC-Agent`.
* **Standard HTML Inclusions**: Every HTML page must include the universal CSS stack in canonical standard order.
* **Strict Design Token Usage**: All custom components and module templates must strictly consume CSS Custom Properties (`var(--bg-main)`, `var(--bg-card)`, `var(--text)`, `var(--border)`, `var(--primary)`, `var(--card-radius)`, etc.).
* Use modern layout systems: Flexbox, CSS Grid, Container Queries, Logical Properties, CSS Custom Properties.
* Avoid obsolete CSS properties and techniques.
* Do not use table-based layouts.
* Do not use inline styles unless there is a documented technical reason.
* Maintain responsive design and accessibility requirements.

---

## 5. JavaScript

The system must use the **latest stable ECMAScript standard supported by the project's target runtime and browsers**.

Requirements:

* Use modern ECMAScript syntax and APIs (`const`, `let`, arrow functions, `import`/`export`, `async`/`await`, `fetch`, optional chaining `?.`, nullish coalescing `??`).
* Do not introduce deprecated JavaScript APIs.
* Do not use `var` in new code.
* Do not use synchronous APIs when modern asynchronous alternatives exist.
* Handle asynchronous errors explicitly.
* Validate API responses before processing them.
* Never silently ignore exceptions.

---

## 6. Strict Zero-Mock Policy

**MOCK DATA IS STRICTLY PROHIBITED.**

The GBOC system must **NEVER** use:

* mock data;
* fake data;
* simulated system status;
* hardcoded monitoring values;
* fabricated service states;
* fabricated hardware information;
* fake network information;
* placeholder production values;
* simulated API responses;
* fake database records;
* fake process information;
* fake disk information;
* fake CPU/RAM information;
* fake Windows service information;
* fake agent status;
* fake backup status;
* fake connectivity status.

Whenever a feature displays system information, it must retrieve **100% real data from the actual execution environment**.

---

## 7. Absolute Development Rules

* **NEVER use mock data.**
* **NEVER use fake system information.**
* **NEVER fabricate API responses.**
* **ALWAYS prefer current stable standards and supported APIs.**
* **ALWAYS retrieve system information from the real execution environment.**
* **ALWAYS maintain the modular architecture defined by `ARCHITECTURE_POLICIES.md`.**
* **ALWAYS enforce Universal CSS Architecture Policy (100% shared standard CSS stack, zero isolated/orphan CSS, universal design tokens).**
* **ALWAYS update the distribution package (`build_installer_package.ps1`) whenever a new file is added or modified in the workspace.**
* **ALWAYS apply Motion Principles (Kyle Zantos Motion Principles: Skeleton loaders, lazy loading, smooth entering/exiting and fluid progress animations) on all user interfaces.**
* **ALWAYS enforce Observability, Code Governance and E2E/Unit Test Integrity.**
* **ALWAYS prioritize security, reliability, accessibility and maintainability.**