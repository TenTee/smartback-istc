from django.contrib import admin

from .models import Coordination, PointageEnseignant, RecapMensuel


@admin.register(Coordination)
class CoordinationAdmin(admin.ModelAdmin):
    list_display = ("formateur", "filiere", "est_active", "date_debut", "date_fin")
    list_filter = ("est_active", "filiere")
    search_fields = ("formateur__nom", "filiere__nom")


@admin.register(PointageEnseignant)
class PointageEnseignantAdmin(admin.ModelAdmin):
    list_display = ("date", "formateur", "filiere", "module", "statut", "heure_arrivee", "heure_fin", "heures_calculees", "heures_corrigees")
    list_filter = ("statut", "filiere", "date")
    search_fields = ("formateur__nom", "module__nom", "classe__nom")
    date_hierarchy = "date"


@admin.register(RecapMensuel)
class RecapMensuelAdmin(admin.ModelAdmin):
    list_display = ("formateur", "filiere", "mois", "annee", "total_heures", "montant", "statut")
    list_filter = ("statut", "annee", "mois", "filiere")
    search_fields = ("formateur__nom",)
