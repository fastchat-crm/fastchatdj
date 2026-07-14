# cron_jobs — tareas programadas

Todos los crons del sistema viven en esta carpeta y este es su **único** documento.

## ¿Por qué existen?

Django solo reacciona a peticiones HTTP: cuando alguien entra a una página o llega un
webhook. **Nadie ejecuta código "a las 3 de la tarde" por sí solo.** Todo lo que el
sistema promete hacer *más tarde* (enviar una campaña programada, el paso 2 de una
secuencia, un recordatorio de cita 24h antes, cerrar chats muertos) queda guardado en
la base de datos como "pendiente"… y estos scripts son el motor que revisa el reloj y
lo ejecuta. **Sin conectarlos, esas funciones se ven en pantalla pero nunca envían nada.**

## Resumen: para qué es cada uno

| Script | En una frase | Si NO lo conectas | Frecuencia |
|---|---|---|---|
| `ejecutar_campanas.py` | Envía las campañas masivas que creas en `/whatsapp/campanas/` | Las campañas quedan en "programada" para siempre | Cada 1 min |
| `enviar_mensajes_programados.py` | Envía los mensajes individuales agendados a fecha/hora desde la ficha del contacto | Los mensajes agendados nunca salen | Cada 1 min |
| `ejecutar_secuencias.py` | Envía los pasos de las secuencias drip de `/whatsapp/secuencias/` cuando vence su espera | Los inscritos nunca reciben la serie de mensajes | Cada 5 min |
| `enviar_recordatorios_turnos.py` | Recuerda las citas de agenda N horas antes (con confirmar/cancelar por respuesta) | Clientes sin recordatorio → más ausencias | Cada 15 min |
| `enviar_mensaje_reconexion.py` | Da un empujón al cliente que dejó de responder antes de que venza la ventana 24h | Leads tibios mueren; recuperarlos costará plantilla paga | Cada 15 min |
| `enviar_mensaje_despedida.py` | Cierra ordenadamente conversaciones expiradas o muertas (dispara resumen + sentimiento) | Bandejas infladas de zombies y sin resúmenes IA | Cada 10 min |
| `reabrir_pospuestas.py` | Devuelve a la bandeja las conversaciones pospuestas (snooze) cuando llega su hora | Lo pospuesto nunca reaparece; el cliente queda esperando | Cada 5 min |
| `reconectar_sesiones.py` | Levanta sesiones Baileys caídas sin intervención manual | Una caída de red deja el número mudo hasta que alguien lo note | Cada 5 min |
| `aprender_conversaciones.py` | Minería nocturna: genera FAQs desde chats exitosos + resumen por contacto (gasta tokens LLM) | El bot no aprende solo; todo es curación manual | 1 vez/día 3am |
| `enviar_correo_prueba.py` | Diagnóstico manual del SMTP | — (no se programa) | Manual |

Regla de dedo: **los 3 primeros son el marketing**, los 5 siguientes son **la higiene
de la operación**, y `aprender_conversaciones` es **la mejora continua**. Si solo vas a
conectar unos pocos: `ejecutar_campanas`, `enviar_mensajes_programados` y
`enviar_mensaje_despedida` son el mínimo para que lo visible en la UI funcione.

## Cómo conectarlos

Cada script se ejecuta como `python cron_jobs/<script>.py` — bootstrapean Django solos,
no necesitan el servidor corriendo, solo el virtualenv y la BD accesibles.

**Linux (crontab):**

```
* * * * *    cd /ruta/fastchatdj && /ruta/venv/bin/python cron_jobs/ejecutar_campanas.py
* * * * *    cd /ruta/fastchatdj && /ruta/venv/bin/python cron_jobs/enviar_mensajes_programados.py
*/5 * * * *  cd /ruta/fastchatdj && /ruta/venv/bin/python cron_jobs/ejecutar_secuencias.py
*/5 * * * *  cd /ruta/fastchatdj && /ruta/venv/bin/python cron_jobs/reabrir_pospuestas.py
*/5 * * * *  cd /ruta/fastchatdj && /ruta/venv/bin/python cron_jobs/reconectar_sesiones.py
*/10 * * * * cd /ruta/fastchatdj && /ruta/venv/bin/python cron_jobs/enviar_mensaje_despedida.py
*/15 * * * * cd /ruta/fastchatdj && /ruta/venv/bin/python cron_jobs/enviar_recordatorios_turnos.py
*/15 * * * * cd /ruta/fastchatdj && /ruta/venv/bin/python cron_jobs/enviar_mensaje_reconexion.py
0 3 * * *    cd /ruta/fastchatdj && /ruta/venv/bin/python cron_jobs/aprender_conversaciones.py
```

**Windows (Task Scheduler):** una tarea básica por script — Acción: iniciar programa
`C:\ruta\venv\Scripts\python.exe`, Argumentos: `cron_jobs\<script>.py`, Iniciar en:
`C:\DESARROLLO_PROYECTOS\fastchat\fastchatdj`, con el disparador repitiendo cada N
minutos según la tabla.

Todos son **seguros de correr en paralelo y de correr tarde**: usan claims atómicos
anti-doble-envío y semántica catch-up (lo pendiente sale al reanudar, no se pierde).
Toda ejecución se registra vía `logCron`.

Reglas comunes: todos respetan `sesion.activo`, y los envíos salientes respetan
`Contacto.opt_out` / `whatsapp_invalido` (salvo lo transaccional, ver recordatorios
de turnos).

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

## ejecutar_secuencias.py

**Objetivo:** despachar los pasos vencidos de las secuencias drip (`SecuenciaWhatsApp`
/ `PasoSecuencia` / `InscripcionSecuencia`, UI en `/whatsapp/secuencias/`).

