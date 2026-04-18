/**
 * ============================================================================
 * VOICE COMMERCE WIDGET  —  widget.js
 * ============================================================================
 * Version:  1.0.0  (Phase 9 + 10)
 * Works on: WooCommerce, Shopify (partial), any HTML store
 *
 * EMBED ON ANY STORE (one line):
 *   <script
 *     src="https://your-server.com/widget.js"
 *     data-ws-url="wss://your-server.com/ws/voice"
 *     data-tenant="your-store-id"
 *     data-api-key="vc_your_api_key"
 *     data-theme="auto"
 *     data-position="bottom-right"
 *     data-lang="en"
 *   ></script>
 *
 * KEYBOARD SHORTCUT: Ctrl+Shift+A (or Cmd+Shift+A on Mac) toggles the panel
 *
 * ============================================================================
 * FILE STRUCTURE  (find any section quickly)
 * ============================================================================
 *  SECTION 1  — CONFIGURATION          (reads data-* from <script> tag)
 *  SECTION 2  — CSS STYLES             (all widget CSS, injected into <head>)
 *  SECTION 3  — HTML TEMPLATE          (widget panel DOM structure)
 *  SECTION 4  — DOM INJECTION          (inserts CSS + HTML into the page)
 *  SECTION 5  — STATE MANAGEMENT       (all mutable state in one object)
 *  SECTION 6  — WEBSOCKET LAYER        (connect, reconnect, message routing)
 *  SECTION 7  — AUDIO PLAYBACK         (Gemini → PCM → Web Audio, gapless)
 *  SECTION 8  — MICROPHONE CAPTURE     (mic → AudioWorklet → PCM → server)
 *  SECTION 9  — CHAT UI                (transcript bubbles, typing indicator)
 *  SECTION 10 — BROWSER ACTION HANDLER (highlight, cart badge, toast, modal…)
 *  SECTION 11 — STORE ADAPTERS         (WooCommerce / Shopify DOM selectors)
 *  SECTION 12 — EVENT WIRING           (button clicks, keyboard shortcuts)
 *  SECTION 13 — PUBLIC API             (window.VoiceCommerce for devs)
 *  SECTION 14 — BOOT                   (auto-start when DOM is ready)
 * ============================================================================
 */

