from django.contrib import admin

from .models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("etudiant", "module", "session", "note_finale", "validee")
    list_filter = ("validee", "session", "annee_academique")
    search_fields = ("etudiant__nom", "etudiant__matricule", "module__nom")
    list_editable = ("validee",)
