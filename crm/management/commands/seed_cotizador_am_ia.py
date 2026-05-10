"""
Seed del agente IA "Vida Buena Asesor" — capa conversacional sobre el
cotizador AM existente (NO duplica infraestructura).

Reusa lo que ya está construido:
  - El flujo determinístico `seed_cotizador_am` sigue siendo la fuente única
    de verdad para disparar el webhook oficial (función `cotizar_am`).
  - El cotizador web público https://fguerrero.mgaseguros.ec/cotizar/ es la
    salida self-service.
  - El endpoint público de lookup `?action=cliente&cedula=` se usa con tool.

Lo que aporta la IA:
  1. Educa al cliente sobre los 4 planes (PROTECCIÓN, ÚNICO, PREDILECTO,
     MAGNO) con contexto estático compactado del xlsx.
  2. Pregunta perfil (edad, presupuesto, dependientes, red preferida) y
     recomienda 1-2 planes con justificación clara.
  3. Cuando el cliente quiere cotizar, deriva al cotizador web (link) o
     al asesor humano (handoff vía link de form). NO ejecuta el webhook
     directamente — esa responsabilidad sigue en el flujo determinístico
     o en el asesor humano.

Tools:
  - `lookup_cliente`  GET ?action=cliente&cedula=  (pre-fill datos)

Conocimiento (compactado del xlsx en CONTEXTO_PLANES):
    docs/PLANES INDIVIDUALES VIDA SANA 2026.xlsx

Pre-requisitos:
  - 1 ApiKeyIA configurada (--apikey N)

Uso:
    python manage.py seed_cotizador_am_ia
    python manage.py seed_cotizador_am_ia --reset
    python manage.py seed_cotizador_am_ia --apikey 1
    python manage.py seed_cotizador_am_ia --apikey 1 --sesion 5
    python manage.py seed_cotizador_am_ia --base-am https://otra.dominio.ec/cotimedica-api/v1
    python manage.py seed_cotizador_am_ia --delete
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crm.models import AgentesIA, ApiKeyIA, DetalleAgentesAI, HerramientaAgente, PerfilNegocioIA
from whatsapp.models import SesionWhatsApp

User = get_user_model()


NOMBRE_AGENTE = 'Vida Buena Asesor IA'

BASE_AM_DEFAULT = 'https://fguerrero.mgaseguros.ec/cotimedica-api/v1/'
COTIZADOR_WEB_URL = 'https://fguerrero.mgaseguros.ec/cotizar/'
FORMULARIO_ASESOR_URL = 'https://admisiones.ister.edu.ec/?action=ver&id=ASESOR_VIDA_BUENA'
FASTCHAT_URL_DEFAULT = 'https://fastchat.local'


CONTEXTO_PLANES = """
INFORMACIÓN DE PLANES VIDA BUENA (Vida Sana 2026 — para Ecuador)

Hay 4 planes individuales de asistencia médica. Todos cubren territorio
nacional, período de presentación de reclamos 60 días, y todos incluyen:
- Servicios exequiales (titular): 100% Jardines del Valle
- Telemedicina incluida
- Plan dental básico incluido
- Seguro por muerte accidental (titular): $10.000

──────────────────────────────────────────────────────────────────
🟢 PROTECCIÓN 10.000 — Nivel N-4, modalidad MIXTA, anual, SIN deducible
   ➜ Plan de entrada económico, modalidad mixta (red abierta + cerrada).

   Cobertura ambulatoria: 80% red cerrada con copago/convenio · 70% red
   abierta o cerrada sin copago. Consultas red abierta reembolso $25.
   Habitación hospitalaria: $50/día sin límite de días.
   Maternidad: $1.200 · Ambulancia terrestre: 80% hasta $55.
   Enfermedades catastróficas: $5.000.
   Cirugía plástica reconstructiva: $800 · Tratamientos dentales por
   accidente: $300.

🟡 ÚNICO 10.000 — Nivel N-2, modalidad CERRADA, por incapacidad, SIN deducible
   ➜ Plan económico de RED CERRADA pura. NO cubre red abierta.
   Pensado para quien aceptaría atenderse SOLO en clínicas convenio.

   Cobertura ambulatoria: 80% red cerrada · NO aplica red abierta.
   Medicamentos ambulatorios: 70% red cerrada solamente.
   Habitación hospitalaria: $50/día · Maternidad: $1.200.
   NO incluye ambulancia terrestre.
   Enfermedades catastróficas: $10.000.
   Único plan que incluye Prótesis no dentales / aparatos ortopédicos: $250.

🔵 PREDILECTO 20.000 — Nivel N-3, modalidad MIXTA, anual, SIN deducible
   ➜ Plan intermedio, mejor balance precio/cobertura. Mismo enfoque mixto
   que PROTECCIÓN pero con tope $20.000 y mejores honorarios.

   Cobertura ambulatoria: 80% red cerrada · 70% red abierta.
   Consultas red abierta reembolso $50.
   Habitación hospitalaria: $100/día sin límite.
   Maternidad: $1.800 · Ambulancia terrestre: 80% hasta $100.
   Enfermedades catastróficas: $10.000.
   Cirugía plástica reconstructiva: $1.000.

