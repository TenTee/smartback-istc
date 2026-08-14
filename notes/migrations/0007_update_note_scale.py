# Generated manual migration to update Note field scales
from django.db import migrations, models
import django.core.validators

class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0006_note_validee'),
    ]

    operations = [
        migrations.AlterField(
            model_name='note',
            name='note_cc',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Note CC (échelle configurable, ex. 30)', max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)]),
        ),
        migrations.AlterField(
            model_name='note',
            name='note_sn',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Note SN (échelle configurable, ex. 70)', max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)]),
        ),
        migrations.AlterField(
            model_name='note',
            name='note_rattrapage',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Note Rattrapage (échelle configurable, facultatif)', max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)]),
        ),
        migrations.AlterField(
            model_name='note',
            name='note_finale',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Note finale sur 100', max_digits=6, null=True),
        ),
    ]
