/**
 * GBOC System v15.0.0 Enterprise — React 19 Compatible Core Runtime & Reactive Store
 * ==================================================================================
 * Arquitetura Frontend Reactiva (Air-Gapped Ready / Zero External CDN Dependency).
 * Implementa Virtual DOM, Hooks (useState, useEffect, useMemo, useCallback, useRef),
 * createRoot (React 19 API) e createStore (Zustand-pattern Reactive State Management).
 */
(function (global) {
    'use strict';

    const Fragment = Symbol.for('gboc.react.fragment');

    let currentComponent = null;
    let hookIndex = 0;

    function createElement(type, props, ...children) {
        const normalizedProps = Object.assign({}, props || {});
        const flatChildren = [];

        const pushChild = (child) => {
            if (Array.isArray(child)) {
                child.forEach(pushChild);
            } else if (child !== null && child !== undefined && child !== false && child !== true) {
                flatChildren.push(typeof child === 'object' ? child : String(child));
            }
        };
        children.forEach(pushChild);
        normalizedProps.children = flatChildren;

        return {
            $$typeof: Symbol.for('gboc.react.element'),
            type,
            props: normalizedProps,
            key: normalizedProps.key ?? null
        };
    }

    function useState(initialValue) {
        const instance = currentComponent;
        if (!instance) {
            throw new Error('useState deve ser chamado dentro de um componente React GBOC.');
        }
        const idx = hookIndex++;
        if (instance.hooks.length <= idx) {
            const init = typeof initialValue === 'function' ? initialValue() : initialValue;
            instance.hooks.push({ type: 'state', value: init });
        }
        const hook = instance.hooks[idx];
        const setState = (nextValue) => {
            const computed = typeof nextValue === 'function' ? nextValue(hook.value) : nextValue;
            if (!Object.is(computed, hook.value)) {
                hook.value = computed;
                instance.scheduleUpdate();
            }
        };
        return [hook.value, setState];
    }

    function useRef(initialValue) {
        const instance = currentComponent;
        if (!instance) {
            throw new Error('useRef deve ser chamado dentro de um componente React GBOC.');
        }
        const idx = hookIndex++;
        if (instance.hooks.length <= idx) {
            instance.hooks.push({ type: 'ref', current: initialValue });
        }
        return instance.hooks[idx];
    }

    function depsChanged(prevDeps, nextDeps) {
        if (!prevDeps || !nextDeps) return true;
        if (prevDeps.length !== nextDeps.length) return true;
        for (let i = 0; i < prevDeps.length; i++) {
            if (!Object.is(prevDeps[i], nextDeps[i])) return true;
        }
        return false;
    }

    function useMemo(factory, deps) {
        const instance = currentComponent;
        if (!instance) {
            throw new Error('useMemo deve ser chamado dentro de um componente React GBOC.');
        }
        const idx = hookIndex++;
        if (instance.hooks.length <= idx) {
            const val = factory();
            instance.hooks.push({ type: 'memo', value: val, deps });
            return val;
        }
        const hook = instance.hooks[idx];
        if (depsChanged(hook.deps, deps)) {
            hook.value = factory();
            hook.deps = deps;
        }
        return hook.value;
    }

    function useCallback(callback, deps) {
        return useMemo(() => callback, deps);
    }

    function useEffect(effect, deps) {
        const instance = currentComponent;
        if (!instance) {
            throw new Error('useEffect deve ser chamado dentro de um componente React GBOC.');
        }
        const idx = hookIndex++;
        if (instance.hooks.length <= idx) {
            instance.hooks.push({ type: 'effect', effect, deps, cleanup: null, dirty: true });
            return;
        }
        const hook = instance.hooks[idx];
        if (depsChanged(hook.deps, deps)) {
            hook.effect = effect;
            hook.deps = deps;
            hook.dirty = true;
        }
    }

    function applyProps(dom, props) {
        Object.keys(props).forEach((key) => {
            if (key === 'children' || key === 'key' || key === 'ref') return;
            const val = props[key];
            if (key === 'className' || key === 'class') {
                dom.className = val || '';
            } else if (key === 'style' && val && typeof val === 'object') {
                Object.assign(dom.style, val);
            } else if (key === 'dangerouslySetInnerHTML' && val && typeof val.__html === 'string') {
                dom.innerHTML = val.__html;
            } else if (key.startsWith('on') && typeof val === 'function') {
                const eventName = key.slice(2).toLowerCase();
                dom.addEventListener(eventName, val);
            } else if (val !== false && val !== null && val !== undefined) {
                dom.setAttribute(key, val === true ? '' : String(val));
            }
        });
        if (props.ref && typeof props.ref === 'object') {
            props.ref.current = dom;
        }
    }

    function renderVNode(vnode, parentInstance) {
        if (vnode === null || vnode === undefined || vnode === false) {
            return document.createTextNode('');
        }
        if (typeof vnode === 'string' || typeof vnode === 'number') {
            return document.createTextNode(String(vnode));
        }
        if (vnode.type === Fragment) {
            const frag = document.createDocumentFragment();
            (vnode.props?.children || []).forEach((ch) => {
                frag.appendChild(renderVNode(ch, parentInstance));
            });
            return frag;
        }
        if (typeof vnode.type === 'function') {
            const subKey = vnode.key || vnode.type.name || 'anon';
            let childInstance = parentInstance.childInstances.get(subKey);
            if (!childInstance) {
                childInstance = createComponentInstance(vnode.type, vnode.props);
                parentInstance.childInstances.set(subKey, childInstance);
            } else {
                childInstance.props = vnode.props;
            }
            return childInstance.mountOrUpdate();
        }
        const dom = document.createElement(vnode.type);
        applyProps(dom, vnode.props || {});
        (vnode.props?.children || []).forEach((ch) => {
            dom.appendChild(renderVNode(ch, parentInstance));
        });
        return dom;
    }

    function createComponentInstance(ComponentFn, initialProps) {
        const instance = {
            ComponentFn,
            props: initialProps || {},
            hooks: [],
            childInstances: new Map(),
            domNode: null,
            container: null,
            isScheduled: false,
            scheduleUpdate() {
                if (this.isScheduled) return;
                this.isScheduled = true;
                queueMicrotask(() => {
                    this.isScheduled = false;
                    this.mountOrUpdate();
                });
            },
            mountOrUpdate() {
                const prevComp = currentComponent;
                const prevIdx = hookIndex;
                currentComponent = this;
                hookIndex = 0;

                let vtree = null;
                try {
                    vtree = this.ComponentFn(this.props);
                } finally {
                    currentComponent = prevComp;
                    hookIndex = prevIdx;
                }

                const newDom = renderVNode(vtree, this);
                if (this.domNode && this.domNode.parentNode) {
                    this.domNode.parentNode.replaceChild(newDom, this.domNode);
                } else if (this.container) {
                    this.container.innerHTML = '';
                    this.container.appendChild(newDom);
                }
                this.domNode = newDom;

                this.hooks.forEach((h) => {
                    if (h.type === 'effect' && h.dirty) {
                        h.dirty = false;
                        if (typeof h.cleanup === 'function') {
                            try { h.cleanup(); } catch (_) {}
                        }
                        const cleanup = h.effect();
                        h.cleanup = typeof cleanup === 'function' ? cleanup : null;
                    }
                });

                return newDom;
            },
            unmount() {
                this.hooks.forEach((h) => {
                    if (h.type === 'effect' && typeof h.cleanup === 'function') {
                        try { h.cleanup(); } catch (_) {}
                    }
                });
                this.childInstances.forEach((ci) => ci.unmount());
                this.childInstances.clear();
            }
        };
        return instance;
    }

    function createRoot(container) {
        if (!container) {
            throw new Error('createRoot requer um container DOM válido.');
        }
        let rootInstance = null;
        return {
            render(element) {
                const RootWrapper = () => element;
                if (!rootInstance) {
                    rootInstance = createComponentInstance(RootWrapper, {});
                    rootInstance.container = container;
                } else {
                    rootInstance.ComponentFn = RootWrapper;
                }
                rootInstance.mountOrUpdate();
            },
            unmount() {
                if (rootInstance) {
                    rootInstance.unmount();
                    rootInstance = null;
                }
                container.innerHTML = '';
            }
        };
    }

    /**
     * Zustand-inspired Reactive Store for GBOC v15.0.0
     */
    function createStore(initializer) {
        let state = {};
        const listeners = new Set();

        const setState = (partial, replace = false) => {
            const nextState = typeof partial === 'function' ? partial(state) : partial;
            if (!Object.is(nextState, state)) {
                state = replace ? nextState : Object.assign({}, state, nextState);
                listeners.forEach((listener) => listener(state));
            }
        };

        const getState = () => state;

        const subscribe = (listener) => {
            listeners.add(listener);
            return () => listeners.delete(listener);
        };

        state = initializer(setState, getState);

        function useStore(selector = (s) => s) {
            const [slice, setSlice] = useState(() => selector(state));
            useEffect(() => {
                return subscribe((nextState) => {
                    const nextSlice = selector(nextState);
                    setSlice(() => nextSlice);
                });
            }, []);
            return slice;
        }

        return Object.assign(useStore, { getState, setState, subscribe });
    }

    const GBOCReact = {
        version: '19.0.0-gboc.15.0.0',
        createElement,
        h: createElement,
        Fragment,
        createRoot,
        useState,
        useEffect,
        useMemo,
        useCallback,
        useRef,
        createStore
    };

    global.GBOCReact = GBOCReact;
    if (!global.React) {
        global.React = GBOCReact;
    }
    if (!global.ReactDOM) {
        global.ReactDOM = { createRoot };
    }
})(typeof window !== 'undefined' ? window : globalThis);
