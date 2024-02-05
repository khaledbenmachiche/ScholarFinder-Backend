from rest_framework import serializers
from Articles.models import Article, Auteur, Institution

class InstitutionSearchResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = Institution
        fields = ["id", "nom"]
        ref_name = 'InstitutionSearchResultSerializer'

class AuteurSearchResultSerializer(serializers.ModelSerializer):
    institutions = InstitutionSearchResultSerializer(many=True)    
    class Meta:
        model = Auteur
        fields = ["id", "nom","institutions"]
        ref_name = 'AuteurSearchResultSerializer'

class ArticleSearchResultSerializer(serializers.ModelSerializer):
    auteurs = AuteurSearchResultSerializer(many=True)

    class Meta:
        model = Article
        fields = ["id", "titre", "resume", "auteurs"]
        ref_name='ArticleSearchResultSerializer'