🟣 MAGNO 30.000 — Nivel N-1, modalidad MIXTA, por incapacidad, $80 deducible
   ➜ Plan PREMIUM. Mayor cobertura. Único con ambulancia aérea/fluvial.

   Cobertura ambulatoria: 80% red cerrada · 70% red abierta.
   Consultas red abierta reembolso $65.
   Medicamentos: 80% dentro de red, 60% fuera.
   Habitación hospitalaria: $200/día sin límite.
   Acompañantes en hospitalización (recién nacidos, <16 y >75): $100/día.
   Maternidad: $2.500 · Ambulancia terrestre: $100 + AÉREA/FLUVIAL: $2.500.
   Enfermedades catastróficas: $30.000.
   Único plan con: Audífonos $50/año, Cristales ópticos $50, Prótesis
   no dentales $500. Cirugía plástica reconstructiva: $1.000.

──────────────────────────────────────────────────────────────────
COBERTURAS COMUNES IMPORTANTES (todos los planes)

- Maternidad SIN aplicación de deducible (parto normal, cesárea, aborto
  no provocado, complicaciones).
- Recién nacido: cubierto hasta el monto del plan si la inclusión
  intraútero fue antes de la semana 12; sino hasta $800.
- Tarifa 0 (MSP) incluida.
- Atención médica en el hogar: $10-$15 según distancia.
- Terapias (física, respiratoria, lenguaje, cardiaca): 15-20 sesiones
  por año por usuario, $15-$25 por sesión según plan.
- Consultas con homeópatas / acupunturistas / quiroprácticos / medicina
  alternativa: 6 consultas con tope $25 c/u (excepto ÚNICO que aplica al
  80% sin tope monetario).
- Métodos anticonceptivos: $80 (PROTECCIÓN/ÚNICO) o $100 (PREDILECTO/MAGNO).

──────────────────────────────────────────────────────────────────
CARENCIAS (mismas para todos los planes salvo donde se indica)

- Cobertura ambulatoria: 30 días
- Medicamentos ambulatorios: 30 días
- Cobertura prehospitalaria: 90 días
- Cobertura hospitalaria: 90 días
- Maternidad (parto normal/cesárea/aborto): 60 días
- Tarifa 0: 30 días
- Recién nacido: 30 días ambulatorio / 90 días hospitalario
- Preexistencias declaradas: 90 días ambulatorio / 12-24 meses hospitalario
  (MAGNO: 180 días ambulatorio / 12-24 meses)
- Emergencias y tratamientos dentales por accidente: 24 horas

──────────────────────────────────────────────────────────────────
TARIFARIO RESUMIDO 2026 (mensual aprox · masculino básico, USD)

Edad        | PROTECCIÓN | ÚNICO  | PREDILECTO | MAGNO
20-25 años  | $32        | $23    | $44        | $49
30-35 años  | $35        | $26    | $51        | $58
40-45 años  | $48        | $37    | $63        | $73
50-55 años  | $69        | $56    | $98        | $112
60-65 años  | $96        | $84    | $148       | $165
70+ años    | $149       | $120   | $230       | $251

Femenino: similar en mayoría de tramos. En PROTECCIÓN hay un leve
incremento desde 20 años; en PREDILECTO desde 15 años. Plan dental "PLUS"
suma ~$2.50 sobre el plan base. Para tarifa exacta por edad y sexo, usar
la herramienta de cotización oficial.

──────────────────────────────────────────────────────────────────
COBERTURA DENTAL BÁSICA (incluida en todos los planes)
Examen, profilaxis y fluorización: SIN COPAGO.
Restauración simple $10 · compuesta $12 · compleja $15.
Extracción simple $16 · molares erupcionados $36.
Brackets metálicos $700 · blanqueamiento dos arcadas $140.

COBERTURA DENTAL PLUS (opcional, suma a la prima)
Incluye: rayos X periapicales $6, urgencias odontológicas $15, biopsias
$60, cirugías de tejido blando $81, apicectomía $81, entre otras.
""".strip()


GUIA_RECOMENDACION = """
GUÍA INTERNA PARA RECOMENDAR EL PLAN

Cuando recolectes el perfil del cliente, usa este árbol de decisión:

1. ¿Cuál es su prioridad principal?
   ➜ "Pagar lo menos posible" + acepta atenderse solo en clínicas convenio:
       → ÚNICO 10.000 (red cerrada pura, sin reembolso fuera de red).
   ➜ "Pagar poco pero quiero libertad de ir a cualquier clínica":
       → PROTECCIÓN 10.000 (mixto con menor monto contratado).
   ➜ "Quiero balance precio/protección":
       → PREDILECTO 20.000.
   ➜ "Máxima protección, no me importa el precio":
       → MAGNO 30.000.

2. Casos específicos que inclinan a MAGNO:
   - Cliente >60 años o con preexistencias declaradas relevantes.
   - Necesita cobertura de cristales ópticos o audífonos.
   - Vive en zona remota (única ambulancia aérea/fluvial).
   - Requiere prótesis no dentales / aparatos ortopédicos.

3. Casos específicos que inclinan a PREDILECTO:
   - Familia con hijos pequeños (mejor maternidad $1.800 vs $1.200).
   - Suele atenderse en red abierta y necesita reembolsos de consulta
     mayores a $50.
   - Necesita habitación hospitalaria privada (cubre $100/día).

4. Casos donde ÚNICO es la mejor opción:
   - Cliente joven y sano que solo quiere cobertura por accidentes
     graves o emergencias.
   - Acepta clínicas convenio (que son varias en cada provincia).
   - Quiere el menor pago mensual posible con cobertura formal.

5. Cuándo NO insistir en cotizar:
   - Cliente muestra dudas serias o pregunta cosas fuera del alcance
     (planes corporativos, financiamiento) → handoff a asesor humano.
   - Cliente no quiere dar datos personales todavía → mostrar planes
     en abstracto, dejar abierto el canal.

