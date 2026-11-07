from django import forms


class DemandDataUploadForm(forms.Form):
    demand_file = forms.FileField(
        label='Historical demand file',
        help_text=(
            'Upload CSV or Excel with national_id, season, input_type, and quantity_kg. '
            'For multiple events in the same season/input, include a unique usage_event_id column.'
        ),
    )

    def clean_demand_file(self):
        uploaded_file = self.cleaned_data['demand_file']
        filename = uploaded_file.name.lower()
        if not filename.endswith(('.csv', '.xlsx')):
            raise forms.ValidationError('Upload a CSV or Excel file (.csv or .xlsx).')
        return uploaded_file