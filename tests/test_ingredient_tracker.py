import io
import json
import os
import re
import tempfile
import unittest
from datetime import date

# Point at a throwaway database before the app reads its config.
_db_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_db_file.close()
os.environ['DATABASE_URL'] = 'sqlite:///' + _db_file.name

from app import create_app
from app.extensions import db
from app.models import IngredientPrice
from app.routes.ingredient_tracker import build_ingredient_chart_data


def _entry(name, report_date, unit_price, quantity=1, amount=None, row_id=None):
    return IngredientPrice(
        id=row_id,
        ingredient_name=name,
        date=report_date,
        unit_price=unit_price,
        quantity=quantity,
        amount=amount if amount is not None else unit_price * quantity,
        unit='Kg',
        item_code='1',
        discount=0,
        cgst_tax=0,
        sgst_tax=0,
        igst_tax=0,
        non_gst_tax=0,
        total=amount if amount is not None else unit_price * quantity,
    )


class ChartSeriesTests(unittest.TestCase):
    def test_history_stays_in_order_when_newer_and_duplicate_rows_arrive(self):
        entries = [
            _entry('Tomato', date(2025, 6, 13), 40, quantity=10, row_id=5),
            _entry('Tomato', date(2025, 6, 13), 35.46, quantity=8, row_id=162),
            _entry('Tomato', date(2025, 6, 13), 35.46, quantity=8, row_id=304),
            _entry('Tomato', date(2025, 4, 3), 35.46, quantity=8, row_id=400),
            _entry('Tomato', date(2025, 4, 3), 35.46, quantity=8, row_id=401),
            _entry('Tomato', date(2025, 2, 1), 45, quantity=3, row_id=500),
        ]

        ingredient_data, stats, _, _ = build_ingredient_chart_data(entries)
        points = ingredient_data['Tomato']

        self.assertEqual(
            [point['date'] for point in points],
            ['2025-02-01', '2025-04-03', '2025-06-13'],
        )
        self.assertEqual(points[0]['unit_price'], 45)
        self.assertEqual(points[1]['unit_price'], 35.46)
        # Same-day prices are kept as one point instead of snapping back to a duplicate.
        self.assertEqual(points[2]['unit_price'], round((40 + 35.46) / 2, 2))
        self.assertEqual(stats['Tomato']['count'], 3)
        self.assertEqual([point['date'] for point in points], sorted(point['date'] for point in points))


class UploadHistoryTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            db.session.add(_entry('Tomato', date(2025, 1, 15), 45, quantity=4, amount=180))
            db.session.add(_entry('Onion', date(2025, 2, 2), 30, quantity=6, amount=180))
            db.session.commit()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['user'] = {'email': 'ops@dosacoffee.in', 'name': 'Ops User'}

    def _workbook(self, rows):
        import pandas as pd
        frame = pd.DataFrame(
            [['Posist Stock Entry Report'] + [''] * 11, ['Range'] + [''] * 11, [''] * 12] + rows
        )
        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False, header=False)
        buffer.seek(0)
        return buffer

    def _upload(self, rows, report_date, filename='entry.xlsx'):
        self._login()
        response = self.client.post(
            '/ingredient-tracker/upload',
            data={
                'files': (self._workbook(rows), filename),
                'report_dates': report_date,
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 302)
        return response

    def _tomato_points(self):
        self._login()
        response = self.client.get('/ingredient-tracker/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        match = re.search(r'const ingredientData = (\{.*?\});', html, re.S)
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        return payload['Tomato']

    def test_new_report_appends_a_point_and_keeps_stored_values(self):
        self._upload(
            [[141, 'Tomato', 12, 'Kg', 55, 660, 0, 0, 0, 0, 0, 660]],
            '2025-07-01',
        )

        points = self._tomato_points()
        self.assertEqual([point['date'] for point in points], ['2025-01-15', '2025-07-01'])
        self.assertEqual([point['unit_price'] for point in points], [45, 55])

        with self.app.app_context():
            stored = IngredientPrice.query.filter_by(ingredient_name='Onion').all()
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].date, date(2025, 2, 2))
            self.assertEqual(stored[0].unit_price, 30)

    def test_reupload_does_not_reset_or_duplicate_the_series(self):
        rows = [[141, 'Tomato', 12, 'Kg', 55, 660, 0, 0, 0, 0, 0, 660]]
        self._upload(rows, '2025-07-01', filename='july.xlsx')
        self._upload(rows, '2025-07-01', filename='july-again.xlsx')

        points = self._tomato_points()
        self.assertEqual([point['date'] for point in points], ['2025-01-15', '2025-07-01'])
        self.assertEqual([point['unit_price'] for point in points], [45, 55])

        with self.app.app_context():
            july_rows = IngredientPrice.query.filter_by(
                ingredient_name='Tomato',
                date=date(2025, 7, 1),
            ).count()
            self.assertEqual(july_rows, 1)

    def test_failed_upload_does_not_wipe_existing_points(self):
        self._upload(
            [[141, 'Tomato', 12, 'Kg', 55]],
            '2025-08-01',
            filename='broken.xlsx',
        )
        points = self._tomato_points()
        self.assertEqual([point['date'] for point in points], ['2025-01-15'])
        self.assertEqual(points[0]['unit_price'], 45)

    def test_upload_page_still_links_to_posist(self):
        self._login()
        response = self.client.get('/ingredient-tracker/upload')
        html = response.get_data(as_text=True)
        self.assertIn('https://dosacoffee.posist.biz/eStock/reports/entryReport#', html)
        self.assertIn('Stock Entry Posist Reports', html)


if __name__ == '__main__':
    unittest.main()
