import csv
import tempfile
from pathlib import Path
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from .models import Farmer, FarmerInputUsage


class FarmerUsageDatasetCommandTests(TestCase):
    def test_registers_twenty_crop_diverse_farmers_and_exports_only_csv_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / 'farmer_events.csv'
            output = StringIO()

            call_command(
                'register_farmers_and_export_usage_events',
                output=str(output_path),
                stdout=output,
            )

            farmers = list(Farmer.objects.order_by('district', 'national_id'))
            self.assertEqual(len(farmers), 20)
            self.assertEqual({farmer.district for farmer in farmers}, {'Kitwe', 'Ndola'})
            self.assertGreaterEqual(len({farmer.primary_crop for farmer in farmers}), 5)
            self.assertEqual(FarmerInputUsage.objects.count(), 0)

            with output_path.open(newline='', encoding='utf-8-sig') as csv_file:
                rows = list(csv.DictReader(csv_file))

            self.assertEqual(len(rows), 5600)
            self.assertEqual(len({row['usage_event_id'] for row in rows}), 5600)
            self.assertEqual({row['season'] for row in rows}, {
                '2017/2018', '2018/2019', '2019/2020', '2020/2021',
                '2021/2022', '2022/2023', '2023/2024', '2024/2025',
            })
            self.assertEqual(
                {int(row['farmer_id']) for row in rows},
                {farmer.pk for farmer in farmers},
            )
            self.assertIn('No FarmerInputUsage records were inserted.', output.getvalue())
