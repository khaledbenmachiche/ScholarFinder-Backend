"""Tests for the GROBID extraction pipeline (Articles/grobid/).

The parser tests run against a TEI fixture, the client tests against a fake
HTTP session, so no GROBID server is needed. `GrobidLiveTests` exercises a
real server and only runs when GROBID_TEST_URL and GROBID_TEST_PDF are set:

    GROBID_TEST_URL=http://localhost:8070 GROBID_TEST_PDF=paper.pdf python manage.py test Articles
"""
import datetime as dt
import json
import os
import tempfile
from pathlib import Path
from unittest import mock, skipUnless

import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from Authentication.models import User

from .grobid import ArticleIngestor, GrobidClient, GrobidError, GrobidUnavailable, parse_tei
from .grobid.dates import extract_date_from_text, parse_iso_partial
from .grobid.tei_parser import TEIParseError
from .models import Article

FIXTURE = Path(__file__).parent / "fixtures" / "tei" / "sample_fulltext.tei.xml"
SAMPLE_TEI = FIXTURE.read_text(encoding="utf-8")
MINIMAL_PDF = b"%PDF-1.4\n%%EOF\n"


class TEIParserTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.article = parse_tei(SAMPLE_TEI, url="https://example.org/paper.pdf")

    def test_header_fields(self):
        self.assertEqual(self.article["titre"], "Graph Neural Networks for Citation Recommendation")
        self.assertEqual(self.article["url"], "https://example.org/paper.pdf")
        self.assertEqual(self.article["resume"], "We study citation recommendation.\n\nOur model outperforms baselines.")

    def test_prefers_published_date_over_other_dates(self):
        self.assertEqual(self.article["date_de_publication"], dt.date(2021, 6, 15))

    def test_keywords_are_deduplicated_case_insensitively(self):
        self.assertEqual(
            self.article["mot_cles"], [{"text": "graph neural networks"}, {"text": "recommender systems"}]
        )

    def test_authors(self):
        self.assertEqual(
            self.article["auteurs"],
            [
                {
                    "nom": "Amina K Benali",
                    "institutions": [
                        {"nom": "École nationale Supérieure d'Informatique"},
                        {"nom": "LCSI Laboratory"},
                    ],
                },
                # Kept although GROBID found no affiliation; the affiliation-only
                # <author> entry and the duplicate are dropped.
                {"nom": "John Smith", "institutions": []},
            ],
        )

    def test_full_text_sections(self):
        sections = json.loads(self.article["text_integral"])
        self.assertEqual(
            sections,
            [
                {
                    "header": "Introduction",
                    "paragraph": [
                        "Citation recommendation helps researchers [1].",
                        "This paragraph follows a figure and has no heading.",
                    ],
                },
                {
                    "header": "Method",
                    "paragraph": ["We define the score as follows.", "s(u, v) = σ(h_u · h_v)(1)"],
                },
                # Annexes are kept, acknowledgements are not.
                {"header": "Hyper-parameters", "paragraph": ["Learning rate 0.001."]},
            ],
        )

    def test_references(self):
        self.assertEqual(
            [ref["nom"] for ref in self.article["references_bibliographique"]],
            [
                '[1] Thomas N Kipf, Max Welling. "Semi-supervised classification with graph convolutional networks". '
                "Journal of Machine Learning 12(3): 100-110. 2017. doi:10.1000/example.1",
                '[2] Jimmy Lei Ba. "Layer normalization. arXiv preprint". 2016. arXiv:1607.06450',
                "[3] Anonymous. Some unparseable reference, 1999.",
            ],
        )

    def test_payload_is_accepted_by_the_serializer(self):
        from .serializers import ArticleSerializer

        serializer = ArticleSerializer(data=self.article)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_minimal_document(self):
        article = parse_tei('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader/><text/></TEI>')
        self.assertEqual(article["titre"], "")
        self.assertIsNone(article["date_de_publication"])
        self.assertEqual(article["auteurs"], [])
        self.assertEqual(json.loads(article["text_integral"]), [])

    def test_rejects_non_tei(self):
        with self.assertRaises(TEIParseError):
            parse_tei("not xml")
        with self.assertRaises(TEIParseError):
            parse_tei("<html/>")


