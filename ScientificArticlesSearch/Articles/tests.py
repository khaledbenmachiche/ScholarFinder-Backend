import datetime as dt

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from Authentication.models import User

from .models import Article, Auteur, Institution, MotCle, ReferenceBibliographique
from .serializers import ArticleSerializer

ARTICLE_PAYLOAD = {
    "titre": "titre corrigé",
    "resume": "resume",
    "text_integral": "text_integral",
    "url": "url",
    "date_de_publication": "2021-01-01",
    "mot_cles": [{"text": "graph coloring"}, {"text": "heuristics"}],
    "auteurs": [{"nom": "Yessed", "institutions": [{"nom": "ESI"}]}],
    "references_bibliographique": [{"nom": "ICTCS 2020"}],
}


def create_article(titre="titre", is_validated=False):
    article = Article.objects.create(
        titre=titre, resume="resume", text_integral="text_integral", url="url",
        date_de_publication="2021-01-01", is_validated=is_validated,
    )
    auteur = Auteur.objects.create(nom="nom")
    auteur.institutions.set([Institution.objects.create(nom="nom")])
    article.auteurs.set([auteur])
    article.mot_cles.set([MotCle.objects.create(text="text")])
    article.references_bibliographique.set([ReferenceBibliographique.objects.create(nom="nom")])
    return article


class ArticleModelTests(TestCase):
    def test_article_relations(self):
        article = create_article()
        self.assertEqual(article.titre, "titre")
        self.assertEqual(article.mot_cles.get().text, "text")
        self.assertEqual(article.auteurs.get().institutions.get().nom, "nom")
        self.assertEqual(article.references_bibliographique.get().nom, "nom")
        self.assertFalse(article.is_validated)


class ArticleSerializerTests(TestCase):
    def test_create_with_nested_objects(self):
        serializer = ArticleSerializer(data=ARTICLE_PAYLOAD)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        article = serializer.save()
        self.assertEqual(article.date_de_publication, dt.date(2021, 1, 1))
        self.assertEqual(sorted(article.mot_cles.values_list("text", flat=True)), ["graph coloring", "heuristics"])
        self.assertEqual(article.auteurs.get().institutions.get().nom, "ESI")

    def test_update_replaces_nested_lists(self):
        article = create_article()
        serializer = ArticleSerializer(article, data=ARTICLE_PAYLOAD)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        article.refresh_from_db()
        self.assertEqual(article.titre, "titre corrigé")
        self.assertEqual(sorted(article.mot_cles.values_list("text", flat=True)), ["graph coloring", "heuristics"])
        self.assertEqual(list(article.auteurs.values_list("nom", flat=True)), ["Yessed"])

    def test_partial_update_keeps_nested_lists(self):
        article = create_article()
        serializer = ArticleSerializer(article, data={"titre": "nouveau"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.assertEqual(article.mot_cles.get().text, "text")


class ArticleApiTests(TestCase):
    def setUp(self):
        self.pending = create_article("pending")
        self.validated = create_article("validated", is_validated=True)
        self.anonymous = APIClient()
        self.user = self._client("reader", "User")
        self.moderator = self._client("moderator", "Mod")

    @staticmethod
    def _client(username, user_type):
        client = APIClient()
        client.force_authenticate(User.objects.create_user(username=username, password="pw", user_type=user_type))
        return client

    def test_public_list_only_shows_validated_articles(self):
        response = self.anonymous.get(reverse("article-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([a["titre"] for a in response.data["results"]], ["validated"])

    def test_moderators_see_pending_articles(self):
        response = self.moderator.get(reverse("article-list"))
        self.assertEqual({a["titre"] for a in response.data["results"]}, {"pending", "validated"})

    def test_retrieve(self):
        self.assertEqual(self.anonymous.get(reverse("article-detail", args=[self.validated.id])).status_code, 200)
        self.assertEqual(self.anonymous.get(reverse("article-detail", args=[self.pending.id])).status_code, 404)
        self.assertEqual(self.moderator.get(reverse("article-detail", args=[self.pending.id])).status_code, 200)

    def test_articles_cannot_be_created_directly(self):
        response = self.moderator.post(reverse("article-list"), ARTICLE_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_moderator_corrects_article(self):
        url = reverse("article-detail", args=[self.pending.id])
        response = self.moderator.put(url, ARTICLE_PAYLOAD, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.titre, "titre corrigé")
        self.assertEqual(self.pending.auteurs.get().nom, "Yessed")

    def test_put_invalid_data(self):
        url = reverse("article-detail", args=[self.pending.id])
        self.assertEqual(self.moderator.put(url, {}, format="json").status_code, status.HTTP_400_BAD_REQUEST)
        invalid = {**ARTICLE_PAYLOAD, "date_de_publication": "not a date"}
        self.assertEqual(self.moderator.put(url, invalid, format="json").status_code, status.HTTP_400_BAD_REQUEST)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.titre, "pending")

    def test_only_moderators_can_modify(self):
        url = reverse("article-detail", args=[self.pending.id])
        self.assertEqual(self.anonymous.put(url, ARTICLE_PAYLOAD, format="json").status_code, 401)
        self.assertEqual(self.user.put(url, ARTICLE_PAYLOAD, format="json").status_code, 403)
        self.assertEqual(self.user.delete(url).status_code, 403)
        self.assertEqual(Article.objects.count(), 2)

    def test_delete(self):
        response = self.moderator.delete(reverse("article-detail", args=[self.pending.id]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Article.objects.filter(id=self.pending.id).exists())
        self.assertEqual(self.moderator.delete(reverse("article-detail", args=[999])).status_code, 404)

    def test_validation_workflow(self):
        pending_url = reverse("article-get-not-validated-articles")
        self.assertEqual(self.user.get(pending_url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual([a["titre"] for a in self.moderator.get(pending_url).data], ["pending"])

        validate_url = reverse("article-validate-article", args=[self.pending.id])
        self.assertEqual(self.moderator.put(validate_url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.moderator.put(validate_url).status_code, status.HTTP_400_BAD_REQUEST)

        validated = self.user.get(reverse("article-get-validated-articles")).data
        self.assertEqual({a["titre"] for a in validated}, {"pending", "validated"})
