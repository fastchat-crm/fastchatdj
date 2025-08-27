/**
 * Sidebar State Persistence with localStorage
 * Archivo separado para no modificar app.js
 */

(function () {
    'use strict';

    const STORAGE_KEY = 'sidebar-state';
    const DEFAULT_STATE = 'default';

    /**
     * Obtiene el estado guardado del localStorage
     */
    function getSavedState() {
        try {
            return localStorage.getItem(STORAGE_KEY) || DEFAULT_STATE;
        } catch (e) {
            console.warn('Error al leer localStorage:', e);
            return DEFAULT_STATE;
        }
    }

    /**
     * Guarda el estado actual en localStorage
     */
    function saveState(state) {
        try {
            localStorage.setItem(STORAGE_KEY, state);
        } catch (e) {
            console.warn('Error al guardar en localStorage:', e);
        }
    }

    /**
     * Aplica el estado al body
     */
    function applyState(state) {
        if (state && (state === 'collapsed' || state === 'default')) {
            document.body.setAttribute('data-sidebar-size', state);
        }
    }

    /**
     * Detecta si el dispositivo es de escritorio/PC
     */
    function isDesktopDevice() {
        // Verificar ancho de pantalla mínimo
        const minWidth = window.innerWidth >= 1200;

        // Verificar que tenga capacidades de hover (mouse)
        const hasHover = window.matchMedia('(hover: hover)').matches;

        // Verificar que el pointer sea preciso (mouse, no touch)
        const hasFinePointer = window.matchMedia('(pointer: fine)').matches;

        // Verificar que no sea un dispositivo táctil primario
        const notTouch = !('ontouchstart' in window || navigator.maxTouchPoints > 0);

        // User agent básico para descartar móviles/tablets conocidos
        const userAgent = navigator.userAgent.toLowerCase();
        const isMobileUA = /android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini|mobile|tablet/i.test(userAgent);

        return minWidth && hasHover && hasFinePointer && notTouch && !isMobileUA;
    }

    /**
     * Inicializa la funcionalidad al cargar la página
     */
    function initSidebarPersistence() {
        // Solo habilitar en dispositivos de escritorio
        if (!isDesktopDevice()) {
            console.log('Sidebar persistence disabled: Mobile/Tablet device detected');
            return;
        }

        // Aplicar estado guardado al cargar la página
        const savedState = getSavedState();
        applyState(savedState);

        // Observar cambios en el atributo data-sidebar-size
        const observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                if (mutation.type === 'attributes' && mutation.attributeName === 'data-sidebar-size') {
                    const currentState = document.body.getAttribute('data-sidebar-size');
                    if (currentState && currentState !== getSavedState()) {
                        saveState(currentState);
                    }
                }
            });
        });

        // Configurar el observer
        observer.observe(document.body, {
            attributes: true,
            attributeFilter: ['data-sidebar-size']
        });

        // Verificar cambios de tamaño de ventana por si cambia de móvil a escritorio
        let resizeTimeout;
        window.addEventListener('resize', function () {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(function () {
                if (!isDesktopDevice()) {
                    observer.disconnect();
                    console.log('Sidebar persistence disabled: Device no longer detected as desktop');
                }
            }, 300);
        });

        // Log para debugging
        console.log('Sidebar persistence initialized for desktop. Current state:', savedState);
    }

    /**
     * Función pública para limpiar el localStorage (opcional)
     */
    window.clearSidebarState = function () {
        try {
            localStorage.removeItem(STORAGE_KEY);
            applyState(DEFAULT_STATE);
            console.log('Sidebar state cleared');
        } catch (e) {
            console.warn('Error al limpiar localStorage:', e);
        }
    };

    /**
     * Función pública para obtener el estado actual (opcional)
     */
    window.getSidebarState = function () {
        return getSavedState();
    };

    // Inicializar cuando el DOM esté listo
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSidebarPersistence);
    } else {
        initSidebarPersistence();
    }

})();