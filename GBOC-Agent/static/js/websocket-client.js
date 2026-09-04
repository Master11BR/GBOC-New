/*
==============================================================================
GBOC System v14.0.0 Enterprise Edition
Copyright (c) 2026 Master11BR - Todos os direitos reservados.
Propriedade Intelectual & Direitos Autorais Registrados.
==============================================================================
*/
/**
 * GBOC v14.0.0 - WebSocket Client
 * Auto-reconnecting WebSocket with event dispatching.
 */
class GBOCWebSocket {
    constructor(options = {}) {
        this.url = options.url || `ws://${location.host}/ws`;
        this.reconnectDelay = options.reconnectDelay || 3000;
        this.maxReconnect = options.maxReconnect || 50;
        this.ws = null;
        this._attempt = 0;
        this._listeners = {};
        this._connected = false;
        this._queue = [];
        this.connect();
    }

    connect() {
        try {
            this.ws = new WebSocket(this.url);
            this.ws.onopen = () => {
                this._connected = true;
                this._attempt = 0;
                console.log('[WS] Connected');
                this._emit('connected', {});
                // flush queue
                while (this._queue.length) {
                    this.ws.send(this._queue.shift());
                }
            };
            this.ws.onmessage = (evt) => {
                try {
                    const msg = JSON.parse(evt.data);
                    this._emit(msg.event, msg.data || {}, msg.timestamp);
                } catch (e) { console.warn('[WS] parse error', e); }
            };
            this.ws.onclose = () => {
                this._connected = false;
                console.log('[WS] Disconnected');
                this._emit('disconnected', {});
                this._reconnect();
            };
            this.ws.onerror = (err) => {
                console.warn('[WS] Error', err);
            };
        } catch (e) {
            this._reconnect();
        }
    }

    _reconnect() {
        if (this._attempt >= this.maxReconnect) return;
        this._attempt++;
        const delay = Math.min(this.reconnectDelay * Math.pow(1.5, this._attempt - 1), 30000);
        setTimeout(() => this.connect(), delay);
    }

    send(command, data = {}) {
        const msg = JSON.stringify({ command, ...data });
        if (this._connected && this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(msg);
        } else {
            this._queue.push(msg);
        }
    }

    on(event, fn) {
        if (!this._listeners[event]) this._listeners[event] = [];
        this._listeners[event].push(fn);
        return this;
    }

    off(event, fn) {
        if (!this._listeners[event]) return;
        this._listeners[event] = this._listeners[event].filter(f => f !== fn);
    }

    _emit(event, data, timestamp) {
        (this._listeners[event] || []).forEach(fn => {
            try { fn(data, timestamp); } catch (e) { console.error('[WS] listener error', e); }
        });
        // Also fire on wildcard '*'
        (this._listeners['*'] || []).forEach(fn => {
            try { fn(event, data, timestamp); } catch (e) {}
        });
    }

    get connected() { return this._connected; }

    close() {
        this.maxReconnect = 0;
        if (this.ws) this.ws.close();
    }
}

// Global instance
window.gbocWS = new GBOCWebSocket();
