from decimal import Decimal, ROUND_HALF_UP
from django.db import migrations


def forwards(apps, schema_editor):
    Note = apps.get_model('notes', 'Note')
    ParametresGlobaux = apps.get_model('academique', 'ParametresGlobaux')

    # Get current parameters (there should be a single row)
    params = ParametresGlobaux.objects.first()
    if params is None:
        # fallback to defaults
        pc = Decimal('30')
        psn = Decimal('70')
    else:
        pc = Decimal(str(params.pourcentage_cc or 30))
        psn = Decimal(str(params.pourcentage_sn or 70))

    notes = Note.objects.all()
    for n in notes:
        changed = False

        # Convert component scores from scale 20 -> scale of weight (pc/psn)
        if n.note_cc is not None:
            try:
                old_cc = Decimal(str(n.note_cc))
                new_cc = (old_cc / Decimal('20')) * pc
                n.note_cc = new_cc.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                changed = True
            except Exception:
                pass

        if n.note_sn is not None:
            try:
                old_sn = Decimal(str(n.note_sn))
                new_sn = (old_sn / Decimal('20')) * psn
                n.note_sn = new_sn.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                changed = True
            except Exception:
                pass

        if n.note_rattrapage is not None:
            try:
                old_r = Decimal(str(n.note_rattrapage))
                # rattrapage uses SN scale
                new_r = (old_r / Decimal('20')) * psn
                n.note_rattrapage = new_r.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                changed = True
            except Exception:
                pass

        # Convert final score from scale 20 -> 100
        if n.note_finale is not None:
            try:
                old_final = Decimal(str(n.note_finale))
                new_final = (old_final / Decimal('20')) * Decimal('100')
                n.note_finale = new_final.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                changed = True
            except Exception:
                pass

        if changed:
            n.save(update_fields=['note_cc', 'note_sn', 'note_rattrapage', 'note_finale'])


def reverse(apps, schema_editor):
    # Reverse conversion: from 100 back to 20 (used only if rollback required)
    Note = apps.get_model('notes', 'Note')
    ParametresGlobaux = apps.get_model('academique', 'ParametresGlobaux')

    params = ParametresGlobaux.objects.first()
    if params is None:
        pc = Decimal('30')
        psn = Decimal('70')
    else:
        pc = Decimal(str(params.pourcentage_cc or 30))
        psn = Decimal(str(params.pourcentage_sn or 70))

    notes = Note.objects.all()
    for n in notes:
        changed = False
        if n.note_cc is not None:
            try:
                new_cc = (Decimal(str(n.note_cc)) / pc) * Decimal('20') if pc > 0 else Decimal('0')
                n.note_cc = new_cc.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                changed = True
            except Exception:
                pass
        if n.note_sn is not None:
            try:
                new_sn = (Decimal(str(n.note_sn)) / psn) * Decimal('20') if psn > 0 else Decimal('0')
                n.note_sn = new_sn.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                changed = True
            except Exception:
                pass
        if n.note_rattrapage is not None:
            try:
                new_r = (Decimal(str(n.note_rattrapage)) / psn) * Decimal('20') if psn > 0 else Decimal('0')
                n.note_rattrapage = new_r.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                changed = True
            except Exception:
                pass
        if n.note_finale is not None:
            try:
                new_final = (Decimal(str(n.note_finale)) / Decimal('100')) * Decimal('20')
                n.note_finale = new_final.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                changed = True
            except Exception:
                pass
        if changed:
            n.save(update_fields=['note_cc', 'note_sn', 'note_rattrapage', 'note_finale'])


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0007_update_note_scale'),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]
