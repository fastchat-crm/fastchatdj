# Agentes IA — guía de uso

Esta guía cubre cómo crear, configurar y mantener un agente IA en FastChat DJ
después de la simplificación del 2026-04. El objetivo es que cualquier
usuario nuevo pueda dejar un agente atendiendo WhatsApp en menos de 5 minutos
sin perderse entre 25 campos.

## Resumen de la nueva experiencia

| Antes | Ahora |
|---|---|
| Form con ~25 campos visibles | Form con 1 card + 1 textarea + 1 select |
| Configurar tono, estilo, nombre, personalidad y temperature a mano | 1 click en una card preset |
| 4 campos de "contexto" duplicados | 1 sólo (`contexto_estatico`, gestionado vía pestaña Conocimiento) |
| Sin punto de entrada guiado | Wizard de 3 pasos en `/crm/entrenamiento/wizard/` |

## Crear un agente nuevo (modo rápido)

1. Andá a **CRM → Crear Agente Rápido** (URL: `/crm/entrenamiento/wizard/`).
2. **Paso 1 — Personalidad.** Escribí un nombre interno (sólo lo ves vos) y
   elegí una de las 6 cards:

   | Preset | Para cuándo | Persona | Temperature |
   |---|---|---|---|
   | **Amable** | Default — sirve casi siempre. | Sofi, cálida y paciente. | 0.85 |
   | **Directo** | Clientes apurados, soporte de primera línea. | Mateo, al grano. | 0.65 |
   | **Formal** | Banca, legales, salud. | Asistente profesional, "usted". | 0.50 |
   | **Vendedor** | Ventas activas, captura de leads. | Camila, entusiasta y cierra. | 0.90 |
   | **Soporte técnico** | Resolución de problemas paso a paso. | Lucas, didáctico. | 0.55 |
   | **Personalizado** | Querés controlar cada campo a mano. | Vos. | tu valor |

3. **Paso 2 — Contexto del negocio.** Pegá lo esencial:
   - Productos y precios.
   - Horarios.
   - Zona de cobertura.
   - FAQ frecuentes.
   - Políticas (envíos, devoluciones, formas de pago).

   Tip: si tenés mucho material (PDFs grandes, hojas de Excel), no lo pegues
   acá — sumalo después en la pestaña **Conocimiento** del editor completo,
   que lo indexa con FAISS para búsqueda semántica.

4. **Paso 3 — API Key.** Elegí la API Key (Gemini, OpenAI o Claude). Si no
   tenés una, creala primero desde **Entrenamiento → API Keys** y volvé.

5. Click **Crear agente**. El sistema te lleva al editor completo donde
   podés afinar lo que quieras.

## Editar un agente existente

Andá a **CRM → Entrenamiento IA**, click en la card del agente, **Editar**.
El form tiene 7 pestañas:

### Tab Persona
- **Nombre del agente**: el que ves vos en el panel.
- **API Key**: con qué proveedor responde.
- **Personalidad del bot**: 6 cards (las mismas del wizard).
  - Click en una card → autocompleta `nombre_bot`, `personalidad`, `tono`,
    `estilo_escritura` y `temperature` con los valores del preset.
  - Click en **Personalizado** → se abren los 5 campos manuales para
    control total.

### Tab Conocimiento
3 tipos de fuentes (combinables):
- **Documentos / Archivos**: PDF, Excel, CSV. Se indexan en FAISS.
- **Enlace / API externa**: el agente la consulta en tiempo real
  (catálogos dinámicos, precios cambiantes).
- **Texto libre**: FAQ corta, menú, políticas. Se inyecta directo al
  prompt sin embeddings.

Si el texto total es chico (≤ 40 000 caracteres) se usa **modo estático**
(cero costo de embeddings por mensaje). Si supera ese límite, se construye
un índice FAISS automáticamente.

Toggle **Anotar listas en memoria**: actívalo si el agente gestiona
pedidos / carritos. Habilita el loop de tool-calling.

