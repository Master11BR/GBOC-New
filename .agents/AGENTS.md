# GBOC System Agent Workspace Rules

## 1. Arquitetura e Modularização

* **Modular Code Requirement:** Always follow the modular structure defined in [ARCHITECTURE_POLICIES.md](file:///d:/GBOC-New/GBOC-New/ARCHITECTURE_POLICIES.md).
* **1 Module = 1 Directory:** Each menu feature or domain must reside in `modules/<domain>/`.
* Each module must contain, when applicable:

  * `modules/<domain>/<domain>_router.py`
  * `modules/<domain>/<domain>.js`
  * `modules/<domain>/<domain>.html`
  * Additional CSS, assets, services, models or utilities when required by the architecture.
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

Examples of preferred modern elements include:

* `<header>`
* `<nav>`
* `<main>`
* `<section>`
* `<article>`
* `<aside>`
* `<footer>`
* `<dialog>`
* `<details>`
* `<summary>`
* `<template>`

Do not use obsolete elements such as:

* `<font>`
* `<center>`
* `<marquee>`
* presentation-only HTML structures when CSS provides the appropriate solution.

---

## 4. CSS

The frontend must use **modern CSS according to the current CSS specifications and browser-supported standards**.

> CSS does not have a single "CSS 4" or "CSS 5" version. Modern CSS is developed as a collection of continuously evolving specifications/modules.

Requirements:

* Use the latest stable CSS features supported by the project's target browsers.
* Prefer modern CSS layout systems:

  * Flexbox
  * CSS Grid
  * Container Queries
  * Logical Properties
  * CSS Custom Properties
  * modern media queries
  * modern selectors
  * modern color functions when appropriate
* Avoid obsolete CSS properties and techniques.
* Do not use table-based layouts.
* Do not use inline styles unless there is a documented technical reason.
* Prefer reusable CSS classes and CSS Custom Properties.
* Maintain responsive design.
* Support accessibility requirements.
* Avoid unnecessary JavaScript for functionality that can be implemented reliably using modern CSS.
* Remove obsolete vendor-prefix workarounds when they are no longer required by supported browsers.

---

## 5. JavaScript

The system must use the **latest stable ECMAScript standard supported by the project's target runtime and browsers**.

> JavaScript does not have a "JavaScript 3" version. The language specification is ECMAScript and is released as continuously evolving annual editions.

Requirements:

* Use modern ECMAScript syntax and APIs.
* Prefer:

  * `const`
  * `let`
  * arrow functions
  * modules (`import` / `export`)
  * `async` / `await`
  * `Promise`
  * `fetch`
  * optional chaining (`?.`)
  * nullish coalescing (`??`)
  * destructuring
  * template literals
  * modern array/object methods
  * `AbortController`
  * `URL` / `URLSearchParams`
  * modern Web APIs
* Do not introduce deprecated JavaScript APIs.
* Do not use obsolete browser APIs when a modern standard replacement exists.
* Avoid unnecessary global variables.
* Avoid polluting the global namespace.
* Prefer ES modules and modular JavaScript architecture.
* Do not use `var` in new code.
* Do not use synchronous APIs when modern asynchronous alternatives exist.
* Do not use `XMLHttpRequest` when `fetch()` is appropriate.
* Do not use obsolete DOM techniques when modern DOM APIs are available.
* Handle asynchronous errors explicitly.
* Validate API responses before processing them.
* Never silently ignore exceptions.

---

## 6. jQuery

If jQuery is required by an existing module or dependency:

* Always use the **latest stable, officially supported jQuery release compatible with the system**.
* Do not introduce deprecated jQuery APIs.
* Do not use legacy jQuery functionality when an equivalent modern browser API is available, unless jQuery is required for compatibility with an existing component.
* Prefer native modern JavaScript APIs for new functionality whenever practical.
* Existing jQuery code should be progressively modernized where safe.
* Avoid adding new dependencies on obsolete jQuery plugins.

Examples of preferred modern alternatives:

* `fetch()` instead of `$.ajax()` for new API calls when appropriate.
* `document.querySelector()` / `querySelectorAll()` instead of unnecessary jQuery selectors.
* `classList` instead of excessive `.addClass()` / `.removeClass()` usage.
* `addEventListener()` instead of introducing new jQuery event dependencies.

---

## 7. Tailwind CSS

When Tailwind CSS is used:

* Always use the **latest stable Tailwind CSS release available and supported by the project**.
* Do not use deprecated Tailwind utilities.
* Follow the current Tailwind configuration and build methodology.
* Avoid unnecessary custom CSS when an appropriate Tailwind utility exists.
* Do not mix obsolete Tailwind syntax with the current version.
* Keep Tailwind configuration modular and maintainable.
* Remove obsolete utilities when upgrading Tailwind.
* Verify generated CSS after major Tailwind upgrades.

---

## 8. Bootstrap

When Bootstrap is used:

* Always use the **latest stable Bootstrap release compatible with the project**.
* Do not introduce deprecated Bootstrap components, classes or JavaScript APIs.
* Use the current Bootstrap component structure and utilities.
* Do not mix components from incompatible Bootstrap major versions.
* When upgrading Bootstrap, migrate deprecated APIs instead of preserving legacy implementations.
* Prefer Bootstrap's current responsive utilities and layout system.

---

## 9. Python

The backend must use **modern Python syntax, APIs and libraries**.

Requirements:

* Use the latest stable Python version officially supported by the project.
* Do not introduce deprecated Python syntax, modules, functions or APIs.
* Remove obsolete/deprecated Python constructs encountered during modernization when safe.
* Prefer modern Python features such as:

  * type hints;
  * `dataclasses`;
  * `pathlib`;
  * `enum`;
  * context managers;
  * `async` / `await` where appropriate;
  * modern exception handling;
  * structural pattern matching where appropriate;
  * modern type syntax compatible with the project's Python version.
* Prefer `pathlib` instead of legacy filesystem manipulation with `os.path` when appropriate.
* Prefer modern standard-library APIs over obsolete alternatives.
* Avoid unnecessary global state.
* Avoid deprecated APIs.
* Do not use Python 2 syntax or compatibility code.
* Do not use obsolete library interfaces when a maintained replacement exists.
* Keep dependencies updated to supported stable versions.
* Validate external input.
* Handle exceptions explicitly.
* Use structured logging instead of `print()` for application diagnostics.
* Do not suppress exceptions without a documented reason.

### Python modernization rule

Whenever existing Python code contains a deprecated or obsolete implementation:

1. Identify the obsolete API.
2. Determine the currently supported replacement.
3. Replace it when compatibility permits.
4. Test the affected functionality.
5. Do not preserve obsolete code merely because it already exists.

---

## 10. API Design

All APIs must return structured responses.

Requirements:

* Always use the correct HTTP status code.
* Return structured JSON for API endpoints unless another response format is explicitly required.
* Validate request parameters and payloads.
* Validate external/system data before returning it.
* Provide meaningful error responses.
* Never expose internal stack traces, credentials, secrets or sensitive system information to clients.
* Maintain consistent response structures throughout the system.
* Use appropriate HTTP methods:

  * `GET` for retrieval;
  * `POST` for creation/actions;
  * `PUT`/`PATCH` for updates;
  * `DELETE` for deletion.
* Avoid implementing state-changing operations through `GET`.

---

## 11. Strict Zero-Mock Policy

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

### Real Data Requirement

Whenever a feature displays system information, it must retrieve **100% real data from the actual execution environment**.

Examples:

* CPU → actual host CPU information.
* RAM → actual host memory information.
* Disk → actual disks and volumes.
* Network → actual network interfaces and addresses.
* Processes → actual running processes.
* Services → actual operating-system services.
* Windows information → actual Windows APIs/system commands.
* Linux information → actual Linux APIs/system interfaces.
* Backup status → actual configured backup system.
* Agent status → actual agent process/service state.
* Application status → actual application state.
* Database information → actual database.
* Logs → actual system/application logs.

### No Fake UI States

The interface must not display statuses such as:

* `Online`
* `Healthy`
* `Running`
* `Connected`
* `OK`
* `Available`
* `Operational`

unless that state has been verified from the real underlying system.

If real data cannot be obtained:

* return an explicit error;
* identify the reason;
* indicate that the information is unavailable;
* do not substitute fake or placeholder values.

Example:

```json
{
  "status": "unavailable",
  "error": {
    "code": "SYSTEM_DATA_UNAVAILABLE",
    "message": "Unable to retrieve the actual service status."
  }
}
```

Never replace this with:

```json
{
  "status": "running"
}
```

unless the service was actually verified as running.

---

## 12. System Command Execution

When system information requires operating-system commands:

* Use the actual executable installed on the host.
* Resolve and verify executable paths whenever possible.
* Do not assume that a command exists.
* Do not fabricate command output.
* Validate exit codes.
* Capture and handle `stdout` and `stderr`.
* Apply appropriate execution timeouts.
* Avoid shell execution when a direct API or subprocess invocation is safer.
* Never construct unsafe shell commands from untrusted input.
* Verify that returned information corresponds to the actual host environment.

---

## 13. Security

Security must be considered part of every implementation.

Requirements:

* Never hardcode passwords.
* Never hardcode API keys.
* Never hardcode access tokens.
* Never commit secrets to source control.
* Validate and sanitize external input.
* Use secure authentication mechanisms.
* Use authorization checks for protected operations.
* Apply least-privilege principles.
* Avoid command injection.
* Avoid SQL injection.
* Avoid path traversal.
* Avoid XSS.
* Avoid unsafe deserialization.
* Avoid exposing sensitive diagnostics to users.
* Do not disable security controls merely to make functionality work.

---

## 14. Frontend / Backend Separation

The frontend and backend must remain clearly separated.

Frontend responsibilities:

* presentation;
* interaction;
* client-side validation;
* API consumption;
* UI state management.

Backend responsibilities:

* business logic;
* authentication;
* authorization;
* system operations;
* database access;
* operating-system integration;
* validation of trusted system state;
* API responses.

The frontend must never fabricate backend/system information.

---

## 15. Error Handling

All modules must implement explicit error handling.

Requirements:

* Never silently swallow errors.
* Log relevant technical details server-side.
* Return safe and structured error information to the frontend.
* Use appropriate HTTP status codes.
* Distinguish between:

  * validation errors;
  * authentication errors;
  * authorization errors;
  * resource-not-found errors;
  * system errors;
  * dependency failures;
  * timeout errors;
  * unavailable services.

---

## 16. Dependency Management

All third-party dependencies must:

* use maintained versions;
* use supported releases;
* avoid known obsolete APIs;
* avoid abandoned libraries whenever a maintained alternative exists;
* be periodically reviewed;
* be upgraded when compatibility and stability permit.

Do not add a dependency merely to reproduce functionality already available through modern browser, Python or framework APIs.

---

## 17. Accessibility

All UI modules must follow modern accessibility practices.

Requirements include:

* semantic HTML;
* keyboard navigation;
* accessible labels;
* appropriate ARIA usage when necessary;
* visible focus states;
* sufficient contrast;
* accessible forms;
* meaningful error messages;
* screen-reader compatibility;
* responsive layouts.

Prefer native semantic HTML over unnecessary ARIA.

---

## 18. Responsive Design

All frontend modules must be responsive.

The interface must work correctly on:

* desktop;
* notebook;
* tablet;
* mobile devices;
* different resolutions;
* different browser zoom levels.

Do not create fixed-size layouts that unnecessarily prevent responsive behavior.

---

## 19. Code Quality

All code must prioritize:

* readability;
* maintainability;
* modularity;
* testability;
* security;
* performance;
* observability;
* standards compliance.

Avoid:

* duplicated logic;
* unnecessary abstractions;
* dead code;
* commented-out obsolete implementations;
* magic numbers;
* magic strings;
* global state;
* unnecessarily complex functions;
* obsolete compatibility workarounds.

---

## 20. Modernization of Existing Code

When modifying an existing module, do not simply append new functionality to outdated code.

Whenever practical:

1. Inspect the existing implementation.
2. Identify obsolete APIs and patterns.
3. Replace deprecated implementations.
4. Preserve existing functional behavior.
5. Improve architecture where safe.
6. Improve error handling.
7. Improve security.
8. Improve performance where appropriate.
9. Maintain real-data requirements.
10. Test the complete affected functionality.

The objective is to **modernize the existing system progressively**, not to accumulate new code on top of legacy implementations.

---

## 21. Absolute Development Rules

The following rules are mandatory:

* **NEVER use mock data.**
* **NEVER use fake system information.**
* **NEVER fabricate API responses.**
* **NEVER fabricate system status.**
* **NEVER introduce deprecated APIs in new code.**
* **NEVER introduce obsolete commands when a supported replacement exists.**
* **NEVER use outdated JavaScript syntax in new code.**
* **NEVER use obsolete HTML elements.**
* **NEVER use obsolete CSS techniques when modern CSS provides an equivalent.**
* **NEVER introduce deprecated Python APIs.**
* **NEVER hardcode production system information.**
* **NEVER assume that a service, process, disk, network interface or backup is operational without verifying it against the real system.**
* **ALWAYS prefer current stable standards and supported APIs.**
* **ALWAYS retrieve system information from the real execution environment.**
* **ALWAYS validate API responses and system command results.**
* **ALWAYS maintain the modular architecture defined by `ARCHITECTURE_POLICIES.md`.**
* **ALWAYS preserve the separation between frontend, backend and system-integration responsibilities.**
* **ALWAYS prioritize security, reliability, accessibility and maintainability.**

---

## 22. Technology Baseline

The project technology baseline is:

| Technology      | Required Standard                                            |
| --------------- | ------------------------------------------------------------ |
| HTML            | Modern HTML5 / current HTML Living Standard                  |
| CSS             | Current stable CSS specifications/modules                    |
| JavaScript      | Latest stable ECMAScript supported by the target environment |
| jQuery          | Latest stable supported release when jQuery is required      |
| Tailwind CSS    | Latest stable supported release                              |
| Bootstrap       | Latest stable supported release                              |
| Python          | Latest stable version supported by the project               |
| APIs            | Current supported API specifications                         |
| Browser APIs    | Current standards supported by target browsers               |
| Backend APIs    | Current supported framework APIs                             |
| System Commands | Current, supported OS commands/APIs                          |
| Dependencies    | Maintained and supported versions                            |

### Versioning rule

Do **not** interpret "latest version" as permission to blindly upgrade every dependency.

Before adopting a newer major version:

* verify compatibility;
* verify breaking changes;
* verify supported runtime versions;
* verify deprecated API removals;
* migrate affected code;
* test the affected modules.

The objective is always:

**Latest stable + supported + compatible + secure + tested.**

---

## 23. Final Development Principle

> **Build the GBOC system as a modern, production-grade system using current standards, current supported APIs and real information from the actual environment.**

No simulations.

No fake data.

No obsolete implementations.

No unnecessary legacy compatibility.

No fabricated status.

Every displayed system state must originate from the **real system being monitored or managed**.

 