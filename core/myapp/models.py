# models.py
from django.db import models
from django.contrib.auth.models import AbstractBaseUser

from django.db import models
from django.contrib.auth.models import AbstractBaseUser

class Auteur(models.Model):
    nom = models.CharField(max_length=255)
    prenom = models.CharField(max_length=255)
    institutions = models.ManyToManyField('Institution', related_name='auteurs')

class Institution(models.Model):
    nom = models.CharField(max_length=255, blank=True)

class MotCle(models.Model):
    libelle = models.CharField(max_length=50)

class ReferenceBibliographique(models.Model):
    reference = models.CharField(max_length=255, blank=True)

class Article(models.Model):
    titre = models.CharField(max_length=255, blank=True)
    resume = models.TextField(blank=True)
    texte_integrale = models.TextField(blank=True)
    url_pdf = models.CharField(max_length=255)
    date_publication = models.DateField()
    auteurs = models.ManyToManyField('Auteur', related_name='article_auteurs')
    mots_cles = models.ManyToManyField('MotCle', related_name='article_mots_cles')
    references_bibliographiques = models.ManyToManyField('ReferenceBibliographique', related_name='article_references_bibliographiques')

class User(AbstractBaseUser):
    
    # UserName et Password dans la class par défaut
    
    user_type_choices = [
        ('admin', 'Admin'),
        ('regular', 'Regular'),
        ('moderator', 'Moderator'),
    ]

    user_type = models.CharField(max_length=10, choices=user_type_choices)
    nom = models.CharField(max_length=30)
    prenom = models.CharField(max_length=30)
    email = models.EmailField(unique=True)
    favorites = models.ManyToManyField('Article', related_name='user_article_favorites')
    
    

# migrations file    
# from django.db import migrations
# from django.contrib.auth.hashers import make_password

# def create_admin_user(apps, schema_editor):
#     User = apps.get_model('yourappname', 'User')
#     admin_user = User(
#         username="admin",
#         password=make_password("admin"),
#         nom="admin",
#         prenom="admin",
#         email="admin@admin.com",
#         user_type="admin",
#     )
#     admin_user.save()

# class Migration(migrations.Migration):

#     dependencies = [
#         # Add your dependencies here
#     ]

#     operations = [
#         migrations.RunPython(create_admin_user),
#     ]
