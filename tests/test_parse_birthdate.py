"""
Test unitario de pac.io.parse_birthdate.

La regla de parseo es la única transformación no trivial de Etapa 0,
así que vale la pena blindarla con tests explícitos de los casos observados
en la cohorte real + edge cases.

Ejecutar desde la raíz del proyecto:
    python -m tests.test_parse_birthdate
o con pytest (si está instalado):
    pytest tests/
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

# Permitir `from pac.io import parse_birthdate` corriendo desde la raíz
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from pac.io import parse_birthdate  # noqa: E402


class TestParseBirthdate(unittest.TestCase):
    """Casos de la cohorte real + edge cases."""

    # -- yy ≤ 25 → 20yy, flag_audit = 1 (año resuelto >= 2000) ---------------

    def test_salvador_2009(self):
        """687 Salvador Martinez: 28/7/09 → 2009-07-28, flag=1."""
        d, flag = parse_birthdate("28/7/09")
        self.assertEqual(d, date(2009, 7, 28))
        self.assertEqual(flag, 1)

    def test_ano_25_frontera_superior(self):
        """25 es el pivot inclusivo → 2025."""
        d, flag = parse_birthdate("1/1/25")
        self.assertEqual(d, date(2025, 1, 1))
        self.assertEqual(flag, 1)

    # -- yy > 25 → 19yy, flag_audit = 0 ---------------------------------------

    def test_roberto_1965(self):
        """688 Roberto Inza: 8/7/65 → 1965-07-08, flag=0."""
        d, flag = parse_birthdate("8/7/65")
        self.assertEqual(d, date(1965, 7, 8))
        self.assertEqual(flag, 0)

    def test_domingo_1939(self):
        """336 Domingo Catena: 12/11/39 → 1939-11-12, flag=0."""
        d, flag = parse_birthdate("12/11/39")
        self.assertEqual(d, date(1939, 11, 12))
        self.assertEqual(flag, 0)

    def test_ano_26_frontera_inferior(self):
        """26 está fuera del pivot → 1926."""
        d, flag = parse_birthdate("1/1/26")
        self.assertEqual(d, date(1926, 1, 1))
        self.assertEqual(flag, 0)

    # -- yyyy de 4 dígitos → literal, flag_audit = 0 --------------------------

    def test_ano_4_digitos_no_flaggea(self):
        """Si el año viene explícito en 4 dígitos, no hay ambigüedad."""
        d, flag = parse_birthdate("10/7/2009")
        self.assertEqual(d, date(2009, 7, 10))
        self.assertEqual(flag, 0)

    # -- inválidos → (None, 0) ------------------------------------------------

    def test_vacio(self):
        self.assertEqual(parse_birthdate(""), (None, 0))

    def test_none(self):
        self.assertEqual(parse_birthdate(None), (None, 0))

    def test_nan_literal(self):
        self.assertEqual(parse_birthdate("nan"), (None, 0))

    def test_formato_incorrecto(self):
        self.assertEqual(parse_birthdate("1965-07-08"), (None, 0))

    def test_fecha_imposible(self):
        """31 de febrero no existe."""
        d, flag = parse_birthdate("31/2/90")
        self.assertIsNone(d)

    def test_componentes_no_numericos(self):
        self.assertEqual(parse_birthdate("abc/def/ghi"), (None, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