REGLAS DE COTIZACIÓN:
- Antes de llamar cotizar_vida_buena, CONFIRMA con el cliente:
  "Voy a cotizarte el plan {{X}}. ¿Está bien que envíe la solicitud?"
- Si el cliente quiere comparar 2 planes, ofrece llamarlos UNO POR UNO
  (la herramienta cotiza el plan elegido por el cliente, no devuelve
  comparativa automática).
- Si el cliente no tiene fecha exacta de nacimiento, pedile la edad.
  La fecha exacta puede quedar vacía y el webhook usará la edad.
""".strip()


CHUNKS_CONOCIMIENTO = [
    (
        "Plan PROTECCIÓN 10.000 (entrada económica, mixto)",
        "PROTECCIÓN 10.000 — Nivel N-4, modalidad MIXTA, anual, SIN deducible.\n"
        "Plan de entrada económico, modalidad mixta (red abierta + cerrada).\n\n"
        "Cobertura ambulatoria: 80% red cerrada con copago/convenio · 70% red\n"
        "abierta o cerrada sin copago. Consultas red abierta reembolso $25.\n"
        "Habitación hospitalaria: $50/día sin límite de días.\n"
        "Maternidad: $1.200 · Ambulancia terrestre: 80% hasta $55.\n"
        "Enfermedades catastróficas: $5.000.\n"
        "Cirugía plástica reconstructiva: $800 · Tratamientos dentales por\n"
        "accidente: $300.\n"
        "Carencias: ambulatoria 30 días · hospitalaria 90 días · maternidad 60 días."
    ),
    (
        "Plan ÚNICO 10.000 (más económico, red cerrada pura)",
        "ÚNICO 10.000 — Nivel N-2, modalidad CERRADA, por incapacidad, SIN deducible.\n"
        "Plan económico de RED CERRADA pura. NO cubre red abierta. Pensado para\n"
        "quien aceptaría atenderse SOLO en clínicas convenio.\n\n"
        "Cobertura ambulatoria: 80% red cerrada · NO aplica red abierta.\n"
        "Medicamentos ambulatorios: 70% red cerrada solamente.\n"
        "Habitación hospitalaria: $50/día · Maternidad: $1.200.\n"
        "NO incluye ambulancia terrestre.\n"
        "Enfermedades catastróficas: $10.000.\n"
        "Único plan que incluye Prótesis no dentales / aparatos ortopédicos: $250."
    ),
    (
        "Plan PREDILECTO 20.000 (intermedio, balance precio/cobertura)",
        "PREDILECTO 20.000 — Nivel N-3, modalidad MIXTA, anual, SIN deducible.\n"
        "Plan intermedio, mejor balance precio/cobertura. Mismo enfoque mixto que\n"
        "PROTECCIÓN pero con tope $20.000 y mejores honorarios.\n\n"
        "Cobertura ambulatoria: 80% red cerrada · 70% red abierta.\n"
        "Consultas red abierta reembolso $50.\n"
        "Habitación hospitalaria: $100/día sin límite.\n"
        "Maternidad: $1.800 · Ambulancia terrestre: 80% hasta $100.\n"
        "Enfermedades catastróficas: $10.000.\n"
        "Cirugía plástica reconstructiva: $1.000."
    ),
    (
        "Plan MAGNO 30.000 (premium, máxima cobertura)",
        "MAGNO 30.000 — Nivel N-1, modalidad MIXTA, por incapacidad, $80 deducible.\n"
        "Plan PREMIUM. Mayor cobertura. Único con ambulancia aérea/fluvial.\n\n"
        "Cobertura ambulatoria: 80% red cerrada · 70% red abierta.\n"
        "Consultas red abierta reembolso $65.\n"
        "Medicamentos: 80% dentro de red, 60% fuera.\n"
        "Habitación hospitalaria: $200/día sin límite.\n"
        "Acompañantes en hospitalización (recién nacidos, <16 y >75): $100/día.\n"
        "Maternidad: $2.500 · Ambulancia terrestre: $100 + AÉREA/FLUVIAL: $2.500.\n"
        "Enfermedades catastróficas: $30.000.\n"
        "Único plan con: Audífonos $50/año, Cristales ópticos $50, Prótesis no\n"
        "dentales $500. Cirugía plástica reconstructiva: $1.000."
    ),
    (
        "Coberturas comunes a los 4 planes",
        "Todos los planes incluyen:\n"
        "- Servicios exequiales (titular): 100% Jardines del Valle\n"
        "- Telemedicina incluida\n"
        "- Plan dental básico incluido\n"
        "- Seguro por muerte accidental (titular): $10.000\n"
        "- Maternidad SIN aplicación de deducible (parto normal, cesárea, aborto\n"
        "  no provocado, complicaciones).\n"
        "- Recién nacido: cubierto hasta el monto del plan si la inclusión\n"
        "  intraútero fue antes de la semana 12; sino hasta $800.\n"
        "- Tarifa 0 (MSP) incluida.\n"
        "- Atención médica en el hogar: $10-$15 según distancia.\n"
        "- Terapias (física, respiratoria, lenguaje, cardiaca): 15-20 sesiones\n"
        "  por año por usuario, $15-$25 por sesión según plan.\n"
        "- Consultas con homeópatas/acupunturistas/quiroprácticos/medicina\n"
        "  alternativa: 6 consultas con tope $25 c/u (ÚNICO aplica al 80% sin tope).\n"
        "- Métodos anticonceptivos: $80 (PROTECCIÓN/ÚNICO) o $100 (PREDILECTO/MAGNO).\n\n"
        "Cobertura territorio nacional. Período de presentación de reclamos: 60 días."
    ),
    (
        "Carencias por tipo de cobertura",
        "Carencias (mismas para todos salvo donde se indica):\n"
        "- Cobertura ambulatoria: 30 días\n"
        "- Medicamentos ambulatorios: 30 días\n"
        "- Cobertura prehospitalaria: 90 días\n"
        "- Cobertura hospitalaria: 90 días\n"
        "- Maternidad (parto normal/cesárea/aborto): 60 días\n"
        "- Tarifa 0: 30 días\n"
        "- Recién nacido: 30 días ambulatorio / 90 días hospitalario\n"
        "- Preexistencias declaradas: 90 días ambulatorio / 12-24 meses hospitalario\n"
        "  (MAGNO: 180 días ambulatorio / 12-24 meses)\n"
        "- Emergencias y tratamientos dentales por accidente: 24 horas"
    ),
    (
        "Tarifario resumido por edad (USD mensual aprox · masculino básico)",
        "Tarifario aproximado 2026:\n\n"
        "Edad        | PROTECCIÓN | ÚNICO  | PREDILECTO | MAGNO\n"
        "20-25 años  | $32        | $23    | $44        | $49\n"
        "30-35 años  | $35        | $26    | $51        | $58\n"
        "40-45 años  | $48        | $37    | $63        | $73\n"
        "50-55 años  | $69        | $56    | $98        | $112\n"
        "60-65 años  | $96        | $84    | $148       | $165\n"
        "70+ años    | $149       | $120   | $230       | $251\n\n"
        "Femenino: similar en mayoría de tramos. PROTECCIÓN tiene leve incremento\n"
        "desde 20 años; PREDILECTO desde 15 años. Plan dental PLUS suma ~$2.50\n"
        "sobre el plan base. Para tarifa exacta por edad y sexo, usar el cotizador\n"
        "oficial."
    ),
    (
        "Cobertura dental básica (incluida) y plus (opcional)",
        "DENTAL BÁSICA (incluida en todos los planes):\n"
        "- Examen, profilaxis y fluorización: SIN COPAGO.\n"
        "- Restauración simple $10 · compuesta $12 · compleja $15.\n"
        "- Extracción simple $16 · molares erupcionados $36.\n"
        "- Brackets metálicos $700 · blanqueamiento dos arcadas $140.\n\n"
        "DENTAL PLUS (opcional, suma a la prima):\n"
        "Incluye: rayos X periapicales $6, urgencias odontológicas $15, biopsias\n"
        "$60, cirugías de tejido blando $81, apicectomía $81, entre otras."
    ),
    (
        "Guía interna de recomendación de plan",
        "ÁRBOL DE DECISIÓN para recomendar plan según perfil del cliente:\n\n"
        "1. ¿Cuál es su prioridad principal?\n"
        "   - 'Pagar lo menos posible' + acepta clínicas convenio → ÚNICO 10.000\n"
        "   - 'Pagar poco con libertad de clínica' → PROTECCIÓN 10.000\n"
        "   - 'Balance precio/protección' → PREDILECTO 20.000\n"
        "   - 'Máxima protección, no importa precio' → MAGNO 30.000\n\n"
        "2. Casos que inclinan a MAGNO:\n"
        "   - Cliente >60 años o con preexistencias declaradas.\n"
        "   - Necesita cobertura de cristales ópticos o audífonos.\n"
        "   - Vive en zona remota (única ambulancia aérea/fluvial).\n"
        "   - Requiere prótesis no dentales / aparatos ortopédicos.\n\n"
        "3. Casos que inclinan a PREDILECTO:\n"
        "   - Familia con hijos pequeños (mejor maternidad $1.800).\n"
        "   - Suele atenderse en red abierta.\n"
        "   - Necesita habitación hospitalaria privada ($100/día).\n\n"
        "4. ÚNICO es ideal para:\n"
        "   - Cliente joven y sano que solo quiere cobertura por accidentes graves.\n"
        "   - Acepta clínicas convenio.\n"
        "   - Quiere pago mensual mínimo.\n\n"
        "5. NO insistir en cotizar si:\n"
        "   - Cliente pregunta sobre planes corporativos o financiamiento.\n"
        "   - Cliente muestra dudas o no quiere dar datos personales aún."
    ),
]


PROMPT_TEMPLATE = """
Eres {nombre_bot}, asesora virtual de Vida Buena (asistencia médica).
Tu trabajo: en el MENOR número de mensajes posible, conseguir la cédula del
cliente, hacer lookup automático para obtener edad y género, recomendar el
plan ideal con su tarifa estimada (porque las tarifas dependen de edad y
género), y derivarlo al cotizador o al asesor para cerrar.

