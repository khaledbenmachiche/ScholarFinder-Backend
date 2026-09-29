from django.db import migrations, models


class Migration(migrations.Migration):
    # GROBID titles regularly exceed 200 characters, and public PDF links exceed 100.

    dependencies = [
        ("Articles", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="article",
            name="titre",
            field=models.CharField(max_length=500),
        ),
        migrations.AlterField(
            model_name="article",
            name="url",
            field=models.CharField(max_length=500),
        ),
    ]
