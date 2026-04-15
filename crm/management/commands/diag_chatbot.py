"""
Diagnóstico de un Departamento ChatBot: muestra el estado real de los nodos
en la base de datos para depurar problemas de configuración.

Uso:
    python manage.py diag_chatbot                  # lista todos los deptos
    python manage.py diag_chatbot --id <depto_id>  # detalle del depto
    python manage.py diag_chatbot --nombre "Centro de Atención Estudiantil"
    python manage.py diag_chatbot --fix-inicio --id <depto_id>
        Si ningún nodo raíz tiene es_inicio=True, marca el primero.
"""

from django.core.management.base import BaseCommand
from crm.models import DepartamentoChatBot, OpcionDepartamentoChatBot, EstadoFlujoChatbot


class Command(BaseCommand):
    help = 'Diagnóstico de un departamento-chatbot (muestra nodos, es_inicio, config).'

    def add_arguments(self, parser):
        parser.add_argument('--id', type=int, default=None)
        parser.add_argument('--nombre', type=str, default=None)
        parser.add_argument('--fix-inicio', action='store_true',
                            help='Auto-marcar primer nodo raíz como es_inicio si ninguno lo tiene.')
        parser.add_argument('--reset-estados', action='store_true',
                            help='Borrar EstadoFlujoChatbot de este depto (limpia en_handoff/finalizado).')

    def handle(self, *args, **opts):
        if not opts.get('id') and not opts.get('nombre'):
            self.stdout.write(self.style.NOTICE('Deptos ChatBot disponibles:'))
            for d in DepartamentoChatBot.objects.filter(status=True).order_by('id'):
                n_nodos = d.opciondepartamentochatbot_set.filter(status=True).count()
                self.stdout.write(f'  #{d.id}  "{d.nombre}"  — {n_nodos} nodos activos '
                                  f'{"[DEFAULT]" if d.es_default else ""} '
                                  f'{"[FLUJO ACTIVO]" if d.activo_tradicional else "[FLUJO INACTIVO]"}')
            return

        if opts.get('id'):
            d = DepartamentoChatBot.objects.filter(pk=opts['id']).first()
        else:
            d = DepartamentoChatBot.objects.filter(nombre=opts['nombre']).first()
        if not d:
            self.stdout.write(self.style.ERROR('Depto no encontrado.'))
            return

        self.stdout.write(self.style.SUCCESS(f'\n═══ Depto #{d.id}: "{d.nombre}" ═══'))
        self.stdout.write(f'  es_default:         {d.es_default}')
        self.stdout.write(f'  activo_tradicional: {d.activo_tradicional}')
        self.stdout.write(f'  status:             {d.status}')
        self.stdout.write(f'  palabras_clave:     {d.get_palabras_clave()}')
        self.stdout.write(f'  mensaje_saludo:     "{(d.mensaje_saludo or "")[:80]}"')

        nodos = list(d.opciondepartamentochatbot_set.filter(status=True).order_by('orden', 'id'))
        raices = [n for n in nodos if n.opcion_padre_id is None]

        self.stdout.write(f'\n  Total nodos activos: {len(nodos)} '
                          f'({len(raices)} raíces, {len(nodos)-len(raices)} hijos)')

        if raices:
            self.stdout.write(self.style.WARNING('\n  Nodos raíz:'))
            for n in raices:
                marca_inicio = ' ⭐ [ES_INICIO]' if n.es_inicio else ''
                self.stdout.write(
                    f'    · #{n.id} orden={n.orden}  tipo={n.tipo_nodo}  '
                    f'var={n.variable_destino or "-"}  val={n.validacion_tipo}'
                    f'{marca_inicio}'
                )
                self.stdout.write(f'        nombre:    "{n.nombre}"')
                self.stdout.write(f'        respuesta: "{(n.respuesta or "")[:80]}"')
                if n.config:
                    keys = list((n.config or {}).keys())
                    self.stdout.write(f'        config:    {keys}')
                    if n.tipo_nodo == 'menu':
                        ops = (n.config or {}).get('opciones') or []
                        self.stdout.write(f'          menu.opciones ({len(ops)}):')
                        for i, o in enumerate(ops, 1):
                            self.stdout.write(f'            {i}. etiqueta="{o.get("etiqueta","")}" '
                                              f'salida="{o.get("salida","")}"')
                    if n.tipo_nodo == 'http':
                        self.stdout.write(f'          http: metodo={n.config.get("metodo")} '
                                          f'path="{n.config.get("path")}" '
                                          f'endpoint={n.endpoint_id}')
                        self.stdout.write(f'          query: {n.config.get("query")}')
                else:
                    self.stdout.write('        config:    {} (vacía)')

        # Cuál escogería nodo_inicio()
        elegido = d.nodo_inicio()
        self.stdout.write(self.style.SUCCESS(
            f'\n  → nodo_inicio() elegiría: '
            f'#{elegido.id if elegido else None} '
            f'tipo={elegido.tipo_nodo if elegido else "—"} '
            f'nombre="{elegido.nombre if elegido else ""}"'
        ))

        if elegido and elegido.tipo_nodo == 'pregunta':
            self.stdout.write(self.style.ERROR(
                '  ⚠️  El nodo inicial es una PREGUNTA — por eso el bot muestra "¿Puedes indicarme el dato?".\n'
                '      Deberías tener un MENU como nodo inicial.\n'
                '      Usa --fix-inicio para auto-marcar el primer menú raíz como inicio,\n'
                '      o corre `python manage.py seed_centro_estudiantil --reset` para recrear.'
            ))

        # Estados de conversación activos
        estados = EstadoFlujoChatbot.objects.filter(departamento=d)
        self.stdout.write(f'\n  Estados runtime: {estados.count()} (en_handoff: {estados.filter(en_handoff=True).count()}, finalizados: {estados.filter(finalizado=True).count()})')

        # ── Fixes ──
        if opts.get('fix_inicio'):
            hay_inicio = any(n.es_inicio for n in raices)
            if hay_inicio:
                self.stdout.write(self.style.WARNING('\n  --fix-inicio: ya hay un nodo con es_inicio=True, nada que hacer.'))
            else:
                # Prefiere marcar un menu; si no hay, el primero por orden
                candidato = next((n for n in raices if n.tipo_nodo == 'menu'), None)
                if not candidato and raices:
                    candidato = raices[0]
                if candidato:
                    candidato.es_inicio = True
                    candidato.save(update_fields=['es_inicio'])
                    self.stdout.write(self.style.SUCCESS(
                        f'\n  ✓ Marcado #{candidato.id} "{candidato.nombre}" (tipo={candidato.tipo_nodo}) como es_inicio=True.'
                    ))

        if opts.get('reset_estados'):
            n = estados.count()
            estados.delete()
            self.stdout.write(self.style.SUCCESS(f'\n  ✓ Borrados {n} EstadoFlujoChatbot del depto.'))