NO sos un chatbot de preguntas. NO hagas cuestionarios largos. NO pidas
preferencias si todavía no tenés la cédula. La cédula desbloquea TODO.

CONTEXTO TEMPORAL:
- Es primer mensaje de la conversación: {es_primer_mensaje}
- Estamos fuera de horario laboral: {fuera_horario}
- Horario de atención humana: {horario_atencion}
- Contacto: {contacto_nombre} · momento: {hora_local}

CANALES DE CIERRE:
- Cotizador web self-service: https://fguerrero.mgaseguros.ec/cotizar/
- Hablar con asesor humano: https://admisiones.ister.edu.ec/?action=ver&id=ASESOR_VIDA_BUENA

REGLA DE ORO — LA CÉDULA ES OBLIGATORIA PARA COTIZAR:
La tarifa depende de EDAD + GÉNERO. Sin esos dos datos no podés recomendar
plan ni dar tarifa. La cédula te da AMBOS automáticamente vía lookup_cliente.
Por eso TODA conversación que vaya hacia cotización debe pasar por la cédula.

DETECTAR INTENT DE COTIZAR — palabras clave del cliente:
"cotizar", "cotizame", "cotización", "precio", "tarifa", "cuánto cuesta",
"cuánto sale", "quiero contratar", "comprar", "afiliarme", "cuánto pago",
"qué plan me sirve", "recomendame", "cuál me conviene", "armame algo".
Cuando detectás CUALQUIERA de estos, el siguiente paso es PEDIR LA CÉDULA
(si todavía no la tenés). No respondas con tarifas inventadas.

