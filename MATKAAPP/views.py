from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from .models import MatkaNumber, Profile

def login_view(request):
    # If user is already logged in, don't show the login page    
    if request.user.is_authenticated:
        return redirect('index')
    
    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('index')
        else:
            messages.error(request, "Invalid username or password.")
            return redirect('login')

    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    messages.info(request, "You have successfully logged out.")
    return redirect('index')

def register_view(request):
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        name = request.POST.get('name')
        username = request.POST.get('username')
        password = request.POST.get('password')
        mobile = request.POST.get('mobile')
        profile_pic = request.FILES.get('profile_pic')

        # Check if username already exists
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken!")
            return render(request, 'register.html')

        # 1. Create User (This triggers the signal in models.py)
        user = User.objects.create_user(
            username=username, 
            password=password,
            first_name=name
        )

        # 2. Update the profile automatically created by the signal
        # Use hasattr check just in case the signal failed
        if hasattr(user, 'profile'):
            profile = user.profile
            profile.mobile = mobile
            if profile_pic:
                profile.profile_pic = profile_pic
            profile.save()

        messages.success(request, "Registration successful! Please login.")
        return redirect('login')

    return render(request, 'register.html')

def index(request):
    """
    Main index page view. 
    Fetches matka_numbers so that the template has data to display.
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