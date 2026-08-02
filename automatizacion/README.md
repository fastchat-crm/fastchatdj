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

Los ocho eventos declarados emiten. Cuatro se disparan a mano desde su punto de
origen y cuatro por señal — la diferencia está explicada abajo.

| Evento | Contexto que trae | Emitido desde |
|---|---|---|
| `contacto_creado` | `contacto_id`, `contacto_nombre`, `numero`, `canal`, `sesion_id`, `sesion` | `whatsapp/procesar_mensaje.py` (explícito) |
| `conversacion_finalizada` | `conversacion_id`, `contacto_id`, `contacto_nombre`, `numero`, `sesion_id`, `clasificacion`, `estado_atencion` | `ConversacionWhatsApp.cerrar()` (explícito) |
| `cita_cumplida` | `turno_id`, `contacto_id`, `servicio`, `recurso`, `estado_anterior` | `agenda/view_citas.py` (explícito) |
| `oportunidad_ganada` | `card_id`, `conversacion_id`, `contacto_id`, `etapa`, `etapa_anterior`, `pipeline`, `valor`, `moneda` | `whatsapp/view_pipeline.py` → `mover_card` a una etapa con `es_ganado` (explícito) |
| `etiqueta_agregada` | `contacto_id`, `contacto_nombre`, `numero`, `canal`, `etiqueta`, `etiqueta_id` | `signals.py` — `m2m_changed` sobre `Contacto.etiquetas` |
| `conversacion_iniciada` | `conversacion_id`, `contacto_id`, `contacto_nombre`, `numero`, `canal`, `sesion_id` | `signals.py` — `post_save` de `ConversacionWhatsApp` |
| `cita_creada` | `turno_id`, `contacto_id`, `servicio`, `recurso`, `inicio`, `origen`, `reagendado` | `signals.py` — `post_save` de `Turno` |
| `registro_creado` | `registro_id`, `objeto`, `objeto_slug`, `titulo`, `datos` | `signals.py` — `post_save` de `RegistroPersonalizado` |

**Por qué unos por señal y otros a mano.** Los cuatro de señal se originan en
varios sitios: cinco lugares distintos hacen `contacto.etiquetas.add(...)` y tres
construyen un `Turno`. Engancharlos uno por uno sería frágil — cualquier sitio
nuevo quedaría sin emitir y nadie lo notaría hasta que una automatización no
corriera. Los cuatro explícitos tienen un único origen y **contexto que la señal
no vería**: desde qué etapa venía la oportunidad, si el cierre fue manual o por
cron, con qué clasificación terminó la conversación.

Para emitir un evento nuevo desde un punto único basta con llamar a
`motor.disparar(evento, contexto)`; si el origen es múltiple, agregar un receptor
en `signals.py`.

Los valores de un objeto personalizado viajan planos en el contexto, así que una
condición puede leerlos con notación de punto: `datos.precio`, `datos.titulo`.

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
