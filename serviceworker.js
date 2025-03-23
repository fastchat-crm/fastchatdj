const CACHE_NAME = 'IMAEBS-V3';
var urlsToCache = [
];

const addResourcesToCache = async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(urlsToCache);
};

addEventListener('install', function (event) {
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

addEventListener('push', async function (event) {
    const eventInfo = event.data.text();
    const data = JSON.parse(eventInfo);
    const head = data.head;
    const body = data.body;

    if (data.btn_notificaciones) {
        var clientes = await clients.matchAll({includeUncontrolled: true, type: 'window'});
        for (const client of clientes) {
            client.postMessage(data);
        }
    }

    var DATANOT = {
        body: body,
        icon: "/static/pwalogo/512x512.png",
        badge: "/static/pwalogo/badge.png",
        vibrate: [500, 110, 500, 500, 110, 500],
        data: {url: data.url ? data.url : ''},
        actions: [{action: "open_url", title: "Ver ahora"}],
        requireInteraction: true
    };

    self.registration.showNotification(head, DATANOT);
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
    switch (event.action) {
        case 'open_url':
            if (event.notification.data.url) {
                clients.openWindow(event.notification.data.url); //which we got from above
            }
            break;
    }
}, false);