# ScholarFinder — Backend

REST API for a scientific-article search platform. Administrators upload research papers as PDFs; a **GROBID-based extraction pipeline** turns each PDF into structured data (title, authors and affiliations, abstract, keywords, sectioned full text, bibliography); **moderators review and correct** the extracted metadata; validated articles become searchable through **Elasticsearch** full-text search with filters.

Built with Django REST Framework, MySQL, Elasticsearch and GROBID, with Docker Compose for the whole stack.

```mermaid
flowchart LR
    A[Admin uploads<br/>PDF / zip / URL / Drive folder] --> B[GROBID<br/>processFulltextDocument]
    B -->|TEI XML| C[TEI parser]
    C --> D[(MySQL<br/>Article, pending)]
    D --> E[Moderator reviews<br/>and corrects]
    E -->|validated| F[(Elasticsearch)]
    F --> G[Users search<br/>and save favorites]
```

## PDF extraction pipeline

Code: [`Articles/grobid/`](ScientificArticlesSearch/Articles/grobid/)

[GROBID](https://github.com/kermitt2/grobid) is a machine-learning library (CRF and deep-learning sequence labelling models) that parses scholarly PDFs into [TEI XML](https://tei-c.org/). The pipeline wraps it in three layers, each small enough to test on its own:

| Module | Responsibility |
|---|---|
| [`client.py`](ScientificArticlesSearch/Articles/grobid/client.py) | HTTP client for the GROBID service. Retries with backoff when GROBID answers `503` (all engines busy), so a batch can safely send more documents in parallel than the server has workers. Uses explicit timeouts and separates "server unreachable" (aborts the batch) from "this PDF failed" (skips that PDF and continues). |
| [`tei_parser.py`](ScientificArticlesSearch/Articles/grobid/tei_parser.py) | Pure function `parse_tei(xml) -> dict` with no I/O and no Django. Extracts title, authors with *all* their affiliations, the publication date (the `published` date is preferred over submission dates), keywords, abstract, full text as `{header, paragraphs}` sections (formulas and appendices kept, acknowledgements dropped), and formatted references. |
| [`ingestion.py`](ScientificArticlesSearch/Articles/grobid/ingestion.py) | Runs GROBID calls in a thread pool while parsing and database writes stay on the calling thread. Validates the result through the DRF serializer, saves each article in a transaction, and keeps the raw TEI so extraction can be re-run without calling GROBID again. |

GROBID output on real papers is noisy, and the parser handles the recurring failure modes:

- **Author list:**
  - GROBID emits `<author>` entries that are only an affiliation with no person; these are skipped.
  - Authors whose affiliation was not recognised are kept, with an empty institution list.
  - Duplicate authors are merged.
- **Heading-less `<div>`s:** text that continues after a figure or page break arrives without a heading, and is appended to the previous section.
- **References:**
  - Some reports and preprints come with an empty `<title/>` and the real title in `<note type="report_type">`; that note is used as the title.
  - When GROBID could not structure a reference at all, the raw citation string is used instead (`includeRawCitations=1`).
- **Titles:**
  - Titles longer than the database column are truncated.
  - A missing title falls back to the file name, so the article is never lost; a moderator corrects it.
- **Dates** can be `YYYY`, `YYYY-MM` or free text (English or French month names). They are always converted to a `date`.

Every extracted article starts out `is_validated=False` and stays out of search until a human moderator has reviewed it (human in the loop).

### Try it without the web UI

```bash
docker compose up -d grobid                       # from ScientificArticlesSearch/
python manage.py ingest_pdfs path/to/papers/      # files or directories
#   Processing 2 PDF(s) with GROBID at http://localhost:8070 ...
#     created #1: BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding
#     failed broken.pdf: broken.pdf: GROBID returned HTTP 500: [BAD_INPUT_DATA] ...
#   1 created, 1 failed
```

## Running the project

### With Docker (recommended)

```bash
cd ScientificArticlesSearch
cp .env.example .env
docker compose up --build
docker compose exec backend python manage.py search_index --rebuild -f   # create the Elasticsearch index
docker compose exec backend python manage.py createsuperuser
```

The API is served at http://localhost:8000 and interactive Swagger docs at http://localhost:8000/docs/. The first PDF takes longer while GROBID loads its models.

### Locally

Requires Python 3.10+. MySQL is optional: leave `DB_NAME` empty in `.env` and SQLite is used.

```bash
python -m venv env && source env/bin/activate
pip install -r requirements.txt
cd ScientificArticlesSearch
cp .env.example .env            # then edit it
docker compose up -d grobid elasticsearch
python manage.py migrate
python manage.py runserver
```

On Debian or Ubuntu, `mysqlclient` needs `sudo apt install default-libmysqlclient-dev build-essential pkg-config` first.

## API overview

| Endpoint | Who | Description |
|---|---|---|
| `POST /api/authentication/login/` | anyone | JWT access token (the refresh token is set in an HttpOnly cookie) |
| `GET /api/articles/` | anyone | Validated articles (moderators also see pending ones) |
| `POST /api/articles/upload-via-{file,zip,url,drive}/` | admin | Extract articles from PDFs with GROBID |
| `GET /api/articles/not_validated/` | moderator | Review queue |
| `PUT /api/articles/{id}/` | moderator | Correct extracted metadata |
| `PUT /api/articles/{id}/validate/` | moderator | Publish to search |
| `GET /api/recherche/article/{query}/?keywords=&authors=&institutions=&start_date=&end_date=` | user | Fuzzy full-text search with filters |
| `/api/articles_favoris/` | user | Save and remove favorite articles |
| `/api/moderation/` | admin | Manage moderator accounts |

## Tests

```bash
cd ScientificArticlesSearch
python manage.py test
```

The pipeline tests run against a TEI fixture and a mocked HTTP session, so they need neither GROBID nor Elasticsearch. To also run the end-to-end test against a real GROBID server:

```bash
GROBID_TEST_URL=http://localhost:8070 GROBID_TEST_PDF=paper.pdf python manage.py test Articles
```

## Configuration

All settings are read from `.env`; see [`.env.example`](ScientificArticlesSearch/.env.example). The GROBID-related ones:

| Variable | Default | |
|---|---|---|
| `GROBID_URL` | `http://localhost:8070` | |
| `GROBID_MAX_WORKERS` | `4` | Concurrent requests per batch |
| `GROBID_TIMEOUT` | `180` | Seconds per PDF |
| `GROBID_CONSOLIDATE_HEADER` | `True` | Correct title, authors and DOI against CrossRef (needs internet access) |
| `GOOGLE_DRIVE_UPLOAD_FOLDER_ID` | empty | Optional. When set, uploaded PDFs are hosted on Google Drive instead of `MEDIA_ROOT` |

## Limitations and next steps

- Extraction runs synchronously inside the upload request. Large zip archives should move to a task queue such as Celery, with a status endpoint.
- The lightweight `lfoppiano/grobid` image uses CRF models only. `grobid/grobid` adds deep-learning models and is more accurate, but slower on CPU.
- Scanned PDFs without a text layer need OCR before GROBID can read them.
