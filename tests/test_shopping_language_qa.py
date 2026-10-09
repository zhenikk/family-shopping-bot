"""User-facing regression corpus: deterministic parser behavior, without API calls."""
import unittest
from shopping_bot.store import parse_items

class ShoppingLanguageQA(unittest.TestCase):
    def test_user_phrase_matrix(self):
        cases = [
            ('купи дві пачки масла', [('Масло', '2 пачки')]),
            ('купи дві буханки хліба', [('Хліб', '2 буханки')]),
            ('купи одне молоко без лактози', [('Молоко без лактози', '1 шт.')]),
            ('купи дві пачки масла без лактози', [('Масло без лактози', '2 пачки')]),
            ('1.5 л молока', [('Молоко', '1.5 л')]),
            ('2 кг картоплі', [('Картопля', '2 кг')]),
            ('12 яєць', [('Яйця', '12 шт.')]),
            ('купи 7 up', [('7 up', None)]),
            ('buy two bottles of milk', [('Milk', '2 bottles')]),
            ('buy one loaf of bread', [('Bread', '1 loaf')]),
            ('купи молоко :: 2 л; без лактози', [('Молоко без лактози', '2 л')]),
            ('купи хліб, хліб', [('Хліб', None)]),
            ('Не купуй молоко, купи хліб', [('Хліб', None)]),
            ('купи молоко, ні, краще кефір', [('Кефір', None)]),
            ('buy milk, milk', [('Milk', None)]),
            ('buy milk and bread', [('Milk', None), ('Bread', None)]),
            ('купи 1 л молока і 2 кг картоплі', [('Молоко', '1 л'), ('Картопля', '2 кг')]),
            ('творог', [('Сир кисломолочний', None)]),
            ('купи хліб, ні, краще молоко', [('Молоко', None)]),
            ('do not buy milk, buy bread', [('Bread', None)]),
            ('купи молоко :: без лактози', [('Молоко без лактози', None)]),
            ('купи молоко :: в Mercadona', [('Молоко', 'в Mercadona')]),
            ('купи молоко @Lidl', [('Молоко', 'Lidl')]),
            ('купи одну пачку масла', [('Масло', '1 пачка')]),
            ('купи дві пачки масла :: без лактози', [('Масло без лактози', '2 пачки')]),
            ('thanks', []), ('дякую', []), ('', []),
            ('купи молоко без лактози і молоко', [('Молоко без лактози', None), ('Молоко', None)]),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_items(text), expected)

    def test_input_boundaries(self):
        self.assertEqual(parse_items('x' * 121), [])
        self.assertEqual(parse_items('молоко :: ' + 'x' * 201), [])
        self.assertEqual(parse_items('молоко\n\nхліб'), [('Молоко', None), ('Хліб', None)])
