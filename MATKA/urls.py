from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.urls import re_path

urlpatterns = [
    path('secure-admin-5266/', admin.site.urls),
    path('', include('MATKAAPP.urls')),

] 

handler404 = 'MATKAAPP.views.error_404'
handler500 = 'MATKAAPP.views.error_500'
handler403 = 'MATKAAPP.views.error_403'
handler400 = 'MATKAAPP.views.error_400'

# This line is the "magic" that serves your profile pictures during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
        re_path(r"^static/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}),
    ]