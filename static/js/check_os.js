const platform = navigator.platform.toLowerCase(),
        iosPlatforms = ['iphone', 'ipad', 'ipod', 'ipod touch'];

let infoDevice = new UAParser();

var isMobile = {
    Android: function() {
        return infoDevice.getOS().name==="Android";
    },
    BlackBerry: function() {
        return infoDevice.getOS().name==="BlackBerry";
    },
    iOS: function() {
        return infoDevice.getOS().name==="iOS";
    },
    /**
     * @return {boolean}
     */
    Mac: function() {
        return infoDevice.getOS().name==="Mac OS";
    },
    /**
     * @return {boolean}
     */
    Windows: function() {
        return infoDevice.getOS().name==="Windows";
    },
    /**
     * @return {boolean}
     */
    Linux: function() {
        return infoDevice.getOS().name==="Linux";
    },
    any: function() {
        return (isMobile.Android() || isMobile.BlackBerry() || isMobile.iOS() || isMobile.Opera() || isMobile.Windows());
    }
};