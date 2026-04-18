from django import forms
from django_recaptcha.fields import ReCaptchaField
from django_recaptcha.widgets import ReCaptchaV2Checkbox

class MyContactForm(forms.Form):
    name = forms.CharField(max_length=100)
    email = forms.EmailField()
    # This adds the "I'm not a robot" checkbox
    # captcha = ReCaptchaField(widget=ReCaptchaV2Checkbox)