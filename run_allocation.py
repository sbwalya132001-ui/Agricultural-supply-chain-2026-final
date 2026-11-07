#!/usr/bin/env python
import argparse
import os
import django
from decimal import Decimal
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fisp_system.settings')
django.setup()

from inventory.services import run_inventory_allocation
from farmers.models import FarmerInputUsage

parser = argparse.ArgumentParser(description='Run an inventory allocation with explicit supply and costs.')
INPUT_TYPES = tuple(input_type for input_type, _ in FarmerInputUsage.INPUT_TYPE_CHOICES)
for input_type in INPUT_TYPES:
    parser.add_argument(f'--supply-{input_type}', type=Decimal, required=True)
    parser.add_argument(f'--cost-{input_type}', type=Decimal, required=True)
args = parser.parse_args()
supply = {input_type: getattr(args, f'supply_{input_type}') for input_type in INPUT_TYPES}
costs = {input_type: getattr(args, f'cost_{input_type}') for input_type in INPUT_TYPES}

result = run_inventory_allocation(supply, costs)

print(f"\n=== Inventory Allocation Results ===")

if result['error']:
    print(f"ERROR: {result['error']}")
else:
    print(f"Succeeded: {len(result['succeeded'])} allocations")
    for allocation in result['succeeded'][:5]:  # Show first 5
        print(f"  - {allocation.district} / {allocation.get_input_type_display()}: {allocation.allocated_quantity_kg}kg @ ${allocation.cost_per_unit}/kg = ${allocation.total_cost}")
    if len(result['succeeded']) > 5:
        print(f"  ... and {len(result['succeeded']) - 5} more")

if result['skipped']:
    print(f"\nSkipped (no solution): {len(result['skipped'])}")
    for district, input_type in result['skipped']:
        print(f"  - {district} / {input_type}")

print(f"\nAllocation optimization complete!")