FLUJO IDEAL:

PASO 1 — Primer mensaje (si es_primer_mensaje=true):
   Saludá corto, explicá qué hacés, pedí la cédula directo.
   "¡Hola {contacto_nombre}! 👋 Soy {nombre_bot}, te ayudo a encontrar el
   plan de asistencia médica ideal para vos. Para darte la recomendación
   precisa con tarifa estimada necesito tu *cédula* (10 dígitos) — con
   eso busco tus datos automáticamente. ¿Me la pasás?"
   NO listes los 4 planes en este momento. NO preguntés nada más.

PASO 2 — Cliente expresa intent de cotizar (en CUALQUIER turno):
   Si todavía NO tenés la cédula del cliente:
   "¡Perfecto! Para cotizarte el plan ideal con tarifa estimada necesito
   tu *cédula* (10 dígitos). Con eso busco tu edad y género y te
   recomiendo el plan que mejor encaja. ¿Me la pasás?"
   No procedas sin cédula (o sin edad+género manuales si la rechaza).

PASO 3 — Cliente da cédula:
   Llamá la herramienta `lookup_cliente` (con action='cliente' y la cédula).
   No pidas permiso explícito — el cliente ya te la dio, eso es permiso.

PASO 4 — Lookup respondió OK (con nombre, edad, sexo):
   Confirmá los datos y RECOMIENDA un plan basado en EDAD + GÉNERO + perfil
   por defecto. Mostrá tarifa aproximada del tarifario.
   Ejemplo:
   "Hola {contacto_nombre}! Veo que tenés 35 años y sos M. Por tu perfil
   te recomiendo *PREDILECTO 20.000* (~$51/mes para tu edad/género):
   ✅ Cobertura mixta — atendete en cualquier clínica
   ✅ Habitación hospitalaria $100/día sin límite
   ✅ Maternidad $1.800 (ideal si planeás familia)
   ✅ Tope anual $20.000 + enfermedades catastróficas $10.000
   ¿Querés cotizar este plan oficial o querés ver alternativas?"

   Para elegir el plan default usá el árbol:
   - Joven sano (<35) sin hijos planeados → PROTECCIÓN o ÚNICO si quiere
     pagar menos.
   - Familia / pensando en hijos → PREDILECTO.
   - Mayor (>55) o con preexistencias → MAGNO.
   - Si no tenés señales especiales → PREDILECTO (default seguro).

PASO 5 — Si el cliente pregunta por otros planes, comparalos brevemente
   (1 línea por plan) y mencioná tarifa aproximada según edad/género del
   cliente. Usá el tarifario del conocimiento.

PASO 6 — Cierre (cliente acepta cotizar):
   Confirmá el plan elegido y LLAMÁ LA HERRAMIENTA `cotizar_vida_buena`
   con todos los datos que tengas. Parámetros mínimos:
   - edad_titular (OBLIGATORIO)
   - budget_intent ("equilibrio" si no estás seguro)
   - plan_preferido (el plan que recomendaste, ej: "PREDILECTO_20000")
   - cedula, nombres, apellidos, sexo, email, edades_dependientes (si los tenés)

   La herramienta dispara el webhook OFICIAL — el cliente recibe en minutos
   por WhatsApp y email la recomendación con tarifa exacta y planes
   alternativos. NO compartas el link del cotizador web a menos que la
   herramienta falle (status="error"). Si falla, ahí sí ofrecé el link
   web o el asesor humano.

EXCEPCIONES:

- Si el cliente NO quiere dar cédula → ofrecé alternativa mínima:
  "Sin problema. Para recomendarte el plan necesito al menos tu *edad* y
  si sos *M o F*. ¿Me los pasás?"
  Si tampoco quiere → mostrá los 4 planes de forma compacta y derivá al
  cotizador web sin recomendación específica.

- Si lookup_cliente devuelve "no encontrado" → pedí edad y sexo manualmente:
  "No encontré tu cédula en nuestra base. ¿Me decís tu edad y si sos M o F?
  Con eso te recomiendo igual."

- Si el cliente pide mucho detalle de un plan → respondé con info del
  conocimiento (cobertura, carencias, tarifas), pero después volvé al
  flujo: "¿Querés cotizar este plan ahora o te muestro alternativas?"

- AVISO DE HORARIO — REGLA ESTRICTA:
  Si fuera_horario=true Y es_primer_mensaje=true → SOLO en esa primera
  respuesta agregás una línea corta tipo:
  "🌙 Estamos fuera de horario, pero te ayudo igual."
  En CUALQUIER otro mensaje (es_primer_mensaje=false), NUNCA menciones
  el horario, NUNCA listes los días/horas. El cliente ya sabe.

REGLAS DURAS:
- NUNCA inventes tarifas exactas — usá rangos del tarifario y aclará
  "tarifa aproximada, la oficial te llega en el cotizador".
- NUNCA pidas más de UN dato por mensaje (cédula sola, después edad sola
  si hace falta, etc).
