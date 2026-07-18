"""
Indexa el conocimiento de una empresa en su tenant de Weaviate (RAG).

Fuentes:
  - Cuestionario Q&A (CUESTIONARIO.docx) — pares pregunta/respuesta por plan.
  - Coberturas parametrizadas en BD (modelo Cobertura) — una entrada por concepto/plan.

Uso:
    python manage.py indexar_conocimiento --perfil-id 2 \
        --cuestionario "/home/fastchatdj/cotizador/data/CUESTIONARIO.docx"

Reemplaza el contenido previo del tenant (idempotente).
"""
import re
import zipfile

from django.core.management.base import BaseCommand, CommandError

from crm.models import PerfilNegocioIA, ApiKeyIA
from cotizador.models import Cobertura, Plan
from agents_ai import weaviate_rag as W


PLANES_RE = re.compile(r'PLAN\s+(MAGNO|PREDILECTO|PROTECCI[ÓO]N|[ÚU]NICO)', re.IGNORECASE)


def _texto_docx(path: str) -> list[str]:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    parrafos = []
    for bloque in re.split(r'</w:p>', xml):
        ts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', bloque)
        linea = "".join(ts).strip()
        if linea:
            parrafos.append(linea)
    return parrafos


def _parsear_cuestionario(path: str) -> list[dict]:
    """Devuelve docs {content, source, tipo, categoria} desde el cuestionario."""
    docs = []
    plan_actual = "General"
    for p in _texto_docx(path):
        m = PLANES_RE.search(p)
        if m and len(p) < 60:
            plan_actual = m.group(0).title()
            continue
        # Pares "Cliente: "..." Respuesta: ..."
        if 'Respuesta:' in p and ('Cliente:' in p or '"' in p):
            partes = p.split('Respuesta:', 1)
            pregunta = partes[0].replace('Cliente:', '').strip().strip('"').strip()
            respuesta = partes[1].strip()
            if respuesta:
                content = f"Plan: {plan_actual}\nPregunta: {pregunta}\nRespuesta: {respuesta}"
                docs.append({
                    "content": content, "source": "cuestionario",
                    "tipo": "faq", "categoria": plan_actual,
                })
    return docs


def _docs_coberturas(empresa) -> list[dict]:
    docs = []
    for cob in Cobertura.objects.filter(plan__empresa=empresa, status=True).select_related('plan'):
        valor = (cob.valor or "").strip()
        if not valor:
            continue
        content = f"Plan {cob.plan.nombre_comercial} — {cob.categoria}: {cob.concepto} = {valor}"
        docs.append({
            "content": content, "source": "cobertura_bd",
            "tipo": "cobertura", "categoria": cob.categoria,
        })
    return docs


class Command(BaseCommand):
    help = 'Indexa el conocimiento (cuestionario + coberturas) en el tenant Weaviate de la empresa.'

    def add_arguments(self, parser):
        parser.add_argument('--perfil-id', type=int, required=True)
        parser.add_argument('--cuestionario', help='Ruta al CUESTIONARIO.docx (opcional)')
        parser.add_argument('--gemini-key-id', type=int,
                            help='ID de ApiKeyIA Gemini para embeddings (si no, toma la primera del perfil)')

    def handle(self, *args, **opts):
        try:
            empresa = PerfilNegocioIA.objects.get(id=opts['perfil_id'])
        except PerfilNegocioIA.DoesNotExist:
            raise CommandError(f"No existe perfil {opts['perfil_id']}")

        # Key Gemini para embeddings
        if opts.get('gemini_key_id'):
            gem = ApiKeyIA.objects.filter(id=opts['gemini_key_id']).first()
        else:
            gem = ApiKeyIA.objects.filter(perfil=empresa, proveedor=2, estado=True).first()
        if not gem:
            raise CommandError('No hay ApiKeyIA Gemini para embeddings. Pasa --gemini-key-id.')

        docs = []
        if opts.get('cuestionario'):
            faqs = _parsear_cuestionario(opts['cuestionario'])
            docs.extend(faqs)
            self.stdout.write(f'Cuestionario: {len(faqs)} Q&A')
        cobs = _docs_coberturas(empresa)
        docs.extend(cobs)
        self.stdout.write(f'Coberturas BD: {len(cobs)}')

        if not docs:
            raise CommandError('No hay documentos para indexar.')

        n = W.indexar_documentos(empresa.id, gem.descripcion, docs, reemplazar=True)
        total = W.contar(empresa.id)
        self.stdout.write(self.style.SUCCESS(
            f'Indexados {n} documentos en tenant empresa_{empresa.id}. Total en tenant: {total}.'
        ))
