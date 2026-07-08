# cron_jobs — tareas programadas

Todos los crons del sistema viven en esta carpeta y este es su **único** documento.
Se ejecutan como `python cron_jobs/<script>.py` (bootstrapean Django solos) vía cron
de Linux o Task Scheduler de Windows.

Reglas comunes: todos loguean con `logCron`, respetan `sesion.activo` y los envíos
salientes respetan `Contacto.opt_out` / `whatsapp_invalido` (salvo lo transaccional,
ver recordatorios de turnos).

| Script | Objetivo | Frecuencia recomendada |
|---|---|---|
| `ejecutar_campanas.py` | Despachar campañas masivas con throttle y tope diario | Cada 1 minuto |
| `enviar_mensajes_programados.py` | Enviar mensajes individuales agendados | Cada 1 minuto |
| `enviar_mensaje_reconexion.py` | Nudge a conversaciones donde el cliente calló >1 h (dentro de la ventana 24 h) | Cada 15 minutos |
| `enviar_mensaje_despedida.py` | Cerrar conversaciones expiradas con mensaje de despedida | Cada 10 minutos |
| `reabrir_pospuestas.py` | Reabrir conversaciones cuyo snooze venció | Cada 5 minutos |
| `reconectar_sesiones.py` | Reconectar sesiones Baileys caídas | Cada 5 minutos |
| `enviar_recordatorios_turnos.py` | Recordatorio de turnos/citas próximos | Cada 15 minutos |
| `aprender_conversaciones.py` | Extraer FAQs de conversaciones exitosas + resumen por contacto | 1 vez al día (madrugada) |
| `enviar_correo_prueba.py` | Prueba manual de la configuración de email | Manual (no programar) |

---

## ejecutar_campanas.py

**Objetivo:** despachar las campañas masivas (texto o plantilla Meta) sin gatillar
rate limits ni reventar el tier del número.

**Qué hace en cada tick:**
1. Arranca campañas `programada` cuya fecha llegó → materializa un `EnvioCampana` por contacto de la audiencia (filtrada por canal + etiquetas, excluyendo `opt_out` y `whatsapp_invalido`).
2. Para cada campaña `enviando`: respeta la ventana horaria, calcula el tope diario de la sesión (`Campana.limite_diario`; 0 = automático por `messaging_limit_tier` de Meta) y envía hasta `throttle_por_minuto` mensajes.
3. Errores síncronos con código 131030/131050 marcan al contacto inválido / opt-out.
4. Sin pendientes → campaña `completada`.

**Frecuencia:** cada 1 minuto (`* * * * *`) — el throttle por minuto depende de esta cadencia.

**Si no corre:** las campañas quedan en `programada`/`enviando` sin avanzar; no se pierde nada, retoma al volver.

## enviar_mensajes_programados.py

**Objetivo:** enviar los `MensajeWhatsAppProgramado` (mensajes individuales agendados
a fecha/hora: seguimientos, recordatorios manuales).

**Qué hace:** toma los pendientes vencidos (`enviado=False`, fecha/hora ≤ ahora) de
sesiones Baileys activas, excluyendo contactos con `opt_out` o `whatsapp_invalido`;
envía texto (con simulación de escritura) y el archivo adjunto si existe; marca `enviado=True`.

**Meta:** soportado. Se pasa la conversación para que aplique la ventana de 24 h — si
está vencida, el envío queda en espera (reintento cada 6 h o cuando el cliente vuelva
a escribir); la alternativa inmediata es enviar una plantilla aprobada desde el chat.

**Frecuencia:** cada 1 minuto (`* * * * *`) para respetar la hora agendada con precisión de minuto.

**Si no corre:** los mensajes se acumulan y salen todos juntos al reanudar (el filtro incluye fechas pasadas).

## enviar_mensaje_reconexion.py

**Objetivo:** recuperar conversaciones que se enfriaron — si el cliente dejó de
responder, darle un empujón ANTES de que venza la ventana de 24 h (después ya solo se
puede con plantilla pagada).

**Condiciones para enviar (todas):**
1. Conversación abierta, no finalizada, `reconexion_enviada=False`.
2. Sesión activa con `reconexion_activa=True` y `mensaje_reconexion` configurado.
3. El último mensaje es NUESTRO (saliente) y lleva **más de 1 hora** sin respuesta.
4. El último mensaje DEL CLIENTE fue hace **menos de 24 horas** (ventana viva).
5. El contacto no está en baja (`opt_out=False`) ni marcado inválido.

