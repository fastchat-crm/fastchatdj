"""
Ejemplo de uso del AgenteConsultor con capacidades de listas
"""

from .agente_consultor import AgenteConsultor

def ejemplo_uso_listas():
    """
    Ejemplo completo de cómo usar las funcionalidades de listas del AgenteConsultor
    """
    
    # Inicializar el agente (ajustar parámetros según tu configuración)
    agente = AgenteConsultor(
        vectorstore_path="ruta/a/tu/vectorstore",
        provider=2,  # Gemini
        apikey="tu_api_key",
        model_name="gemini-1.5-pro",
        conversacion=None,  # O tu objeto conversación
        prompt_template_text="Tu prompt template aquí"
    )
    
    # Ejemplos de comandos que el usuario puede enviar:
    
    # 1. Crear una lista de menú de restaurante
    print("1. Creando lista de menú:")
    respuesta = agente.consultar("Crea una lista del menú de platos principales")
    print(respuesta)
    
    # 2. Agregar items al menú
    print("\n2. Agregando platos al menú:")
    respuesta = agente.consultar("Agregar pollo a la parrilla al menú de platos principales")
    print(respuesta)
    
    respuesta = agente.consultar("Incluir pasta carbonara en platos principales")
    print(respuesta)
    
    respuesta = agente.consultar("Añadir salmón al horno a la lista de platos principales")
    print(respuesta)
    
    # 3. Mostrar la lista completa
    print("\n3. Mostrando el menú completo:")
    respuesta = agente.consultar("Muéstrame el menú de platos principales")
    print(respuesta)
    
    # 4. Crear otra lista (bebidas)
    print("\n4. Creando lista de bebidas:")
    respuesta = agente.consultar("Hacer una nueva lista de bebidas")
    print(respuesta)
    
    # 5. Agregar bebidas
    print("\n5. Agregando bebidas:")
    respuesta = agente.consultar("Poner coca cola en la lista de bebidas")
    print(respuesta)
    
    respuesta = agente.consultar("Agregar agua mineral a bebidas")
    print(respuesta)
    
    # 6. Ver todas las listas
    print("\n6. Viendo todas las listas:")
    respuesta = agente.consultar("Muéstrame todas las listas que tenemos")
    print(respuesta)
    
    # 7. Eliminar un item
    print("\n7. Eliminando un item:")
    respuesta = agente.consultar("Quitar pasta carbonara del menú de platos principales")
    print(respuesta)
    
    # 8. Ver preguntas frecuentes
    print("\n8. Preguntas frecuentes:")
    respuesta = agente.obtener_preguntas_frecuentes(5)
    print(respuesta)
    
    return agente


def ejemplo_menu_restaurante():
    """
    Ejemplo específico para un menú de restaurante
    """
    
    # Simular una conversación de restaurante
    consultas_restaurante = [
        "Hola, quiero ver el menú",
        "Crear lista de entradas",
        "Agregar ensalada césar a entradas",
        "Incluir sopa de tomate en entradas", 
        "Poner alitas de pollo en la lista de entradas",
        "Crear lista de platos principales",
        "Agregar filete de res a platos principales",
        "Incluir pollo al curry en platos principales",
        "Añadir pescado a la plancha a platos principales",
        "Mostrar todas las listas del menú",
        "¿Qué entradas tienen?",
        "¿Cuáles son los platos principales?",
        "Crear lista de postres",
        "Agregar tiramisu a postres",
        "Incluir helado de vainilla en postres",
        "Mostrar el menú completo"
    ]
    
    print("🍽️  SIMULACIÓN DE MENÚ DE RESTAURANTE")
    print("="*50)
    
    # Aquí deberías inicializar tu agente con los parámetros reales
    # agente = AgenteConsultor(...)
    
    for i, consulta in enumerate(consultas_restaurante, 1):
        print(f"\n👤 Cliente: {consulta}")
        # respuesta = agente.consultar(consulta)
        # print(f"🤖 Asistente: {respuesta}")
        print(f"🤖 Asistente: [Respuesta simulada para '{consulta}']")


def ejemplo_preguntas_frecuentes():
    """
    Ejemplo de cómo se registran y consultan las preguntas frecuentes
    """
    
    preguntas_ejemplo = [
        "¿Cuál es el horario de atención?",
        "¿Hacen delivery?",
        "¿Cuáles son los precios?",
        "¿Tienen opciones vegetarianas?",
        "¿Aceptan tarjetas de crédito?",
        "¿Necesito hacer reserva?",
        "¿Cuál es la dirección?",
        "¿Tienen WiFi?",
        "¿Hay estacionamiento?",
        "¿Abren los fines de semana?"
    ]
    
    print("❓ EJEMPLO DE PREGUNTAS FRECUENTES")
    print("="*40)
    
    # Simular que estas preguntas fueron hechas por diferentes usuarios
    for pregunta in preguntas_ejemplo:
        print(f"Usuario preguntó: {pregunta}")
        # agente.consultar(pregunta)  # Esto registraría la pregunta automáticamente
    
    print("\n📊 Las preguntas más frecuentes serían:")
    # respuesta = agente.obtener_preguntas_frecuentes(5)
    # print(respuesta)


if __name__ == "__main__":
    print("🤖 EJEMPLOS DE USO - AGENTE CONSULTOR CON LISTAS")
    print("="*60)
    
    print("\n📋 1. Ejemplo general de listas:")
    # ejemplo_uso_listas()
    
    print("\n🍽️  2. Ejemplo menú de restaurante:")
    ejemplo_menu_restaurante()
    
    print("\n❓ 3. Ejemplo preguntas frecuentes:")
    ejemplo_preguntas_frecuentes()
    
    print("\n✅ Ejemplos completados. Descomenta las líneas con 'agente.consultar()' para uso real.")