class DateParsingTests(SimpleTestCase):
    def test_iso_partial(self):
        self.assertEqual(parse_iso_partial("2019"), dt.date(2019, 1, 1))
        self.assertEqual(parse_iso_partial("2019-05"), dt.date(2019, 5, 1))
        self.assertEqual(parse_iso_partial("2019-05-24"), dt.date(2019, 5, 24))
        self.assertIsNone(parse_iso_partial("2019-13-01"))
        self.assertIsNone(parse_iso_partial(None))

    def test_free_text(self):
        cases = {
            "2 Aug 2023": dt.date(2023, 8, 2),
            "Published: 12/03/2021": dt.date(2021, 3, 12),
            "Accepted 15 juin 2020": dt.date(2020, 6, 15),
            "Décembre 2019": dt.date(2019, 12, 1),
            "Proceedings of ACL 2018": dt.date(2018, 1, 1),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(extract_date_from_text(text), expected)

    def test_always_returns_a_date_not_a_datetime(self):
        self.assertIs(type(extract_date_from_text("12/03/2021")), dt.date)

    def test_no_date(self):
        for text in (None, "", "   ", "no date here"):
            with self.subTest(text=text):
                self.assertIsNone(extract_date_from_text(text))


def _response(code, text=""):
    response = requests.Response()
    response.status_code = code
    response._content = text.encode()
    return response


class GrobidClientTests(SimpleTestCase):
    def setUp(self):
        self.session = mock.Mock(spec=requests.Session)
        self.client = GrobidClient("http://grobid:8070/", session=self.session, retry_backoff=0)
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(MINIMAL_PDF)
        tmp.close()
        self.pdf = tmp.name
        self.addCleanup(os.unlink, self.pdf)

    def test_returns_tei_and_sends_expected_request(self):
        self.session.post.return_value = _response(200, "<TEI/>")
        self.assertEqual(self.client.process_fulltext(self.pdf), "<TEI/>")
        url = self.session.post.call_args.args[0]
        kwargs = self.session.post.call_args.kwargs
        self.assertEqual(url, "http://grobid:8070/api/processFulltextDocument")
        self.assertEqual(kwargs["data"]["includeRawCitations"], 1)
        self.assertEqual(kwargs["timeout"], self.client.timeout)

    def test_retries_while_server_is_busy(self):
        self.session.post.side_effect = [_response(503), _response(503), _response(200, "<TEI/>")]
        self.assertEqual(self.client.process_fulltext(self.pdf), "<TEI/>")
        self.assertEqual(self.session.post.call_count, 3)

    def test_gives_up_after_max_retries(self):
        self.session.post.return_value = _response(503)
        with self.assertRaisesRegex(GrobidError, "still busy"):
            self.client.process_fulltext(self.pdf)
        self.assertEqual(self.session.post.call_count, self.client.max_retries)

    def test_error_statuses(self):
        for code, message in ((204, "no content"), (500, "HTTP 500")):
            with self.subTest(code=code):
                self.session.post.return_value = _response(code, "boom")
                with self.assertRaisesRegex(GrobidError, message):
                    self.client.process_fulltext(self.pdf)

    def test_connection_error_means_unavailable(self):
        self.session.post.side_effect = requests.ConnectionError()
        with self.assertRaises(GrobidUnavailable):
            self.client.process_fulltext(self.pdf)

    def test_timeout(self):
        self.session.post.side_effect = requests.Timeout()
        with self.assertRaisesRegex(GrobidError, "timed out"):
            self.client.process_fulltext(self.pdf)

    def test_process_many_isolates_failures(self):
        def fake(path):
            if Path(path).name == "bad.pdf":
                raise GrobidError("bad")
            return "<TEI/>"

        with mock.patch.object(self.client, "process_fulltext", side_effect=fake):
            results = {p.name: (tei, err) for p, tei, err in self.client.process_many(["a.pdf", "bad.pdf"])}
        self.assertEqual(results["a.pdf"], ("<TEI/>", None))
        self.assertIsNone(results["bad.pdf"][0])
        self.assertIsInstance(results["bad.pdf"][1], GrobidError)

    def test_is_alive(self):
        self.session.get.return_value = _response(200, "true")
        self.assertTrue(self.client.is_alive())
        self.session.get.side_effect = requests.ConnectionError()
        self.assertFalse(self.client.is_alive())


class FakeGrobid(GrobidClient):
    """Returns canned TEI per file name instead of calling a server."""

    def __init__(self, responses):
        super().__init__("http://fake")
        self.responses = responses

    def process_fulltext(self, pdf_path):
        result = self.responses[Path(pdf_path).name]
        if isinstance(result, Exception):
            raise result
        return result


class ArticleIngestorTests(TestCase):
    def test_ingest_persists_articles_pending_moderation(self):
        client = FakeGrobid({"good.pdf": SAMPLE_TEI, "broken.pdf": GrobidError("GROBID returned HTTP 500")})
        report = ArticleIngestor(client).ingest([("good.pdf", "https://x/good.pdf"), ("broken.pdf", "https://x/b.pdf")])

        self.assertEqual(list(report.failed), ["broken.pdf"])
        article = Article.objects.get()
        self.assertEqual(report.created, [article])
        self.assertFalse(article.is_validated)
        self.assertEqual(article.url, "https://x/good.pdf")
        self.assertEqual(article.date_de_publication, dt.date(2021, 6, 15))
        self.assertEqual(article.auteurs.count(), 2)
        self.assertEqual(article.auteurs.get(nom="Amina K Benali").institutions.count(), 2)
        self.assertEqual(article.mot_cles.count(), 2)
        self.assertEqual(article.references_bibliographique.count(), 3)

    def test_long_or_missing_titles_do_not_lose_the_article(self):
        long_title = SAMPLE_TEI.replace(
            "Graph Neural Networks for Citation Recommendation</title>\n\t\t\t</titleStmt>", "x" * 800 + "</title></titleStmt>"
        )
        no_title = SAMPLE_TEI.replace(
            "Graph Neural Networks for Citation Recommendation</title>\n\t\t\t</titleStmt>", "</title></titleStmt>"
        )
        ingestor = ArticleIngestor(FakeGrobid({}))
        self.assertEqual(len(ingestor.save_tei(long_title, "u").titre), Article._meta.get_field("titre").max_length)
        self.assertEqual(ingestor.save_tei(no_title, "u", fallback_title="my_paper").titre, "my_paper")

    def test_unavailable_server_aborts(self):
        client = FakeGrobid({"a.pdf": GrobidUnavailable("down")})
        with self.assertRaises(GrobidUnavailable):
            ArticleIngestor(client).ingest([("a.pdf", "u")])

    def test_keeps_raw_tei(self):
        with tempfile.TemporaryDirectory() as tmp:
            ArticleIngestor(FakeGrobid({"p.pdf": SAMPLE_TEI}), tei_dir=tmp).ingest([("p.pdf", "u")])
            self.assertEqual((Path(tmp) / "p.tei.xml").read_text(encoding="utf-8"), SAMPLE_TEI)


@override_settings(GOOGLE_DRIVE_ENABLED=False)
class UploadEndpointTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name, GROBID_TEI_DIR=None)
        override.enable()
        self.addCleanup(override.disable)

        self.api = APIClient()
        admin = User.objects.create_user(username="admin", password="pw", user_type="Admin")
        self.api.force_authenticate(admin)
        self.url = reverse("article-upload-article-via-file")

    def upload(self, content, name="paper.pdf"):
        return self.api.post(self.url, {"file": SimpleUploadedFile(name, content)}, format="multipart")

    @mock.patch.object(GrobidClient, "process_fulltext", return_value=SAMPLE_TEI)
    def test_upload_pdf_creates_pending_article(self, _):
        response = self.upload(MINIMAL_PDF)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        article = Article.objects.get()
        self.assertEqual(response.data["created"], [{"id": article.id, "titre": article.titre}])
        self.assertTrue(article.url.startswith("http://testserver/uploads/EchantillonsArticlesScrapping/paper"))
        self.assertFalse(article.is_validated)

    def test_rejects_non_pdf(self):
        response = self.upload(b"hello", name="paper.pdf")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @mock.patch.object(GrobidClient, "process_fulltext", side_effect=GrobidError("HTTP 500"))
    def test_extraction_failure(self, _):
        response = self.upload(MINIMAL_PDF)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn("paper.pdf", response.data["failed"])

    @mock.patch.object(GrobidClient, "process_fulltext", side_effect=GrobidUnavailable("down"))
    def test_grobid_down(self, _):
        self.assertEqual(self.upload(MINIMAL_PDF).status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_requires_admin(self):
        self.api.force_authenticate(User.objects.create_user(username="u", password="pw", user_type="User"))
        self.assertEqual(self.upload(MINIMAL_PDF).status_code, status.HTTP_403_FORBIDDEN)
        self.api.force_authenticate(None)
        self.assertEqual(self.upload(MINIMAL_PDF).status_code, status.HTTP_401_UNAUTHORIZED)


@skipUnless(os.getenv("GROBID_TEST_URL") and os.getenv("GROBID_TEST_PDF"), "needs a live GROBID server")
class GrobidLiveTests(TestCase):
    def test_end_to_end(self):
        client = GrobidClient(os.environ["GROBID_TEST_URL"], consolidate_header=False)
        self.assertTrue(client.is_alive())
        report = ArticleIngestor(client).ingest([(os.environ["GROBID_TEST_PDF"], "https://example.org/p.pdf")])
        self.assertEqual(report.failed, {})
        article = report.created[0]
        self.assertTrue(article.titre)
        self.assertGreater(article.auteurs.count(), 0)
        self.assertGreater(article.references_bibliographique.count(), 0)
        self.assertGreater(len(json.loads(article.text_integral)), 0)
