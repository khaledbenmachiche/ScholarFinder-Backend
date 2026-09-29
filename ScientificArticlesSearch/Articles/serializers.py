from django.db import transaction
from rest_framework import serializers
from .models import Article, MotCle, Institution, ReferenceBibliographique, Auteur


class MotCleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MotCle
        fields = "__all__"


class InstitutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Institution
        fields = "__all__"


class ReferenceBibliographiqueSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferenceBibliographique
        fields = "__all__"


class AuteurSerializer(serializers.ModelSerializer):
    institutions = InstitutionSerializer(many=True)

    class Meta:
        model = Auteur
        fields = "__all__"


NESTED_FIELDS = ("mot_cles", "auteurs", "references_bibliographique")


class ArticleSerializer(serializers.ModelSerializer):
    mot_cles = MotCleSerializer(many=True)
    auteurs = AuteurSerializer(many=True)
    references_bibliographique = ReferenceBibliographiqueSerializer(many=True)

    class Meta:
        model = Article
        fields = "__all__"
    
    def create(self, validated_data):
        nested = self._pop_nested(validated_data)
        with transaction.atomic():
            article = Article.objects.create(**validated_data)
            self._set_nested(article, nested)
        return article

    def update(self, instance, validated_data):
        nested = self._pop_nested(validated_data)
        with transaction.atomic():
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()
            # Nested lists are replaced, not appended to, so a moderator's
            # corrected list of authors/keywords/references is the final one.
            self._set_nested(instance, nested)
        return instance

    @staticmethod
    def _pop_nested(validated_data):
        return {name: validated_data.pop(name) for name in NESTED_FIELDS if name in validated_data}

    @staticmethod
    def _set_nested(article, nested):
        if "mot_cles" in nested:
            article.mot_cles.set([MotCle.objects.create(**data) for data in nested["mot_cles"]])
        if "references_bibliographique" in nested:
            article.references_bibliographique.set(
                [ReferenceBibliographique.objects.create(**data) for data in nested["references_bibliographique"]]
            )
        if "auteurs" in nested:
            auteurs = []
            for data in nested["auteurs"]:
                data = dict(data)
                institutions = data.pop("institutions", [])
                auteur = Auteur.objects.create(**data)
                auteur.institutions.set([Institution.objects.create(**inst) for inst in institutions])
                auteurs.append(auteur)
            article.auteurs.set(auteurs)
