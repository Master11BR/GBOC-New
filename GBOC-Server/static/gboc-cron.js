/* GBOC — Agendamento em linguagem simples.
 * Converte a expressão cron (ex.: 0 a cada 2 horas) em frase para qualquer usuário:
 *   minuto 0 a cada 2 horas -> "A cada 2 horas"
 *   0 2 * * * -> "Todo dia às 02:00"
 *   "0 2 * * 1-5"  -> "De segunda a sexta às 02:00"
 *   "0 2 * * 1"    -> "Toda segunda-feira às 02:00"
 *   a cada 15 minutos -> "A cada 15 minutos"
 * Uso: GBOCCron.texto(expr, habilitado) -> string ; GBOCCron.html(expr, habilitado) -> HTML com tooltip.
 */
(function (g) {
    'use strict';
    const DIAS = ['domingo', 'segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado'];
    const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
    const esc = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const hhmm = (h, m) => String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
    const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
    const isNum = (s) => /^\d+$/.test(s);

    function listaDias(dow) {
        const set = new Set();
        for (const parte of dow.split(',')) {
            const faixa = parte.match(/^(\d)-(\d)$/);
            if (faixa) { for (let i = +faixa[1]; i <= +faixa[2]; i++) set.add(i % 7); }
            else if (isNum(parte)) set.add(+parte % 7);
            else return null;
        }
        return [...set].sort((a, b) => a - b);
    }

    function textoDias(lista) {
        const k = lista.join(',');
        if (k === '0,1,2,3,4,5,6') return 'todos os dias';
        if (k === '1,2,3,4,5') return 'de segunda a sexta';
        if (k === '0,6') return 'aos fins de semana';
        if (lista.length === 1) return (lista[0] === 0 || lista[0] === 6 ? 'todo ' : 'toda ') + DIAS[lista[0]];
        const nomes = lista.map((d) => DIAS[d]);
        return 'nos dias ' + nomes.slice(0, -1).join(', ') + ' e ' + nomes[nomes.length - 1];
    }

    function texto(expr, habilitado) {
        if (!expr) return 'Manual (só quando você executar)';
        const sufixo = habilitado === false ? ' (pausado)' : '';
        const raw = String(expr).trim();
        const p = raw.split(/\s+/);
        const avancado = 'Personalizado: ' + raw + sufixo;
        if (p.length !== 5) return avancado;
        const [min, hor, dom, mes, dow] = p;

        // A cada N minutos: */N * * * *
        if (/^\*\/\d+$/.test(min) && hor === '*' && dom === '*' && mes === '*' && dow === '*') {
            const n = +min.slice(2);
            return (n === 1 ? 'A cada minuto' : `A cada ${n} minutos`) + sufixo;
        }
        // A cada N horas: M */N * * *
        if (isNum(min) && /^\*\/\d+$/.test(hor) && dom === '*' && mes === '*' && dow === '*') {
            const n = +hor.slice(2);
            const base = n === 1 ? 'Toda hora' : `A cada ${n} horas`;
            return (+min === 0 ? base : `${base}, no minuto ${+min}`) + sufixo;
        }
        if (!isNum(min) || !hor.split(',').every(isNum)) return avancado;

        // Horários: um ou mais por dia (ex.: 8,20)
        const horarios = hor.split(',').map((h) => hhmm(h, min));
        const quando = 'às ' + horarios.join(' e às ');

        // Todo dia
        if (dom === '*' && mes === '*' && dow === '*') return `Todo dia ${quando}` + sufixo;
        // Dias da semana
        if (dom === '*' && mes === '*' && dow !== '*') {
            const lista = listaDias(dow);
            if (!lista) return avancado;
            return `${cap(textoDias(lista))} ${quando}` + sufixo;
        }
        // Dia fixo do mês (ex.: 0 0 1 * *)
        if (isNum(dom) && mes === '*' && dow === '*') return `Todo dia ${dom} de cada mês ${quando}` + sufixo;
        // Mês e dia fixos (ex.: 0 0 25 12 *)
        if (isNum(dom) && isNum(mes) && dow === '*') return `Todo ano, dia ${dom} de ${MESES[(+mes - 1) % 12] || mes} ${quando}` + sufixo;
        if (dom === '*' && isNum(mes) && dow === '*') return `Todos os dias de ${MESES[(+mes - 1) % 12] || mes}, ${quando}` + sufixo;
        return avancado;
    }

    function html(expr, habilitado) {
        const t = texto(expr, habilitado);
        const dica = expr ? 'Expressão técnica: ' + String(expr).trim() : 'Sem agendamento';
        return `<span title="${esc(dica)}">${esc(t)}</span>`;
    }

    g.GBOCCron = { texto, html };
})(window);
