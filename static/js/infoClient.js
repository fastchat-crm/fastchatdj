async function getClientInfo() {
    // Objeto con valores por defecto
    let clientInfo = {
        browser: '',
        os: '',
        deviceType: '',
        clientIP: '',
        screenSize: ''
    };

    try {
        // Detectar navegador
        const userAgent = navigator.userAgent;
        if (userAgent.indexOf("Firefox") > -1) {
            clientInfo.browser = "Firefox";
        } else if (userAgent.indexOf("Chrome") > -1 && !userAgent.match(/Edg|OPR/)) {
            clientInfo.browser = "Chrome";
        } else if (userAgent.indexOf("Safari") > -1 && userAgent.indexOf("Chrome") === -1) {
            clientInfo.browser = "Safari";
        } else if (userAgent.indexOf("Edg") > -1) {
            clientInfo.browser = "Edge";
        } else if (userAgent.indexOf("OPR") > -1) {
            clientInfo.browser = "Opera";
        }

        // Detectar Sistema Operativo
        if (userAgent.indexOf("Win") > -1) {
            clientInfo.os = "Windows";
        } else if (userAgent.indexOf("Mac") > -1) {
            clientInfo.os = "MacOS";
        } else if (userAgent.indexOf("Linux") > -1) {
            clientInfo.os = "Linux";
        } else if (/Android/.test(userAgent)) {
            clientInfo.os = "Android";
        } else if (/iPhone|iPad|iPod/.test(userAgent)) {
            clientInfo.os = "iOS";
        }

        // Detectar tipo de dispositivo
        if (/(tablet|ipad|playbook|silk)|(android(?!.*mobi))/i.test(userAgent)) {
            clientInfo.deviceType = "Tablet";
        } else if (/Mobile|Android|iP(hone|od)|IEMobile|BlackBerry|Kindle|Silk-Accelerated|(hpw|web)OS|Opera M(obi|ini)/.test(userAgent)) {
            clientInfo.deviceType = "Mobile";
        } else {
            clientInfo.deviceType = "Desktop";
        }

        // Obtener tamaño de pantalla
        clientInfo.screenSize = `${window.screen.width}x${window.screen.height}`;

        // Intentar obtener IP del cliente
        try {
            const response = await fetch('https://api.ipify.org?format=json');
            const data = await response.json();
            clientInfo.clientIP = data.ip;
        } catch (ipError) {
            console.warn('No se pudo obtener la IP del cliente:', ipError);
        }

    } catch (error) {
        console.error('Error al obtener información del cliente:', error);
    }

    return clientInfo;
}
