# App `automatizacion/` — motor de reglas transversal

> Fase 1.3 del plan en `.ai/docs/estudio_gohighlevel.md`. Es el equivalente al
> Workflow Builder de GoHighLevel.

## En qué se diferencia del motor de flujos que ya existía

`crm/motor_flujo_chatbot.py` vive **dentro de la conversación**: recibe un
mensaje y decide qué responder. Esto es otra cosa: escucha eventos de
**cualquier** parte del sistema y ejecuta pasos que pueden tardar días.

    cita cumplida  →  esperar 2 días  →  pedir reseña por WhatsApp
    contacto creado (canal = instagram)  →  etiquetar  →  asignar asesor

## La pieza clave: el `esperar` se persiste

Una ejecución que llega a un paso `esperar` guarda **en qué acción quedó**
(`indice_accion`) y **cuándo retomar** (`ejecutar_en`), y devuelve el control.
El cron `procesar_automatizaciones` la levanta cuando vence. Sin eso, "esperar 2
días" exigiría un proceso vivo esos dos días.

El índice se avanza **antes** de dormir, así al retomar no se vuelve a esperar
el mismo paso.

## Modelos

| Modelo | Rol |
|---|---|
| `Automatizacion` | Disparador (`evento`) + condiciones + estado activo |
| `AccionAutomatizacion` | Un paso ordenado, con `parametros` en JSONB |
| `EjecucionAutomatizacion` | Una corrida. Sobrevive a los `esperar` |
| `LogAutomatizacion` | Traza por acción. Es lo que se mira cuando algo no pasó |

## Eventos y su contexto

| Evento | Contexto que trae | Emitido desde |
|---|---|---|
| `contacto_creado` | `contacto_id`, `contacto_nombre`, `numero`, `canal`, `sesion_id`, `sesion` | `whatsapp/procesar_mensaje.py` |
| `conversacion_finalizada` | `conversacion_id`, `contacto_id`, `contacto_nombre`, `numero`, `sesion_id`, `clasificacion`, `estado_atencion` | `ConversacionWhatsApp.cerrar()` |
| `cita_cumplida` | `turno_id`, `contacto_id`, `servicio`, `recurso`, `estado_anterior` | `agenda/view_citas.py` |
| `conversacion_iniciada`, `etiqueta_agregada`, `cita_creada`, `oportunidad_ganada`, `registro_creado` | — | **Declarados pero sin emisor todavía** |

Para emitir un evento nuevo basta con llamar a `motor.disparar(evento, contexto)`
desde el código de dominio.

## Acciones disponibles

`esperar` · `enviar_whatsapp` · `enviar_email` · `agregar_etiqueta` ·
`asignar_asesor` · `webhook` · `notificar`

Los textos admiten interpolación `{{campo}}` contra el contexto, con rutas
anidadas (`{{cliente.plan}}`). Un placeholder inexistente se reemplaza por vacío
en lugar de romper el envío.

## Decisiones que conviene no revertir

- **`disparar()` no ejecuta nada de forma síncrona.** Crea la ejecución y
  vuelve. Así un webhook lento o un SMTP caído nunca bloquean el flujo que
  disparó el evento — y eso incluye el webhook de WhatsApp, donde una demora se
  traduce en reintentos de Meta.

- **`disparar()` nunca lanza excepción.** Está envuelto en `try/except` porque
  se lo llama desde `cerrar()` y desde el procesamiento de mensajes: un error de
  automatización no puede impedir que se cierre una conversación.

- **Una acción fallida no cancela la automatización entera.** Se reintenta la
  ejecución desde ese paso, con backoff lineal (10, 20, 30 min) y tope de 3
  intentos; recién ahí queda `fallida`.

- **`select_for_update(skip_locked=True)` en `procesar_pendientes`.** Dos
  corridas solapadas del cron no pueden procesar la misma ejecución dos veces.

- **Apagar una automatización no mata las ejecuciones en curso.** `activo=False`
  solo impide crear nuevas; las que estaban esperando siguen su curso. Para
  cortarlas hay que cancelarlas desde la UI.

## Cron

`cron_jobs/procesar_automatizaciones.py`, cada 1 minuto. Sin él las
automatizaciones con `esperar` nunca terminan.

## Pendiente

- UI para las condiciones: el backend las evalúa (`cumple_condiciones`) y el
  modelo las guarda, pero el formulario todavía no las carga.
- Reordenar los pasos desde la UI (hoy se agregan al final).
- Acciones sobre objetos personalizados: crear y actualizar registros.
- Emisores para los cinco eventos declarados que aún no dispara nadie.
