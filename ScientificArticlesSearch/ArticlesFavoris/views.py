from rest_framework import viewsets, permissions
from rest_framework.response import Response
from .models import ArticleFavoris
from .serializers import ArticleFavorisSerializer
from Articles.models import Article
from Authentication.models import User
from .CustomPermissions import IsAuth,IsAdmin,IsModerator
from rest_framework.permissions import AllowAny , IsAuthenticated
from Articles.serializers import ArticleSerializer
from django.shortcuts import get_object_or_404
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
class ArticleFavorisViewSet(viewsets.ModelViewSet):
    queryset = ArticleFavoris.objects.all()
    serializer_class = ArticleFavorisSerializer
    permission_classes = [IsAuthenticated]
    
    @swagger_auto_schema(
        operation_description="Get all articles in favorites , le id d'un utilisateur n'est pas specifier dans les parametres car on utilise le token d'authentification pour recuperer l'utilisateur",
        responses={200: ArticleSerializer(many=True)}
    )
    def list(self, request, *args, **kwargs):
        user_id = request.user.id
        favorite_articles = ArticleFavoris.objects.filter(user=user_id)
        articles = [fav.article for fav in favorite_articles]
        serializer = ArticleSerializer(articles, many=True)
        return Response(serializer.data)
    
    @swagger_auto_schema(
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'article_id': openapi.Schema(type=openapi.TYPE_INTEGER, description='The ID of the article to be added to favorites.'),
            },
            required=['article_id'],
        ),
        operation_description="Ajouter un article au favorites , le id d'un utilisateur n'est pas specifier dans les parametres car on utilise le token d'authentification pour recuperer l'utilisateur",

        responses={
            200: openapi.Response('Article added to favorites successfully.'),
            400: openapi.Response('Article is not validated.'),
            500: openapi.Response('internal server error.'),
        }
    )
    def create(self, request, *args, **kwargs):
        try:
            user_id = request.user.id
            user = get_object_or_404(User,id=user_id)
            if user.user_type != 'User':
                return Response({'detail': 'Only users can add articles to favorites.'}, status=400)
            article_id =  request.data.get('article_id')
            article = get_object_or_404(Article, id=article_id)

            if not article.is_validated:
                return Response({'detail': 'Article is not validated.'}, status=400)

            if ArticleFavoris.objects.filter(user=user,article=article).exists():
                return Response({'detail': 'article is already in favorites.'}, status=400)

            ArticleFavoris.objects.create(user=user,article=article)

            return Response({'detail': 'Article added to favorites successfully.'}, status=201)
        except Exception as e:
            print(e)
            return Response({'detail': 'internal server error.'}, status=500)


    def destroy(self, request, *args, **kwargs):
        user_id = request.user.id
        article_id = kwargs.get('pk')
        try:
            article_favoris = ArticleFavoris.objects.get(user=user_id,article=article_id)
        except ArticleFavoris.DoesNotExist:
            return Response({'detail': 'Article not found in favorites.'}, status=404)

        article_favoris.delete()

        return Response({'detail': 'Article removed from favorites successfully.'}, status=204)
