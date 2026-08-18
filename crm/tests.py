"""Tests del motor de flujo del chatbot (funciones puras, sin BD)."""
from django.test import SimpleTestCase

from crm.motor_flujo_chatbot import (
    _get_path,
    _normalizar_texto,
    evaluar_condicion,
    normalizar_numero,
    resolver_expresion,
    validar_entrada,
)


class NormalizarTextoTest(SimpleTestCase):
    def test_quita_tildes_y_baja_a_minusculas(self):
        self.assertEqual(_normalizar_texto('Información'), 'informacion')
        self.assertEqual(_normalizar_texto('BECAS'), 'becas')

    def test_vacio_y_none(self):
        self.assertEqual(_normalizar_texto(''), '')
        self.assertEqual(_normalizar_texto(None), '')


class NormalizarNumeroTest(SimpleTestCase):
    def test_formato_europeo(self):
        self.assertEqual(normalizar_numero('1.234,56'), '1234.56')

    def test_formato_us(self):
        self.assertEqual(normalizar_numero('1,234.56'), '1234.56')

    def test_entero_simple(self):
        self.assertEqual(normalizar_numero('15'), '15')


class ValidarEntradaTest(SimpleTestCase):
    def test_sin_validacion(self):
        self.assertTrue(validar_entrada('none', '', 'lo que sea'))
        self.assertTrue(validar_entrada('', '', 'lo que sea'))

    def test_email(self):
        self.assertTrue(validar_entrada('email', '', 'a@b.com'))
        self.assertFalse(validar_entrada('email', '', 'no-es-email'))

    def test_numero(self):
        self.assertTrue(validar_entrada('numero', '', '42'))
        self.assertFalse(validar_entrada('numero', '', 'abc'))

    def test_fecha(self):
        self.assertTrue(validar_entrada('fecha', '', '2026-05-31'))
        self.assertFalse(validar_entrada('fecha', '', '31/05/2026'))

    def test_ruc(self):
        self.assertTrue(validar_entrada('ruc', '', '1790012345001'))
        self.assertFalse(validar_entrada('ruc', '', '123'))

    def test_cedula_invalida_por_longitud(self):
        self.assertFalse(validar_entrada('cedula', '', '123'))

    def test_regex(self):
        self.assertTrue(validar_entrada('regex', r'^\d{4}$', '1234'))
        self.assertFalse(validar_entrada('regex', r'^\d{4}$', 'ab'))


class GetPathTest(SimpleTestCase):
    def test_dict_anidado_y_lista(self):
        raiz = {'a': {'b': [{'c': 7}]}}
        self.assertEqual(_get_path(raiz, 'a.b[0].c'), 7)

    def test_path_inexistente(self):
        self.assertIsNone(_get_path({'a': 1}, 'a.b.c'))


class ResolverExpresionTest(SimpleTestCase):
    def test_substitucion_simple(self):
        ctx = {'contacto': {'nombre': 'Ana'}}
        self.assertEqual(resolver_expresion('{{contacto.nombre}}', ctx), 'Ana')

    def test_substitucion_embebida(self):
        ctx = {'contacto': {'nombre': 'Ana'}}
        self.assertEqual(resolver_expresion('Hola {{contacto.nombre}}', ctx), 'Hola Ana')

    def test_match_completo_preserva_tipo(self):
        ctx = {'variables': {'n': 5}}
        self.assertEqual(resolver_expresion('{{variables.n}}', ctx), 5)


class EvaluarCondicionTest(SimpleTestCase):
    def test_mayor_igual_numerico(self):
        ctx = {'variables': {'x': 15}}
        self.assertTrue(evaluar_condicion({'izq': '{{variables.x}}', 'op': '>=', 'der': 10}, ctx))
        self.assertFalse(evaluar_condicion({'izq': '{{variables.x}}', 'op': '>=', 'der': 20}, ctx))

    def test_igualdad_string(self):
        ctx = {'variables': {'estado': 'activo'}}
        self.assertTrue(evaluar_condicion({'izq': '{{variables.estado}}', 'op': '==', 'der': 'activo'}, ctx))
        self.assertTrue(evaluar_condicion({'izq': '{{variables.estado}}', 'op': '!=', 'der': 'cerrado'}, ctx))

    def test_contiene(self):
        ctx = {'variables': {'msg': 'Quiero una COTIZACION ya'}}
        self.assertTrue(evaluar_condicion({'izq': '{{variables.msg}}', 'op': 'contiene', 'der': 'cotizacion'}, ctx))

    def test_vacio(self):
        self.assertTrue(evaluar_condicion({'izq': '{{variables.no_existe}}', 'op': 'vacio'}, {}))
        self.assertFalse(evaluar_condicion({'izq': '{{variables.no_existe}}', 'op': 'no_vacio'}, {}))

    def test_operador_desconocido_es_false(self):
        self.assertFalse(evaluar_condicion({'izq': 'a', 'op': '???', 'der': 'b'}, {}))
