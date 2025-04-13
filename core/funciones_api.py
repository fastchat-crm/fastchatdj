import requests


def traerApiPersona(documento):
    try:
        urlEnlace = f'https://ister.academicok.com/api?a=apidatospersona&cedula={documento}&key=ISTER2024_API!'
        respuesta = requests.get(urlEnlace).json()
        if 'data' in respuesta and respuesta['result'] == 'ok':
            if 'error' in respuesta['data']:
                raise NameError(f"Error al obtener datos")
            datosResp = respuesta['data']['data'][0]
            return True, datosResp
    except Exception as ex:
        return False, f"{ex}"


# PARA BUSCAR PERSONA EN ELEMENTO SELECT2 SEGUN EL TIPO DE BUSQUEDA QUE ENVIEN DESDE EL TEMPLATE
def filtro_persona_select(request, idsexcluidas=[]):
    from django.db.models import Q
    from autenticacion.models import Usuario
    try:
        idsagregados = request.GET.get('idsagregados', '')
        tipos = request.GET.get('tipo', '').split(', ')
        if idsagregados:
            idsagregados = idsagregados.split(',')
            idsexcluidas += [idl for idl in idsagregados]
        q = request.GET['q'].upper().strip()
        s = q.split(" ")
        filtro = Q(status=True)
        for idx, tipo in enumerate(tipos, start=1):
            if idx == 1:
                if tipo == "administrativos":
                    filtro = filtro & Q(perfiladministrativo__isnull=False)
                elif tipo == "clientes":
                    filtro = filtro & Q(perfilpersona__isnull=False)
            else:
                if tipo == "administrativos":
                    filtro = filtro | Q(perfiladministrativo__isnull=False)
                elif tipo == "clientes":
                    filtro = filtro | Q(perfilpersona__isnull=False)

        qspersona = Usuario.objects.filter(filtro).exclude(id__in=idsexcluidas).order_by('last_name')
        if len(s) == 1:
            qspersona = qspersona.filter((Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(
                documento__icontains=q) | Q(documento__contains=q)), Q(status=True)).distinct()[:15]
        elif len(s) == 2:
            qspersona = qspersona.filter(Q(last_name__contains=q) | Q(first_name__icontains=q)).filter(status=True).distinct()[:15]
        elif len(s) == 3:
            qspersona = qspersona.filter(
                (Q(first_name__contains=s[0]+' '+s[1]) & Q(last_name__contains=s[2])) |
                (Q(first_name__contains=s[2]) & Q(last_name__contains=s[0]+' '+s[1]))).filter(status=True).distinct()[:15]
        else:
            qspersona = qspersona.filter(
                (Q(first_name__contains=s[0]+' '+s[1]) & Q(last_name__contains=s[2]+' '+s[3])) |
                (Q(first_name__contains=s[2]+' '+s[3]) & Q(last_name__contains=s[0]+' '+s[1]))).filter(status=True).distinct()[:15]
        resp = [{'id': qs.pk, 'text': f"{qs.full_name()}",
                 'documento': qs.documento,
                 'foto': qs.get_foto()} for qs in qspersona]
        return resp
    except Exception as ex:
        pass