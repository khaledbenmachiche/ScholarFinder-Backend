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
    nom = models.CharField(max_length=255, blank=True, null=False)

class MotCle(models.Model):
    libelle = models.CharField(max_length=50, null=False)

class ReferenceBibliographique(models.Model):
    reference = models.CharField(max_length=255, blank=True, null=False)

class Article(models.Model):
    titre = models.CharField(max_length=255, blank=True, null=False)
    resume = models.TextField(blank=True)
    texte_integrale = models.TextField(blank=True, null=False)
    url_pdf = models.URLField(null=False)
    date_publication = models.DateField()
    is_valide = models.BooleanField(default=False, null=False)
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
    

    user_type = models.CharField(max_length=10, choices=user_type_choices, null=False)
    nom = models.CharField(max_length=30, null=False)
    prenom = models.CharField(max_length=30, null=False)
    # user_name = models.CharField(max_length=50, null=False)
    email = models.EmailField(unique=True, null=False)
    favorites = models.ManyToManyField('Article', related_name='user_article_favorites')
    # USERNAME_FIELD = 'user_name'
    