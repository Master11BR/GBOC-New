# GBOC System Copilot Workspace Instructions

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