**Qué hace:** toma inscripciones `activa` con `proximo_envio <= ahora` e
`intentos < 3` (excluye opt-out, números inválidos y sesiones inactivas), envía el
paso pendiente y agenda el siguiente (`proximo_envio = ahora + espera_horas` del
próximo paso). Sin más pasos → `completada`.

**Anti doble envío:** claim atómico del avance de paso
(`UPDATE ... WHERE estado='activa' AND paso_actual=<n>`); en fallo revierte el
avance e incrementa `intentos` (al tercer fallo → estado `error`).

**Meta:** ventana 24h manejada con backoff de 6 h vía cache
(`seq_meta_bloqueado_<id>`) sin consumir `intentos`.

**Salida al responder:** no la maneja el cron — cuando el contacto escribe,
`procesar_mensaje.py` cancela sus inscripciones con `salir_al_responder=True`
(`whatsapp/funciones_secuencias.py::cancelar_por_respuesta`). La inscripción
automática por etiqueta disparadora vive en el signal m2m de
`Contacto.etiquetas` (`whatsapp/signals.py`).

**Frecuencia:** cada 5 minutos (`*/5 * * * *`) — las esperas son en horas, no
necesita precisión de minuto.

**Si no corre:** los pasos se acumulan y salen al reanudar (la condición es
`proximo_envio <= ahora`, no una ventana).

## enviar_mensajes_programados.py

**Objetivo:** enviar los `MensajeWhatsAppProgramado` (mensajes individuales agendados
a fecha/hora: seguimientos, recordatorios manuales).

**Qué hace:** toma los pendientes vencidos (`enviado=False`, `intentos < 3`, fecha/hora ≤ ahora)
de sesiones Baileys activas, excluyendo contactos con `opt_out` o `whatsapp_invalido`;
envía texto (con simulación de escritura) y el archivo adjunto si existe.

**Anti doble envío:** antes de enviar hace un claim atómico
(`UPDATE ... WHERE enviado=False` → `enviado=True`); si otro proceso concurrente ya lo
tomó, el update devuelve 0 filas y se salta. Si el envío falla, revierte el flag e
incrementa `intentos`; al tercer fallo el mensaje deja de reintentarse (queda visible
con `enviado=False` e `intentos=3` para revisión manual). Si el texto salió pero el
adjunto falló, se mantiene `enviado=True` (no se duplica el texto) y el adjunto perdido
queda en el log.

**Meta:** soportado. Se pasa la conversación para que aplique la ventana de 24 h — si
está vencida, el envío queda en espera (reintento cada 6 h o cuando el cliente vuelva
a escribir) sin consumir `intentos` hasta el próximo intento real; la alternativa
inmediata es enviar una plantilla aprobada desde el chat.

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

**Objetivo:** cerrar ordenadamente las conversaciones, en dos modos (2026-07-13):

1. **Expiración clásica** (sesiones con `min_sesion > 0`): `fecha_hora_expira`
   vencida → cierra CON despedida y respetando asignación humana, como siempre.
2. **Cierre higiénico** (sesiones con `min_sesion = 0` → `fecha_hora_expira=None`,
   el modo "solo cierra el asesor"): conversaciones con más de
   `Configuracion.dias_cierre_higienico` días sin mensajes (default 3; 0 = nunca)
   → cierra SIN despedida, incluso si están asignadas (3 días muertas), para que
   corran resumen + sentimiento + reglas de fin y el inbox no acumule zombies.
   `bloquear_cierre=True` sigue exceptuando.

**Qué hace:** delega el cierre en `ConversacionWhatsApp.cerrar()` (despedida opcional +
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
opción de confirmar, cancelar o reagendar respondiendo. Las respuestas *confirmar* y
*cancelar* las captura `agenda/respuestas_recordatorio.py` de forma determinista
(sin tokens LLM, funciona con cualquier `modo_bot`): confirma el turno
(`pending`→`confirmed`) o lo cancela (`cancelled` + notificación interna al
responsable del grupo). *Reagendar* sigue el pipeline normal (motor/IA con tools de
agenda).

**Qué hace:** selecciona turnos activos futuros con `recordatorio_enviado=False` e
`recordatorio_intentos < 3` cuyo momento de aviso ya llegó: desde
`inicio − horas_antes` hasta el `inicio` del turno (semántica *catch-up* — si el cron
estuvo caído, el recordatorio sale igual en la próxima corrida en vez de perderse).
`horas_antes` sale de `Turno.recordatorio_horas_antes` si el cliente pidió una
anticipación propia al agendar ("avísame 2 días antes", vía tool `agenda_registrar_turno`),
sino de `GrupoAgenda.recordatorio_horas_antes` (default 24). Reservas hechas DESPUÉS
del momento de aviso (ej. turno para dentro de 2 h con recordatorio de 24 h) no se
recuerdan — el cliente acaba de agendar y ya recibió la confirmación.
Es mensajería transaccional: NO se filtra por opt-out (el opt-out es de
masivos/promociones), pero sí respeta números inválidos a nivel de envío.

**Anti doble envío:** claim atómico del flag antes de enviar
(`UPDATE ... WHERE recordatorio_enviado=False`); dos crons concurrentes no duplican.
En fallo revierte el flag e incrementa `recordatorio_intentos`; al tercer fallo deja
de reintentar.

**Frecuencia:** cada 15 minutos (`*/15 * * * *`).

**Si no corre:** los recordatorios se acumulan y salen al reanudar, siempre que el
turno no haya empezado todavía.

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
