# """
# WSGI config for MATKA project.

# It exposes the WSGI callable as a module-level variable named ``application``.

# For more information on this file, see
# https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
# """

# import os

# from django.core.wsgi import get_wsgi_application

# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MATKA.settings')

# application = get_wsgi_application()



"""
WSGI config for MATKA project.

It exposes the WSGI callable as a module-level variable named ``application``.
"""

import os
import threading
import requests
import time
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MATKA.settings')

application = get_wsgi_application()

# --- KEEP ALIVE CODE START ---
def keep_alive():
    # Replace this with your actual Render URL
    url = "https://matka-project.onrender.com" 
    while True:
        try:
            # Pings the site to prevent it from idling
            requests.get(url)
            print("Keep-alive ping successful.")
        except Exception as e:
            print(f"Keep-alive ping failed: {e}")
        
        # Sleep for 14 minutes (Render sleeps after 15 minutes of inactivity)
        time.sleep(840) 

# Start the keep-alive thread in the background
# This will run as soon as Gunicorn starts the application on Render
threading.Thread(target=keep_alive, daemon=True).start()
# --- KEEP ALIVE CODE END ---