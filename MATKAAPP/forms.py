from django import forms
from .models import Market

class MarketForm(forms.ModelForm):
    class Meta:
        model = Market
        fields = ["name", "open_time", "close_time"]

    # Override default widgets with custom format
    open_time = forms.DateTimeField(
        input_formats=["%d:%m:%Y %I:%M %p"],
        widget=forms.DateTimeInput(
            format="%d:%m:%Y %I:%M %p",
            attrs={"class": "form-control", "placeholder": "dd:mm:yyyy hh:mm AM/PM"}
        )
    )

    close_time = forms.DateTimeField(
        input_formats=["%d:%m:%Y %I:%M %p"],
        widget=forms.DateTimeInput(
            format="%d:%m:%Y %I:%M %p",
            attrs={"class": "form-control", "placeholder": "dd:mm:yyyy hh:mm AM/PM"}
        )
    )


# forms.py
from django import forms
from .models import MarketBet

class MarketBetForm(forms.ModelForm):
    class Meta:
        model = MarketBet
        fields = ['market', 'session', 'number', 'amount']

