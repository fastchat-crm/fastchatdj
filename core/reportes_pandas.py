import os
import pandas as pd
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from django.db import connection
from django.http import JsonResponse, HttpResponse
from django.conf import settings
import traceback

class ReporteFacturas:
    def __init__(self, cabecera, nombre_archivo_base, page_size=10000):
        self.cabecera = cabecera
        self.nombre_archivo_base = nombre_archivo_base
        self.page_size = page_size

    def generar_nombre_archivo(self, extension):
        try:
            fecha_hora = datetime.now().strftime("%Y%m%d_%H%M%S")
            nombre_archivo = f"{self.nombre_archivo_base}_{fecha_hora}.{extension}"
            # Crear el directorio si no existe
            folder_reportes = os.path.join(settings.MEDIA_ROOT, 'reportes')
            os.makedirs(folder_reportes, exist_ok=True)
            return os.path.join(folder_reportes, nombre_archivo), '', ''
        except Exception as e:
            return None, str(e), traceback.format_exc()

    def ejecutar_parte_query(self, query, offset):
        try:
            query_paginado = f"{query} LIMIT {self.page_size} OFFSET {offset}"
            with connection.cursor() as cursor:
                cursor.execute(query_paginado)
                columns = [col[0] for col in cursor.description]
                data = cursor.fetchall()
            return pd.DataFrame(data, columns=columns)
        except Exception as e:
            raise e

    def generar_reporte_excel(self, query_base, footer):
        try:
            start_time = time.time()  # Inicia el contador
            all_data = []
            offset = 0
            with ThreadPoolExecutor() as executor:
                futures = []
                while True:
                    futures.append(executor.submit(self.ejecutar_parte_query, query_base, offset))
                    offset += self.page_size
                    # Verificar si hay más datos
                    if futures[-1].result().empty:
                        break

                for future in futures:
                    df = future.result()
                    if not df.empty:
                        all_data.append(df)

            if not all_data:
                return None, JsonResponse({"status": "warning", "message": "La consulta no devolvió ningún registro."},
                                          status=200)

            # Concatenar todos los DataFrames
            final_df = pd.concat(all_data, ignore_index=True)

            # Verificar que las columnas de la consulta coinciden con la cabecera
            print("Columnas del DataFrame antes de asignar cabecera:", final_df.columns)
            print("Cabecera esperada:", self.cabecera)
            if len(self.cabecera) != len(final_df.columns):
                return None, JsonResponse({"status": "error",
                                           "message": f"El número de columnas de la cabecera no coincide con el número de columnas de la consulta ({len(final_df.columns)})."},
                                          status=400)

            # Añadir una fila con la suma de las columnas especificadas en el footer
            sum_row = {col: final_df[col].sum() if footer[idx] else '' for idx, col in enumerate(final_df.columns)}
            final_df = final_df.append(sum_row, ignore_index=True)

            nombre_archivo, error, traceback_info = self.generar_nombre_archivo('xlsx')
            if error:
                return None, JsonResponse({"status": "error", "message": f"Error al generar nombre de archivo: {error}",
                                           "traceback": traceback_info}, status=500)

            # Verificar nuevamente las columnas del DataFrame antes de asignar encabezados
            print("Columnas antes de asignar cabecera:", final_df.columns)
            print("Cabecera:", self.cabecera)

            if len(self.cabecera) == len(final_df.columns):
                final_df.columns = self.cabecera
            else:
                print(f"Mismatch: DataFrame columns {len(final_df.columns)} vs. headers {len(self.cabecera)}")
                print("Column names:", final_df.columns)
                print("Headers:", self.cabecera)
                raise ValueError("El número de columnas en el DataFrame no coincide con el número de encabezados.")

            with pd.ExcelWriter(nombre_archivo, engine='xlsxwriter') as writer:
                final_df.to_excel(writer, index=False, header=self.cabecera)
                workbook = writer.book
                worksheet = writer.sheets['Sheet1']

                # Definir el formato de dinero
                money_format = workbook.add_format({'num_format': '$#,##0.00'})

                # Aplicar el formato a las columnas de dinero
                money_columns = ['Subtotal Base IVA', 'Subtotal Base 0', 'Total Descuento', 'Total IVA', 'Total']
                for column in money_columns:
                    col_idx = self.cabecera.index(column)
                    worksheet.set_column(col_idx, col_idx, None, money_format)

            end_time = time.time()  # Finaliza el contador
            elapsed_time = end_time - start_time  # Calcula el tiempo transcurrido
            return nombre_archivo, None
        except Exception as e:
            return None, JsonResponse({"status": "error", "message": str(e), "traceback": traceback.format_exc()},
                                      status=500)

    def generar_reporte_txt(self, query_base, footer):
        try:
            start_time = time.time()  # Inicia el contador
            all_data = []
            offset = 0
            with ThreadPoolExecutor() as executor:
                futures = []
                while True:
                    futures.append(executor.submit(self.ejecutar_parte_query, query_base, offset))
                    offset += self.page_size
                    # Verificar si hay más datos
                    if futures[-1].result().empty:
                        break

                for future in futures:
                    df = future.result()
                    if not df.empty:
                        all_data.append(df)

            if not all_data:
                return None, JsonResponse({"status": "warning", "message": "La consulta no devolvió ningún registro."},
                                          status=200)

            # Concatenar todos los DataFrames
            final_df = pd.concat(all_data, ignore_index=True)

            # Verificar que las columnas de la consulta coinciden con la cabecera
            if len(self.cabecera) != len(final_df.columns):
                return None, JsonResponse({"status": "error",
                                           "message": "El número de columnas de la cabecera no coincide con el número de columnas de la consulta."},
                                          status=400)

            nombre_archivo, error, traceback_info = self.generar_nombre_archivo('txt')
            if error:
                return None, JsonResponse({"status": "error", "message": f"Error al generar nombre de archivo: {error}",
                                           "traceback": traceback_info}, status=500)

            # Añadir una fila con la suma de las columnas especificadas en el footer
            sum_row = {col: final_df[col].sum() if footer[idx] else '' for idx, col in enumerate(final_df.columns)}
            sum_row['Comprobante'] = 'Totales'
            final_df = final_df.append(sum_row, ignore_index=True)

            # Escribir los datos en un archivo TXT
            with open(nombre_archivo, 'w') as file:
                # Escribir la cabecera
                file.write('\t'.join(self.cabecera) + '\n')
                # Escribir los datos fila por fila
                for row in final_df.itertuples(index=False):
                    file.write('\t'.join(map(str, row)) + '\n')

            end_time = time.time()  # Finaliza el contador
            elapsed_time = end_time - start_time  # Calcula el tiempo transcurrido
            return nombre_archivo, None
        except Exception as e:
            return None, JsonResponse({"status": "error", "message": str(e), "traceback": traceback.format_exc()},
                                      status=500)