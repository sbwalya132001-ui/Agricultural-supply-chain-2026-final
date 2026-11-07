from django import forms

from farmers.models import FarmerInputUsage
from logistics.models import AgroDealer, Supplier

from .models import SupplierDispatch


class InventoryAllocationForm(forms.Form):
    INPUT_TYPES = tuple(input_type for input_type, _ in FarmerInputUsage.INPUT_TYPE_CHOICES)
    INPUT_LABELS = dict(FarmerInputUsage.INPUT_TYPE_CHOICES)
    QUANTITY_SOURCE_CHOICES = (
        ('baseline', 'ARIMA Baseline / Allocation quantity'),
        ('zmd_scenario', 'ZMD Scenario Quantity (kg)'),
        ('seas5_scenario', 'ECMWF SEAS5 Scenario Quantity (kg)'),
    )

    allocation_quantity_source = forms.ChoiceField(
        choices=QUANTITY_SOURCE_CHOICES,
        initial='baseline',
        required=False,
        label='Allocation quantity source',
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, supply_totals=None, **kwargs):
        super().__init__(*args, **kwargs)
        supply_totals = supply_totals or {}
        for input_type in self.INPUT_TYPES:
            self.fields[f'supply_{input_type}'] = forms.DecimalField(
                min_value=0,
                decimal_places=2,
                max_digits=12,
                label=f'{self.INPUT_LABELS[input_type]} forecast total (kg)',
                initial=supply_totals.get(input_type, 0),
                disabled=True,
                widget=forms.NumberInput(attrs={
                    'class': 'form-control',
                    'step': '0.01',
                    'aria-label': f'{self.INPUT_LABELS[input_type]} forecast total in kilograms',
                }),
            )
            self.fields[f'cost_{input_type}'] = forms.DecimalField(
                min_value=0,
                decimal_places=2,
                max_digits=10,
                label=f'{self.INPUT_LABELS[input_type]} cost per kg',
                widget=forms.NumberInput(attrs={
                    'class': 'form-control',
                    'min': '0',
                    'step': '0.01',
                    'placeholder': 'Enter price per kg',
                }),
            )


class SupplierDispatchForm(forms.ModelForm):
    class Meta:
        model = SupplierDispatch
        fields = ['supplier', 'agro_dealer', 'input_type', 'quantity_kg']
        widgets = {
            'quantity_kg': forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
        }

    def __init__(self, *args, district_scope=None, **kwargs):
        super().__init__(*args, **kwargs)
        if district_scope:
            self.fields['supplier'].queryset = Supplier.objects.filter(
                district__iexact=district_scope,
                is_active=True,
            )
            self.fields['agro_dealer'].queryset = AgroDealer.objects.filter(
                district__iexact=district_scope,
            )
        else:
            self.fields['supplier'].queryset = Supplier.objects.filter(is_active=True)
            self.fields['agro_dealer'].queryset = AgroDealer.objects.all()

    def clean_quantity_kg(self):
        quantity = self.cleaned_data['quantity_kg']
        if quantity <= 0:
            raise forms.ValidationError('Dispatch quantity must be greater than zero.')
        return quantity