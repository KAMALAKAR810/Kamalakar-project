from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'logo.jpeg')),
    path('secure-admin-5266/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('', include('MATKAAPP.urls')),
]

handler404 = 'MATKAAPP.views.error_404'
handler500 = 'MATKAAPP.views.error_500'
handler403 = 'MATKAAPP.views.error_403'
handler400 = 'MATKAAPP.views.error_400'

# Serve media/static only in development.
# In production (PythonAnywhere), configure static/media mappings in the Web tab:
#   /static/  →  /home/<username>/<project>/staticfiles
#   /media/   →  /home/<username>/<project>/media
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)