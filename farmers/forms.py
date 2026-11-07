from django import forms
from .models import DeliveryConfirmation, Farmer


class FarmerForm(forms.ModelForm):
    def __init__(self, *args, district_scope=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.district_scope = district_scope
        if district_scope:
            self.fields['district'].initial = district_scope
            self.fields['district'].disabled = True
        # Apply Bootstrap's form-control class to every field automatically —
        # reuse this pattern in forecasting/inventory/logistics forms later
        # instead of repeating it per app.
        for field in self.fields.values():
            existing_classes = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f"{existing_classes} form-control".strip()

    class Meta:
        model = Farmer
        fields = [
            'first_name', 'last_name', 'national_id', 'phone_number',
            'district', 'ward', 'latitude', 'longitude',
            'farm_size_hectares', 'primary_crop',
        ]


class DeliveryConfirmationForm(forms.ModelForm):
    class Meta:
        model = DeliveryConfirmation
        fields = ['status', 'message']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        self.confirmation_source = kwargs.pop('confirmation_source', 'farmer')
        super().__init__(*args, **kwargs)
        if self.confirmation_source == 'dealer':
            self.fields['status'].choices = [
                ('delivered', 'Delivered'),
                ('issue', 'Issue reported'),
            ]

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('status') == 'issue' and not cleaned_data.get('message'):
            self.add_error('message', 'Please describe the issue so it can be followed up.')
        return cleaned_data