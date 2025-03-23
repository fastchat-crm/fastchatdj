import requests
from datetime import datetime, timedelta

# Configuración de la API
BASE_URL = "https://api.contifico.com/sistema/api/v1"
API_KEY = "FTTw8ViAz2ldVcN7FaZXVEbPUsGhXraongGZL7ztLsc"  # Reemplaza con tu API_KEY proporcionada por Contífico


# Función para obtener el listado de personas
def obtener_listado_personas():
    url = f"{BASE_URL}/persona/"
    headers = {"Authorization": API_KEY}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error al obtener personas: {e}")
        return []


# Función para obtener el listado de bodegas
def obtener_listado_bodegas():
    url = f"{BASE_URL}/bodega/"
    headers = {"Authorization": API_KEY}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error al obtener bodegas: {e}")
        return []


# Función para obtener documentos por bodega con un rango de fechas
def obtener_documentos_por_bodega_y_rango_fechas(bodega_id, fecha_inicial, fecha_final):
    url = f"{BASE_URL}/registro/documento/"
    headers = {"Authorization": API_KEY}
    params = {
        "bodega_id": bodega_id,
        "fecha_inicial": fecha_inicial,  # Rango de fecha inicial
        "fecha_final": fecha_final  # Rango de fecha final
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        # Depuración: Imprimir la respuesta para verificar
        # print(f"Respuesta para bodega {bodega_id} de {fecha_inicial} a {fecha_final}: {data}")

        if isinstance(data, list):
            return data
        else:
            print("La respuesta no es una lista de documentos.")
            return []
    except requests.exceptions.RequestException as e:
        print(f"Error al obtener documentos para la bodega {bodega_id} en el rango de fechas: {e}")
        return []


# Función para generar el resumen
def generar_resumen():
    # personas = obtener_listado_personas()
    # total_personas = len(personas)
    # print(f"Total de personas: {total_personas}\n")

    bodegas = obtener_listado_bodegas()
    print("Listado de bodegas y número de documentos por bodega:")

    # Definir el rango de fechas (por ejemplo, los últimos 7 días)
    fecha_actual = datetime.now()
    fecha_inicial = (fecha_actual - timedelta(days=1)).strftime("%d/%m/%Y")
    fecha_final = fecha_actual.strftime("%d/%m/%Y")

    for bodega in bodegas:
        bodega_id = bodega["id"]
        bodega_nombre = bodega["nombre"]

        # Obtener documentos filtrados por bodega y rango de fechas
        documentos = obtener_documentos_por_bodega_y_rango_fechas(bodega_id, fecha_inicial, fecha_final)
        total_documentos = len(documentos)
        print(f"Bodega: {bodega_nombre} - Total de documentos: {total_documentos}")

        if total_documentos > 0:
            print("Detalles de ventas del rango de fechas:")
            for documento in documentos:
                fecha = documento.get("fecha_emision")
                total = documento.get("total")
                cliente = documento.get('persona', {}).get('razon_social', "Desconocido")
                productos = documento.get("detalles", [])

                print(documento)

                print(f"Venta - Fecha: {fecha}, Total: {total}, Cliente: {cliente}, Bodega: {bodega_nombre}")
                print("Productos:")
                for producto in productos:
                    producto_id = producto.get("producto_id")
                    producto_nombre = producto.get('producto_nombre', "Sin nombre")
                    cantidad = producto.get("cantidad")
                    precio = producto.get("precio")
                    print(f"  - Producto ID: {producto_id}, Producto: {producto_nombre}, Cantidad: {cantidad}, Precio: {precio}")
            print("\n")


# Ejecución del script
if __name__ == "__main__":
    generar_resumen()
