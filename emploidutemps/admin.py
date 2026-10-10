from django.contrib import admin
from .models import EmploiDuTemps, Salle, EmploiDuTempsDocument

@admin.register(Salle)
class SalleAdmin(admin.ModelAdmin):
    list_display = ("nom", "capacite", "description", "created_at")
    search_fields = ("nom", "description")

@admin.register(EmploiDuTemps)
class EmploiDuTempsAdmin(admin.ModelAdmin):
    list_display = ("filiere", "niveau", "module", "formateur", "jour", "heure_debut", "heure_fin", "salle")
    list_filter = ("jour", "filiere", "niveau", "formateur")
    search_fields = ("salle__nom", "filiere__nom", "module__nom", "formateur__nom")

@admin.register(EmploiDuTempsDocument)
class EmploiDuTempsDocumentAdmin(admin.ModelAdmin):
    list_display = ("titre", "classe", "date_effective", "est_actif", "created_at")
    list_filter = ("est_actif", "date_effective", "classe")
    search_fields = ("titre", "classe__nom", "description")