### Tab FAQs
Banco de preguntas frecuentes aprobadas. Las top-N (por prioridad) se
inyectan literal al prompt. Las demás quedan disponibles vía RAG.

### Tab Herramientas
Conexiones a APIs externas con esquema JSON. El LLM las puede invocar
function-calling (consultar pedido, validar email, buscar disponibilidad).

### Tab Cierre
Plantilla de cierre de conversación: detección automática de fin
(despedida, agradecimiento) + acción a ejecutar (notificar, asignar
asesor, etiquetar).

### Tab Asistente IA (Auditoría)
Historial de revisiones automáticas del agente. La IA evalúa el prompt
y propone mejoras. Vos aplicás con un click si te gusta la sugerencia.

### Tab Prompt — ★ Modo experto
El template Jinja-ish que efectivamente recibe el LLM. Variables
disponibles:

| Variable | Origen |
|---|---|
| `{question}` | Mensaje del usuario |
| `{context}` | Fragmentos RAG + FAQs |
| `{contexto_extra}` | Historial reciente |
| `{nombre_bot}` `{personalidad}` `{tono}` `{estilo_escritura}` | Persona |
| `{contacto_nombre}` `{hora_local}` `{primera_vez_hoy}` | Runtime |
| `{estado_animo}` `{guia_animo}` | Detector ánimo |
| `{historial_contacto}` | Resumen persistente del cliente |

Sólo tocá esto si tenés claro qué cambia. Si rompés `{question}` o
`{context}` el agente se rompe.

### Tab Avanzado
Parámetros finos del comportamiento. Defaults razonables. Sólo movelos
con un caso de uso claro:

| Campo | Qué controla |
|---|---|
| `cfg_faiss_k` | Cuántos fragmentos del entrenamiento se inyectan |
| `cfg_max_context_chars` | Tope de contexto del entrenamiento |
| `cfg_history_turns` | Cuántos turnos previos recuerda |
| `cfg_max_output_tokens` | Largo máximo de respuesta |
| `humaniz_chars_burbuja_ideal/max` | Tamaño de burbujas WhatsApp |
| `humaniz_lectura_cps` `humaniz_escritura_cps` | Velocidad de "tipeo" simulado |
| `humanizar_timing` | Toggle del envío en burbujas con delays |

## Cómo funciona la humanización por dentro

1. **Mensaje entra** vía webhook.
2. `agente_consultor.py` arma prompt con persona del preset + contexto
   recuperado por híbrido **FAISS + BM25**.
3. LLM responde con `temperature` del preset (0.50 formal → 0.90 vendedor).
4. La respuesta se divide en burbujas (`dividir_en_burbujas`) respetando
   párrafos y listas.
5. Para cada burbuja se calcula `(lectura, escritura)` con jitter ±20%
   (`calcular_delays`).
6. Se envía `presence_update: composing` + delay + mensaje. Resultado:
   se siente como un humano tipeando.

Detector de ánimo (`detectar_animo`): regex liviano sobre el último
mensaje del cliente. Detecta `frustracion / enojo / urgencia / duda /
agradecimiento / buen_humor / neutral` y agrega una guía al prompt
("empatizá primero", "respondé corto y directo", etc).

## Modificar los presets

Los presets viven en `core/constantes.py:PERSONALIDAD_PRESETS`. Para
agregar/editar:

```python
PERSONALIDAD_PRESETS['mi_preset'] = {
    'label': 'Mi preset',
    'descripcion_corta': 'Para qué sirve.',
    'icono': 'fa-icon',
    'color': '#hexcolor',
    'nombre_bot': 'Nombre',
    'personalidad': 'Cómo se comporta…',
    'tono': 'amigable',          # debe coincidir con TONO_CHOICES
    'estilo_escritura': 'Reglas de forma.',
    'temperature': '0.75',
}
```

No olvides regenerar las choices si las quemaste en migración:

```bash
python manage.py makemigrations crm
python manage.py migrate
```

