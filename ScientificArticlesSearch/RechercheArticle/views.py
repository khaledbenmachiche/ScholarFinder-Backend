import abc

from django.http import HttpResponse
from elasticsearch_dsl import Q
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.views import APIView
from rest_framework import permissions
from .CustomPermissions import IsAuth,IsAdmin,IsModerator
from rest_framework.permissions import AllowAny , IsAuthenticated
from Articles.documents import ArticleDocument
from .serializers import ArticleSearchResultSerializer
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema

class PaginatedElasticSearchAPIView(APIView, LimitOffsetPagination):
    serializer_class = None
    document_class = None
    
    @abc.abstractmethod
    def generate_q_expression(self, query, filters):
        """This method should be overridden
        and return a Q() expression."""

    def get(self, request, query):
        try:
            filters = request.GET.dict()
            q = self.generate_q_expression(query, filters)

            search = self.document_class.search().query(q)
            response = search.execute()

            print(f'Found {response.hits.total.value} hit(s) for query: "{query}"')

            results = self.paginate_queryset(response, request, view=self)
            serializer = self.serializer_class(results, many=True)
            return self.get_paginated_response(serializer.data)
        except Exception as e:
            return HttpResponse(e, status=500)


class SearchArticles(PaginatedElasticSearchAPIView):
    serializer_class = ArticleSearchResultSerializer
    document_class = ArticleDocument
    permission_classes = (IsAuthenticated,)
    
    @swagger_auto_schema(
        operation_description="Recherche des articles dans le titre, les mots clés, les auteurs et le texte intégral, tous les articles contenant un ou plusieurs mots spécifiés \n dans le titre, les mots clés, les auteurs et le texte intégral seront retournés.\n si des filtres sont spécifiés, les articles retournés doivent satisfaire les filtres spécifiés.",
        manual_parameters=[
            openapi.Parameter(
                name='query',
                in_=openapi.IN_PATH,
                type=openapi.TYPE_STRING,
                required=True,
                description='le titre, les mots clés, les auteurs et le texte intégral à rechercher dans les articles.',
            ),
            openapi.Parameter(
                name='keywords',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                required=False,
                description='Mots clés à rechercher dans les articles retourner par la recherche initial.'
            ),
            openapi.Parameter(
                name='authors',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                required=False,
                description='Auteurs à rechercher dans les articles retourner par la recherche initial.'
            ),
            openapi.Parameter(
                name='institutions',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                required=False,
                description='Institutions à rechercher dans les articles retourner par la recherche initial.'
            ),
            openapi.Parameter(
                name='start_date',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                required=False,
                description='Date de début de publication des articles retourner par la recherche initial.'
            ),
            openapi.Parameter(
                name='end_date',
                in_=openapi.IN_QUERY,
                type=openapi.TYPE_STRING,
                required=False,
                description='Date de fin de publication des articles.'
            ),
        ],
        responses={200: ArticleSearchResultSerializer(many=True)}
    )
    def get(self, request, query):
        return super().get(request, query)
    
    def generate_q_expression(self, query, filters=None):
        base_q = Q(
            "multi_match",
            query=query,
            type="most_fields",
            fields=[
                "titre",
                "text_integral",
                "auteurs.nom",
                "mot_cles.text",
            ], fuzziness="auto")

        if filters:
            keywords = filters.get('keywords')
            authors = filters.get('authors')
            institutions = filters.get('institutions')
            start_date = filters.get('start_date')
            end_date = filters.get('end_date')

            if keywords:
                base_q &= Q(
                        "multi_match",
                        query= keywords,
                        type="most_fields",
                        fields=[
                            "mot_cles.text",
                        ])
            if authors:
                base_q &=  Q(
                        "multi_match",
                        query= authors,
                        type="most_fields",
                        fields=[
                            "auteurs.nom",
                        ])
            if institutions:
                base_q &= Q(
                        "multi_match",
                        query= institutions,
                        type="most_fields",
                        fields=[
                            "auteurs.institutions.nom",
                        ])
            if start_date and end_date:
                base_q &= Q("range", date_de_publication={"gte": start_date, "lte": end_date})
        return base_q