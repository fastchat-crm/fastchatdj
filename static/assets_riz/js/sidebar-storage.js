(function () {
    'use strict';

    const STORAGE_KEY = 'sidebar-state';
    const VALID_STATES = ['collapsed', 'default'];
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

    const initialState = getSavedState();
    if (initialState && shouldPersist()) {
        applyState(initialState);
    }

    let userToggling = false;

    function bindToggle() {
        const btn = document.querySelector('.mobile-menu-btn');
        if (!btn || btn.dataset.sidebarStorageBound === '1') return;
        btn.dataset.sidebarStorageBound = '1';
        btn.addEventListener('click', function () {
            userToggling = true;
            setTimeout(function () {
                if (shouldPersist()) {
                    const current = document.body.getAttribute('data-sidebar-size');
                    if (VALID_STATES.includes(current)) {
                        saveState(current);
                    }
                }
                userToggling = false;
            }, 0);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindToggle);
    } else {
        bindToggle();
    }

    if (document.body && typeof MutationObserver !== 'undefined') {
        const observer = new MutationObserver(function () {
            if (userToggling) return;
            if (!shouldPersist()) return;
            const saved = getSavedState();
            if (!saved) return;
            const current = document.body.getAttribute('data-sidebar-size');
            if (current !== saved) {
                applyState(saved);
            }
        });
        observer.observe(document.body, {
            attributes: true,
            attributeFilter: ['data-sidebar-size']
        });
    }

    window.addEventListener('load', function () {
        if (!shouldPersist()) return;
        const saved = getSavedState();
        if (saved) applyState(saved);
    });

    window.clearSidebarState = function () {
        try {
            localStorage.removeItem(STORAGE_KEY);
            applyState('default');
        } catch (e) {}
    };
    window.getSidebarState = getSavedState;
})();