Envía un solo nudge por silencio: marca `reconexion_enviada=True` y no repite hasta
que el cliente vuelva a escribir (el webhook resetea el flag).

**Frecuencia:** cada 15 minutos (`*/15 * * * *`) — con cadencia horaria el umbral de "1 hora" puede estirarse hasta 2 h reales.

**Si no corre:** conversaciones tibias mueren sin reintento y recuperar al cliente pasa a costar una plantilla.

## enviar_mensaje_despedida.py

**Objetivo:** cerrar ordenadamente las conversaciones que superaron su tiempo de
expiración (`fecha_hora_expira`), enviando el mensaje de despedida de la sesión.

**Qué hace:** selecciona conversaciones no finalizadas con `despedida_enviado=False` y
expiración vencida, y delega el cierre en `ConversacionWhatsApp.cerrar()` (despedida +
resumen + sentimiento + acciones de fin de conversación). Al cerrar, el resumen también
se indexa en la memoria RAG del agente.

**Frecuencia:** cada 10 minutos (`*/10 * * * *`).

**Si no corre:** las conversaciones quedan abiertas indefinidamente — los asesores ven
bandejas infladas y los resúmenes/aprendizaje no se generan.

## reabrir_pospuestas.py

**Objetivo:** devolver a la bandeja "abierta" las conversaciones que un asesor pospuso
(snooze) cuando llega su hora.

**Qué hace:** busca conversaciones con `snooze_hasta <= ahora`, limpia el snooze y las
marca `estado_atencion='abierta'`.

**Frecuencia:** cada 5 minutos (`*/5 * * * *`).

**Si no corre:** las conversaciones pospuestas nunca reaparecen y el cliente queda esperando respuesta.

## reconectar_sesiones.py

**Objetivo:** levantar automáticamente las sesiones Baileys que se cayeron sin
intervención del usuario (caída del Node, pérdida de red).

**Condiciones:** sesión activa (`status=True`), en estado `desconectado` o `error`, y
que NO fue desconectada manualmente (`desconectado_manualmente=False`).

**Frecuencia:** cada 5 minutos (`*/5 * * * *`).

**Si no corre:** una sesión caída deja de recibir y responder mensajes hasta que
alguien la reconecte a mano — clientes sin respuesta y campañas frenadas.

## enviar_recordatorios_turnos.py

**Objetivo:** recordar por WhatsApp los turnos/citas próximos (módulo agenda), con
opción de cancelar o reagendar respondiendo.

**Qué hace:** busca turnos cuyo recordatorio cae dentro de la ventana del cron
(`CRON_WINDOW_MIN = 30`) y envía el mensaje con servicio, recurso, fecha/hora y precio.
Es mensajería transaccional: NO se filtra por opt-out (el opt-out es de
masivos/promociones), pero sí respeta números inválidos a nivel de envío.

**Frecuencia:** cada 15 minutos (`*/15 * * * *`) — debe ser menor que `CRON_WINDOW_MIN`
para no saltarse recordatorios.

**Si no corre:** clientes sin recordatorio → más ausencias a turnos.

## aprender_conversaciones.py

**Objetivo:** que los agentes aprendan de lo que salió bien — minería de
conversaciones finalizadas exitosas.

**Qué hace:**
1. De conversaciones finalizadas con sentimiento positivo/neutral y sin feedback
   negativo, extrae pares pregunta→respuesta y los crea como `FaqAgente` en estado
   `pendiente` (revisión humana antes de inyectarse al prompt).
2. Actualiza el resumen persistente por contacto (`PerfilContacto.resumen`, vía
   `AgenteResumidor`) — es lo que llega al prompt como `{historial_contacto}`.

**Costo:** consume tokens LLM (resumidor + extractor) — por eso corre 1 vez al día, no
cada minuto. También se puede disparar por agente desde la UI ("Aprender ahora" en entrenamiento).

**Frecuencia:** 1 vez al día en madrugada (`0 3 * * *`).

**Si no corre:** los agentes no generan FAQs nuevas ni actualizan la memoria por
contacto; el chat sigue funcionando normal.

## enviar_correo_prueba.py

**Objetivo:** verificar manualmente que la configuración SMTP del sistema funciona
(envía un correo de prueba con la plantilla de registro).

**Frecuencia:** NO programar — es un script de diagnóstico manual. Ejecutar a mano
cuando se cambien credenciales de email: `python cron_jobs/enviar_correo_prueba.py`.
