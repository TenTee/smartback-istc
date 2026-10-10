from rest_framework import routers
from .views import EmploiDuTempsViewSet, SalleViewSet, EmploiDuTempsDocumentViewSet

router = routers.DefaultRouter()
router.register(r'emploi-du-temps', EmploiDuTempsViewSet)
router.register(r'emploi-du-temps-documents', EmploiDuTempsDocumentViewSet, basename='emploi-du-temps-documents')
router.register(r'salles', SalleViewSet)

urlpatterns = router.urls