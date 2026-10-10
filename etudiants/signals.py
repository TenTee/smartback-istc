from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Etudiant, Inscription
from notes.models import Note
from users.models import CustomUser


@receiver(post_save, sender=Etudiant)
def create_user_for_etudiant(sender, instance, created, **kwargs):
    """
    Lorsqu'un étudiant est créé :
    - Création automatique d'un compte utilisateur (CustomUser)
    - Association du compte à l'étudiant
    - Stockage du mot de passe initial pour l'administrateur
    """
    if created and not instance.user:
        parts = instance.nom.split(' ', 1)
        nom = parts[0]
        prenom = parts[1] if len(parts) > 1 else ""

        clean_email = (instance.email or "").strip().lower()
        existing_user = CustomUser.objects.filter(email__iexact=clean_email).first()

        if existing_user:
            # On ne rattache un compte existant que s'il s'agit d'un compte étudiant libre :
            # auparavant, un étudiant créé avec l'email d'un membre du personnel ou d'un
            # administrateur récupérait ce compte (et ses droits).
            already_linked = Etudiant.objects.filter(user=existing_user).exclude(pk=instance.pk).exists()
            if existing_user.role != "etudiant" or already_linked:
                return
            user = existing_user
            raw_password = None
        else:
            user = CustomUser.objects.create(
                noms=nom,
                prenoms=prenom,
                email=clean_email,
                role="etudiant",
            )
            raw_password = getattr(user, '_raw_password', None)

        instance.user = user
        instance.initial_password = raw_password
        instance.save(update_fields=['user', 'initial_password'])

@receiver(post_save, sender=Inscription)
def create_or_update_notes_on_inscription(sender, instance, created, **kwargs):
    """
    ✅ Lorsqu'une inscription est ajoutée ou modifiée :
    - Génération des notes basées sur les modules de la CLASSE
    """
    if not instance.classe:
        return

    # Modules de la classe
    current_modules = set(instance.classe.modules.all())
    
    # Une seule note par module, dans le semestre auquel appartient le module.
    # (Auparavant une note vide était créée pour CHAQUE semestre : chaque module
    # apparaissait en double, et la saisie groupée modifiait l'une ou l'autre au hasard.)
    for module in current_modules:
        Note.objects.get_or_create(
            etudiant=instance.etudiant,
            module=module,
            classe=instance.classe,
            evaluation=None,
            session=module.semestre or "Semestre 1",
        )


@receiver(post_delete, sender=Etudiant)
def deactivate_user_on_etudiant_delete(sender, instance, **kwargs):
    """
    Lorsqu'un étudiant est supprimé, son compte portail est désactivé (comme pour
    les formateurs) : il ne doit plus pouvoir se connecter.
    Les notes sont supprimées automatiquement (on_delete=CASCADE).
    """
    user_id = instance.user_id
    if user_id:
        CustomUser.objects.filter(pk=user_id, role="etudiant").update(is_active=False)