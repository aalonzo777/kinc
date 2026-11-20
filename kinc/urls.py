from django.contrib import admin
from django.urls import path, include

# Nota: ya NO se sirve /media/ públicamente. Las fotos se entregan solo con sesión
# iniciada y permisos (ver core.views.proof_image).
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]
