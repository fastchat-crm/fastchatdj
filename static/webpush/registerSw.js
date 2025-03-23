const isLogged = document.querySelector('meta[name=islogged]').getAttribute('content');

const registerSw = async () => {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.ready.then(registration => {
            initialiseState(registration);
        });
    }
};

const initialiseState = (reg) => {
    if (!reg.showNotification) {
        return;
    }
    if (Notification.permission === 'denied') {
        return
    }
    if (!'PushManager' in window) {
        return
    }
    reg.update();
    subscribe(reg);
}

function urlB64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
        .replace(/\-/g, '+')
        .replace(/_/g, '/');

    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    const outputData = outputArray.map((output, index) => rawData.charCodeAt(index));

    return outputData;
}

const subscribe = async (reg) => {
    const subscription = await reg.pushManager.getSubscription();
    if (subscription) {
        sendSubData(subscription);
        return;
    }

    const vapidMeta = document.querySelector('meta[name="vapid-key"]');
    const key = vapidMeta.content;
    const options = {
        userVisibleOnly: true,
        // if key exists, create applicationServerKey property
        ...(key && {applicationServerKey: urlB64ToUint8Array(key)})
    };

    const sub = await reg.pushManager.subscribe(options);
    sendSubData(sub)
};

const unsubscribe = async (reg) => {
    const subscription = await reg.pushManager.getSubscription();
    if (subscription) {
        sendUnData(subscription);
        return;
    }

    const vapidMeta = document.querySelector('meta[name="vapid-key"]');
    const key = vapidMeta.content;
    const options = {
        userVisibleOnly: true,
        // if key exists, create applicationServerKey property
        ...(key && {applicationServerKey: urlB64ToUint8Array(key)})
    };

    const sub = await reg.pushManager.subscribe(options);
    sendUnData(sub)
};

const sendUnData = async (subscription) => {
    try {
        if (isLogged) {
            const browser = navigator.userAgent.match(/(firefox|msie|chrome|safari|trident)/ig)[0].toLowerCase();
            const data = {
                status_type: 'unsubscribe',
                subscription: subscription.toJSON(),
                browser: browser,
            };

            const res = await fetch('/webpush/save_information', {
                method: 'POST',
                body: JSON.stringify(data),
                headers: {
                    'content-type': 'application/json'
                },
                credentials: "include"
            }).catch(function (error) {

            });

            handleResponse(res);
        }
    } catch (e) {

    }
};

const sendSubData = async (subscription) => {
    try {
        if (isLogged) {
            const browser = navigator.userAgent.match(/(firefox|msie|chrome|safari|trident)/ig)[0].toLowerCase();
            const data = {
                status_type: 'subscribe',
                subscription: subscription.toJSON(),
                browser: browser,
            };

            const res = await fetch('/webpush/save_information', {
                method: 'POST',
                body: JSON.stringify(data),
                headers: {
                    'content-type': 'application/json'
                },
                credentials: "include"
            }).catch(function (error) {

            });
            handleResponse(res);
        }
    } catch (e) {

    }
};

const handleResponse = (res) => {
    console.log(res.status);
};

registerSw();