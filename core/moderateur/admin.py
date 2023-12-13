from django.contrib import admin
from .models import Institution, MotCle, ReferenceBibliographique, Auteur, Article, User
# Register your models here.

admin.site.register(Institution)
admin.site.register(MotCle)
admin.site.register(ReferenceBibliographique)
admin.site.register(Auteur)
admin.site.register(Article)
admin.site.register(User)