(function () {
    'use strict';

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 1 — CONFIGURATION
     * Reads settings from the <script data-*=""> tag that loaded this file.
     * Falls back to safe defaults for every option.
     * ══════════════════════════════════════════════════════════════════════════ */

    /**
     * Find our own <script> tag so we can read its data-* attributes.
     * Works even if the script is loaded async or defer.
     */
    function _findScriptTag() {
        // Modern browsers: document.currentScript is set during synchronous execution
        if (document.currentScript) return document.currentScript;
        // Fallback: find the last <script> whose src contains "widget.js"
        var scripts = document.querySelectorAll('script[src]');
        for (var i = scripts.length - 1; i >= 0; i--) {
            if (scripts[i].src && scripts[i].src.indexOf('widget.js') !== -1) {
                return scripts[i];
            }
        }
        return null;
    }

    var _scriptTag = _findScriptTag();

    /** Read one data-* attribute from the script tag, with a fallback default */
    function _cfg(attr, fallback) {
        if (_scriptTag && _scriptTag.dataset[attr] !== undefined) {
            return _scriptTag.dataset[attr];
        }
        return fallback !== undefined ? fallback : '';
    }

    /** Build the default WebSocket URL based on the current page's protocol/host */
    function _defaultWsUrl() {
        var proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return proto + '//' + window.location.host + '/ws/voice';
    }
    /** Gets or creates a permanent Session ID for this browser tab */
    function _getOrCreateSessionId() {
        var id = sessionStorage.getItem('vc_session_id');
        if (!id) {
            id = 'vc_' + Math.random().toString(36).slice(2, 10);
            sessionStorage.setItem('vc_session_id', id);
        }
        return id;
    }
    /**
     * CONFIG — all tunable settings in one place.
     * Modify these defaults here or override them via data-* attributes.
     */
    var CONFIG = {
        // Server connection
        wsUrl: _cfg('wsUrl', _defaultWsUrl()),   // WebSocket endpoint
        tenant: _cfg('tenant', 'default'),          // store identifier / slug
        apiKey: _cfg('apiKey', ''),                 // vc_... API key
        sessionId: _getOrCreateSessionId(), // 
        // UI
        theme: _cfg('theme', 'auto'),             // 'light' | 'dark' | 'auto'
        position: _cfg('position', 'bottom-right'),     // 'bottom-right' | 'bottom-left'
        lang: _cfg('lang', 'en'),               // UI language (en | ar | fr)

        // Audio
        serverSampleRate: 16000,   // PCM rate sent TO server (Gemini input)
        playbackSampleRate: 24000,   // PCM rate received FROM server (Gemini output)

        // Behaviour
        autoConnect: true,    // connect WebSocket when panel opens
        reconnectDelay: 3000,    // ms before reconnection attempt
        maxReconnects: 5,       // give up after this many failures
        toastDuration: 3500,    // ms how long toast notifications stay visible
        highlightDuration: 3500,    // ms how long product highlight ring stays

        // Feature flags (can be disabled per-tenant in Phase 12+)
        enableVoice: true,
        enableText: true,
        enableActions: true,

        // Keyboard shortcut: Ctrl/Cmd + Shift + A
        shortcutKey: 'a',
        shortcutModifier: true,    // requires Ctrl/Cmd + Shift
    };

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 2 — CSS STYLES
     * ══════════════════════════════════════════════════════════════════════════
     *
     * ALL classes are prefixed  vc-  so they never collide with the host page.
     *
     * CSS custom properties (variables) are defined on  .vc-root  so that:
     *   1. Light / dark themes are a single class swap on .vc-root
     *   2. Store owners can override colours with  .vc-root { --vc-accent: #e44; }
     *   3. The entire widget recolours without touching any other CSS rule
     *
     * Layout:
     *   .vc-fab          — floating action button (always visible)
     *   .vc-panel        — main chat panel (slides up/down)
     *   .vc-panel-header — title bar with mic status dot and close button
     *   .vc-transcript   — scrollable chat history
     *   .vc-msg.*        — individual chat message bubbles
     *   .vc-input-row    — text input + mic button + send button
     *
     * Notifications / overlays (appended to <body>):
     *   .vc-toast-container + .vc-toast
     *   #vc-modal-overlay + .vc-modal-box
     * ══════════════════════════════════════════════════════════════════════════ */

    var CSS = [
        /* ── Theme variables ──────────────────────────────────────────────────── */
        // '.vc-root {',
        // '  --vc-accent:       #2563eb;',
        // '  --vc-accent-dark:  #1d4ed8;',
        // '  --vc-accent-light: #eff6ff;',
        // '  --vc-success:      #16a34a;',
        // '  --vc-error:        #dc2626;',
        // '  --vc-warning:      #d97706;',
        // '  --vc-info:         #2563eb;',
        // '  --vc-surface:      #ffffff;',
        // '  --vc-surface2:     #f8fafc;',
        // '  --vc-surface3:     #f1f5f9;',
        // '  --vc-border:       #e2e8f0;',
        // '  --vc-border2:      #cbd5e1;',
        // '  --vc-text:         #0f172a;',
        // '  --vc-text2:        #475569;',
        // '  --vc-text3:        #94a3b8;',
        // '  --vc-shadow:       0 4px 24px rgba(0,0,0,0.10);',
        // '  --vc-shadow-lg:    0 8px 40px rgba(0,0,0,0.16);',
        // '  --vc-radius:       14px;',
        // '  --vc-radius-sm:    8px;',
        // '  --vc-radius-pill:  999px;',
        // '  --vc-font:         -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;',
        // '  --vc-z:            2147483600;',   /* just below max z-index */
        // '}',
        '.vc-root {',
        '  --vc-accent:       #6365f1c1;', /* Modern Indigo */
        '  --vc-accent-dark:  #4f46e5;',
        '  --vc-accent-light: rgba(99, 102, 241, 0.15);',
        '  --vc-success:      #10b981;',
        '  --vc-error:        #ef4444;',
        '  --vc-warning:      #f59e0b;',
        '  --vc-info:         #3b82f6;',
        '  --vc-surface:      #18181b;', /* Deep Charcoal Panel */
        '  --vc-surface2:     #27272a;', /* Transcript Background */
        '  --vc-surface3:     #3f3f46;', /* Borders & Buttons */
        '  --vc-border:       #3f3f46;',
        '  --vc-border2:      #52525b;',
        '  --vc-text:         #f4f4f5;', /* Crisp White Text */
        '  --vc-text2:        #a1a1aa;',
        '  --vc-text3:        #71717a;',
        '  --vc-shadow:       0 8px 32px rgba(0,0,0,0.40);',
        '  --vc-shadow-lg:    0 12px 48px rgba(0,0,0,0.55);',
        '  --vc-radius:       16px;',
        '  --vc-radius-sm:    10px;',
        '  --vc-radius-pill:  999px;',
        '  --vc-font:         -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;',
        '  --vc-z:            2147483600;',
        '}',
        /* ── Dark theme ───────────────────────────────────────────────────────── */
        '.vc-root.vc-dark {',
        '  --vc-surface:      #1e293b;',
        '  --vc-surface2:     #0f172a;',
        '  --vc-surface3:     #1e293b;',
        '  --vc-border:       #334155;',
        '  --vc-border2:      #475569;',
        '  --vc-text:         #f1f5f9;',
        '  --vc-text2:        #94a3b8;',
        '  --vc-text3:        #64748b;',
        '  --vc-shadow:       0 4px 24px rgba(0,0,0,0.40);',
        '  --vc-shadow-lg:    0 8px 40px rgba(0,0,0,0.55);',
        '}',

        /* ── Animations ───────────────────────────────────────────────────────── */
        '@keyframes vc-pulse {',
        '  0%,100%{box-shadow:0 0 0 0 rgba(37,99,235,0.5)}',
        '  50%{box-shadow:0 0 0 8px rgba(37,99,235,0)}',
        '}',
        '@keyframes vc-recording-pulse {',
        '  0%,100%{box-shadow:0 0 0 0 rgba(220,38,38,0.5)}',
        '  50%{box-shadow:0 0 0 8px rgba(220,38,38,0)}',
        '}',
        '@keyframes vc-slide-up {',
        '  from{opacity:0;transform:translateY(16px) scale(0.97)}',
        '  to{opacity:1;transform:translateY(0) scale(1)}',
        '}',
        '@keyframes vc-slide-down {',
        '  from{opacity:1;transform:translateY(0) scale(1)}',
        '  to{opacity:0;transform:translateY(16px) scale(0.97)}',
        '}',
        '@keyframes vc-toast-in {',
        '  from{opacity:0;transform:translateY(-10px)}',
        '  to{opacity:1;transform:translateY(0)}',
        '}',
        '@keyframes vc-highlight-ring {',
        '  0%{outline-color:rgba(37,99,235,0.92);outline-offset:2px}',
        '  50%{outline-color:rgba(37,99,235,0.58);outline-offset:5px}',
        '  100%{outline-color:rgba(37,99,235,0);outline-offset:8px}',
        '}',
        '@keyframes vc-typing {',
        '  0%,80%,100%{transform:scale(0.8);opacity:0.4}',
        '  40%{transform:scale(1.2);opacity:1}',
        '}',
        '@keyframes vc-spin {',
        '  to{transform:rotate(360deg)}',
        '}',

        /* ── Floating action button ───────────────────────────────────────────── */
        '.vc-fab {',
        '  position:fixed;',
        '  width:56px;height:56px;',
        '  border-radius:50%;',
        '  background:var(--vc-accent);',
        '  color:#fff;',
        '  border:none;',
        '  cursor:pointer;',
        '  display:flex;align-items:center;justify-content:center;',
        '  box-shadow:0 4px 20px rgba(37,99,235,0.4);',
        '  z-index:var(--vc-z);',
        '  transition:transform 0.2s ease,background 0.2s ease,box-shadow 0.2s ease;',
        '  font-family:var(--vc-font);',
        '  font-size:22px;',
        '  user-select:none;',
        '  -webkit-tap-highlight-color:transparent;',
        '  outline:none;',
        '}',
        '.vc-fab:hover{transform:scale(1.08);background:var(--vc-accent-dark);}',
        '.vc-fab:active{transform:scale(0.96);}',
        '.vc-fab.vc-fab--open{background:var(--vc-accent-dark);}',
        '.vc-fab.vc-fab--recording{background:#dc2626;animation:vc-recording-pulse 1.2s infinite;}',
        '.vc-fab.vc-fab--connecting{animation:vc-spin 1s linear infinite;}',

        /* Position variants */
        '.vc-root.vc-pos-bottom-right .vc-fab{bottom:24px;right:24px;}',
        '.vc-root.vc-pos-bottom-left  .vc-fab{bottom:24px;left:24px;}',

        /* FAB icon */
        '.vc-fab-icon{transition:transform 0.22s ease,opacity 0.18s ease;display:flex;}',

        /* ── Cart badge on FAB ────────────────────────────────────────────────── */
        '.vc-fab-badge{',
        '  position:absolute;top:-4px;right:-4px;',
        '  min-width:18px;height:18px;',
        '  background:#dc2626;color:#fff;',
        '  border-radius:var(--vc-radius-pill);',
        '  font-size:10px;font-weight:700;',
        '  display:none;align-items:center;justify-content:center;',
        '  padding:0 4px;',
        '  font-family:var(--vc-font);',
        '  pointer-events:none;',
        '  border:2px solid #fff;',
        '  transition:transform 0.15s ease;',
        '}',
        '.vc-fab-badge.vc-show{display:flex;}',
        '.vc-fab-badge.vc-bump{transform:scale(1.4);}',

        /* ── Panel ────────────────────────────────────────────────────────────── */
        '.vc-panel{',
        '  position:fixed;',
        '  width:330px;',
        '  max-width:calc(100vw - 32px);',
        // '  height: 480px;', 
        // '  max-height:calc(100vh - 150px);', /* <--- THE FIX: Stops it from hitting the top of the screen */
        '  max-height: 480px;',
        '  background:var(--vc-surface);',
        '  border:1px solid var(--vc-border);',
        '  border-radius:var(--vc-radius);',
        '  box-shadow:var(--vc-shadow-lg);',
        '  display:flex;flex-direction:column;',
        '  overflow:hidden;',
        '  z-index:calc(var(--vc-z) - 1);',
        '  font-family:var(--vc-font);',
        '  opacity:0;pointer-events:none;',
        '  transform:translateY(16px) scale(0.97);',
        '  transition:opacity 0.22s cubic-bezier(.34,1.56,.64,1),',
        '             transform 0.22s cubic-bezier(.34,1.56,.64,1);',
        '}',
        '.vc-panel.vc-panel--visible{',
        '  opacity:1;pointer-events:all;',
        '  transform:translateY(0) scale(1);',
        '}',

        /* Panel position variants */
        '.vc-root.vc-pos-bottom-right .vc-panel{bottom:92px;right:24px;}',
        '.vc-root.vc-pos-bottom-left  .vc-panel{bottom:92px;left:24px;}',

        /* ── Panel header ─────────────────────────────────────────────────────── */
        '.vc-header{',
        '  background:var(--vc-accent);',
        '  padding:14px 16px;',
        '  display:flex;align-items:center;gap:10px;',
        '  flex-shrink:0;',
        '}',
        '.vc-header-dot{',
        '  width:8px;height:8px;border-radius:50%;',
        '  background:rgba(255,255,255,0.4);',
        '  flex-shrink:0;',
        '  transition:background 0.3s ease;',
        '}',
        '.vc-header-dot.vc-connected{background:#4ade80;}',
        '.vc-header-dot.vc-connecting{background:#fbbf24;animation:vc-pulse 1s infinite;}',
        '.vc-header-dot.vc-error{background:#f87171;}',
        '.vc-header-title{',
        '  flex:1;font-size:14px;font-weight:600;color:#fff;',
        '  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;',
        '}',
        '.vc-header-subtitle{',
        '  font-size:10px;color:rgba(255,255,255,0.7);font-weight:400;',
        '  display:block;margin-top:1px;',
        '}',
        '.vc-header-actions{display:flex;gap:4px;align-items:center;}',
        '.vc-header-btn{',
        '  background:rgba(255,255,255,0.15);',
        '  border:none;border-radius:6px;',
        '  width:28px;height:28px;',
        '  display:flex;align-items:center;justify-content:center;',
        '  cursor:pointer;color:rgba(255,255,255,0.9);',
        '  font-size:14px;',
        '  transition:background 0.15s ease;',
        '}',
        '.vc-header-btn:hover{background:rgba(255,255,255,0.28);}',

        /* ── Transcript area ──────────────────────────────────────────────────── */
        '.vc-transcript{',
        '  flex:1;',
        '  overflow-y:auto;',
        '  overflow-x:hidden;',
        '  padding:14px 12px;',
        '  display:flex;flex-direction:column;gap:8px;',
        '  min-height:200px;',
        '  background:var(--vc-surface2);',
        '  scroll-behavior:smooth;',
        '}',
        '.vc-transcript::-webkit-scrollbar{width:4px;}',
        '.vc-transcript::-webkit-scrollbar-track{background:transparent;}',
        '.vc-transcript::-webkit-scrollbar-thumb{background:var(--vc-border2);border-radius:4px;}',

        /* ── Message bubbles ──────────────────────────────────────────────────── */
        '.vc-msg{',
        '  max-width:85%;',
        '  padding:9px 13px;',
        '  border-radius:12px;',
        '  font-size:13px;line-height:1.55;',
        '  word-break:break-word;',
        '  position:relative;',
        '  animation:vc-slide-up 0.2s ease;',
        '}',
        '.vc-msg.vc-user{',
        '  align-self:flex-end;',
        '  background:var(--vc-accent);',
        '  color:#fff;',
        '  border-bottom-right-radius:3px;',
        '}',
        '.vc-msg.vc-assistant{',
        '  align-self:flex-start;',
        '  background:var(--vc-surface);',
        '  color:var(--vc-text);',
        '  border:1px solid var(--vc-border);',
        '  border-bottom-left-radius:3px;',
        '}',
        '.vc-msg.vc-system{',
        '  align-self:center;',
        '  background:transparent;',
        '  color:var(--vc-text3);',
        '  font-size:11px;',
        '  padding:4px 10px;',
        '  border-radius:var(--vc-radius-pill);',
        '  border:1px solid var(--vc-border);',
        '}',
        /* Message timestamp */
        '.vc-msg-time{',
        '  font-size:10px;opacity:0.55;',
        '  display:block;margin-top:3px;text-align:right;',
        '}',
        '.vc-user .vc-msg-time{color:rgba(255,255,255,0.7);}',
        '.vc-assistant .vc-msg-time{color:var(--vc-text3);}',

        /* ── Typing indicator ─────────────────────────────────────────────────── */
        '.vc-typing{',
        '  align-self:flex-start;',
        '  background:var(--vc-surface);',
        '  border:1px solid var(--vc-border);',
        '  border-radius:12px;border-bottom-left-radius:3px;',
        '  padding:10px 14px;',
        '  display:none;gap:5px;align-items:center;',
        '}',
        '.vc-typing.vc-visible{display:flex;}',
        '.vc-typing-dot{',
        '  width:7px;height:7px;border-radius:50%;',
        '  background:var(--vc-text3);',
        '}',
        '.vc-typing-dot:nth-child(1){animation:vc-typing 1.2s 0.0s infinite ease-in-out;}',
        '.vc-typing-dot:nth-child(2){animation:vc-typing 1.2s 0.2s infinite ease-in-out;}',
        '.vc-typing-dot:nth-child(3){animation:vc-typing 1.2s 0.4s infinite ease-in-out;}',

        /* ── Voice waveform bar (shown while recording) ───────────────────────── */
        '.vc-waveform{',
        '  padding:8px 12px;',
        '  background:var(--vc-surface3);',
        '  border-top:1px solid var(--vc-border);',
        '  display:none;align-items:center;gap:2px;justify-content:center;',
        '  height:44px;flex-shrink:0;',
        '}',
        '.vc-waveform.vc-active{display:flex;}',
        '.vc-waveform-bar{',
        '  width:3px;',
        '  background:var(--vc-accent);',
        '  border-radius:2px;',
        '  height:8px;',
        '  animation:vc-typing 1.1s ease-in-out infinite;',
        '}',
        '.vc-waveform-bar:nth-child(1){animation-delay:0.0s;height:12px;}',
        '.vc-waveform-bar:nth-child(2){animation-delay:0.1s;height:20px;}',
        '.vc-waveform-bar:nth-child(3){animation-delay:0.2s;height:28px;}',
        '.vc-waveform-bar:nth-child(4){animation-delay:0.1s;height:20px;}',
        '.vc-waveform-bar:nth-child(5){animation-delay:0.0s;height:12px;}',

        /* ── Input row ────────────────────────────────────────────────────────── */
        '.vc-input-row{',
        '  display:flex;gap:6px;',
        '  padding:10px 10px;',
        '  border-top:1px solid var(--vc-border);',
        '  background:var(--vc-surface);',
        '  flex-shrink:0;',
        '  align-items:flex-end;',
        '}',
        '.vc-text-input{',
        '  flex:1;',
        '  border:1.5px solid var(--vc-border);',
        '  border-radius:var(--vc-radius-sm);',
        '  padding:8px 11px;',
        '  font-size:13px;',
        '  font-family:var(--vc-font);',
        '  color:var(--vc-text);',
        '  background:var(--vc-surface2);',
        '  outline:none;',
        '  resize:none;',
        '  min-height:36px;max-height:100px;',
        '  line-height:1.5;',
        '  transition:border-color 0.15s ease;',
        '}',
        '.vc-text-input:focus{border-color:var(--vc-accent);}',
        '.vc-text-input::placeholder{color:var(--vc-text3);}',

        '.vc-icon-btn{',
        '  width:36px;height:36px;',
        '  border-radius:var(--vc-radius-sm);',
        '  border:none;',
        '  display:flex;align-items:center;justify-content:center;',
        '  cursor:pointer;',
        '  font-size:16px;',
        '  flex-shrink:0;',
        '  transition:background 0.15s ease,transform 0.1s ease;',
        '}',
        '.vc-icon-btn:active{transform:scale(0.93);}',
        '.vc-btn-send{background:var(--vc-accent);color:#fff;}',
        '.vc-btn-send:hover{background:var(--vc-accent-dark);}',
        '.vc-btn-send:disabled{background:var(--vc-border2);cursor:not-allowed;}',
        '.vc-btn-mic{background:var(--vc-surface3);color:var(--vc-text2);}',
        '.vc-btn-mic:hover{background:var(--vc-border);}',
        '.vc-btn-mic.vc-active{background:#fef2f2;color:#dc2626;}',
        '.vc-btn-mic.vc-active:hover{background:#fee2e2;}',

        /* ── Toast notifications ─────────────────────────────────────────────── */
        '.vc-toast-container{',
        '  position:fixed;',
        '  top:20px; right:20px;', /* MOVED TO TOP RIGHT */
        '  z-index: 2147483647 !important;', /* FORCED TO BE ON TOP */
        '  display:flex;flex-direction:column;align-items:center;gap:10px;',
        '  pointer-events:none;',
        '  width:min(360px,calc(100vw - 32px));',
        '}',
        '.vc-toast{',
        '  background:var(--vc-surface3);',
        '  border:1px solid var(--vc-border2);',
        '  border-radius:var(--vc-radius-sm);',
        '  padding:12px 14px;',
        '  font-family:var(--vc-font);font-size:13px;font-weight:500;',
        '  box-shadow:var(--vc-shadow-lg);',
        '  color:var(--vc-text);',
        '  animation:vc-toast-in 0.35s cubic-bezier(.34,1.56,.64,1) forwards;',
        '  pointer-events:auto;',
        '  display:flex;align-items:flex-start;gap:10px;',
        '  position:relative;overflow:hidden;cursor:pointer;',
        '  border-left:3px solid transparent;',
        '}',
        '.vc-toast.vc-success{background:#f0fdf4;color:#15803d;border-color:#16a34a;}',
        '.vc-toast.vc-error  {background:#fef2f2;color:#dc2626;border-color:#dc2626;}',
        '.vc-toast.vc-info   {background:#eff6ff;color:#1d4ed8;border-color:#2563eb;}',
        '.vc-toast.vc-warning{background:#fffbeb;color:#92400e;border-color:#d97706;}',
        '.vc-toast-icon{font-size:15px;flex-shrink:0;}',

        // /* --- Floating Notifications (Toasts) --- */
        // '#vc-toasts {',
        // '  position: fixed !important;',
        // '  top: 20px !important;',
        // '  right: 20px !important;',
        // '  left: auto !important;',
        // '  z-index: 2147483647 !important;', /* Maximum possible z-index */
        // '  display: flex !important;',
        // '  flex-direction: column !important;',
        // '  gap: 10px !important;',
        // '  pointer-events: none !important;',
        // '  width: max-content !important;',
        // '  max-width: 80vw !important;',
        // '}',
        // '.vc-toast {',
        // '  background: var(--vc-surface) !important;',
        // '  color: var(--vc-text) !important;',
        // '  padding: 14px 20px !important;',
        // '  border-radius: var(--vc-radius-sm) !important;',
        // '  box-shadow: var(--vc-shadow-lg) !important;',
        // '  display: flex !important;',
        // '  align-items: center !important;',
        // '  gap: 12px !important;',
        // '  font-family: var(--vc-font) !important;',
        // '  font-size: 14px !important;',
        // '  font-weight: 500 !important;',
        // '  opacity: 0;',
        // '  transform: translateX(30px);',
        // '  transition: all 0.4s cubic-bezier(0.25, 0.8, 0.25, 1) !important;',
        // '  border-left: 4px solid var(--vc-info) !important;',
        // '  pointer-events: auto !important;',
        // '  margin: 0 !important;',
        // '  line-height: 1.4 !important;',
        // '}',
        // '.vc-toast.vc-success { border-left-color: var(--vc-success) !important; }',
        // '.vc-toast.vc-error { border-left-color: var(--vc-error) !important; }',
        // '.vc-toast.vc-warning { border-left-color: var(--vc-warning) !important; }',
        // '.vc-toast.vc-in { opacity: 1 !important; transform: translateX(0) !important; }',
        /* ── Product highlight ring (applied to host page elements) ──────────── */

        '.vc-highlight-primary {',
        '  position: relative !important;',
        '  z-index: 100 !important;',
        '  outline: none !important;',
        '  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.14), 0 0 30px rgba(99, 102, 241, 0.42), 0 12px 28px rgba(37, 99, 235, 0.18) !important;',
        '  opacity: 1;',
        '  transform: translateY(-2px) scale(1.01) !important;',
        '  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;',
        '  scroll-margin-top: 120px;',
        '  border-radius: var(--vc-radius-sm);',
        '  animation: vc-highlight-ring 0.9s ease-out;',
        '}',
        '.vc-highlight-secondary {',
        '  position: relative !important;',
        '  z-index: 50 !important;',
        '  outline: none !important;',
        '  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.10), 0 0 18px rgba(99, 102, 241, 0.20) !important;',
        '  opacity: 1;',
        '  transition: all 0.35s ease !important;',
        '  border-radius: var(--vc-radius-sm);',
        '}',
        '.vc-highlight-fade {',
            '  outline: none !important;',
            '  box-shadow: none !important;',
            '  transform: none !important;',
            '  transition: all 0.7s ease !important;',
        '}',
        '.vc-highlight-badge {',
        '  position: absolute !important;',
        '  top: 8px !important;',
        '  left: 8px !important;',
        '  min-width: 24px !important;',
        '  height: 24px !important;',
        '  display: inline-flex !important;',
        '  align-items: center !important;',
        '  justify-content: center !important;',
        '  background: linear-gradient(135deg, #2563eb, #1e40af) !important;',
        '  color: #fff !important;',
        '  font-weight: 800 !important;',
        '  font-size: 11px !important;',
        '  line-height: 1 !important;',
        '  padding: 0 8px !important;',
        '  border-radius: 999px !important;',
        '  border: 1px solid rgba(255,255,255,0.36) !important;',
        '  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.34) !important;',
        '  z-index: 101 !important;',
        '  pointer-events: none !important;',
        '  white-space: nowrap !important;',
        '  overflow: visible !important;',
        '  animation: vc-bounce-in 0.35s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards !important;',
        '}',
        '@keyframes vc-bounce-in {',
        '  0% { transform: scale(0); opacity: 0; }',
        '  100% { transform: scale(1); opacity: 1; }',
        '}',
        // '  100% { transform: scale(1); opacity: 1; }',
        // '}',
        // '@keyframes vc-pulse-ring {',
        // '  0% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.7) !important; }',
        // '  70% { box-shadow: 0 0 0 20px rgba(59, 130, 246, 0) !important; }',
        // '  100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0) !important; }',
        // '}',
        /* ── Modal overlay ────────────────────────────────────────────────────── */
        '#vc-modal-overlay{',
        '  position:fixed;inset:0;',
        '  z-index:calc(var(--vc-z) + 20);',
        '  background:rgba(15,23,42,0.34);',
        '  backdrop-filter:blur(14px) saturate(1.05);',
        '  display:none;align-items:center;justify-content:center;',
        '  padding:24px;',
        '  animation:vc-toast-in 0.18s ease;',
        '}',
        '#vc-modal-overlay.vc-open{display:flex;}',
        '.vc-modal-box{',
        '  background:#ffffff;',
        '  border-radius:24px;',
        '  padding:0;',
        '  max-width:760px;width:min(100%, 760px);',
        '  max-height:min(88vh,820px);',
        '  overflow:hidden;',
        '  border:1px solid rgba(226,232,240,0.85);',
        '  box-shadow:0 36px 110px rgba(15,23,42,0.24);',
        '  font-family:var(--vc-font);',
        '  animation:vc-slide-up 0.24s ease;',
        '  position:relative;',
        '}',
        '.vc-modal-inner{display:flex;flex-direction:column;background:#ffffff;position:relative;}',
        '.vc-modal-shell{display:flex;flex-direction:column;background:#ffffff;}',
        '.vc-modal-close-x{position:absolute;top:18px;right:18px;z-index:3;width:42px;height:42px;border-radius:999px;border:1px solid rgba(226,232,240,0.95);background:rgba(255,255,255,0.98);color:#111827;font-size:22px;font-weight:400;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 10px 24px rgba(15,23,42,0.12);transition:transform 0.16s ease,background 0.16s ease,border-color 0.16s ease;}',
        '.vc-modal-close-x:hover{background:#f8fafc;border-color:#cbd5e1;transform:scale(1.04);}',
        '.vc-modal-img-wrap{background:#ffffff;min-height:340px;display:flex;align-items:center;justify-content:center;overflow:hidden;padding:36px 36px 18px;border-bottom:1px solid #eef2f7;}',
        '.vc-modal-content{display:flex;flex-direction:column;gap:14px;padding:24px 24px 26px;background:#ffffff;}',
        '.vc-modal-category{display:inline-flex;align-self:flex-start;padding:6px 11px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;background:#eff6ff;color:#1d4ed8;border:1px solid #dbeafe;}',
        '.vc-modal-title{font-size:38px;font-weight:800;line-height:1.04;color:#0f172a;margin:0;letter-spacing:-0.035em;}',
        '.vc-modal-price{font-size:34px;font-weight:800;color:#0f172a;margin:2px 0 0;letter-spacing:-0.03em;}',
        '.vc-modal-desc{font-size:15px;color:#475569;line-height:1.72;margin:0;max-width:56ch;}',
        '.vc-modal-img{',
        '  width:100%;height:100%;max-height:360px;object-fit:contain;',
        '  display:block;',
        '}',
        '.vc-modal-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;}',
        '.vc-btn{',
        '  flex:1;min-width:180px;padding:14px 18px;',
        '  border-radius:14px;',
        '  border:1px solid transparent;cursor:pointer;',
        '  font-size:15px;font-weight:700;',
        '  font-family:var(--vc-font);',
        '  transition:transform 0.15s ease,background 0.15s ease,border-color 0.15s ease,color 0.15s ease,box-shadow 0.15s ease;',
        '}',
        '.vc-btn:hover{transform:translateY(-1px);}',
        '.vc-btn-primary{background:#0f172a;color:#fff;box-shadow:0 14px 28px rgba(15,23,42,0.16);}',
        '.vc-btn-primary:hover{background:#111827;box-shadow:0 16px 32px rgba(15,23,42,0.2);}',
        '.vc-btn-ghost{background:#ffffff;color:#0f172a;border-color:#cbd5e1;}',
        '.vc-btn-ghost:hover{background:#f8fafc;border-color:#94a3b8;}',
        '@media (min-width: 760px){',
        '  .vc-modal-shell{flex-direction:row;align-items:stretch;}',
        '  .vc-modal-img-wrap{flex:0 0 46%;min-height:520px;max-width:360px;border-bottom:none;border-right:1px solid #eef2f7;padding:40px 24px;}',
        '  .vc-modal-content{flex:1;justify-content:center;padding:34px 34px 32px;}',
        '  .vc-modal-actions{margin-top:16px;}',
        '}',
        '@media (max-width: 640px){',
        '  #vc-modal-overlay{padding:14px;}',
        '  .vc-modal-box{border-radius:20px;}',
        '  .vc-modal-close-x{top:14px;right:14px;width:38px;height:38px;font-size:20px;}',
        '  .vc-modal-img-wrap{min-height:260px;padding:28px 20px 12px;}',
        '  .vc-modal-content{padding:18px 18px 20px;gap:12px;}',
        '  .vc-modal-title{font-size:30px;}',
        '  .vc-modal-price{font-size:28px;}',
        '  .vc-btn{min-width:100%;padding:13px 16px;font-size:14px;}',
        '}',

        /* ── Product search results panel (shown inside transcript) ────────────  */
        '.vc-products-panel{',
        '  align-self:stretch;',
        '  background:var(--vc-surface);',
        '  border:1px solid var(--vc-border);',
        '  border-radius:var(--vc-radius-sm);',
        '  overflow:hidden;',
        '  animation:vc-slide-up 0.2s ease;',
        '}',
        '.vc-products-title{',
        '  font-size:11px;font-weight:600;',
        '  color:var(--vc-text3);',
        '  padding:8px 12px;',
        '  border-bottom:1px solid var(--vc-border);',
        '  text-transform:uppercase;letter-spacing:0.05em;',
        '}',
        '.vc-product-card{',
        '  display:flex;gap:10px;align-items:center;',
        '  padding:10px 12px;',
        '  border-bottom:1px solid var(--vc-border);',
        '  cursor:pointer;',
        '  transition:background 0.12s ease;',
        '}',
        '.vc-product-card:last-child{border-bottom:none;}',
        '.vc-product-card:hover{background:var(--vc-accent-light);}',
        '.vc-product-thumb{',
        '  width:44px;height:44px;',
        '  border-radius:6px;',
        '  object-fit:cover;',
        '  background:var(--vc-surface3);',
        '  flex-shrink:0;',
        '}',
        '.vc-product-info{flex:1;min-width:0;}',
        '.vc-product-name{',
        '  font-size:12px;font-weight:600;color:var(--vc-text);',
        '  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;',
        '}',
        '.vc-product-price{font-size:12px;color:var(--vc-accent);font-weight:600;margin-top:1px;}',
        '.vc-product-badge{',
        '  font-size:10px;padding:2px 6px;border-radius:var(--vc-radius-pill);',
        '  background:#dcfce7;color:#15803d;font-weight:500;flex-shrink:0;',
        '}',
        '.vc-product-badge.vc-out-stock{background:#fef2f2;color:#dc2626;}',

        /* ── Responsive: small screens ────────────────────────────────────────── */
        '@media(max-width:400px){',
        '  .vc-panel{width:calc(100vw - 16px);}',
        '  .vc-root.vc-pos-bottom-right .vc-panel{right:8px;}',
        '  .vc-root.vc-pos-bottom-left  .vc-panel{left:8px;}',
        '}',

        /* ── RTL support (Arabic) ─────────────────────────────────────────────── */
        '.vc-root[dir="rtl"] .vc-msg.vc-user{align-self:flex-start;border-bottom-right-radius:12px;border-bottom-left-radius:3px;}',
        '.vc-root[dir="rtl"] .vc-msg.vc-assistant{align-self:flex-end;border-bottom-left-radius:12px;border-bottom-right-radius:3px;}',
        '.vc-root[dir="rtl"] .vc-toast-container{left:auto;right:50%;transform:translateX(50%);}',

        /* ── Reduce motion ────────────────────────────────────────────────────── */
        '@media(prefers-reduced-motion:reduce){',
        '  .vc-fab,.vc-panel,.vc-msg{animation:none!important;transition:none!important;}',
        '}',
    ].join('\n');

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 3 — HTML TEMPLATE
     * The full widget panel structure as a string.
     * IDs are prefixed  vc-  to avoid collisions.
     * ══════════════════════════════════════════════════════════════════════════ */

    var HTML_TEMPLATE = [
        /* Toast container — appended separately to <body> */

        /* Modal overlay — appended separately to <body> */

        /* Floating action button */
        '<button class="vc-fab" id="vc-fab" aria-label="Open shopping assistant" title="Shopping Assistant (Ctrl+Shift+A)">',
        '  <span class="vc-fab-icon" id="vc-fab-icon">🎙️</span>',
        '  <span class="vc-fab-badge" id="vc-fab-badge">0</span>',
        '</button>',

        /* Main panel */
        '<div class="vc-panel" id="vc-panel" role="dialog" aria-label="Shopping assistant" aria-modal="false">',

        '  <!-- Header -->',
        '  <div class="vc-header">',
        '    <div class="vc-header-dot vc-disconnected" id="vc-status-dot"></div>',
        '    <div>',
        '      <div class="vc-header-title">Shopping Assistant</div>',
        '      <span class="vc-header-subtitle" id="vc-status-text">Connecting…</span>',
        '    </div>',
        '    <div class="vc-header-actions">',
        '      <button class="vc-header-btn" id="vc-btn-clear" title="Clear conversation" aria-label="Clear chat">🗑️</button>',
        '      <button class="vc-header-btn" id="vc-btn-close" title="Close" aria-label="Close">✕</button>',
        '    </div>',
        '  </div>',

        '  <!-- Transcript -->',
        '  <div class="vc-transcript" id="vc-transcript" aria-live="polite" aria-label="Chat history">',
        '    <!-- Typing indicator (hidden by default) -->',
        '    <div class="vc-typing" id="vc-typing">',
        '      <div class="vc-typing-dot"></div>',
        '      <div class="vc-typing-dot"></div>',
        '      <div class="vc-typing-dot"></div>',
        '    </div>',
        '  </div>',

        '  <!-- Voice waveform (shown while recording) -->',
        '  <div class="vc-waveform" id="vc-waveform">',
        '    <div class="vc-waveform-bar"></div>',
        '    <div class="vc-waveform-bar"></div>',
        '    <div class="vc-waveform-bar"></div>',
        '    <div class="vc-waveform-bar"></div>',
        '    <div class="vc-waveform-bar"></div>',
        '  </div>',

        '  <!-- Input row -->',
        '  <div class="vc-input-row">',
        '    <textarea class="vc-text-input" id="vc-input"',
        '      placeholder="Ask about products…" rows="1"',
        '      aria-label="Type your message"></textarea>',
        '    <button class="vc-icon-btn vc-btn-mic" id="vc-btn-mic" aria-label="Toggle microphone" title="Hold to speak">🎤</button>',
        '    <button class="vc-icon-btn vc-btn-send" id="vc-btn-send" aria-label="Send message" title="Send">',
        '      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">',
        '        <path d="M14 8L2 14l2.5-6L2 2l12 6z" fill="currentColor"/>',
        '      </svg>',
        '    </button>',
        '  </div>',

        '</div>',  /* end .vc-panel */
    ].join('\n');

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 4 — DOM INJECTION
     * Inserts CSS into <head> and HTML into <body>.
     * Both happen once during boot.
     * ══════════════════════════════════════════════════════════════════════════ */

    function _injectCSS() {
        var style = document.createElement('style');
        style.id = 'vc-widget-styles';
        style.textContent = CSS;
        document.head.appendChild(style);
    }

    function _injectHTML() {
        /* ── Root wrapper — carries theme class and position class ── */
        var root = document.createElement('div');
        root.id = 'vc-root';
        root.className = 'vc-root';
        root.setAttribute('dir', CONFIG.lang === 'ar' ? 'rtl' : 'ltr');
        root.innerHTML = HTML_TEMPLATE;

        /* ── Toast container (separate from panel so it's always on top) ── */
        var toastContainer = document.createElement('div');
        toastContainer.className = 'vc-toast-container';
        toastContainer.id = 'vc-toasts';

        /* ── Modal overlay ── */
        var modal = document.createElement('div');
        modal.id = 'vc-modal-overlay';
        modal.innerHTML = '<div class="vc-modal-box" id="vc-modal-box"></div>';

        document.body.appendChild(root);
        document.body.appendChild(toastContainer);
        document.body.appendChild(modal);

        _applyTheme();
        _applyPosition();
        /* Restore chat memory if it exists */
        var savedHistory = sessionStorage.getItem('vc_chat_history');
        if (savedHistory) {
            var t = document.getElementById('vc-transcript');
            if (t) {
                t.innerHTML = savedHistory;
                // Ensure typing dots aren't stuck on
                var typing = document.getElementById('vc-typing');
                if (typing) typing.classList.remove('vc-visible');
                setTimeout(function () { t.scrollTop = t.scrollHeight; }, 100);
            }
        }
    }

    /** Apply light/dark/auto theme class to root */
    function _applyTheme() {
        var root = document.getElementById('vc-root');
        var theme = CONFIG.theme;
        var isDark = false;

        if (theme === 'dark') {
            isDark = true;
        } else if (theme === 'auto') {
            isDark = window.matchMedia &&
                window.matchMedia('(prefers-color-scheme: dark)').matches;

            /* Auto-detect from host page background colour */
            try {
                var bg = getComputedStyle(document.body).backgroundColor;
                var rgb = bg.match(/\d+/g);
                if (rgb) {
                    var luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255;
                    isDark = luminance < 0.4;
                }
            } catch (e) { }
        }

        if (isDark) root.classList.add('vc-dark');
        else root.classList.remove('vc-dark');
    }

    /** Apply bottom-right / bottom-left position class */
    function _applyPosition() {
        var root = document.getElementById('vc-root');
        root.classList.remove('vc-pos-bottom-right', 'vc-pos-bottom-left');
        root.classList.add('vc-pos-' + CONFIG.position);
    }

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 5 — STATE MANAGEMENT
     * All mutable runtime state in one object.
     * Never spread state across module-level vars — put it here.
     * ══════════════════════════════════════════════════════════════════════════ */

    var STATE = {
        /* Panel visibility */
        panelOpen: false,

        /* WebSocket */
        ws: null,
        wsStatus: 'disconnected',   /* disconnected | connecting | connected | error */
        reconnectCount: 0,
        reconnectTimer: null,

        /* Audio playback (Gemini → browser) */
        playbackCtx: null,
        nextPlayAt: 0,

        /* Microphone (browser → Gemini) */
        isRecording: false,
        micStream: null,
        micAudioCtx: null,
        micWorklet: null,
        micWorkletUrl: null,

        /* Cart */
        cartCount: 0,

        /* Conversation */
        turnIndex: 0,
        lastUserText: '',

        /* Gemini speaking flag — used to show typing indicator */
        currentBubble: null,
        currentRole: null,

        /* Current assistant message being built (streaming text) */
        currentAssistantEl: null,
    };

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 6 — WEBSOCKET LAYER
     * Manages connection lifecycle, reconnection, and message routing.
     *
     * Three WebSocket frame types (same protocol as the Python server):
     *   Binary frame    → PCM audio bytes from Gemini → Section 7 (playback)
     *   Text JSON type=transcript → chat bubble → Section 9 (chat UI)
     *   Text JSON type=action     → browser command → Section 10 (actions)
     * ══════════════════════════════════════════════════════════════════════════ */

    /* ══════════════════════════════════════════════════════════════════════════
     *  — SMART CONTEXT SCANNER (Optimized with State Signature)
     * ══════════════════════════════════════════════════════════════════════════ */
    
    // 1. Create a variable to remember the last state so we don't spam the server
    var _lastContextSignature = "";

    function _getCartSnapshot() {
        if (_store && typeof _store.getCartSnapshot === 'function') {
            return _store.getCartSnapshot();
        }
        if (window.__VC_EMBED_DEMO__ === true && typeof window.vcGetCartSnapshot === 'function') {
            return window.vcGetCartSnapshot();
        }
        return [];
    }

    function _getCartCountFromSnapshot(items) {
        var snapshot = Array.isArray(items) ? items : [];
        var total = 0;
        for (var i = 0; i < snapshot.length; i++) {
            var qty = Number(snapshot[i] && (snapshot[i].quantity || snapshot[i].qty || 0));
            if (Number.isFinite(qty) && qty > 0) total += qty;
        }
        return total;
    }

    function _sendCartSync(reason, options) {
        if (STATE.wsStatus !== 'connected') return;

        var cartItems = _getCartSnapshot();
        var realCartCount = _getCartCountFromSnapshot(cartItems);
        if (!realCartCount && Number.isFinite(Number(STATE.cartCount))) {
            realCartCount = Number(STATE.cartCount || 0);
        }

        var pageContext = {
            title: document.title,
            url: window.location.href,
            cart_count: realCartCount,
            active_filters: [],
            cart_items: cartItems,
        };

        _wsSendJSON({
            type: 'cart_sync',
            reason: reason || 'sync',
            product_id: options && options.product_id ? options.product_id : null,
            announce_to_ai: !!(options && options.announce_to_ai),
            page: pageContext,
            cart_items: pageContext.cart_items,
            products: [],
        });
    }

    function _sendContextUpdate() {
        if (STATE.wsStatus !== 'connected') return;

        var cartItems = _getCartSnapshot();
        var realCartCount = _getCartCountFromSnapshot(cartItems);
        if (!realCartCount && Number.isFinite(Number(STATE.cartCount))) {
            realCartCount = Number(STATE.cartCount || 0);
        }

        // 3. NEW: Scrape Active Filters & Categories!
        var activeFilters = [];
        var activeNodes = document.querySelectorAll('.active, .current-cat, .current-menu-item');
        for (var j = 0; j < activeNodes.length; j++) {
            var text = activeNodes[j].textContent.trim();
            // Ignore overly long text to avoid accidentally scraping huge containers
            if (text && text.length < 30) {
                activeFilters.push(text);
            }
        }
        // Remove duplicates from the array
        activeFilters = activeFilters.filter(function(item, pos) { return activeFilters.indexOf(item) == pos; });

        var pageContext = {
            title: document.title,
            url: window.location.href,
            cart_count: realCartCount,
            active_filters: activeFilters,
            cart_items: cartItems
        };

        // 4. Scrape visible products from the WooCommerce DOM
        var visibleProducts = [];
        var cards = document.querySelectorAll('.product, .product-card'); 
        
        var productIdsForSignature = []; // We use this to build our hash

        for (var i = 0; i < Math.min(cards.length, 24); i++) { 
            var card = cards[i];
            var nameEl = card.querySelector('.woocommerce-loop-product__title, .name');
            var priceEl = card.querySelector('.price-current, .price');
            var id = card.getAttribute('data-product_id') || card.getAttribute('data-product-id') || card.getAttribute('data-id') || 'unknown';

            if (nameEl && id !== 'unknown') {
                visibleProducts.push({
                    id: id,
                    name: nameEl.textContent.trim(),
                    price: priceEl ? priceEl.textContent.trim() : ''
                });
                productIdsForSignature.push(id);
            }
        }
        // SAFETY CHECK: If we found 0 products but we are on a shop page, the DOM might still be loading. 
        // Wait 1 second and try again before giving up!
        if (visibleProducts.length === 0 && window.location.href.includes('shop')) {
            return; // Abort this send, the event listener will likely fire again
        }
        // 5. THE MAGIC: Create a unique string based on the URL, Cart, Filters, and Products
        var cartIdsForSignature = pageContext.cart_items.map(function (item) {
            return String(item.product_id || item.id || '') + ':' + String(item.quantity || item.qty || 0);
        });
        var currentSignature = pageContext.url + '|' + pageContext.cart_count + '|' + activeFilters.join(',') + '|' + productIdsForSignature.join(',') + '|' + cartIdsForSignature.join(',');
        
        // 6. If the screen hasn't changed at all, DO NOT SEND! (Saves bandwidth & tokens)
        if (currentSignature === _lastContextSignature) {
            return; 
        }
        
        // 7. If it has changed, update our memory and send the new data to Python
        _lastContextSignature = currentSignature;

        _wsSendJSON({
            type: 'context_update',
            page: pageContext,
            products: visibleProducts
        });
        
        console.log('[VoiceCommerce] Injected Context. Products:', visibleProducts.length, '| Filters:', activeFilters.length ? activeFilters : 'None');
    }

    function _wsConnect() {
        if (STATE.ws && STATE.ws.readyState <= WebSocket.OPEN) return;

        _setStatus('connecting');

        /* Build WebSocket URL with tenant + API key as query params.
         * Browsers cannot set custom headers on WebSocket connections,
         * so we pass the API key as a query param (same as Phase 12 server). */
        var url = CONFIG.wsUrl
            + '?tenant=' + encodeURIComponent(CONFIG.tenant)
            + '&session_id=' + encodeURIComponent(CONFIG.sessionId) // <-- ADD THIS LINE
            + (CONFIG.apiKey ? '&api_key=' + encodeURIComponent(CONFIG.apiKey) : '');

        try {
            STATE.ws = new WebSocket(url);
            STATE.ws.binaryType = 'arraybuffer';
        } catch (e) {
            _setStatus('error');
            _showToast('Cannot connect to assistant server.', 'error');
            return;
        }

        STATE.ws.onopen = function () {
            STATE.reconnectCount = 0;
            _setStatus('connected');
            _addSystemMsg(_i18n('connected'));
            // Wait half a second, then scan the screen!
            setTimeout(_sendContextUpdate, 500); 
            
            // If you change filters/categories, update the AI again
            window.addEventListener('popstate', function() {
                setTimeout(_sendContextUpdate, 800);
            });
            // 3. THE FIX: Catch Filter and Category Clicks!
            // This listens to every click on the page. If the user clicks a link, 
            // a button, or a checkbox (like a category filter), it waits 800ms 
            // for the store to update the HTML, and then silently scans the screen again.
            document.addEventListener('click', function(e) {
                var target = e.target.closest('a, button, input[type="checkbox"], select');
                if (target) {
                    setTimeout(_sendContextUpdate, 800);
                }
            });
        };

        STATE.ws.onclose = function (evt) {

            if (evt.code === 1000 && evt.reason === "Gemini session refresh") {
                console.log('[VoiceCommerce] Refreshing session to bypass Gemini limits...');
                _setStatus('connecting');
                setTimeout(_wsConnect, 500); // 500ms instant reconnect
                return; // Stop execution here so we don't trigger the disconnect logic below!
            }
            _setStatus('disconnected');
            _stopMic();

            /* Auto-reconnect with exponential back-off */
            if (STATE.panelOpen && STATE.reconnectCount < CONFIG.maxReconnects) {
                STATE.reconnectCount++;
                var delay = CONFIG.reconnectDelay * Math.pow(1.5, STATE.reconnectCount - 1);
                _addSystemMsg(_i18n('reconnecting'));
                STATE.reconnectTimer = setTimeout(_wsConnect, delay);
            }
        };

        STATE.ws.onerror = function () {
            _setStatus('error');
        };

        STATE.ws.onmessage = function (event) {
            // 1. Handle Raw Audio Bytes
            if (event.data instanceof ArrayBuffer) {
                _scheduleAudio(event.data);
                return;
            }

            var msg;
            try { msg = JSON.parse(event.data); } catch (e) { return; }

            // 2. Handle Browser Actions ("Ghost Hand")
            // Python sends actions directly as {"action": "something"}, not inside a "type"
            if (msg.action) {
                _onAction(msg);
                return;
            }

            // 3. Handle Chat & Status Events
            switch (msg.type) {
                case 'transcript':
                    _onTranscript(msg);
                    break;

                case 'text':
                    // Route plain text chunks as AI transcript
                    _onTranscript({ role: 'assistant', text: msg.text });
                    break;

                case 'status':
                    if (msg.status === 'done' || msg.status === 'ready') {
                        // TURN COMPLETE: The AI is done speaking.
                        // We MUST reset the bubble tracker so the NEXT turn starts a brand new bubble!
                        STATE.currentBubble = null;
                        STATE.currentRole = null;
                        _showTyping(false);
                        // Also update the header text so it doesn't say "Connecting..."
                        if (msg.status === 'ready') _setStatus('connected');

                    } else if (msg.status === 'thinking') {
                        _showTyping(true);
                    }
                    break;

                case 'error':
                    _showToast(msg.message, 'error');
                    break;
            }
        };
    }

    function _wsDisconnect() {
        clearTimeout(STATE.reconnectTimer);
        if (STATE.ws) {
            STATE.ws.onclose = null;   /* suppress reconnect */
            STATE.ws.close();
            STATE.ws = null;
        }
        _setStatus('disconnected');
    }

    /** Send a raw WebSocket message (checks readyState first) */
    function _wsSend(data) {
        if (STATE.ws && STATE.ws.readyState === WebSocket.OPEN) {
            STATE.ws.send(data);
            return true;
        }
        return false;
    }

    /** Send a JSON text frame */
    function _wsSendJSON(obj) {
        return _wsSend(JSON.stringify(obj));
    }

    /** Update connection status dot + subtitle text */
    function _setStatus(status) {
        STATE.wsStatus = status;
        var dot = document.getElementById('vc-status-dot');
        var text = document.getElementById('vc-status-text');
        if (!dot || !text) return;

        dot.className = 'vc-header-dot vc-' + status;

        var labels = {
            connected: _i18n('connected'),
            connecting: _i18n('connecting'),
            disconnected: _i18n('disconnected'),
            error: _i18n('error'),
        };
        text.textContent = labels[status] || status;

        /* Update FAB appearance */
        var fab = document.getElementById('vc-fab');
        if (fab) {
            fab.classList.toggle('vc-fab--connecting', status === 'connecting');
        }
    }

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 7 — AUDIO PLAYBACK
     * Plays PCM audio from Gemini gaplessly using the Web Audio API.
     *
     * Why Web Audio API (not <audio>)?
     *   <audio> requires a complete file or blob URL — it can't play a stream
     *   of raw PCM chunks arriving in real time.
     *   Web Audio API lets us schedule each chunk exactly at the moment it
     *   should play, producing seamless gapless audio even with network jitter.
     *
     * How gapless scheduling works:
     *   Each incoming chunk sets a start time = max(now, nextPlayAt).
     *   nextPlayAt advances by chunk duration after each schedule.
     *   Result: chunks play back-to-back with sub-millisecond gaps.
     * ══════════════════════════════════════════════════════════════════════════ */

    function _getPlaybackCtx() {
        if (!STATE.playbackCtx) {
            STATE.playbackCtx = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: CONFIG.playbackSampleRate,
            });
        }
        /* Resume suspended context (browsers require user gesture) */
        if (STATE.playbackCtx.state === 'suspended') {
            STATE.playbackCtx.resume();
        }
        return STATE.playbackCtx;
    }

    /**
     * Schedule one PCM audio chunk for gapless playback.
     * @param {ArrayBuffer} arrayBuffer  Raw Int16 PCM bytes from server
     */
    function _scheduleAudio(arrayBuffer) {
        var ctx = _getPlaybackCtx();
        var pcm = new Int16Array(arrayBuffer);
        var float32 = new Float32Array(pcm.length);

        /* Convert Int16 [-32768, 32767] → Float32 [-1.0, 1.0] */
        for (var i = 0; i < pcm.length; i++) {
            float32[i] = pcm[i] / 32768;
        }

        var buf = ctx.createBuffer(1, float32.length, CONFIG.playbackSampleRate);
        buf.copyToChannel(float32, 0);

        var src = ctx.createBufferSource();
        src.buffer = buf;
        src.connect(ctx.destination);

        var now = ctx.currentTime;
        var startAt = Math.max(now, STATE.nextPlayAt);
        src.start(startAt);
        STATE.nextPlayAt = startAt + buf.duration;

        /* Show typing indicator while Gemini is speaking */
        if (!STATE.aiSpeaking) {
            STATE.aiSpeaking = true;
            _showTyping(true);
        }
        /* Clear speaking flag a moment after the last chunk finishes */
        clearTimeout(STATE._speakingTimer);
        STATE._speakingTimer = setTimeout(function () {
            STATE.aiSpeaking = false;
            _showTyping(false);
        }, (STATE.nextPlayAt - ctx.currentTime) * 1000 + 300);
    }

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 8 — MICROPHONE CAPTURE
     * Captures mic audio via AudioWorklet, converts to Int16 PCM,
     * and streams it over WebSocket to the server.
     *
     * Why AudioWorklet (not ScriptProcessorNode)?
     *   ScriptProcessorNode runs on the main thread — it can be interrupted
     *   by DOM updates and drops audio frames. AudioWorklet runs on a dedicated
     *   audio rendering thread — it never drops frames regardless of main-thread load.
     *
     * Why inline Blob URL for the worklet?
     *   The worklet module must be loaded from a URL, but we want zero separate
     *   files. Creating a Blob URL from a string lets us ship the entire widget
     *   as one script tag with no build step.
     * ══════════════════════════════════════════════════════════════════════════ */

    /** AudioWorklet processor code as a string (runs in audio thread) */
    var WORKLET_CODE = [
        "class VcPcmProcessor extends AudioWorkletProcessor {",
        "  process(inputs) {",
        "    var ch = inputs[0][0];",
        "    if (!ch || !ch.length) return true;",
        "    var i16 = new Int16Array(ch.length);",
        "    for (var i = 0; i < ch.length; i++) {",
        "      var s = Math.max(-1, Math.min(1, ch[i]));",
        "      i16[i] = s < 0 ? s * 32768 : s * 32767;",
        "    }",
        "    this.port.postMessage(i16.buffer, [i16.buffer]);",
        "    return true;",
        "  }",
        "}",
        "registerProcessor('vc-pcm-processor', VcPcmProcessor);"
    ].join('\n');

    function _getWorkletUrl() {
        if (!STATE.micWorkletUrl) {
            var blob = new Blob([WORKLET_CODE], { type: 'application/javascript' });
            STATE.micWorkletUrl = URL.createObjectURL(blob);
        }
        return STATE.micWorkletUrl;
    }

    function _toggleMic() {
        if (STATE.isRecording) {
            _stopMic();
        } else {
            _startMic();
        }
    }

    function _startMic() {
        if (STATE.wsStatus !== 'connected') {
            _showToast(_i18n('connectFirst'), 'warning');
            return;
        }
        _closeModal();
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            _showToast('Microphone not supported in this browser.', 'error');
            return;
        }

        navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: CONFIG.serverSampleRate,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            }
        }).then(function (stream) {
            STATE.micStream = stream;
            STATE.micAudioCtx = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: CONFIG.serverSampleRate,
            });

            return STATE.micAudioCtx.audioWorklet.addModule(_getWorkletUrl())
                .then(function () {
                    var source = STATE.micAudioCtx.createMediaStreamSource(stream);
                    STATE.micWorklet = new AudioWorkletNode(
                        STATE.micAudioCtx, 'vc-pcm-processor'
                    );
                    STATE.micWorklet.port.onmessage = function (e) {
                        _wsSend(e.data);   /* send raw PCM ArrayBuffer */
                    };
                    source.connect(STATE.micWorklet);
                    STATE.micWorklet.connect(STATE.micAudioCtx.destination);

                    STATE.isRecording = true;
                    _updateMicUI(true);
                });
        }).catch(function (err) {
            var msg = err.name === 'NotAllowedError'
                ? _i18n('micDenied')
                : 'Microphone error: ' + err.message;
            _showToast(msg, 'error');
        });
    }

    function _stopMic() {
        if (!STATE.isRecording) return;

        /* Signal end-of-utterance to the server */
        _wsSendJSON({ type: 'audio_end' });

        /* Clean up media resources */
        if (STATE.micStream) {
            STATE.micStream.getTracks().forEach(function (t) { t.stop(); });
            STATE.micStream = null;
        }
        if (STATE.micAudioCtx) {
            STATE.micAudioCtx.close();
            STATE.micAudioCtx = null;
        }
        STATE.micWorklet = null;
        STATE.isRecording = false;
        _updateMicUI(false);
    }

    function _updateMicUI(recording) {
        var micBtn = document.getElementById('vc-btn-mic');
        var fab = document.getElementById('vc-fab');
        var wave = document.getElementById('vc-waveform');
        if (micBtn) {
            micBtn.classList.toggle('vc-active', recording);
            micBtn.setAttribute('aria-pressed', recording ? 'true' : 'false');
            micBtn.title = recording ? _i18n('stopMic') : _i18n('startMic');
        }
        if (fab) fab.classList.toggle('vc-fab--recording', recording);
        if (wave) wave.classList.toggle('vc-active', recording);
    }



    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 9 — CHAT UI
     * Renders transcript bubbles, typing indicators, product cards,
     * and timestamps. All DOM mutations happen here.
     * ══════════════════════════════════════════════════════════════════════════ */

    /**
     * Handle a transcript frame from the server.
     * @param {Object} msg  { type:'transcript', role:'user'|'assistant', text:'...' }
     */
    function _onTranscript(msg) {
        var role = msg.role === 'user' ? 'vc-user' : 'vc-assistant';
        var text = (msg.text || '');
        if (!text) return;

        if (msg.role === 'assistant') {
            _showTyping(false);
        }

        /* If same speaker, append text to current bubble. Otherwise, create new bubble. */
        if (STATE.currentBubble && STATE.currentRole === role) {
            var contentSpan = STATE.currentBubble.querySelector('.vc-msg-content');
            if (contentSpan) contentSpan.textContent += text;
            _scrollToBottom();
        } else {
            STATE.currentBubble = _addBubble(role, text);
            STATE.currentRole = role;
        }

        /* Save to memory after updating */
        setTimeout(function () {
            sessionStorage.setItem('vc_chat_history', document.getElementById('vc-transcript').innerHTML);
        }, 50);

        STATE.turnIndex++;
    }

    /**
     * Add a chat bubble to the transcript.
     * @param {string} role   'vc-user' | 'vc-assistant' | 'vc-system'
     * @param {string} text   Message text
     * @returns {HTMLElement} The bubble element
     */
    function _addBubble(role, text) {
        var t = document.getElementById('vc-transcript');
        var el = document.createElement('div');
        el.className = 'vc-msg ' + role;

        /* Put text in a specific span so we can easily append to it later */
        var content = document.createElement('span');
        content.className = 'vc-msg-content';
        content.textContent = text;
        el.appendChild(content);

        /* Timestamp — only for user/assistant, not system */
        if (role !== 'vc-system') {
            var ts = document.createElement('span');
            ts.className = 'vc-msg-time';
            ts.textContent = _formatTime(new Date());
            el.appendChild(ts);
        }

        /* Insert BEFORE the typing indicator (which is always last) */
        var typing = document.getElementById('vc-typing');
        t.insertBefore(el, typing);
        _scrollToBottom();

        return el;
    }

    /** Add a system/status message (centered, small) */
    function _addSystemMsg(text) {
        _addBubble('vc-system', text);
    }

    /**
     * Render a product search results panel inside the transcript.
     * Called by the action handler when products arrive.
     * @param {Array} products  list of {id, name, price, in_stock, thumbnail, permalink}
     */
    function _renderProductCards(products) {
        if (!products || !products.length) return;

        var t = document.getElementById('vc-transcript');
        var panel = document.createElement('div');
        panel.className = 'vc-products-panel';

        var title = document.createElement('div');
        title.className = 'vc-products-title';
        title.textContent = products.length + ' product' + (products.length !== 1 ? 's' : '') + ' found';
        panel.appendChild(title);

        products.slice(0, 5).forEach(function (p) {
            var card = document.createElement('div');
            card.className = 'vc-product-card';
            card.setAttribute('data-product-id', p.id);
            card.setAttribute('role', 'button');
            card.setAttribute('tabindex', '0');
            card.title = 'View ' + p.name;

            /* Thumbnail */
            var thumb = document.createElement('img');
            thumb.className = 'vc-product-thumb';
            thumb.src = p.thumbnail || '';
            thumb.alt = p.name;
            thumb.onerror = function () { this.style.display = 'none'; };
            card.appendChild(thumb);

            /* Info */
            var info = document.createElement('div');
            info.className = 'vc-product-info';

            var name = document.createElement('div');
            name.className = 'vc-product-name';
            name.textContent = p.name;
            info.appendChild(name);

            var price = document.createElement('div');
            price.className = 'vc-product-price';
            price.textContent = p.price || '';
            info.appendChild(price);

            card.appendChild(info);

            /* Stock badge */
            var badge = document.createElement('span');
            badge.className = 'vc-product-badge' + (p.in_stock === false ? ' vc-out-stock' : '');
            badge.textContent = p.in_stock === false ? 'Out of stock' : 'In stock';
            card.appendChild(badge);

            /* Click: navigate to product page or highlight it */
            card.addEventListener('click', function () {
                if (p.permalink) {
                    window.location.href = p.permalink;
                } else {
                    _doHighlightProduct(p.id, true);
                }
            });
            card.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') card.click();
            });

            panel.appendChild(card);
        });

        var typing = document.getElementById('vc-typing');
        t.insertBefore(panel, typing);
        _scrollToBottom();
    }

    /** Show/hide the typing animation dots */
    function _showTyping(visible) {
        var el = document.getElementById('vc-typing');
        if (el) el.classList.toggle('vc-visible', visible);
    }

    /** Scroll the transcript to the bottom */
    function _scrollToBottom() {
        var t = document.getElementById('vc-transcript');
        if (t) {
            requestAnimationFrame(function () {
                t.scrollTop = t.scrollHeight;
            });
        }
    }

    /** Format a Date as HH:MM */
    function _formatTime(date) {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    /** Clear all messages from the transcript */
    function _clearTranscript() {
        var t = document.getElementById('vc-transcript');
        if (!t) return;

        var typing = document.getElementById('vc-typing');
        while (t.firstChild) {
            if (t.firstChild === typing) break;
            t.removeChild(t.firstChild);
        }

        /* Clear Memory & State */
        sessionStorage.removeItem('vc_chat_history');
        STATE.turnIndex = 0;
        STATE.currentBubble = null;
        STATE.currentRole = null;

        /* Start a brand new session ID */
        CONFIG.sessionId = 'vc_' + Math.random().toString(36).slice(2, 10);
        sessionStorage.setItem('vc_session_id', CONFIG.sessionId);

        _addSystemMsg('Chat cleared. Started new session.');

        /* Disconnect and reconnect to python with the new ID */
        _wsDisconnect();
        setTimeout(_wsConnect, 100);
    }

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 10 — BROWSER ACTION HANDLER
     * Executes DOM commands sent by the Python server.
     *
     * Action frame shape:
     *   { "type": "action", "action": "<action_name>", ...payload }
     *
     * All action handlers:
     *   highlight_product     — blue ring around a product card
     *   scroll_to_product     — smooth scroll to product
     *   update_cart_badge     — update the cart count bubble on FAB
     *   add_to_real_cart      — add item to platform cart backend (Woo/demo)
     *   show_notification     — toast notification (success/error/info/warning)
     *   open_cart             — open cart drawer/sidebar
     *   close_cart            — close cart drawer
     *   show_product_modal    — quick-view modal for a product
     *   set_search_query      — pre-fill store search input
     *   clear_highlights      — remove all highlight rings
     *   show_products         — render product cards in chat panel
     *   navigate_to           — navigate to a URL (for search results pages)
     *   apply_filter          — set a price/category filter on the store page
     * ══════════════════════════════════════════════════════════════════════════ */

    function _onAction(msg) {
        /* Log to console in dev mode — useful for debugging */
        /* console.debug('[VoiceCommerce] action:', msg.action, msg); */
        console.log('🔴 [DEBUG 1] WebSocket received action payload:', msg);
        console.log('🔴 [DEBUG 2] Action type is:', msg.action);
        switch (msg.action) {
            case 'highlight_product':
                if (msg.show_badge === true || msg.scroll_to !== false) {
                    _closeModal();
                }
                _queueHighlightProduct(
                    msg.product_id,
                    msg.scroll_to !== false,
                    msg.delay_ms || 0,
                    msg.intensity || 'primary',
                    msg.auto_fade_ms || 8000,
                    msg.show_badge === true
                );
                break;
            case 'scroll_to_product':
                _doScrollToProduct(msg.product_id);
                break;
            case 'update_cart_badge':
                _doUpdateCartBadge(msg.count);
                break;
            case 'add_to_real_cart':
                _doAddToRealCart(msg.product_id, msg.quantity);
                break;
            case 'show_notification':
                console.log('🔴 [DEBUG 3] Routing to _showToast with message:', msg.message);
                _showToast(msg.message, msg.level || 'info', msg.duration_ms);
                break;
            case 'open_cart':
                _closeModal();
                _doOpenCart();
                break;
            case 'close_cart':
                _doCloseCart();
                break;
            case 'show_product_modal':
                var _modalDelay = (msg.delay_ms && msg.delay_ms > 0) ? msg.delay_ms : 0;
                var _fadeMs = 300;
                if (_modalDelay > 0) {
                    var _fadeStart = Math.max(0, _modalDelay - _fadeMs);
                    setTimeout(function () {
                        document.querySelectorAll('.vc-highlight-primary, .vc-highlight-secondary, .vc-highlighted').forEach(function (el) {
                            el.classList.add('vc-highlight-fade');
                        });
                    }, _fadeStart);

                    setTimeout(function () {
                        _doShowProductModal(msg.product_id, msg.product_name, msg.product_data);
                    }, _modalDelay);
                } else {
                    _doShowProductModal(msg.product_id, msg.product_name, msg.product_data);
                }
                break;
            case 'set_search_query':
                _closeModal();
                _doSetSearchQuery(msg.query, msg.submit);
                break;
            case 'clear_highlights':
                _closeModal();
                _doClearHighlights();
                break;
            case 'show_products':
                _closeModal();
                /* Render product cards inside the chat panel */
                _renderProductCards(msg.products);
                break;
            case 'navigate_to':
                _closeModal();
                if (msg.url) window.location.href = msg.url;
                break;
            case 'apply_filter':
                _closeModal();
                _doApplyFilter(msg.filter_type, msg.filter_value);
                break;
            default:
                console.log('🔴 [DEBUG] Unknown action:', msg.action);
                /* Ignore unknown actions — forward compatibility */
                break;
        }
    }

    /* ── highlight_product ──────────────────────────────────────────────────── */
    var _vcPendingHighlightTimers = [];
    var _vcQueuedHighlights = [];
    var _vcHighlightBatchTimer = null;
    var _vcLastScrollAt = 0;
    var _vcLastHighlightDelayMs = 1400;
    var _vcModalAutoCloseTimer = null;

    function _clearProductFocusState() {}

    function _removeHighlightBadge(el) {
        if (!el || !el._vcHighlightBadge) return;
        try {
            el._vcHighlightBadge.remove();
        } catch (_) {}
        el._vcHighlightBadge = null;
    }

    function _setHighlightBadge(el, number) {
        _removeHighlightBadge(el);
        if (!el || !number) return;
        var badge = document.createElement('span');
        badge.className = 'vc-highlight-badge';
        badge.setAttribute('aria-hidden', 'true');
        badge.textContent = '#' + number;
        el.appendChild(badge);
        el._vcHighlightBadge = badge;
    }

    function _isElementMostlyInView(el) {
        if (!el || typeof el.getBoundingClientRect !== 'function') return false;
        var rect = el.getBoundingClientRect();
        var viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
        if (viewportH <= 0) return false;
        var topSafe = 110;
        var bottomSafe = 90;
        if (rect.top >= topSafe && rect.bottom <= (viewportH - bottomSafe)) return true;
        var visibleTop = Math.max(rect.top, 0);
        var visibleBottom = Math.min(rect.bottom, viewportH);
        var visibleHeight = Math.max(0, visibleBottom - visibleTop);
        var elHeight = Math.max(1, rect.height);
        return visibleHeight / elHeight >= 0.96;
    }

    function _getScrollViewportTopInset() {
        var inset = 0;
        var selectors = [
            '.site-header',
            'header.site-header',
            '.sticky-header',
            '.header',
            '#wpadminbar'
        ];

        selectors.forEach(function (sel) {
            var el = document.querySelector(sel);
            if (!el || typeof el.getBoundingClientRect !== 'function') return;
            var rect = el.getBoundingClientRect();
            var style = window.getComputedStyle(el);
            var isPinned = (style.position === 'sticky' || style.position === 'fixed') && rect.top <= 2;
            if (!isPinned) return;
            inset = Math.max(inset, Math.max(0, rect.bottom));
        });

        return inset;
    }

    function _scrollElementToViewportCenter(el) {
        if (!el || typeof el.getBoundingClientRect !== 'function') return;

        var rect = el.getBoundingClientRect();
        var viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
        var pageTop = window.pageYOffset || document.documentElement.scrollTop || 0;
        var insetTop = _getScrollViewportTopInset();
        var usableViewportH = Math.max(240, viewportH - insetTop);
        var absoluteTop = pageTop + rect.top;
        var targetTop = absoluteTop - insetTop - ((usableViewportH - rect.height) / 2);
        var maxTop = Math.max(0, (document.documentElement.scrollHeight || document.body.scrollHeight || 0) - viewportH);
        var clampedTop = Math.max(0, Math.min(targetTop, maxTop));

        window.scrollTo({
            top: clampedTop,
            behavior: 'smooth'
        });

        // A second pass corrects final position after layout settles during the smooth scroll.
        setTimeout(function () {
            var nextRect = el.getBoundingClientRect();
            var nextPageTop = window.pageYOffset || document.documentElement.scrollTop || 0;
            var nextTargetTop = nextPageTop + nextRect.top - insetTop - ((usableViewportH - nextRect.height) / 2);
            var nextClampedTop = Math.max(0, Math.min(nextTargetTop, maxTop));
            window.scrollTo({
                top: nextClampedTop,
                behavior: 'smooth'
            });
        }, 360);
    }

    function _scrollIntoViewSequenced(el, forceScroll) {
        if (!el) return;
        var MIN_SCROLL_GAP_MS = Math.max(1200, _vcLastHighlightDelayMs - 120);
        var now = Date.now();
        var waitMs = Math.max(0, MIN_SCROLL_GAP_MS - (now - _vcLastScrollAt));
        setTimeout(function () {
            if (forceScroll || !_isElementMostlyInView(el)) {
                _scrollElementToViewportCenter(el);
                _vcLastScrollAt = Date.now();
            }
        }, waitMs);
    }

    function _clearHighlightTimers(el) {
        if (!el) return;
        if (el._vcPrimaryTimer) { clearTimeout(el._vcPrimaryTimer); el._vcPrimaryTimer = null; }
        if (el._vcFadeTimer) { clearTimeout(el._vcFadeTimer); el._vcFadeTimer = null; }
        if (el._vcRemoveTimer) { clearTimeout(el._vcRemoveTimer); el._vcRemoveTimer = null; }
    }

    function _resolveHighlightTarget(rawEl, productId) {
        var candidates = [];
        if (rawEl) candidates.push(rawEl);
        document.querySelectorAll('[data-product_id="' + productId + '"], [data-product-id="' + productId + '"], .post-' + productId).forEach(function (node) {
            candidates.push(node);
        });

        var best = null;
        var bestScore = -1;
        for (var i = 0; i < candidates.length; i++) {
            var node = candidates[i];
            if (!node || node.nodeType !== 1) continue;

            var host = node.closest('li.product, article.product, [data-product_id], [data-product-id], .product, .product-item, .vc-demo-card') || node;
            if (!host || host.nodeType !== 1) continue;
            if (host.offsetParent === null) continue;

            var rect = host.getBoundingClientRect();
            if (rect.width < 40 || rect.height < 40) continue;

            var score = 0;
            if (_isElementMostlyInView(host)) score += 100;
            score += Math.max(0, Math.min(80, rect.height));
            score += Math.max(0, Math.min(80, rect.width));

            if (score > bestScore) {
                best = host;
                bestScore = score;
            }
        }
        return best;
    }

    function _performHighlightStep(item) {
        var rawEl = _store.findProduct(item.productId);
        var el = _resolveHighlightTarget(rawEl, item.productId);
        if (!el) {
            console.warn('[VoiceCommerce] highlight target not found/visible', {
                productId: item.productId,
                intensity: item.intensity,
                scroll: item.scroll
            });
            return;
        }

        _doCloseCart();
        _clearHighlightTimers(el);

        el.classList.remove('vc-highlight-primary', 'vc-highlight-secondary', 'vc-highlight-fade', 'vc-highlighted');

        var shouldGuideScroll = !!item.scroll;
        var cls;
        if (shouldGuideScroll || item.intensity === 'primary') {
            cls = 'vc-highlight-primary';
        } else {
            cls = 'vc-highlight-secondary';
        }
        el.classList.add(cls);
        if (!item.showBadge) {
            _removeHighlightBadge(el);
        } else {
            _setHighlightBadge(el, item.order);
        }

        if (shouldGuideScroll) {
            _scrollIntoViewSequenced(el, true);
        }

        if (shouldGuideScroll || item.intensity === 'primary') {
            el._vcPrimaryTimer = setTimeout(function () {
                el.classList.remove('vc-highlight-primary');
                el.classList.add('vc-highlight-secondary');
            }, 2600);
        }

        el._vcFadeTimer = setTimeout(function () {
            el.classList.add('vc-highlight-fade');
        }, Math.max(0, item.autoFadeMs - 900));

        el._vcRemoveTimer = setTimeout(function () {
            el.classList.remove('vc-highlight-primary', 'vc-highlight-secondary', 'vc-highlight-fade', 'vc-highlighted');
            el.style.transform = '';
            _removeHighlightBadge(el);
        }, item.autoFadeMs);
    }

    function _flushQueuedHighlights() {
        if (_vcHighlightBatchTimer) {
            clearTimeout(_vcHighlightBatchTimer);
            _vcHighlightBatchTimer = null;
        }
        if (!_vcQueuedHighlights.length) return;

        var batch = _vcQueuedHighlights.slice().sort(function (a, b) {
            return a.delayMs - b.delayMs;
        });
        _vcQueuedHighlights = [];

        for (var i = 0; i < batch.length; i++) {
            batch[i].order = i + 1;
            if (i > 0) {
                var deltaMs = Math.max(0, batch[i].delayMs - batch[i - 1].delayMs);
                if (deltaMs > 0) _vcLastHighlightDelayMs = deltaMs;
            }
        }
        batch.forEach(function (item) {
            var timerId = setTimeout(function () {
                _performHighlightStep(item);
            }, Math.max(0, item.delayMs));
            _vcPendingHighlightTimers.push(timerId);
        });
    }

    function _queueHighlightProduct(productId, scroll, delayMs, intensity, autoFadeMs, showBadge) {
        _vcQueuedHighlights.push({
            productId: productId,
            scroll: !!scroll,
            delayMs: delayMs || 0,
            intensity: intensity || 'primary',
            autoFadeMs: autoFadeMs || 8000,
            showBadge: showBadge === true,
            order: 1
        });

        if (_vcHighlightBatchTimer) {
            clearTimeout(_vcHighlightBatchTimer);
        }

        _vcHighlightBatchTimer = setTimeout(function () {
            _flushQueuedHighlights();
        }, 24);
    }
    /* --- Highlight Queue State --- */
    // var _highlightQueue = [];
    // var _isHighlighting = false;
    // var _highlightSequenceNumber = 0;
    // var _autoClearTimer = null; /* NEW: Timer to clean up the screen */

    // function _doHighlightProduct(productId) {
    //     // If a new search happens, stop the cleanup timer so we can start a new tour
    //     if (_autoClearTimer) clearTimeout(_autoClearTimer);

    //     _highlightQueue.push(productId);

    //     // Start the tour if it isn't running
    //     if (!_isHighlighting) {
    //         _processHighlightQueue();
    //     }
    // }

    // function _processHighlightQueue() {
    //     // If the queue is empty, the tour is over!
    //     if (_highlightQueue.length === 0) {
    //         _isHighlighting = false;

    //         console.log('[VoiceCommerce] Highlight tour finished! Starting 4-second cleanup timer...');

    //         // Start the 4-second auto-cleanup timer
    //         _autoClearTimer = setTimeout(_doClearHighlights, 4000);
    //         return;
    //     }

    //     _isHighlighting = true;
    //     _highlightSequenceNumber++;

    //     var productId = _highlightQueue.shift();
    //     var el = _store.findProduct(productId);

    //     if (!el) {
    //         _processHighlightQueue();
    //         return;
    //     }

    //     el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    //     el.classList.add('vc-highlight-active');

    //     var badge = document.createElement('div');
    //     badge.className = 'vc-highlight-badge';
    //     badge.textContent = '#' + _highlightSequenceNumber;
    //     el.appendChild(badge);

    //     setTimeout(function () {
    //         el.classList.remove('vc-highlight-active');
    //         el.classList.add('vc-highlight-soft');
    //         setTimeout(_processHighlightQueue, 250);
    //     }, 1500);
    // }

    // function _doClearHighlights() {
    //     console.log('[VoiceCommerce] Executing aggressive highlight cleanup!');

    //     // 1. Reset all variables
    //     if (_autoClearTimer) clearTimeout(_autoClearTimer);
    //     _highlightQueue = [];
    //     _isHighlighting = false;
    //     _highlightSequenceNumber = 0;

    //     // 2. Aggressively hunt down and destroy EVERY badge on the page
    //     var badges = document.querySelectorAll('.vc-highlight-badge');
    //     for (var i = 0; i < badges.length; i++) {
    //         badges[i].parentNode.removeChild(badges[i]);
    //     }

    //     // 3. Strip the 'active' (pulsing) class from all products
    //     var activeItems = document.querySelectorAll('.vc-highlight-active');
    //     for (var j = 0; j < activeItems.length; j++) {
    //         activeItems[j].classList.remove('vc-highlight-active');
    //         activeItems[j].style.transform = '';
    //     }

    //     // 4. Strip the 'soft' (static) class from all products
    //     var softItems = document.querySelectorAll('.vc-highlight-soft');
    //     for (var k = 0; k < softItems.length; k++) {
    //         softItems[k].classList.remove('vc-highlight-soft');
    //         softItems[k].style.transform = '';
    //     }
    // }

    /* ── scroll_to_product ──────────────────────────────────────────────────── */
    function _doScrollToProduct(productId) {
        _doCloseCart();
        var el = _store.findProduct(productId);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    /* ── update_cart_badge ──────────────────────────────────────────────────── */
    function _doUpdateCartBadge(count) {
        STATE.cartCount = count;
        var badge = document.getElementById('vc-fab-badge');

        /* Also update the WooCommerce/Shopify native cart count */
        _store.updateCartBadge(count);

        if (!badge) return;
        badge.textContent = count;
        if (count > 0) {
            badge.classList.add('vc-show');
            badge.classList.add('vc-bump');
            setTimeout(function () { badge.classList.remove('vc-bump'); }, 200);
        } else {
            badge.classList.remove('vc-show');
        }
    }

    /* ── add_to_real_cart ─────────────────────────────────────────────────── */
    function _doAddToRealCart(productId, quantity) {
        var pid = Number(productId);
        var qty = Number(quantity || 1);
        if (!pid || !Number.isFinite(pid)) return;
        if (!qty || !Number.isFinite(qty) || qty < 1) qty = 1;

        _closeModal();

        /* 1) Universal event path for demo/custom storefronts */
        window.dispatchEvent(new CustomEvent('vc:addToCart', {
            detail: { id: pid, qty: qty }
        }));

        /* 2) Real WooCommerce AJAX path */
        if (typeof wc_add_to_cart_params !== 'undefined') {
            var formData = new FormData();
            formData.append('product_id', pid);
            formData.append('quantity', qty);

            fetch('/?wc-ajax=add_to_cart', {
                method: 'POST',
                body: formData,
            })
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data && !data.error) {
                        if (window.jQuery) {
                            window.jQuery(document.body).trigger('wc_fragment_refresh');
                        } else {
                            document.body.dispatchEvent(new CustomEvent('wc_fragment_refresh', { bubbles: true }));
                        }
                    }
                    setTimeout(function () {
                        _sendContextUpdate();
                    }, 250);
                })
                .catch(function (err) {
                    console.warn('[VoiceCommerce] WC add_to_cart failed:', err);
                });
        }

        setTimeout(function () {
            _sendContextUpdate();
        }, 250);
    }

    /* ── open_cart ──────────────────────────────────────────────────────────── */
    function _doOpenCart() {
        _store.openCart();
    }

    /* ── close_cart ─────────────────────────────────────────────────────────── */
    function _doCloseCart() {
        _store.closeCart();
    }

    /* ── show_product_modal ──────────────────────────────────────────────────── */
    function _doShowProductModal(productId, productName, productData) {
        var overlay = document.getElementById('vc-modal-overlay');
        var box = document.getElementById('vc-modal-box');
        if (!overlay || !box) return;

        _doCloseCart();
        document.querySelectorAll('.vc-highlight-primary, .vc-highlight-secondary, .vc-highlight-fade, .vc-highlighted').forEach(function (el) {
            _clearHighlightTimers(el);
            el.classList.remove('vc-highlight-primary', 'vc-highlight-secondary', 'vc-highlight-fade', 'vc-highlighted');
            el.style.transform = '';
            _removeHighlightBadge(el);
        });
        _clearProductFocusState();

        var img = (productData && productData.thumbnail) ? productData.thumbnail : '';
        var price = (productData && productData.price) ? productData.price : '';
        var desc = (productData && productData.short_desc) ? productData.short_desc : '';
        var category = (productData && productData.category) ? productData.category : '';

        var cleanDesc = String(desc || '').replace(/<[^>]*>/g, '').trim();

        box.innerHTML = [
            '<div class="vc-modal-inner">',
            '<button class="vc-modal-close-x" id="vc-modal-close-x" type="button" aria-label="Close product details">×</button>',
            '<div class="vc-modal-shell">',
            img ? '<div class="vc-modal-img-wrap"><img class="vc-modal-img" src="' + _esc(img) + '" alt="' + _esc(productName || '') + '" onerror="this.style.display=\'none\'"></div>' : '',
            '<div class="vc-modal-content">',
            category ? '<span class="vc-modal-category">' + _esc(category) + '</span>' : '',
            '<h2 class="vc-modal-title">' + _esc(productName || 'Product #' + productId) + '</h2>',
            price ? '<div class="vc-modal-price">' + _esc(price) + '</div>' : '',
            cleanDesc ? '<p class="vc-modal-desc">' + _esc(cleanDesc) + '</p>' : '',
            '<div class="vc-modal-actions">',
            '  <button class="vc-btn vc-btn-primary" id="vc-modal-add">Add to Cart</button>',
            '  <button class="vc-btn vc-btn-ghost" id="vc-modal-view">View on page</button>',
            '</div>',
            '</div>',
            '</div>',
            '</div>',
        ].join('');

        overlay.classList.add('vc-open');
        overlay.onclick = function (e) { if (e.target === overlay) _closeModal(); };
        if (_vcModalAutoCloseTimer) {
            clearTimeout(_vcModalAutoCloseTimer);
        }
        _vcModalAutoCloseTimer = setTimeout(function () {
            _closeModal();
        }, 15000);

        var closeBtn = document.getElementById('vc-modal-close-x');
        if (closeBtn) closeBtn.onclick = _closeModal;

        var viewBtn = document.getElementById('vc-modal-view');
        if (viewBtn) {
            viewBtn.onclick = function () {
                _closeModal();
                var el = _store.findProduct(productId);
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            };
        }

        var addBtn = document.getElementById('vc-modal-add');
        if (addBtn) {
            addBtn.onclick = function () {
                _closeModal();
                _doAddToRealCart(productId, 1);
                _doUpdateCartBadge(STATE.cartCount + 1);
                _showToast('✓ ' + (productName || ('Product #' + productId)) + ' added', 'success', 2500);
                _sendCartSync('modal_add', {
                    product_id: productId,
                    announce_to_ai: true,
                });
            };
        }
    }

    function _closeModal() {
        var overlay = document.getElementById('vc-modal-overlay');
        if (_vcModalAutoCloseTimer) {
            clearTimeout(_vcModalAutoCloseTimer);
            _vcModalAutoCloseTimer = null;
        }
        if (overlay) overlay.classList.remove('vc-open');
    }

    /* ── set_search_query ────────────────────────────────────────────────────── */
    function _doSetSearchQuery(query, submit) {
        _store.setSearchQuery(query, submit);
    }

    /* ── clear_highlights ────────────────────────────────────────────────────── */
    function _doClearHighlights() {
        _vcPendingHighlightTimers.forEach(function (timerId) {
            clearTimeout(timerId);
        });
        _vcPendingHighlightTimers = [];
        if (_vcHighlightBatchTimer) {
            clearTimeout(_vcHighlightBatchTimer);
            _vcHighlightBatchTimer = null;
        }
        _vcQueuedHighlights = [];
        _vcLastScrollAt = 0;
        _vcLastHighlightDelayMs = 1400;

        var selector = '.vc-highlight-primary, .vc-highlight-secondary, .vc-highlight-fade, .vc-highlighted';
        document.querySelectorAll(selector).forEach(function (el) {
            _clearHighlightTimers(el);
            el.classList.remove('vc-highlight-primary', 'vc-highlight-secondary', 'vc-highlight-fade', 'vc-highlighted');
            el.style.transform = '';
            _removeHighlightBadge(el);
        });
        _clearProductFocusState();
    }

    /* ── apply_filter (price, category, etc.) ───────────────────────────────── */
    function _doApplyFilter(filterType, filterValue) {
        _store.applyFilter(filterType, filterValue);
    }

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 11 — STORE ADAPTERS
     * Abstracts over different store platform DOM structures.
     * Each adapter knows where to find products, the cart, and search inputs
     * for that specific platform.
     *
     * Adapters are tried in order — first one that detects its platform wins.
     * You can add a Shopify adapter, Magento adapter, etc. following the same
     * pattern without touching any other section of this file.
     * ══════════════════════════════════════════════════════════════════════════ */

    var STORE_ADAPTERS = {
        /* ── Embed demo adapter ─────────────────────────────────────────────── */
        embed_demo: {
            detect: function () {
                return document.body.getAttribute('data-vc-demo') === 'true' ||
                    window.__VC_EMBED_DEMO__ === true;
            },

            findProduct: function (productId) {
                return (
                    document.querySelector('[data-product_id="' + productId + '"]') ||
                    document.querySelector('[data-product-id="' + productId + '"]')
                );
            },

            updateCartBadge: function (count) {
                document.querySelectorAll('.cart-contents-count,#drawer-cart-count,#cart-count-header').forEach(function (el) {
                    el.textContent = count;
                });
            },

            getCartSnapshot: function () {
                if (typeof window.vcGetCartSnapshot === 'function') {
                    return window.vcGetCartSnapshot();
                }
                return [];
            },

            openCart: function () {
                if (typeof window.openCart === 'function') {
                    window.openCart();
                }
            },

            closeCart: function () {
                if (typeof window.closeCart === 'function') {
                    window.closeCart();
                }
            },

            setSearchQuery: function (query, submit) {
                var input = document.querySelector('input[name="s"][type="search"], input.search-field');
                if (!input) return;
                input.value = query;
                input.focus();
                input.dispatchEvent(new Event('input', { bubbles: true }));
                if (submit) {
                    var form = input.closest('form');
                    if (form) form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                }
            },

            applyFilter: function () { },
        },

        /* ── WooCommerce adapter ────────────────────────────────────────────── */
        woocommerce: {
            detect: function () {
                /* WooCommerce adds body classes like "woocommerce", "woocommerce-page" */
                return document.body.classList.contains('woocommerce') ||
                    document.body.classList.contains('woocommerce-page') ||
                    !!document.querySelector('.woocommerce, .woocommerce-shop');
            },

            findProduct: function (productId) {
                /* WooCommerce standard: li.product[data-product_id="N"]
                   or article.product[data-product_id="N"]
                   or any element with data-product_id (for custom themes) */
                return (
                    document.querySelector('[data-product_id="' + productId + '"]') ||
                    document.querySelector('[data-product-id="' + productId + '"]') ||
                    document.querySelector('.post-' + productId)
                );
            },

            updateCartBadge: function (count) {
                /* WooCommerce Storefront / most themes use .cart-contents-count */
                var selectors = [
                    '.cart-contents-count',
                    '.cart-count',
                    '.header-cart-count',
                    '.widget_shopping_cart .cart_list',
                ];
                selectors.forEach(function (sel) {
                    document.querySelectorAll(sel).forEach(function (el) {
                        if (el.tagName.toLowerCase() !== 'ul') {
                            el.textContent = count;
                        }
                    });
                });

                /* WooCommerce also stores cart count in jQuery data — trigger update event */
                try {
                    var event = new CustomEvent('wc_fragment_refresh');
                    document.body.dispatchEvent(event);
                } catch (e) { }
            },

            getCartSnapshot: function () {
                var items = [];
                document.querySelectorAll('.woocommerce-mini-cart-item').forEach(function (el) {
                    var nameEl = el.querySelector('.product-name, .mini_cart_item a:not(.remove)');
                    var qtyEl = el.querySelector('.quantity');
                    var rawQty = qtyEl ? qtyEl.textContent : '1';
                    var match = String(rawQty).match(/(\d+)/);
                    items.push({
                        name: nameEl ? nameEl.textContent.trim() : 'Cart item',
                        quantity: match ? Number(match[1]) : 1,
                        price: 0,
                    });
                });
                return items;
            },

            openCart: function () {
                /* Dispatch WooCommerce's built-in cart open event */
                try {
                    var event = new CustomEvent('wc-open-cart');
                    document.dispatchEvent(event);
                } catch (e) { }

                /* Try common cart sidebar/drawer selectors */
                var cartSelectors = [
                    '.wc-block-cart-sidebar',
                    '.widget_shopping_cart_content',
                    '.woocommerce-mini-cart__buttons',
                    '#cart-side-panel',
                    '.cart-offcanvas',
                    '[data-cart-sidebar]',
                ];
                cartSelectors.forEach(function (sel) {
                    var el = document.querySelector(sel);
                    if (el) el.classList.add('active', 'open', 'is-open');
                });

                /* Storefront theme — click cart icon to toggle */
                var cartLink = document.querySelector('.cart-contents, a.cart-icon');
                /* Don't auto-click — would navigate away. Just scroll into view. */
                if (cartLink) cartLink.scrollIntoView({ behavior: 'smooth' });
            },

            closeCart: function () {
                var cartSelectors = [
                    '.wc-block-cart-sidebar',
                    '.cart-offcanvas',
                    '[data-cart-sidebar]',
                ];
                cartSelectors.forEach(function (sel) {
                    var el = document.querySelector(sel);
                    if (el) el.classList.remove('active', 'open', 'is-open');
                });
            },

            setSearchQuery: function (query, submit) {
                /* WooCommerce search: input[name="s"][type="search"] or #woocommerce-product-search-field-* */
                var input = document.querySelector(
                    'input[name="s"][type="search"], input#woocommerce-product-search-field-0, .search-field'
                );
                if (!input) return;
                input.value = query;
                input.focus();
                if (submit) {
                    var form = input.closest('form');
                    if (form) form.submit();
                }
            },

            applyFilter: function (filterType, filterValue) {
                /* WooCommerce price filter widget uses sliders — dispatch events */
                if (filterType === 'max_price') {
                    var slider = document.querySelector('.price_slider_amount [data-max]');
                    if (slider) {
                        slider.value = filterValue;
                        slider.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
                /* Category filter — look for layered nav links */
                if (filterType === 'category') {
                    var link = document.querySelector(
                        '.widget_product_categories a[href*="' + filterValue + '"]'
                    );
                    if (link) link.click();
                }
            },
        },

        /* ── Shopify adapter ────────────────────────────────────────────────── */
        shopify: {
            detect: function () {
                return typeof window.Shopify !== 'undefined' ||
                    !!document.querySelector('[data-shopify], [data-cart-items-count]');
            },

            findProduct: function (productId) {
                return (
                    document.querySelector('[data-product-id="' + productId + '"]') ||
                    document.querySelector('[data-product_id="' + productId + '"]') ||
                    document.querySelector('form[action*="/cart/add"] [name="id"][value="' + productId + '"]')
                    && document.querySelector('form[action*="/cart/add"]')
                );
            },

            updateCartBadge: function (count) {
                var selectors = [
                    '.cart-count',
                    '.cart__count',
                    '[data-cart-count]',
                    '.js-cart-count',
                    '[data-cart-items-count]',
                ];
                selectors.forEach(function (sel) {
                    document.querySelectorAll(sel).forEach(function (el) {
                        el.textContent = count;
                    });
                });
            },

            getCartSnapshot: function () {
                return [];
            },

            openCart: function () {
                /* Shopify drawer cart — commonly triggered by clicking cart icon */
                var cartIcon = document.querySelector(
                    '[data-cart-toggle], .cart-drawer__toggle, .js-drawer-open-cart, .header__cart'
                );
                if (cartIcon) cartIcon.click();
            },

            closeCart: function () {
                var closeBtn = document.querySelector(
                    '[data-drawer-close], .cart-drawer__close, .js-drawer-close'
                );
                if (closeBtn) closeBtn.click();
            },

            setSearchQuery: function (query, submit) {
                var input = document.querySelector(
                    'input[type="search"][name="q"], input.search__input, input.predictive-search__input'
                );
                if (!input) return;
                input.value = query;
                input.focus();
                if (submit) {
                    var form = input.closest('form');
                    if (form) form.submit();
                }
            },

            applyFilter: function () { /* Shopify filter integration TBD */ },
        },

        /* ── Generic fallback adapter ───────────────────────────────────────── */
        generic: {
            detect: function () { return true; },   /* always matches as fallback */

            findProduct: function (productId) {
                /* Try both hyphen and underscore attribute variants */
                return (
                    document.querySelector('[data-product-id="' + productId + '"]') ||
                    document.querySelector('[data-product_id="' + productId + '"]') ||
                    document.querySelector('[data-id="' + productId + '"]')
                );
            },

            updateCartBadge: function (count) {
                document.querySelectorAll(
                    '.cart-count,.cart-badge,.cart-items-count,[data-cart-count]'
                ).forEach(function (el) { el.textContent = count; });
            },

            getCartSnapshot: function () {
                return [];
            },

            openCart: function () {
                var el = document.querySelector(
                    '.cart-drawer,.cart-sidebar,.mini-cart,[data-cart-drawer]'
                );
                if (el) el.classList.add('active', 'open', 'is-open');
            },

            closeCart: function () {
                var el = document.querySelector(
                    '.cart-drawer,.cart-sidebar,.mini-cart,[data-cart-drawer]'
                );
                if (el) el.classList.remove('active', 'open', 'is-open');
            },

            setSearchQuery: function (query, submit) {
                var input = document.querySelector(
                    'input[type="search"], input[name="q"], input[name="s"], .search-input'
                );
                if (!input) return;
                input.value = query;
                input.focus();
                if (submit) {
                    var form = input.closest('form');
                    if (form) form.submit();
                }
            },

            applyFilter: function () { },
        },
    };

    /**
     * Detect which store platform we're on and pick the right adapter.
     * The active adapter is stored in  _store  and used by all action handlers.
     */
    var _store = (function () {
        var order = ['embed_demo', 'woocommerce', 'shopify', 'generic'];
        for (var i = 0; i < order.length; i++) {
            var adapter = STORE_ADAPTERS[order[i]];
            if (adapter.detect()) {
                /* console.log('[VoiceCommerce] store adapter:', order[i]); */
                return adapter;
            }
        }
        return STORE_ADAPTERS.generic;
    }());

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 12 — EVENT WIRING
     * Connects DOM events to the state/WebSocket/UI functions above.
     * ══════════════════════════════════════════════════════════════════════════ */

    function _wireEvents() {
        /* ── FAB: toggle panel ── */
        var fab = document.getElementById('vc-fab');
        if (fab) fab.addEventListener('click', _togglePanel);

        /* ── Close button ── */
        var closeBtn = document.getElementById('vc-btn-close');
        if (closeBtn) closeBtn.addEventListener('click', _closePanel);

        /* ── Clear button ── */
        var clearBtn = document.getElementById('vc-btn-clear');
        if (clearBtn) clearBtn.addEventListener('click', _clearTranscript);

        /* ── Send button ── */
        var sendBtn = document.getElementById('vc-btn-send');
        if (sendBtn) sendBtn.addEventListener('click', _onSendClick);

        /* ── Text input: Enter to send, Shift+Enter for newline ── */
        var input = document.getElementById('vc-input');
        if (input) {
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    _onSendClick();
                }
            });
            /* Auto-resize textarea */
            input.addEventListener('input', function () {
                this.style.height = 'auto';
                this.style.height = Math.min(this.scrollHeight, 100) + 'px';
            });
        }

        /* ── Mic button ── */
        var micBtn = document.getElementById('vc-btn-mic');
        if (micBtn) micBtn.addEventListener('click', _toggleMic);

        /* ── Keyboard shortcut: Ctrl/Cmd + Shift + A ── */
        document.addEventListener('keydown', function (e) {
            if (!CONFIG.shortcutModifier) return;
            var mod = e.ctrlKey || e.metaKey;
            if (mod && e.shiftKey && e.key.toLowerCase() === CONFIG.shortcutKey) {
                e.preventDefault();
                _togglePanel();
            }
        });

        /* ── Modal backdrop ── */
        var modal = document.getElementById('vc-modal-overlay');
        if (modal) {
            modal.addEventListener('click', function (e) {
                if (e.target === modal) _closeModal();
            });
        }

        /* ── System theme change (auto mode) ── */
        if (window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
                if (CONFIG.theme === 'auto') _applyTheme();
            });
        }

        window.addEventListener('vc:cartChanged', function (event) {
            var detail = event && event.detail ? event.detail : {};
            _sendCartSync(detail.reason || 'browser_cart_changed', {
                product_id: detail.product_id || null,
                announce_to_ai: false,
            });
            setTimeout(_sendContextUpdate, 50);
        });
    }

    function _onSendClick() {
        var input = document.getElementById('vc-input');
        var text = input ? input.value.trim() : '';
        if (!text) return;
        if (STATE.wsStatus !== 'connected') { _showToast(_i18n('connectFirst'), 'warning'); return; }
        _closeModal();

        // Create the user bubble AND update the state tracker so AI knows to start a new one!
        STATE.currentBubble = _addBubble('vc-user', text);
        STATE.currentRole = 'vc-user';
        STATE.lastUserText = text;

        _wsSendJSON({ type: 'text', text: text });
        _showTyping(true);

        if (input) { input.value = ''; input.style.height = 'auto'; input.focus(); }
    }

    /* ── Panel open/close ───────────────────────────────────────────────────── */

    function _togglePanel() {
        if (STATE.panelOpen) _closePanel();
        else _openPanel();
    }

    function _openPanel() {
        if (STATE.panelOpen) return;
        STATE.panelOpen = true;

        var panel = document.getElementById('vc-panel');
        var fab = document.getElementById('vc-fab');
        var icon = document.getElementById('vc-fab-icon');

        if (panel) panel.classList.add('vc-panel--visible');
        if (fab) fab.classList.add('vc-fab--open');
        if (icon) icon.textContent = '✕';

        /* Connect WebSocket when panel opens */
        if (CONFIG.autoConnect) _wsConnect();

        /* Focus the text input */
        setTimeout(function () {
            var input = document.getElementById('vc-input');
            if (input) input.focus();
        }, 250);
    }

    function _closePanel() {
        if (!STATE.panelOpen) return;
        STATE.panelOpen = false;

        var panel = document.getElementById('vc-panel');
        var fab = document.getElementById('vc-fab');
        var icon = document.getElementById('vc-fab-icon');

        if (panel) panel.classList.remove('vc-panel--visible');
        if (fab) fab.classList.remove('vc-fab--open');
        if (icon && !STATE.isRecording) {
            icon.textContent = '🎙️';
        }

        /* Stop mic if recording */
        // _stopMic();
    }

    /* ── Toast notifications ────────────────────────────────────────────────── */

    var TOAST_ICONS = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ',
    };
    var TOAST_DURATIONS = { success: 2500, info: 1500, warning: 3500, error: 5000 };
    var TOAST_MAX = 2;   /* max toasts visible at once */

    function _showToast(message, level, duration) {
        level = level || 'info';
        var ms = duration || TOAST_DURATIONS[level] || 2000;

        var container = document.getElementById('vc-toasts');
        if (!container) return;

        /* Enforce max stack — remove oldest if over limit */
        while (container.children.length >= TOAST_MAX) {
            container.removeChild(container.firstChild);
        }

        var toast = document.createElement('div');
        toast.className = 'vc-toast vc-' + level;

        var icon = document.createElement('span');
        icon.className = 'vc-toast-icon';
        icon.textContent = TOAST_ICONS[level] || 'ℹ';
        toast.appendChild(icon);

        var text = document.createElement('span');
        text.textContent = message;
        toast.appendChild(text);

        container.appendChild(toast);

        /* Animate out and remove */
        setTimeout(function () {
            toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-8px)';
            setTimeout(function () {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 350);
        }, ms);
    }

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 13 — UTILITIES
     * ══════════════════════════════════════════════════════════════════════════ */

    /** Escape HTML special characters to prevent XSS */
    function _esc(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /** Simple i18n string lookup */
    var I18N = {
        en: {
            connected: 'Connected — speak or type',
            connecting: 'Connecting…',
            disconnected: 'Disconnected',
            reconnecting: 'Reconnecting…',
            error: 'Connection error',
            chatCleared: 'Chat cleared',
            connectFirst: 'Please wait — connecting…',
            micDenied: 'Microphone access denied. Please allow mic access and try again.',
            startMic: 'Start voice input',
            stopMic: 'Stop recording',
        },
        ar: {
            connected: 'متصل — تحدث أو اكتب',
            connecting: 'جارٍ الاتصال…',
            disconnected: 'غير متصل',
            reconnecting: 'إعادة الاتصال…',
            error: 'خطأ في الاتصال',
            chatCleared: 'تم مسح المحادثة',
            connectFirst: 'يرجى الانتظار…',
            micDenied: 'تم رفض الوصول إلى الميكروفون',
            startMic: 'بدء الإدخال الصوتي',
            stopMic: 'إيقاف التسجيل',
        },
        fr: {
            connected: 'Connecté — parlez ou écrivez',
            connecting: 'Connexion…',
            disconnected: 'Déconnecté',
            reconnecting: 'Reconnexion…',
            error: 'Erreur de connexion',
            chatCleared: 'Conversation effacée',
            connectFirst: 'Veuillez patienter…',
            micDenied: 'Accès au microphone refusé',
            startMic: 'Démarrer la saisie vocale',
            stopMic: 'Arrêter l\'enregistrement',
        },
    };

    function _i18n(key) {
        var lang = I18N[CONFIG.lang] || I18N['en'];
        return lang[key] || I18N['en'][key] || key;
    }

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 14 — PUBLIC API
     * Exposed on window.VoiceCommerce for developers who want programmatic control.
     * All methods are safe to call before the widget is fully initialised.
     * ══════════════════════════════════════════════════════════════════════════ */

    window.VoiceCommerce = {
        /** Open the assistant panel */
        open: function () { _openPanel(); },

        /** Close the assistant panel */
        close: function () { _closePanel(); },

        /** Toggle the assistant panel */
        toggle: function () { _togglePanel(); },

        /** Send a text message programmatically */
        send: function (text) {
            if (!STATE.panelOpen) _openPanel();
            var input = document.getElementById('vc-input');
            if (input) {
                input.value = text;
                _onSendClick();
            }
        },

        /** Start or stop voice recording */
        toggleMic: function () { _toggleMic(); },

        /** Show a toast notification (for external use) */
        notify: function (message, level) { _showToast(message, level || 'info'); },

        /** Get current connection status */
        getStatus: function () { return STATE.wsStatus; },

        /** Get current cart count */
        getCartCount: function () { return STATE.cartCount; },

        /** Manually trigger a browser action (for testing) */
        triggerAction: function (action) { _onAction(action); },
    };

    /* ══════════════════════════════════════════════════════════════════════════
     * SECTION 15 — BOOT
     * Initialise the widget when the DOM is ready.
     * Safe to call multiple times — only boots once.
     * ══════════════════════════════════════════════════════════════════════════ */

    var _booted = false;

    function _boot() {
        if (_booted) return;
        _booted = true;

        _injectCSS();
        _injectHTML();
        _wireEvents();

        /* console.log('[VoiceCommerce] widget loaded. Server:', CONFIG.wsUrl, 'Tenant:', CONFIG.tenant); */
    }

    /* Boot as soon as possible */
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _boot);
    } else {
        /* DOM already ready (script loaded with defer or at end of body) */
        _boot();
    }

}()); /* end IIFE */
