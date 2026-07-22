"""
Indexa el directorio de centros médicos (clínicas) en el tenant Weaviate de la empresa.

Estrategia para RAG: un documento POR CIUDAD que agrupa todos sus centros, para que
una pregunta tipo "¿qué clínicas hay en Quito?" recupere todos en un solo fragmento.

Uso:
    python manage.py indexar_centros --perfil-id 2 \
        --archivo "/home/fastchatdj/cotizador/data/centros_medicos_vidabuena.xlsx" --gemini-key-id 28

Idempotente: borra los centros previos (source='centros_medicos') antes de reindexar.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from crm.models import PerfilNegocioIA, ApiKeyIA, AgentesIA
from agents_ai import weaviate_rag as W


class Command(BaseCommand):
    help = 'Indexa el directorio de centros médicos por ciudad en el RAG de la empresa.'

    def add_arguments(self, parser):
        parser.add_argument('--perfil-id', type=int, required=True)
        parser.add_argument('--agente-id', type=int,
                            help='Indexa solo a este agente. Si se omite, indexa a TODOS los '
                                 'agentes activos del perfil (el RAG es por agente: tenant agente_<id>).')
        parser.add_argument('--archivo', required=True)
        parser.add_argument('--gemini-key-id', type=int)
        parser.add_argument('--hoja', default='Todos los Centros')

    def handle(self, *args, **opts):
        try:
            import openpyxl
        except ImportError:
            raise CommandError('Falta openpyxl.')
        try:
            empresa = PerfilNegocioIA.objects.get(id=opts['perfil_id'])
        except PerfilNegocioIA.DoesNotExist:
            raise CommandError(f"No existe perfil {opts['perfil_id']}")

        # El RAG es POR AGENTE (tenant agente_<agente.id>).
        if opts.get('agente_id'):
            agentes = list(AgentesIA.objects.filter(id=opts['agente_id'], perfil=empresa, status=True))
            if not agentes:
                raise CommandError(
                    f"No existe agente activo {opts['agente_id']} en el perfil {empresa.id}.")
        else:
            agentes = list(empresa.get_agentes())
            if not agentes:
                raise CommandError(
                    f"El perfil {empresa.id} no tiene agentes activos para indexar.")

        if opts.get('gemini_key_id'):
            gem = ApiKeyIA.objects.filter(id=opts['gemini_key_id']).first()
        else:
            gem = ApiKeyIA.objects.filter(perfil=empresa, proveedor=2, estado=True).order_by('-id').first()
        if not gem:
            raise CommandError('No hay ApiKeyIA Gemini para embeddings.')

        wb = openpyxl.load_workbook(opts['archivo'], data_only=True)
        ws = wb[opts['hoja']]

        ciudades = defaultdict(list)
        for row in ws.iter_rows(min_row=2, values_only=True):
            row = (list(row) + [None] * 5)[:5]
            _, prov, ciudad, nombre, tipo = row
            if not nombre or not str(nombre).strip():
                continue
            clave = (str(ciudad or '').strip(), str(prov or '').strip())
            ciudades[clave].append((str(nombre).strip(), str(tipo or '').strip()))

        docs = []
        for (ciudad, prov), centros in ciudades.items():
            if not ciudad:
                continue
            lista = "; ".join(f"{n} ({t})" if t else n for n, t in centros)
            content = (f"Centros médicos de la red Vida Buena en {ciudad} ({prov}) — "
                       f"{len(centros)} centros: {lista}")
            docs.append({
                "content": content, "source": "centros_medicos",
                "tipo": "clinica", "categoria": ciudad,
            })

        if not docs:
            raise CommandError('No se encontraron centros en el Excel.')

        total_centros = sum(len(c) for c in ciudades.values())
        for agente in agentes:
            borrados = W.borrar_por_source(agente.id, "centros_medicos")
            n = W.indexar_documentos(agente.id, gem.descripcion, docs, reemplazar=False)
            total = W.contar(agente.id)
            self.stdout.write(self.style.SUCCESS(
                f'Centros indexados en tenant agente_{agente.id} ({agente.nombre}): '
                f'{n} ciudades ({total_centros} centros). '
                f'Previos borrados: {borrados}. Total tenant: {total}.'
            ))
