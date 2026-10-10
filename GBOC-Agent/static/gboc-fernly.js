/*
==============================================================================
GBOC System v14.8.1 Enterprise — Fernly Runtime (JS puro)
Motor Antigravity + grafismos para os estilos Fernly (data-ui-style="fernly*").

- Micro-oscilação assíncrona no eixo Y: cada card tem fase e período próprios.
- Hover: o card "perde a gravidade" — sobe com impulso, inclina em 3D na
  direção do ponteiro (tilt) e, no Cyberpunk, é atraído magneticamente.
- Integração por mola amortecida (semi-implícito de Euler), 1 único rAF.
- Parâmetros lidos do CSS (--ag-*): o tema declara, o motor executa.
- Entrada escalonada dos cards (cubic-bezier) ao abrir a página.
- Barras dos gráficos Chart.js existentes recebem hachura diagonal
  (cor original preservada e restaurada ao sair do estilo).

Garantias de não-regressão:
- Inativo (e sem custo) em qualquer estilo que não declare --ag-enabled: 1.
- Ao sair do estilo, restaura o transform inline original de cada elemento.
- Pausa com a aba oculta, só anima o que está visível, respeita
  prefers-reduced-motion e cai para "só hover" se o computador não acompanhar.
- Cards dentro de cards, modais e o painel de personalização são ignorados;
  qualquer elemento pode sair com data-antigravity="off" ou entrar com
  data-antigravity.

API: window.GBOCAntigravity.refresh() | .rescan() | .isActive()
==============================================================================
*/

