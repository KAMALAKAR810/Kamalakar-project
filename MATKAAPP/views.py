# from django.shortcuts import render
# from django.http import HttpResponse

# # Create your views here.
# def index(request):
#     return render(request, 'index.html')

# def error(request):
#     return render(request, 'error.html')

# def display(request):
#     from .models import MatkaNumber
#     matka_numbers = MatkaNumber.objects.all()
#     return render(request, 'display.html', {'matka_numbers': matka_numbers})
     
     
# from django.shortcuts import render
# from django.http import HttpResponse
# from .models import MatkaNumber # Standard import location

# def index(request):
#     return render(request, 'index.html')

# def error(request):
#     return render(request, 'error.html')

# def display(request):
#     matka_numbers = MatkaNumber.objects.all()
#     return render(request, 'display.html', {'matka_numbers': matka_numbers})

from django.shortcuts import render
from django.http import HttpResponse
from .models import MatkaNumber

def index(request):
    """
    Main index page view. 
    Fetches matka_numbers so that the {% include 'display.html' %} 
    tag inside index.html has data to display.
    """
    matka_numbers = MatkaNumber.objects.all()
    context = {
        'matka_numbers': matka_numbers,
    }
    return render(request, 'index.html', context)

def display(request):
    """
    Standalone display page view.
    Useful if you want to view just the table at /display/
    """
    matka_numbers = MatkaNumber.objects.all()
    context = {
        'matka_numbers': matka_numbers,
    }
    return render(request, 'display.html', context)

def error(request):
    """
    Error page view.
    """
    return render(request, 'error.html')