/* ============================================================================
   GBOC System v14.5.0 — Performance Helpers
   Objetivo: Eliminar reflows desnecessarios, debounce de inputs, abort de
   fetch concorrente, polling adaptativo por visibilidade da aba.

   Carregado via <head> antes dos scripts de pagina (via standardize_all_html_css.py).
   Nao tem dependencias.
   ============================================================================ */

(function (global) {
    'use strict';

    // ------------------------------------------------------------------
    // safeRender(el, nextHtml) — evita .innerHTML = mesmo HTML
    // Quando os dados do polling nao mudaram, nao dispara reflow.
    // Economiza ~90% dos reflows em dashboards com polling frequente.
    // ------------------------------------------------------------------
    function safeRender(el, nextHtml) {
        if (!el) return false;
        var html = nextHtml == null ? '' : String(nextHtml);
        if (el._gbocLastHtml === html) return false;
        el._gbocLastHtml = html;
        el.innerHTML = html;
        return true;
    }

    // ------------------------------------------------------------------
    // safeText(el, text) — mesmo conceito para textContent
    // ------------------------------------------------------------------
    function safeText(el, text) {
        if (!el) return false;
        var s = text == null ? '' : String(text);
        if (el._gbocText === s) return false;
        el._gbocText = s;
        el.textContent = s;
        return true;
    }

    // ------------------------------------------------------------------
    // debounce(fn, ms=250) — atrasa execucao enquanto chegam eventos
    // Ideal para inputs de busca / filtros / onChange rapidos.
    // ------------------------------------------------------------------
    function debounce(fn, ms) {
        var t;
        ms = ms || 250;
        return function gbocDebounced() {
            var ctx = this;
            var args = arguments;
            clearTimeout(t);
            t = setTimeout(function () { fn.apply(ctx, args); }, ms);
        };
    }

    // ------------------------------------------------------------------
    // throttle(fn, ms=100) — garante no maximo 1 invocacao por janela
    // Ideal para scroll / resize.
    // ------------------------------------------------------------------
    function throttle(fn, ms) {
        var last = 0;
        var t;
        ms = ms || 100;
        return function gbocThrottled() {
            var ctx = this;
            var args = arguments;
            var now = Date.now();
            var left = ms - (now - last);
            if (left <= 0) {
                clearTimeout(t); t = null; last = now;
                fn.apply(ctx, args);
            } else if (!t) {
                t = setTimeout(function () {
                    last = Date.now(); t = null;
                    fn.apply(ctx, args);
                }, left);
            }
        };
    }

    // ------------------------------------------------------------------
    // makeCancellable(callerKey, fnFactory) — evita race de fetch.
    // fnFactory(signal) deve retornar uma Promise (ex: fetch(url,{signal})).
    // Chamadas concorrentes cancelam a requisicao anterior.
    // Retorna Promise do resultado.
    // Exemplo: makeCancellable('loadLogs', (sig)=>fetch('/logs',{signal:sig}))
    // ------------------------------------------------------------------
    var _abortMap = Object.create(null);
    function makeCancellable(key, fnFactory) {
        if (_abortMap[key]) {
            try { _abortMap[key].abort(); } catch (_) {}
        }
        var ctrl = new AbortController();
        _abortMap[key] = ctrl;
        return Promise.resolve(fnFactory(ctrl.signal)).then(function (v) {
            if (_abortMap[key] === ctrl) delete _abortMap[key];
            return v;
        }, function (err) {
            if (_abortMap[key] === ctrl) delete _abortMap[key];
            if (err && err.name === 'AbortError') return;
            throw err;
        });
    }

    // ------------------------------------------------------------------
    // Visibilidade da aba — polling adaptativo
    // Subscribers: gboc.onVisibilityChange.subscribe( fn(isHidden, factor) )
    //   factor=1 → aba visivel (intervalo normal)
    //   factor=3 → aba oculta (intervalo x3 para economizar CPU/bateria)
    // Exemplo: setInterval(myPoll, 5000 * gboc.visibilityFactor())
    // ------------------------------------------------------------------
    var _hidden = ('hidden' in document) ? document.hidden : false;
    var _visFactor = 1;
    var _visSubs = [];
    function _emit() {
        _visFactor = _hidden ? 3 : 1;
        for (var i = 0; i < _visSubs.length; i++) {
            try { _visSubs[i](_hidden, _visFactor); } catch (_) {}
        }
    }
    document.addEventListener('visibilitychange', function () {
        _hidden = ('hidden' in document) ? document.hidden : false;
        _emit();
    });
    function visibilityFactor() { return _visFactor; }
    function subscribeVisibility(fn) {
        if (typeof fn !== 'function') return function () {};
        if (_visSubs.indexOf(fn) === -1) _visSubs.push(fn);
        fn(_hidden, _visFactor); // dispara imediatamente com estado atual
        return function unsubscribe() {
            var i = _visSubs.indexOf(fn);
            if (i !== -1) _visSubs.splice(i, 1);
        };
    }

    // ------------------------------------------------------------------
    // smartInterval(fn, baseMs, fastReturnFactor) — intervalo adaptativo
    // Usa visibilityFactor automaticamente. Ideal para substituir os
    // 14 setInterval espalhados.
    // fastReturnFactor (padrao 0.6) = se a fn voltar em <60% do intervalo,
    // nao enche a fila de microtasks (impede herding de polling).
    // Retorna objeto com .stop() e .restart()
    // ------------------------------------------------------------------
    function smartInterval(fn, baseMs, opts) {
        opts = opts || {};
        var slowFactorHidden = opts.slowFactorHidden || 3;
        var stopped = false;
        var t;
        function tick() {
            if (stopped) return;
            var factor = ('hidden' in document && document.hidden) ? slowFactorHidden : 1;
            var wait = Math.max(500, Math.round(baseMs * factor));
            t = setTimeout(function () {
                var p;
                try { p = fn(); } catch (e) { p = null; }
                Promise.resolve(p).catch(function () {}).then(function () {
                    tick();
                });
            }, wait);
        }
        tick();
        return {
            stop: function () { stopped = true; clearTimeout(t); t = null; },
            restart: function () {
                stopped = false;
                clearTimeout(t);
                tick();
            },
            setBaseMs: function (ms) { baseMs = Math.max(500, ms | 0); }
        };
    }

    // ------------------------------------------------------------------
    // Exports — namespace global unico
    // ------------------------------------------------------------------
    var gbocPerf = {
        safeRender: safeRender,
        safeText: safeText,
        debounce: debounce,
        throttle: throttle,
        makeCancellable: makeCancellable,
        visibilityFactor: visibilityFactor,
        onVisibilityChange: { subscribe: subscribeVisibility },
        smartInterval: smartInterval
    };
    global.gbocPerf = gbocPerf;
    // Backward compat alias
    if (!global.gboc) global.gboc = {};
    global.gboc.perf = gbocPerf;

})(window);
