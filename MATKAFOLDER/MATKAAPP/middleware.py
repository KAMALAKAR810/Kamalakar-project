from django.contrib.sessions.models import Session
from django.shortcuts import redirect
from django.contrib.auth import logout
from django.contrib import messages
from django.conf import settings
import time

class OneSessionPerUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            session_key = request.session.session_key
            try:
                profile = request.user.profile
                # Task 2: If the session key in profile doesn't match current session, logout
                if profile.session_key and profile.session_key != session_key:
                    from django.contrib.sessions.models import Session
                    # Optional: delete the old session from DB
                    Session.objects.filter(session_key=session_key).delete()
                    logout(request)
                    messages.error(request, "You have been logged out because your account was logged in from another device.")
                    return redirect('login')
                elif not profile.session_key and session_key:
                    profile.session_key = session_key
                    profile.save()
            except Exception:
                pass
        
        response = self.get_response(request)
        return response

class SessionTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            current_time = time.time()
            last_activity = request.session.get('last_activity')

            if last_activity:
                elapsed_time = current_time - last_activity
                if elapsed_time > settings.SESSION_TIMEOUT_SECONDS:
                    logout(request)
                    messages.warning(request, "Session expired due to inactivity.")
                    return redirect('login')

            request.session['last_activity'] = current_time
        
        response = self.get_response(request)
        return response
