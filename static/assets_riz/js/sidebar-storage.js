/**
 * Sidebar State Persistence with localStorage
 *
 * Persiste la preferencia del usuario (collapsed/default) entre recargas.
 *
 * Problema que resuelve:
 *   `app.js` (minificado) tiene `changeSidebarSize()` que fuerza el estado del
 *   sidebar según el ancho de la ventana al cargar la página y en cada resize.
 *   Eso pisaba la preferencia del usuario al recargar.
 *
 * Cómo lo resuelve:
 *   1) Aplica el estado guardado lo antes posible (no espera DOMContentLoaded).
 *   2) Solo guarda en localStorage cuando el usuario clickea el hamburger
 *      (no cuando cambia por resize automático de `app.js`).
 *   3) Después de cada resize, re-aplica el estado guardado para revertir el
 *      override automático de `app.js` (su listener corre antes que el nuestro
 *      porque app.js se carga primero).
 *
 * Carga en base.html DESPUÉS de app.js para poder pisar sus efectos iniciales.
 */

(function () {
    'use strict';

    const STORAGE_KEY = 'sidebar-state';
    const VALID_STATES = ['collapsed', 'default'];

    /** Ancho mínimo donde tiene sentido persistir. Bajo eso (mobile real),
     *  el sidebar se maneja como overlay y la preferencia no aplica. */
    const MIN_WIDTH_PERSIST = 768;

    function getSavedState() {
        try {
            const v = localStorage.getItem(STORAGE_KEY);
            return VALID_STATES.includes(v) ? v : null;
        } catch (e) {
            return null;
        }
    }

    function saveState(state) {
        if (!VALID_STATES.includes(state)) return;
        try {
            localStorage.setItem(STORAGE_KEY, state);
        } catch (e) {}
    }

    function applyState(state) {
        if (VALID_STATES.includes(state) && document.body) {
            document.body.setAttribute('data-sidebar-size', state);
        }
    }

    function shouldPersist() {
        return window.innerWidth >= MIN_WIDTH_PERSIST;
    }

    // ── 1) Aplicar de inmediato el estado guardado ───────────────────
    // Este script carga DESPUÉS de app.js, así que para cuando llegamos acá
    // app.js ya corrió changeSidebarSize() y pisó el atributo. Lo restauramos.
    const initialState = getSavedState();
    if (initialState && shouldPersist()) {
        applyState(initialState);
    }

    // ── 2) Detectar toggle MANUAL del usuario y persistirlo ──────────
    // El botón hamburger tiene clase `.mobile-menu-btn` (id=togglemenu).
    // app.js registra un click listener que cambia el atributo. Nuestro
    // listener corre después y persiste el resultado final.
    function bindToggle() {
        const btn = document.querySelector('.mobile-menu-btn');
        if (!btn || btn.dataset.sidebarStorageBound === '1') return;
        btn.dataset.sidebarStorageBound = '1';
        btn.addEventListener('click', function () {
            // Microtask después del handler de app.js
            setTimeout(function () {
                if (!shouldPersist()) return;
                const current = document.body.getAttribute('data-sidebar-size');
                if (VALID_STATES.includes(current)) {
                    saveState(current);
                }
            }, 0);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindToggle);
    } else {
        bindToggle();
    }

    // ── 3) Revertir el override automático en cada resize ────────────
    // app.js registra un resize-listener que llama a changeSidebarSize() y
    // pisa el atributo según el ancho. Como nuestro listener se registra
    // después, corre después y re-aplica el estado guardado del usuario.
    let resizeRaf = null;
    window.addEventListener('resize', function () {
        if (resizeRaf) cancelAnimationFrame(resizeRaf);
        resizeRaf = requestAnimationFrame(function () {
            if (!shouldPersist()) return;
            const saved = getSavedState();
            if (!saved) return;
            const current = document.body.getAttribute('data-sidebar-size');
            if (current !== saved) {
                applyState(saved);
            }
        });
    });

    // ── 4) Re-aplicar después de DOMContentLoaded por si algún script tardío
    //      cambia el atributo (ej. carga diferida de app.js módulos).
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            const saved = getSavedState();
            if (saved && shouldPersist()) applyState(saved);
        });
    }

    // API pública opcional para debug.
    window.clearSidebarState = function () {
        try {
            localStorage.removeItem(STORAGE_KEY);
            applyState('default');
        } catch (e) {}
    };
    window.getSidebarState = getSavedState;
})();
