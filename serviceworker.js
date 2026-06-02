const CACHE_NAME = 'MENSAJERIA-VS';
var urlsToCache = [
];

const addResourcesToCache = async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(urlsToCache);
};

addEventListener('install', function (event) {
    self.skipWaiting();
    event.waitUntil(addResourcesToCache());
});

const cacheFirst = async (request) => {
    let url = request;
    // let origin = self.location.origin;
    // if(request.url.startsWith(`${origin}/ventas/pedido/`)){
    //     url = "/ventas/pedido/";
    //     if(request.url.indexOf("action=add") >= 0){
    //         url = "/ventas/pedido/?action=add"
    //     }
    // }
    try {
        return await fetch(request);
    } catch (e) {
        const responseFromCache = await caches.match(url);
        if (responseFromCache) {
            return responseFromCache;
        }
        return await caches.match("/offline-view/");
    }
};

// self.addEventListener("fetch", (event) => {
//     event.respondWith(cacheFirst(event.request));
// });

const activateEvent = async () => {
    await clients.claim();
    let refresh = false;
    const cacheList = await caches.keys();
    for(let c of cacheList){
        if (c !== CACHE_NAME) {
            refresh = true;
            await caches.delete(c);
        }
    }
    if (refresh) {
        const clientes = await clients.matchAll({includeUncontrolled: true, type: 'window'});
        for (let client of clientes) {
            client.postMessage('refresh');
        }
    }
}

addEventListener('activate', function (event) {
    event.waitUntil(
        activateEvent()
    );
});

var port;

addEventListener('push', function (event) {
    event.waitUntil((async function () {
        let data = {};
        try {
            data = event.data ? JSON.parse(event.data.text()) : {};
        } catch (e) {
            data = {head: 'fastchat', body: (event.data && event.data.text()) || ''};
        }

        const head = data.head || data.title || 'fastchat';
        const body = data.body || data.message || data.descripcion || '';

        if (data.btn_notificaciones) {
            const clientes = await clients.matchAll({includeUncontrolled: true, type: 'window'});
            for (const client of clientes) {
                client.postMessage(data);
            }
        }

        const DATANOT = {
            body: body,
            icon: data.icon || "/static/pwalogo/512x512.png",
            badge: data.badge || "/static/pwalogo/badge.png",
            vibrate: [500, 110, 500, 500, 110, 500],
            data: {url: data.url ? data.url : ''},
            actions: [{action: "open_url", title: "Ver ahora"}],
            requireInteraction: true
        };

        await self.registration.showNotification(head, DATANOT);
    })());
});

self.onmessage = async function (event) {
    if (event.data && event.data.type === 'PORT_INITIALIZATION') {
        //port = event.ports[0];
    } else if (event.data && event.data.type) {
        var clientes = await clients.matchAll({includeUncontrolled: true, type: 'window'});
        for (const client of clientes) {
            client.postMessage(event.data.type);
        }
    }
}

addEventListener('notificationclick', function (event) {
    // Cerrar la notificación siempre (tanto click en el cuerpo como en la acción).
    event.notification.close();

    // El click en el CUERPO de la notificación llega con event.action === ''
    // (string vacío). Antes solo se manejaba la acción 'open_url' del botón
    // "Ver ahora", por eso al tocar la notificación no abría nada. Ahora
    // cubrimos ambos casos.
    if (event.action && event.action !== 'open_url') {
        return;
    }

    var url = (event.notification.data && event.notification.data.url) || '';
    if (!url) {
        return;
    }

    event.waitUntil((async function () {
        // Si ya hay una pestaña abierta en esa URL, la enfocamos; si no, abrimos.
        const ventanas = await clients.matchAll({type: 'window', includeUncontrolled: true});
        for (const cliente of ventanas) {
            if (cliente.url === url && 'focus' in cliente) {
                return cliente.focus();
            }
        }
        return clients.openWindow(url);
    })());
}, false);