- NUNCA des un link al cotizador SIN antes haber recomendado un plan
  específico (el cliente debe ir al cotizador sabiendo qué seleccionar).
- NO listes los 4 planes salvo que el cliente lo pida explícitamente.
- NO respondas con cosas genéricas tipo "Buenas, ¿cómo te ayudo?". Tu
  primer mensaje SIEMPRE debe presentarte + pedir cédula como dice PASO 1.
- Tu personalidad: {tono}. {personalidad}

HISTORIAL RECIENTE:
{contexto_extra}

INFORMACIÓN DE PLANES Y GUÍA DE RECOMENDACIÓN (úsala como única fuente de verdad):
====
{context}
====

PREGUNTA DEL CLIENTE: {question}

Tu respuesta:
""".strip()


HERRAMIENTAS = [
    {
        'nombre': 'cotizar_vida_buena',
        'nombre_amigable': 'Cotizar plan oficial (dispara webhook + email)',
        'descripcion': (
            'Envía la cotización oficial al motor de Vida Buena. El cliente '
            'recibe en minutos por WhatsApp y email la recomendación con tarifa '
            'exacta y los planes alternativos. Llamala SOLO cuando el cliente '
            'haya elegido un plan y confirme que quiere cotizar oficialmente. '
            'Pedile confirmación antes ("¿lanzo la cotización del plan X?").'
        ),
        'metodo': 'POST',
        'es_interno': True,
        'parametros': [
            {'nombre': 'cedula', 'tipo': 'string', 'requerido': False,
             'descripcion': 'Cédula del titular (10 dígitos), opcional pero recomendada.',
             'pregunta_sugerida': ''},
            {'nombre': 'nombres', 'tipo': 'string', 'requerido': False,
             'descripcion': 'Nombres del titular.',
             'pregunta_sugerida': ''},
            {'nombre': 'apellidos', 'tipo': 'string', 'requerido': False,
             'descripcion': 'Apellidos del titular.',
             'pregunta_sugerida': ''},
            {'nombre': 'fecha_nacimiento', 'tipo': 'string', 'requerido': False,
             'descripcion': 'Fecha de nacimiento YYYY-MM-DD. Opcional si pasás edad_titular.',
             'pregunta_sugerida': ''},
            {'nombre': 'sexo', 'tipo': 'string', 'requerido': False,
             'descripcion': 'M o F.',
             'pregunta_sugerida': ''},
            {'nombre': 'email', 'tipo': 'string', 'requerido': False,
             'descripcion': 'Email del titular para recibir el PDF y la recomendación.',
             'pregunta_sugerida': '¿A qué email te mando los detalles?'},
            {'nombre': 'edad_titular', 'tipo': 'integer', 'requerido': True,
             'descripcion': 'Edad del titular en años. OBLIGATORIO.',
             'pregunta_sugerida': ''},
            {'nombre': 'edades_dependientes', 'tipo': 'string', 'requerido': False,
             'descripcion': 'Edades de los demás miembros del grupo separadas por coma. Vacío si solo titular. Ej: "5,12,40".',
             'pregunta_sugerida': ''},
            {'nombre': 'budget_intent', 'tipo': 'string', 'requerido': True,
             'descripcion': 'Intención de presupuesto: "economico", "equilibrio" o "alta_proteccion".',
             'pregunta_sugerida': ''},
            {'nombre': 'plan_preferido', 'tipo': 'string', 'requerido': False,
             'descripcion': 'Si el cliente eligió un plan específico, pasarlo: "PROTECCION_10000", "UNICO_10000", "PREDILECTO_20000" o "MAGNO_30000".',
             'pregunta_sugerida': ''},
        ],
        'plantilla_respuesta': (
            '{% if status == "ok" %}'
            '✅ {{message}}'
            '{% else %}'
            '⚠️ No pudimos procesar la cotización: {{message}}'
            '{% endif %}'
        ),
        'ubicacion_params': 'json',
    },
    {
        'nombre': 'lookup_cliente',
        'nombre_amigable': 'Pre-llenar datos del cliente con su cédula',
        'descripcion': (
            'Busca al cliente en el registro civil por número de cédula y '
            'devuelve nombres, apellidos, fecha de nacimiento, edad y sexo. '
            'Úsala cuando el cliente te dé su cédula y querés evitar pedirle '
            'todos los datos uno por uno (especialmente la edad, clave para '
            'recomendar el plan correcto). Pide PERMISO antes de llamarla.'
        ),
        'metodo': 'GET',
        'parametros': [
            {'nombre': 'cedula', 'tipo': 'string', 'requerido': True,
             'descripcion': 'Cédula ecuatoriana de 10 dígitos del cliente.',
             'pregunta_sugerida': '¿Me das tu número de cédula?'},
            {'nombre': 'action', 'tipo': 'string', 'requerido': True,
             'descripcion': 'Siempre el valor literal "cliente". El LLM debe pasarlo así.',
             'pregunta_sugerida': ''},
        ],
        'plantilla_respuesta': (
            '{% if data.encontrado %}'
            '✅ Cliente encontrado:\n'
            '• Nombre: {{data.nombres}} {{data.apellidos}}\n'
            '• Edad: {{data.edad}} años\n'
            '• Sexo: {{data.sexo}}\n'
            '• Email: {{data.email|default:"(no registrado)"}}\n'
            '• Teléfono: {{data.telefono|default:"(no registrado)"}}'
            '{% else %}'
            '⚠️ No encontré ese registro. Pedile los datos manualmente al cliente.'
            '{% endif %}'
        ),
        'ubicacion_params': 'query',
    },
]


class Command(BaseCommand):
    help = 'Crea/actualiza el agente IA "Vida Buena Asesor" con tools para lookup + cotización oficial.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Borra el agente previo y sus herramientas y recrea todo.')
        parser.add_argument('--delete', action='store_true',
                            help='Solo borra el agente y sale (no recrea).')
        parser.add_argument('--apikey', type=int, default=None,
                            help='ID de ApiKeyIA a vincular (opcional — si no, asignala desde la UI).')
        parser.add_argument('--usuario', type=int, default=1,
                            help='ID del Usuario dueño del agente (default: 1).')
        parser.add_argument('--sesion', type=int, default=None,
                            help='ID de SesionWhatsApp para asignar el agente como modo_bot=ia.')
        parser.add_argument('--base-am', type=str, default=BASE_AM_DEFAULT,
                            help=f'Base URL del cotizador AM REST para el lookup (default: {BASE_AM_DEFAULT}).')
        parser.add_argument('--fastchat-url', type=str, default=FASTCHAT_URL_DEFAULT,
                            help=(f'URL pública de fastchat para el endpoint puente '
                                  f'(default: {FASTCHAT_URL_DEFAULT}). El SSRF guard '
                                  f'bloquea localhost — usá la URL pública real.'))

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts['delete']:
            self._eliminar()
            return

        if opts['reset']:
            self._eliminar()

        agente = AgentesIA.objects.filter(nombre=NOMBRE_AGENTE).first()
        creando = agente is None

        if creando:
            usuario = self._resolver_usuario(opts['usuario'])
            perfil, _ = PerfilNegocioIA.objects.get_or_create(usuario=usuario)
            self.stdout.write(self.style.HTTP_INFO(
                f'Usuario dueño: {usuario.username} (id={usuario.id}) · perfil={perfil.id}'
            ))

            apikey = None
            if opts['apikey']:
                try:
                    apikey = ApiKeyIA.objects.get(id=opts['apikey'], status=True)
                except ApiKeyIA.DoesNotExist:
                    raise CommandError(f'No existe ApiKeyIA activa con id={opts["apikey"]}')

            agente = self._crear_agente(perfil, apikey)
            self.stdout.write(self.style.SUCCESS(f'Agente creado: {agente.nombre} (id={agente.id})'))
            if apikey is None:
                self.stdout.write(self.style.WARNING(
                    'Sin --apikey: el agente quedó SIN ApiKeyIA. '
                    'Asignala manualmente desde /crm/entrenamiento/.'
                ))
        else:
            self.stdout.write(self.style.WARNING(f'Agente ya existe (id={agente.id}) — actualizando.'))
            self._actualizar_agente(agente)

        base_am = opts['base_am'].rstrip('/') + '/'
        fastchat_url = opts['fastchat_url'].rstrip('/')
        creadas, actualizadas = self._sembrar_herramientas(agente, base_am, fastchat_url)
        self.stdout.write(self.style.SUCCESS(
            f'Herramientas: {creadas} creadas, {actualizadas} actualizadas.'
        ))

        n_detalles = self._sembrar_detalles(agente)
        self.stdout.write(self.style.SUCCESS(
            f'Conocimiento: {n_detalles} bloques de texto cargados en el agente '
            '(visibles en /crm/entrenamiento/ → tab Conocimiento).'
        ))

        if opts['sesion']:
            self._vincular_sesion(agente, opts['sesion'])

        self._resumen(agente)

    def _resolver_usuario(self, usuario_id):
        try:
            return User.objects.get(id=usuario_id)
        except User.DoesNotExist:
            raise CommandError(f'No existe Usuario con id={usuario_id}')

    def _eliminar(self):
        agente = AgentesIA.objects.filter(nombre=NOMBRE_AGENTE).first()
        if not agente:
            self.stdout.write(self.style.WARNING(f'No existe agente "{NOMBRE_AGENTE}", nada para borrar.'))
            return
        SesionWhatsApp.objects.filter(agente_ia=agente).update(agente_ia=None, modo_bot='ninguno')
        agente.herramientas.all().delete()
        agente.detalleagentesai_set.all().delete()
        agente.delete()
        self.stdout.write(self.style.SUCCESS(f'Agente "{NOMBRE_AGENTE}" + herramientas + conocimiento eliminados.'))

    def _crear_agente(self, perfil, apikey=None):
        agente = AgentesIA.objects.create(
            perfil=perfil,
            nombre=NOMBRE_AGENTE,
            descripcion=(
                'Asesor virtual conversacional de planes de asistencia médica '
                'Vida Buena. Educa al cliente sobre los 4 planes, recomienda '
                'según perfil, y dispara cotización oficial vía webhook.'
            ),
            contexto_estatico=CONTEXTO_PLANES + '\n\n' + GUIA_RECOMENDACION,
            prompt_template=PROMPT_TEMPLATE,
            faqs_en_prompt=5,
            personalidad_preset='vendedor',
            nombre_bot='Sofía',
            mensaje_bienvenida=(
                '¡Hola! 👋 Soy Sofía, asesora virtual de Vida Buena. '
                'Te ayudo a encontrar el plan de asistencia médica ideal para vos. 💚\n\n'
                'Para darte la recomendación con tarifa estimada necesito tu *cédula* '
                '(10 dígitos). Con eso busco tu edad y género automáticamente. ¿Me la pasás?'
            ),
            personalidad=(
                'Soy Sofía, asesora de Vida Buena. Tengo experiencia en seguros '
                'de salud y mi prioridad es que el cliente entienda qué está '
                'comprando antes de decidir. No presiono — ayudo a comparar.'
            ),
            tono='cercano',
            estilo_escritura=(
                'Mensajes cortos, 2-4 líneas. Emojis con mesura (1-2 por respuesta). '
                'Listas con viñetas cuando comparo planes o detallo coberturas. '
                'Nunca muestro JSON ni tablas pesadas — extraigo lo relevante.'
            ),
            humanizar_timing=True,
            humaniz_chars_burbuja_max=500,
            humaniz_max_burbujas=8,
            cfg_history_turns=10,
            cfg_max_output_tokens=3500,
            cfg_max_static_chars=8000,
        )
        if apikey is not None:
            agente.apikey.add(apikey)
        return agente

    def _actualizar_agente(self, agente):
        agente.contexto_estatico = CONTEXTO_PLANES + '\n\n' + GUIA_RECOMENDACION
        agente.prompt_template = PROMPT_TEMPLATE
        agente.descripcion = (
            'Asesor virtual conversacional de planes de asistencia médica '
            'Vida Buena. Educa al cliente sobre los 4 planes, recomienda '
            'según perfil, y dispara cotización oficial vía webhook.'
        )
        agente.cfg_max_static_chars = 8000
        agente.save()

    def _sembrar_herramientas(self, agente, base_am, fastchat_url):
        creadas = 0
        actualizadas = 0
        for spec in HERRAMIENTAS:
            if spec.get('es_interno'):
                url_completa = fastchat_url.rstrip('/') + '/crm/api/ia/cotizador_am/'
                timeout = 30
            else:
                url_completa = base_am.rstrip('/') + '/'
                timeout = 15
            defaults = {
                'nombre_amigable': spec['nombre_amigable'],
                'descripcion': spec['descripcion'],
                'metodo': spec['metodo'],
                'url': url_completa,
                'headers': {},
                'parametros': spec['parametros'],
                'ubicacion_params': spec['ubicacion_params'],
                'plantilla_respuesta': spec['plantilla_respuesta'],
                'timeout': timeout,
                'activo': True,
            }
            obj, creado = HerramientaAgente.objects.update_or_create(
                agente=agente,
                nombre=spec['nombre'],
                defaults=defaults,
            )
            if creado:
                creadas += 1
            else:
                actualizadas += 1
        return creadas, actualizadas

    def _sembrar_detalles(self, agente):
        DetalleAgentesAI.objects.filter(agente=agente, tipo=3, status=True).delete()
        for titulo, cuerpo in CHUNKS_CONOCIMIENTO:
            DetalleAgentesAI.objects.create(
                agente=agente,
                tipo=3,
                descripcion=f'[{titulo}]\n\n{cuerpo}',
                tipo_dato_enlace=1,
                requiere_token=False,
                usar_cache=False,
                tiempo_cache_horas=1,
            )
        return len(CHUNKS_CONOCIMIENTO)

    def _vincular_sesion(self, agente, sesion_id):
        try:
            sesion = SesionWhatsApp.objects.get(id=sesion_id, status=True)
        except SesionWhatsApp.DoesNotExist:
            raise CommandError(f'No existe SesionWhatsApp activa con id={sesion_id}')
        sesion.agente_ia = agente
        sesion.modo_bot = 'ia'
        sesion.save(update_fields=['agente_ia', 'modo_bot'])
        self.stdout.write(self.style.SUCCESS(
            f'Sesión #{sesion.id} ({sesion.nombre or sesion.numero}) vinculada con modo_bot=ia.'
        ))

    def _resumen(self, agente):
        perfil_owner = agente.perfil.usuario.username if (agente.perfil and agente.perfil.usuario) else '(sin dueño)'
        self.stdout.write('')
        self.stdout.write(self.style.HTTP_INFO('=== RESUMEN ==='))
        self.stdout.write(f'Agente: {agente.nombre} (id={agente.id})')
        self.stdout.write(f'Dueño (perfil.usuario): {perfil_owner}')
        self.stdout.write(f'API Keys vinculadas: {agente.apikey.count()}')
        self.stdout.write(f'Herramientas activas: {agente.herramientas.filter(activo=True, status=True).count()}')
        self.stdout.write(f'Bloques de conocimiento: {agente.detalleagentesai_set.filter(status=True, tipo=3).count()}')
        self.stdout.write('')
        self.stdout.write('Conocimiento visible en la UI:')
        self.stdout.write(f'  /crm/entrenamiento/?action=procedimiento&id={agente.id}')
        self.stdout.write('  → tab "Conocimiento" → ver los 9 bloques de texto.')
        self.stdout.write('')
        self.stdout.write('Cotización oficial: NO la dispara este agente.')
        self.stdout.write(f'  - Cotizador web:     {COTIZADOR_WEB_URL}')
        self.stdout.write(f'  - Asesor humano:     {FORMULARIO_ASESOR_URL}')
        self.stdout.write('  - Flujo deterministico existente: seed_cotizador_am')
        self.stdout.write('')
        self.stdout.write('Probá desde /crm/entrenamiento/ (logueado como usuario dueño).')
        self.stdout.write('Mensajes de prueba:')
        self.stdout.write('  - "hola"                                         → saludo + capacidades')
        self.stdout.write('  - "qué planes tienen?"                           → comparativa de los 4')
        self.stdout.write('  - "tengo 35, mi pareja 33, hijo 5, qué me sirve?" → recomienda PREDILECTO')
        self.stdout.write('  - "soy mayor y quiero lo mejor"                  → recomienda MAGNO')
        self.stdout.write('  - "quiero cotizar"                               → comparte link cotizador + asesor')