(function (window, document) {
    'use strict';

    if (window.GBOCAntigravity) return;

    const ROOT = document.documentElement;

    const TARGETS = [
        '.card', '.panel', '.stat-card', '.kpi-card', '.dashboard-card', '.data-card',
        '.quick-action-card', '.widget', '.theme-showcase-card', '.gboc-card',
        '.card-panel', '.chart-panel', '.task-card', '.repo-usage-card', '[data-antigravity]'
    ].join(',');

    const EXCLUDE = [
        '[data-antigravity="off"]', '#gboc-layout-panel', 'dialog',
        '.modal', '.modal-backdrop', '.modal-dialog', '.modal-content'
    ].join(',');

    const DRAG_STATE = '.dragging, .sortable-chosen, .sortable-ghost, [aria-grabbed="true"]';

    const TAU = Math.PI * 2;
    const GOLDEN = 1.618;
    const MAX_DT = 1 / 30;           // evita explosão da mola após travadas
    const SLOW_FRAME_MS = 40;        // média acima disso => modo econômico
    const SLOW_FRAMES_LIMIT = 90;
    const ENTER_STEP_MS = 45;        // atraso entre cards na entrada
    const ENTER_MAX_MS = 540;

    const bodies = new Map();        // Element -> estado físico
    let params = null;
    let active = false;
    let rafId = 0;
    let lastT = 0;
    let clock = 0;
    let frameAvg = 16.7;
    let slowFrames = 0;
    let degraded = false;
    let hovered = null;
    let io = null;
    let mo = null;
    let rescanTimer = 0;
    let resizeTimer = 0;
    let retryCount = 0;
    let enterIndex = 0;
    let enterDone = false;

    // ── Parâmetros declarados pelo tema ──────────────────────────────────────
    function readParams() {
        const cs = getComputedStyle(ROOT);
        const num = (name, fallback) => {
            const v = parseFloat(cs.getPropertyValue(name));
            return Number.isFinite(v) ? v : fallback;
        };
        return {
            enabled:  num('--ag-enabled', 0) > 0,
            amp:      Math.max(0, num('--ag-float-amp', 0)),
            period:   Math.max(0.5, num('--ag-float-period', 7)),
            tilt:     Math.max(0, num('--ag-tilt', 0)),
            lift:     Math.max(0, num('--ag-lift', 0)),
            scale:    Math.max(0.9, num('--ag-scale', 1)),
            k:        Math.max(1, num('--ag-stiffness', 120)),
            c:        Math.max(0, num('--ag-damping', 18)),
            impulse:  Math.max(0, num('--ag-impulse', 0)),
            magnet:   Math.max(0, num('--ag-magnet', 0)),
            hatch:    num('--ag-hatch-charts', 0) > 0
        };
    }

    const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

    // ── Registro de corpos ───────────────────────────────────────────────────
    function isEligible(el) {
        if (!el.isConnected || el.closest(EXCLUDE)) return false;
        const parent = el.parentElement && el.parentElement.closest(TARGETS);
        // Card aninhado: só o externo flutua (evita dupla transformação)
        return !(parent && !parent.closest(EXCLUDE));
    }

    function measure(state) {
        const w = state.el.offsetWidth || 1;
        const h = state.el.offsetHeight || 1;
        // Painéis grandes oscilam e inclinam menos — o efeito continua elegante
        state.sizeK = clamp(240 / h, 0.3, 1);
        state.tiltK = clamp(360 / Math.max(w, h), 0.3, 1);
    }

    function register(el) {
        if (bodies.has(el)) return;
        const rnd = Math.random;
        const state = {
            el,
            y:  { p: 0, v: 0 },
            x:  { p: 0, v: 0 },
            rx: { p: 0, v: 0 },
            ry: { p: 0, v: 0 },
            s:  { p: 1, v: 0 },
            ph1: rnd() * TAU,
            ph2: rnd() * TAU,
            pf: 0.85 + rnd() * 0.3,              // período individual (assíncrono)
            hover: false,
            focus: false,
            px: 0,
            py: 0,
            rect: null,
            visible: true,
            sizeK: 1,
            tiltK: 1,
            last: '',
            origTransform: el.style.transform,
            origWillChange: el.style.willChange
        };
        measure(state);
        const r0 = el.getBoundingClientRect();
        state.visible = r0.bottom > -80 && r0.top < window.innerHeight + 80;
        el.classList.add('ag-body');
        el.style.willChange = 'transform';
        // Entrada escalonada só na primeira varredura (não em atualizações da página)
        if (!enterDone && state.visible) {
            el.style.setProperty('--ag-enter-delay', Math.min(enterIndex++ * ENTER_STEP_MS, ENTER_MAX_MS) + 'ms');
            el.classList.add('ag-enter');
            el.addEventListener('animationend', function onEnd(e) {
                if (e.animationName !== 'fy-rise') return;
                el.classList.remove('ag-enter');
                el.style.removeProperty('--ag-enter-delay');
                el.removeEventListener('animationend', onEnd);
            });
        }
        bodies.set(el, state);
        if (io) io.observe(el);
    }

    function release(state) {
        const el = state.el;
        if (io) io.unobserve(el);
        el.classList.remove('ag-body', 'ag-hover', 'ag-enter');
        el.style.removeProperty('--ag-enter-delay');
        el.style.transform = state.origTransform;
        el.style.willChange = state.origWillChange;
        bodies.delete(el);
    }

    function rescan() {
        rescanTimer = 0;
        if (!active) return;
        bodies.forEach((state, el) => { if (!isEligible(el)) release(state); });
        document.querySelectorAll(TARGETS).forEach(el => { if (isEligible(el)) register(el); });
    }

    function queueRescan() {
        if (!rescanTimer) rescanTimer = window.setTimeout(rescan, 150);
    }

    function findBody(node) {
        let n = node && node.nodeType === 1 ? node.closest(TARGETS) : null;
        while (n && !bodies.has(n)) n = n.parentElement && n.parentElement.closest(TARGETS);
        return n ? bodies.get(n) : null;
    }

    // ── Interação ────────────────────────────────────────────────────────────
    function setHover(state, on) {
        if (!state || state.hover === on) return;
        state.hover = on;
        state.el.classList.toggle('ag-hover', on || state.focus);
        if (on) {
            state.rect = state.el.getBoundingClientRect();
            state.y.v -= params.impulse;                 // impulso: perde a gravidade
        } else {
            state.px = state.py = 0;
            state.rect = null;
        }
    }

    function onPointerMove(e) {
        const state = findBody(e.target);
        if (state !== hovered) {
            setHover(hovered, false);
            hovered = state;
            setHover(hovered, true);
        }
        if (!hovered || e.pointerType === 'touch') return;
        const r = hovered.rect || (hovered.rect = hovered.el.getBoundingClientRect());
        hovered.px = clamp((e.clientX - (r.left + r.width / 2)) / (r.width / 2 || 1), -1, 1);
        hovered.py = clamp((e.clientY - (r.top + r.height / 2)) / (r.height / 2 || 1), -1, 1);
    }

    function onPointerOut(e) {
        if (!e.relatedTarget) { setHover(hovered, false); hovered = null; }
    }

    function onScroll() {
        if (hovered) hovered.rect = null;
    }

    function onFocusIn(e) {
        const state = findBody(e.target);
        if (!state) return;
        state.focus = true;
        state.el.classList.add('ag-hover');
    }

    function onFocusOut(e) {
        const state = findBody(e.target);
        if (!state || state.el.contains(e.relatedTarget)) return;
        state.focus = false;
        state.el.classList.toggle('ag-hover', state.hover);
    }

    function onResize() {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(() => bodies.forEach(measure), 200);
    }

    function onVisibility() {
        if (!active) return;
        if (document.hidden) {
            cancelAnimationFrame(rafId);
            rafId = 0;
        } else if (!rafId) {
            lastT = 0;
            rafId = requestAnimationFrame(tick);
        }
    }

    // ── Integração física ────────────────────────────────────────────────────
    function spring(ch, target, dt) {
        const a = -params.k * (ch.p - target) - params.c * ch.v;
        ch.v += a * dt;
        ch.p += ch.v * dt;
    }

    function step(state, dt) {
        const P = params;
        let ty, tx = 0, trx = 0, try_ = 0, ts = 1;

        if (state.hover || state.focus) {
            ty = -P.lift;
            ts = P.scale;
            if (state.hover) {
                const tilt = P.tilt * state.tiltK;
                try_ = tilt * state.px;
                trx = -tilt * state.py;
                if (P.magnet > 0 && state.rect) {
                    tx = clamp(P.magnet * state.px * state.rect.width / 2, -14, 14);
                    ty += clamp(P.magnet * state.py * state.rect.height / 2, -10, 10);
                }
            }
        } else {
            const amp = degraded ? 0 : P.amp * state.sizeK;
            const per = P.period * state.pf;
            ty = amp * (0.65 * Math.sin(TAU * clock / per + state.ph1) +
                        0.35 * Math.sin(TAU * clock / (per * GOLDEN) + state.ph2));
        }

        spring(state.y, ty, dt);
        spring(state.x, tx, dt);
        spring(state.rx, trx, dt);
        spring(state.ry, try_, dt);
        spring(state.s, ts, dt);
    }

    function render(state) {
        const el = state.el;
        if (el.matches(DRAG_STATE)) {
            if (state.last) { el.style.transform = state.origTransform; state.last = ''; }
            return;
        }
        const tf = 'perspective(900px) translate3d(' +
            state.x.p.toFixed(2) + 'px,' + state.y.p.toFixed(2) + 'px,0) rotateX(' +
            state.rx.p.toFixed(2) + 'deg) rotateY(' + state.ry.p.toFixed(2) + 'deg) scale(' +
            state.s.p.toFixed(4) + ')';
        if (tf !== state.last) {
            el.style.transform = tf;
            state.last = tf;
        }
    }

    function tick(t) {
        rafId = requestAnimationFrame(tick);
        if (!lastT) { lastT = t; return; }
        const rawMs = t - lastT;
        lastT = t;
        const dt = Math.min(rawMs / 1000, MAX_DT);
        clock += dt;

        // Guarda de desempenho: se o computador não acompanha, desliga a flutuação
        frameAvg += (rawMs - frameAvg) * 0.05;
        if (!degraded) {
            slowFrames = frameAvg > SLOW_FRAME_MS ? slowFrames + 1 : 0;
            if (slowFrames > SLOW_FRAMES_LIMIT) {
                degraded = true;
                ROOT.setAttribute('data-ag-degraded', '1');
            }
        }

        bodies.forEach(state => {
            if (!state.visible && !state.hover && !state.focus) return;
            step(state, dt);
            render(state);
        });
    }

    // ── Ciclo de vida ────────────────────────────────────────────────────────
    function activate() {
        active = true;
        degraded = false;
        slowFrames = 0;
        ROOT.removeAttribute('data-ag-degraded');

        if ('IntersectionObserver' in window) {
            io = new IntersectionObserver(entries => {
                entries.forEach(entry => {
                    const state = bodies.get(entry.target);
                    if (state) state.visible = entry.isIntersecting;
                });
            }, { rootMargin: '80px' });
        }
        if ('MutationObserver' in window && document.body) {
            mo = new MutationObserver(queueRescan);
            mo.observe(document.body, { childList: true, subtree: true });
        }

        document.addEventListener('pointermove', onPointerMove, { passive: true });
        document.addEventListener('pointerdown', onPointerMove, { passive: true });
        document.addEventListener('pointerout', onPointerOut, { passive: true });
        document.addEventListener('focusin', onFocusIn);
        document.addEventListener('focusout', onFocusOut);
        window.addEventListener('scroll', onScroll, { passive: true, capture: true });
        window.addEventListener('resize', onResize, { passive: true });

        enterIndex = 0;
        enterDone = false;
        rescan();
        enterDone = true;
        lastT = 0;
        if (!document.hidden) rafId = requestAnimationFrame(tick);
    }

    function deactivate() {
        active = false;
        cancelAnimationFrame(rafId);
        rafId = 0;
        window.clearTimeout(rescanTimer);
        rescanTimer = 0;
        hovered = null;

        document.removeEventListener('pointermove', onPointerMove);
        document.removeEventListener('pointerdown', onPointerMove);
        document.removeEventListener('pointerout', onPointerOut);
        document.removeEventListener('focusin', onFocusIn);
        document.removeEventListener('focusout', onFocusOut);
        window.removeEventListener('scroll', onScroll, { capture: true });
        window.removeEventListener('resize', onResize);

        bodies.forEach(release);
        if (io) { io.disconnect(); io = null; }
        if (mo) { mo.disconnect(); mo = null; }
        ROOT.removeAttribute('data-ag-degraded');
    }

    // ── Grafismos: hachura nas barras dos gráficos Chart.js ──────────────────
    const patternCache = new Map();
    let chartsHooked = false;

    function hatchPattern(color) {
        if (typeof color !== 'string') return color;     // gradiente/padrão: mantém
        if (patternCache.has(color)) return patternCache.get(color);
        const size = 10;
        const cv = document.createElement('canvas');
        cv.width = cv.height = size;
        const g = cv.getContext('2d');
        g.fillStyle = color;
        g.fillRect(0, 0, size, size);
        g.strokeStyle = 'rgba(255, 255, 255, 0.35)';
        g.lineWidth = 2;
        g.beginPath();
        // três segmentos garantem continuidade da diagonal entre ladrilhos
        for (let o = -size; o <= size; o += size) {
            g.moveTo(o, size);
            g.lineTo(o + size, 0);
        }
        g.stroke();
        const pat = g.createPattern(cv, 'repeat');
        patternCache.set(color, pat);
        return pat;
    }

    function isBarDataset(chart, ds) {
        return (ds.type || chart.config.type) === 'bar';
    }

    function hatchChart(chart) {
        const on = active && params && params.hatch;
        let changed = false;
        (chart.data.datasets || []).forEach(ds => {
            if (!isBarDataset(chart, ds)) return;
            if (on) {
                // guarda o original uma vez; se o app trocar a cor depois, adota a nova
                const cur = ds.backgroundColor;
                if (ds.$gbocHatched !== cur) {
                    ds.$gbocOrigBg = cur;
                    ds.backgroundColor = Array.isArray(cur) ? cur.map(hatchPattern) : hatchPattern(cur);
                    ds.$gbocHatched = ds.backgroundColor;
                    changed = true;
                }
            } else if ('$gbocOrigBg' in ds) {
                if (ds.backgroundColor === ds.$gbocHatched) ds.backgroundColor = ds.$gbocOrigBg;
                delete ds.$gbocOrigBg;
                delete ds.$gbocHatched;
                changed = true;
            }
        });
        // Chart.js 4 já resolveu os escopos do dataset antes de beforeUpdate:
        // limpa o cache para a nova cor valer neste mesmo ciclo.
        if (changed && chart.config && typeof chart.config.clearCache === 'function') chart.config.clearCache();
        // Em update('none') o Chart.js não repropaga opções compartilhadas dos
        // elementos; um update normal no próximo frame aplica a nova cor.
        // Sem laço: a segunda passada não encontra nada para mudar.
        if (changed) requestAnimationFrame(() => { try { chart.update(); } catch (e) { /* destruído */ } });
    }

    function hookCharts() {
        const Chart = window.Chart;
        if (chartsHooked || !Chart || !Chart.register) return;
        chartsHooked = true;
        Chart.register({ id: 'gbocFernlyHatch', beforeUpdate: hatchChart });
    }

    function refreshCharts() {
        hookCharts();
        const Chart = window.Chart;
        if (!Chart || !Chart.instances) return;
        Object.values(Chart.instances).forEach(ch => {
            try { ch.update('none'); } catch (e) { /* gráfico em destruição */ }
        });
    }

    function evaluate() {
        params = readParams();
        const wasActive = active;
        if (params.enabled && !active) activate();
        else if (!params.enabled && active) deactivate();
        if (wasActive !== active || active) refreshCharts();

        // A folha gboc-fernly.css pode chegar depois deste script: tenta de novo
        const wantsFernly = (ROOT.getAttribute('data-ui-style') || '').startsWith('fernly');
        if (wantsFernly && !params.enabled && retryCount < 20) {
            retryCount++;
            window.setTimeout(evaluate, 150);
        } else {
            retryCount = 0;
        }
    }

    new MutationObserver(evaluate).observe(ROOT, {
        attributes: true,
        attributeFilter: ['data-ui-style', 'data-theme', 'data-color-theme']
    });

    const reduceMQ = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
    if (reduceMQ && reduceMQ.addEventListener) reduceMQ.addEventListener('change', evaluate);

    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('load', evaluate, { once: true });
    document.addEventListener('gboc:charts-ready', refreshCharts);

    window.GBOCAntigravity = {
        refresh: evaluate,
        rescan() { if (active) rescan(); },
        isActive() { return active; }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', evaluate, { once: true });
    } else {
        evaluate();
    }
})(window, document);
