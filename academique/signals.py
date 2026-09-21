from django.db.models.signals import post_save
from django.dispatch import receiver

from academique.models import Filiere, Specialite, Cycle, Niveau, Classe, AnneeAcademique


def _get_target_annees():
    return AnneeAcademique.objects.all()


def _create_classes_for(cycle, niveau, filiere=None, specialite=None):
    if not filiere and cycle.filiere:
        filiere = cycle.filiere
    if not specialite and cycle.specialite:
        specialite = cycle.specialite
        if not filiere and specialite:
            filiere = specialite.filiere
    années = _get_target_annees()
    created = []
    for an in années:
        exists = Classe.objects.filter(
            specialite=specialite,
            filiere=filiere,
            cycle=cycle,
            niveau=niveau,
            annee_academique=an
        ).exists()
        if not exists:
            classe = Classe.objects.create(
                specialite=specialite,
                filiere=filiere,
                cycle=cycle,
                niveau=niveau,
                annee_academique=an
            )
            created.append(classe)
    return created


@receiver(post_save, sender=Cycle)
def on_cycle_created(sender, instance, created, **kwargs):
    if not created:
        return
    for niveau in instance.niveaux.all():
        _create_classes_for(instance, niveau, filiere=instance.filiere, specialite=instance.specialite)


@receiver(post_save, sender=Niveau)
def on_niveau_created(sender, instance, created, **kwargs):
    if not created:
        return
    cycle = instance.cycle
    _create_classes_for(cycle, instance, filiere=cycle.filiere, specialite=cycle.specialite)


@receiver(post_save, sender=Specialite)
def on_specialite_created(sender, instance, created, **kwargs):
    if not created:
        return
    for cycle in instance.cycles.all():
        for niveau in cycle.niveaux.all():
            _create_classes_for(cycle, niveau, filiere=instance.filiere, specialite=instance)


@receiver(post_save, sender=Filiere)
def on_filiere_created(sender, instance, created, **kwargs):
    if not created:
        return
    for cycle in instance.cycles.all():
        for niveau in cycle.niveaux.all():
            _create_classes_for(cycle, niveau, filiere=instance)


@receiver(post_save, sender=AnneeAcademique)
def on_annee_academique_created(sender, instance, created, **kwargs):
    if not created:
        return
    source_annee = (
        AnneeAcademique.objects.filter(est_active=True).exclude(pk=instance.pk).first()
        or AnneeAcademique.objects.exclude(pk=instance.pk).order_by('-libelle').first()
    )
    if not source_annee:
        return
    for classe in Classe.objects.filter(annee_academique=source_annee):
        prefix = classe.specialite.nom if classe.specialite else (classe.filiere.nom if classe.filiere else "")
        Classe.objects.get_or_create(
            specialite=classe.specialite,
            filiere=classe.filiere,
            cycle=classe.cycle,
            niveau=classe.niveau,
            annee_academique=instance,
            defaults={"nom": f"{prefix} {classe.cycle.nom} {classe.niveau.ordre} ({instance.libelle})"},
        )
