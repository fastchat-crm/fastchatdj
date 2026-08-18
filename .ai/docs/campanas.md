# Módulo Campañas — `/whatsapp/campanas/`

Vista: `whatsapp/view_campanas.py`. Template:
`whatsapp/templates/whatsapp/campanas/listado.html` (modal `#modalCampana` para
crear). Envío real: cron `cron_jobs/ejecutar_campanas.py` (throttle + opt-out).

## Modal de creación — dos modos (2026-07-13)

Arriba del modal hay dos botones:

- **Crear con IA** (`#btnModoIa`): muestra el asistente (`#iaCampanaCard`,
  POST `action=campana_ia` → `agents_ai/ai_actions/campanas_wa.py:generar`),
  que llena nombre/descripción/mensaje/tipo/throttle desde una descripción
  libre. Requiere sesión seleccionada (usa su contexto) y API Key IA activa
  del perfil. El asistente también aparece solo al elegir sesión
  (`actualizarEstadoIaCampana`).
- **Crear manual — ver cómo funciona** (`#btnModoManual`): expande la guía
  `#campInfo` ("¿Qué es una campaña?": audiencia por etiquetas
  incluir/excluir, contenido, throttle, ciclo de vida Borrador → Programada →
  Enviando → Completada) y enfoca el formulario.

## Acciones POST

`add`, `programar`, `enviar_ahora`, `pausar`, `reanudar`, `cancelar`,
`eliminar`, `add_etiqueta` (crea etiqueta sin salir del modal), `campana_ia`.
Deep-link: `?action=add&sesion=<enc>` abre el modal con la sesión
preseleccionada (`abrir_modal_add`).
