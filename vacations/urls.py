from rest_framework.routers import DefaultRouter

from .views import (
    CoordinationViewSet,
    PointageEnseignantViewSet,
    CoordonnateurViewSet,
    MesHeuresViewSet,
    RecapAdminViewSet,
)

router = DefaultRouter()
router.register(r"coordinations", CoordinationViewSet, basename="vacations-coordinations")
router.register(r"pointages", PointageEnseignantViewSet, basename="vacations-pointages")
router.register(r"coordonnateur", CoordonnateurViewSet, basename="vacations-coordonnateur")
router.register(r"mes-heures", MesHeuresViewSet, basename="vacations-mes-heures")
router.register(r"recaps", RecapAdminViewSet, basename="vacations-recaps")

urlpatterns = router.urls
