PWA_APP_NAME = 'fastchat'
PWA_APP_SHORT_NAME = 'fastchat'
PWA_APP_DESCRIPTION = 'Plataforma WhatsApp + CRM + Agendamiento.'
PWA_APP_THEME_COLOR = '#2874A6'
PWA_APP_BACKGROUND_COLOR = '#ffffff'
PWA_APP_DISPLAY = 'standalone'
PWA_APP_ORIENTATION = 'any'
PWA_APP_START_URL = '/panel/'
PWA_APP_SCOPE = '/'
PWA_APP_STATUS_BAR_COLOR = 'default'
PWA_APP_LANG = 'es-ES'
PWA_APP_DIR = 'auto'
PWA_APP_DEBUG_MODE = False

PWA_APP_ICONS_FALLBACK = [
    {'src': '/static/images/icons/icon-72x72.png', 'sizes': '72x72', 'type': 'image/png'},
    {'src': '/static/images/icons/icon-96x96.png', 'sizes': '96x96', 'type': 'image/png'},
    {'src': '/static/images/icons/icon-128x128.png', 'sizes': '128x128', 'type': 'image/png'},
    {'src': '/static/images/icons/icon-144x144.png', 'sizes': '144x144', 'type': 'image/png'},
    {'src': '/static/images/icons/icon-152x152.png', 'sizes': '152x152', 'type': 'image/png'},
    {'src': '/static/images/icons/icon-192x192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any maskable'},
    {'src': '/static/images/icons/icon-384x384.png', 'sizes': '384x384', 'type': 'image/png'},
    {'src': '/static/images/icons/icon-512x512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'},
]

PWA_APP_SPLASH_SCREEN = [
    {'src': '/static/images/icons/splash-640x1136.png',
     'media': '(device-width: 320px) and (device-height: 568px) and (-webkit-device-pixel-ratio: 2)'},
    {'src': '/static/images/icons/splash-750x1334.png',
     'media': '(device-width: 375px) and (device-height: 667px) and (-webkit-device-pixel-ratio: 2)'},
    {'src': '/static/images/icons/splash-1242x2208.png',
     'media': '(device-width: 621px) and (device-height: 1104px) and (-webkit-device-pixel-ratio: 3)'},
    {'src': '/static/images/icons/splash-1125x2436.png',
     'media': '(device-width: 375px) and (device-height: 812px) and (-webkit-device-pixel-ratio: 3)'},
    {'src': '/static/images/icons/splash-828x1792.png',
     'media': '(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 2)'},
    {'src': '/static/images/icons/splash-1242x2688.png',
     'media': '(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 3)'},
    {'src': '/static/images/icons/splash-1536x2048.png',
     'media': '(device-width: 768px) and (device-height: 1024px) and (-webkit-device-pixel-ratio: 2)'},
    {'src': '/static/images/icons/splash-1668x2224.png',
     'media': '(device-width: 834px) and (device-height: 1112px) and (-webkit-device-pixel-ratio: 2)'},
    {'src': '/static/images/icons/splash-1668x2388.png',
     'media': '(device-width: 834px) and (device-height: 1194px) and (-webkit-device-pixel-ratio: 2)'},
    {'src': '/static/images/icons/splash-2048x2732.png',
     'media': '(device-width: 1024px) and (device-height: 1366px) and (-webkit-device-pixel-ratio: 2)'},
]

PWA_INSTALL_COOLDOWN_HOURS = 10
