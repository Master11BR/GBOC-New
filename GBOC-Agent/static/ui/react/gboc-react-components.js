/**
 * GBOC System v15.0.0 Enterprise — Reusable React 19 UI Components
 * ================================================================
 * Substitui relatórios legados em Python CLI (SUMMARY.py, COMPLETION_REPORT.py,
 * INTEGRATION_EXAMPLE.py) por componentes Reactivos integrados ao DOM real
 * e às APIs do GBOC-Server / GBOC-Agent.
 */
(function (global) {
    'use strict';

    const React = global.GBOCReact;
    if (!React) return;

    const { h, useState, useEffect, useMemo, createRoot, createStore } = React;

    /**
     * Store global de estado de arquitetura e telemetria v15.0.0
     */
    const useArchitectureStore = createStore((set) => ({
        version: '15.0.0',
        goCoreEngine: 'gboc-go-core/15.0.0',
        reactLayer: 'gboc-react/19.0.0',
        releaseChannel: 'Enterprise Stable',
        loaded: false,
        lastChecked: null,
        async fetchArchitectureInfo() {
            try {
                const res = await fetch('/api/v1/version', { credentials: 'same-origin' });
                if (!res.ok) return;
                const data = await res.json();
                set({
                    version: data.raw_version || '15.0.0',
                    goCoreEngine: data.architecture?.go_core_engine || 'gboc-go-core/15.0.0',
                    reactLayer: data.architecture?.react_ui_layer || 'gboc-react/19.0.0',
                    releaseChannel: data.release_channel || 'Enterprise Stable',
                    loaded: true,
                    lastChecked: new Date().toISOString()
                });
            } catch (_) {
                // Preserva dados locais em páginas estáticas de login/setup
            }
        }
    }));

    /**
     * Componente: GBOCKpiBoard
     * Renderiza cartões de indicadores KPI com suporte a skeleton loading e dados reais.
     */
    function GBOCKpiBoard(props) {
        const items = Array.isArray(props.items) ? props.items : [];
        const loading = Boolean(props.loading);

        if (loading) {
            return h('div', { className: 'gboc-react-kpi-grid', role: 'status', 'aria-busy': 'true' },
                [1, 2, 3, 4].map((idx) =>
                    h('div', { key: `skel-${idx}`, className: 'gboc-react-kpi-card gboc-skeleton-pulse' },
                        h('div', { className: 'gboc-react-kpi-label' }, '...'),
                        h('div', { className: 'gboc-react-kpi-value' }, '—')
                    )
                )
            );
        }

        return h('div', { className: 'gboc-react-kpi-grid' },
            items.map((item, idx) =>
                h('article', {
                    key: item.id || `kpi-${idx}`,
                    className: `gboc-react-kpi-card ${item.tone ? `tone-${item.tone}` : ''}`
                },
                    h('header', { className: 'gboc-react-kpi-header' },
                        h('span', { className: 'gboc-react-kpi-label' }, item.label || ''),
                        item.icon ? h('i', { className: item.icon, 'aria-hidden': 'true' }) : null
                    ),
                    h('div', { className: 'gboc-react-kpi-value' }, item.value ?? '—'),
                    item.subtitle
                        ? h('footer', { className: 'gboc-react-kpi-sub' }, item.subtitle)
                        : null
                )
            )
        );
    }

    /**
     * Componente: GBOCReactiveTable
     * Tabela reativa com filtro instantâneo, ordenação por coluna e content-visibility.
     */
    function GBOCReactiveTable(props) {
        const columns = Array.isArray(props.columns) ? props.columns : [];
        const rows = Array.isArray(props.rows) ? props.rows : [];
        const emptyMessage = props.emptyMessage || 'Nenhum registro disponível no momento.';

        const [query, setQuery] = useState('');
        const [sortKey, setSortKey] = useState(props.defaultSortKey || (columns[0]?.key ?? null));
        const [sortAsc, setSortAsc] = useState(true);

        const filteredRows = useMemo(() => {
            const q = query.trim().toLowerCase();
            let list = rows;
            if (q) {
                list = rows.filter((row) =>
                    columns.some((col) => {
                        const val = row[col.key];
                        return val !== null && val !== undefined && String(val).toLowerCase().includes(q);
                    })
                );
            }
            if (sortKey) {
                list = [...list].sort((a, b) => {
                    const va = a[sortKey] ?? '';
                    const vb = b[sortKey] ?? '';
                    if (va < vb) return sortAsc ? -1 : 1;
                    if (va > vb) return sortAsc ? 1 : -1;
                    return 0;
                });
            }
            return list;
        }, [rows, query, sortKey, sortAsc]);

        const handleSort = (key) => {
            if (sortKey === key) {
                setSortAsc(!sortAsc);
            } else {
                setSortKey(key);
                setSortAsc(true);
            }
        };

        return h('section', { className: 'gboc-react-table-wrapper' },
            props.searchable !== false
                ? h('div', { className: 'gboc-react-table-toolbar' },
                    h('input', {
                        type: 'search',
                        className: 'form-control gboc-react-search-input',
                        placeholder: props.searchPlaceholder || 'Filtrar registros...',
                        value: query,
                        onInput: (e) => setQuery(e.target.value),
                        'aria-label': 'Filtrar registros da tabela'
                    }),
                    h('span', { className: 'gboc-react-table-count' }, `${filteredRows.length} item(ns)`)
                )
                : null,
            h('div', { className: 'table-responsive' },
                h('table', { className: 'data-table gboc-react-table' },
                    h('thead', null,
                        h('tr', null,
                            columns.map((col) =>
                                h('th', {
                                    key: col.key,
                                    onClick: () => handleSort(col.key),
                                    className: 'gboc-react-sortable-th'
                                },
                                    col.label,
                                    sortKey === col.key ? (sortAsc ? ' ▲' : ' ▼') : ''
                                )
                            )
                        )
                    ),
                    h('tbody', null,
                        filteredRows.length === 0
                            ? h('tr', null,
                                h('td', {
                                    colSpan: Math.max(1, columns.length),
                                    className: 'gboc-react-empty-cell'
                                }, emptyMessage)
                            )
                            : filteredRows.map((row, rIdx) =>
                                h('tr', { key: row.id || `row-${rIdx}` },
                                    columns.map((col) =>
                                        h('td', { key: col.key },
                                            typeof col.render === 'function'
                                                ? col.render(row[col.key], row)
                                                : (row[col.key] ?? '—')
                                        )
                                    )
                                )
                            )
                    )
                )
            )
        );
    }

    /**
     * Componente: GBOCSystemSummaryWidget
     * Substitui os scripts Python obsoletos (SUMMARY.py e COMPLETION_REPORT.py)
     * exibindo dados reais da arquitetura v15.0.0 via API /api/v1/version.
     */
    function GBOCSystemSummaryWidget() {
        const arch = useArchitectureStore();

        useEffect(() => {
            if (!arch.loaded) {
                useArchitectureStore.getState().fetchArchitectureInfo();
            }
        }, []);

        return h('div', { className: 'gboc-react-arch-pill', title: `Motor: ${arch.goCoreEngine} | UI: ${arch.reactLayer}` },
            h('span', { className: 'gboc-react-arch-dot', 'aria-hidden': 'true' }),
            h('span', { className: 'gboc-react-arch-text' }, `v${arch.version} • Go + React 19`)
        );
    }

    /**
     * Monta automaticamente qualquer container com [data-gboc-react-widget]
     */
    function mountReactWidgets(rootNode = document) {
        const nodes = rootNode.querySelectorAll('[data-gboc-react-widget]');
        nodes.forEach((node) => {
            if (node.dataset.gbocReactMounted === '1') return;
            node.dataset.gbocReactMounted = '1';
            const widgetType = node.dataset.gbocReactWidget;
            const root = createRoot(node);
            if (widgetType === 'system-summary') {
                root.render(h(GBOCSystemSummaryWidget));
            }
        });
    }

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => mountReactWidgets());
        } else {
            mountReactWidgets();
        }
    }

    global.GBOCComponents = {
        GBOCKpiBoard,
        GBOCReactiveTable,
        GBOCSystemSummaryWidget,
        useArchitectureStore,
        mountReactWidgets
    };
    global.GBOCMountReactWidgets = mountReactWidgets;
})(typeof window !== 'undefined' ? window : globalThis);
