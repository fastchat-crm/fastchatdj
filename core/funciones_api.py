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