## Modificar el prompt template global

`core/constantes.py:PROMPT_TEMPLATES['es']`. Tené en cuenta que cada
agente puede sobreescribirlo en la pestaña Prompt. Si querés cambiarlo
para todos los agentes nuevos, edita ahí. Para los viejos, hay que
borrarles el campo `prompt_template` o reasignarles el default.

## Frases rotativas

`core/constantes.py:FRASES_RELLENO` — diccionario con listas de
alternativas para confirmaciones / pensando / transición / cierre /
disculpa. El código elige al azar para que las respuestas no suenen
calcadas.

```python
FRASES_RELLENO = {
    'confirmacion':  ['dale', 'listo', 'perfecto', 'buenísimo', 'joya'],
    'pensando':      ['mm, dejame ver', 'a ver, un segundo', ...],
    ...
}
```

Si querés enchufarlas en código (ej: cuando el bot agradece), importalas
y usá `random.choice()`:

```python
import random
from core.constantes import FRASES_RELLENO
saludo = random.choice(FRASES_RELLENO['confirmacion'])
```

## Troubleshooting

### El bot suena robótico aún con preset "Amable"
- ¿La temperature efectiva es ≥ 0.75? Verificá en `Tab Avanzado`. Si una
  edición vieja la dejó en 0.30, subila o cambiá el preset y volvé a
  guardar (eso fuerza el reset).
- ¿`humanizar_timing` está activo? Si está OFF se manda en una sola
  burbuja sin delay → se nota artificial.

### El bot no responde lo del catálogo aunque está en el contexto
- Revisá Tab Conocimiento: que la fuente esté **activa** (status=True).
- Si el catálogo es muy grande, el FAISS puede no recuperar el chunk
  exacto. Subí `cfg_faiss_k` a 8-10 en Tab Avanzado.
- Si es pocas FAQs concretas, mejor usalas en Tab FAQs (inyección
  literal, no semántica).

### El bot inventa datos
- Bajá `temperature` a 0.50-0.65 (preset Formal o Soporte).
- Reforzá la regla de oro en el prompt: "Tu única fuente de datos duros
  es el texto entre ====. No inventes nada."
- Activar la auditoría IA en Tab Asistente IA — detecta alucinaciones.

### El campo descripción ya no aparece en el form
Es esperado — se eliminó porque el preset + el contexto ya cubren su
función. El backend lo autocompleta al guardar a partir del nombre.
Sigue existiendo en BD para no romper agentes viejos pero no es editable
desde la UI.

### "El módulo no está autorizado" al abrir el wizard
La URL `/crm/entrenamiento/wizard/` ya está registrada en `crm/urls.py`.
Si no aparece en el sidebar o tu rol no la ve, registrá la entrada en la
tabla `seguridad.Modulo` (o resincronizá `urls_sistema` con el comando
que use tu equipo).

## Ubicación de archivos

| Componente | Path |
|---|---|
| Modelo `AgentesIA` | `crm/models.py:179` |
| Presets y prompt | `core/constantes.py` |
| Form Django | `crm/forms.py:185` |
| Form HTML | `crm/templates/crm/entrenamiento/agente/form.html` |
| Wizard view | `crm/view_agente_wizard.py` |
| Wizard HTML | `crm/templates/crm/entrenamiento/agente/wizard.html` |
| CSS form | `static/stylenew/agentesia_form.css` |
| CSS wizard | `static/stylenew/agente_wizard.css` |
| Motor consultor | `agents_ai/agente_consultor.py` |
| Humanización (burbujas, delays, ánimo) | `agents_ai/humanizacion.py` |
| Memoria conversacional | `agents_ai/memoria_django.py` |

## Migraciones recientes

| Migration | Cambio |
|---|---|
| `0036_agentesia_personalidad_preset_and_more` | Agrega `personalidad_preset` y altera `prompt_template` |
| `0037_alter_agentesia_descripcion` | Hace `descripcion` nullable (deprecado en UI) |
