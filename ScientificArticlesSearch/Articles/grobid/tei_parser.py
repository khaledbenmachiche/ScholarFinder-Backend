"""Convert GROBID TEI XML into the payload accepted by `ArticleSerializer`.

Pure functions only (no I/O, no Django) so the extraction logic can be unit
tested against TEI fixtures without a running GROBID server or database.

TEI layout produced by GROBID's processFulltextDocument (abridged):

    TEI/teiHeader/fileDesc/titleStmt/title                  title
    TEI/teiHeader/fileDesc/sourceDesc/biblStruct/analytic/author
        persName/{forename,surname}, affiliation/orgName     authors + institutions
    TEI/teiHeader/fileDesc/sourceDesc/biblStruct/monogr/imprint/date[@when]
    TEI/teiHeader/profileDesc/abstract//p                   abstract
    TEI/teiHeader/profileDesc/textClass/keywords/term       keywords
    TEI/text/body/div/{head,p,formula}                      full text, by section
    TEI/text/back/div[@type="annex"]/div                    appendices
    TEI/text/back//listBibl/biblStruct                      bibliography
"""
import json
import xml.etree.ElementTree as ET
from typing import Iterable, List, Optional, Union

from .dates import extract_date_from_text, parse_iso_partial

TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}

# orgName types in order of preference when naming an author's institution.
_ORG_TYPES = ("institution", "laboratory", "department")
_KEYWORD_SEPARATORS = str.maketrans({";": ",", "·": ",", "•": ",", "|": ","})


class TEIParseError(ValueError):
    """The document is not TEI XML that GROBID could have produced."""


def parse_tei(tei_xml: Union[str, bytes], url: str = "") -> dict:
    """Parse a GROBID full-text TEI document into an `ArticleSerializer` payload.

    `text_integral` is a JSON string: a list of `{"header": str, "paragraph": [str]}`
    sections, which is the format the front-end renders.
    """
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError as exc:
        raise TEIParseError(f"invalid XML: {exc}") from exc
    if root.tag != f"{{{TEI_NS}}}TEI":
        raise TEIParseError(f"expected a TEI root element, got {root.tag!r}")

    return {
        "titre": _title(root),
        "resume": _abstract(root),
        "text_integral": json.dumps(_sections(root), ensure_ascii=False),
        "url": url,
        "date_de_publication": _publication_date(root),
        "mot_cles": [{"text": keyword} for keyword in _keywords(root)],
        "auteurs": _authors(root),
        "references_bibliographique": [{"nom": ref} for ref in _references(root)],
    }


def _text(elem: Optional[ET.Element]) -> str:
    """All text under `elem` with whitespace collapsed."""
    if elem is None:
        return ""
    return " ".join("".join(elem.itertext()).split())


def _unique(values: Iterable[str]) -> List[str]:
    seen, out = set(), []
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _title(root: ET.Element) -> str:
    title_stmt = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt", NS)
    if title_stmt is None:
        return ""
    title = title_stmt.find("tei:title[@type='main']", NS)
    if title is None:
        title = title_stmt.find("tei:title", NS)
    return _text(title)


def _abstract(root: ET.Element) -> str:
    abstract = root.find(".//tei:teiHeader/tei:profileDesc/tei:abstract", NS)
    if abstract is None:
        return ""
    paragraphs = [_text(p) for p in abstract.iterfind(".//tei:p", NS)]
    return "\n\n".join(p for p in paragraphs if p) or _text(abstract)


def _publication_date(root: ET.Element):
    candidates = root.findall(
        ".//tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:biblStruct/tei:monogr/tei:imprint/tei:date", NS
    ) + root.findall(".//tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:date", NS)
    # Prefer the explicit publication date over e.g. submission/acceptance dates.
    candidates.sort(key=lambda d: d.get("type") != "published")
    for date in candidates:
        parsed = parse_iso_partial(date.get("when")) or extract_date_from_text(_text(date))
        if parsed:
            return parsed
    return None


def _keywords(root: ET.Element) -> List[str]:
    keywords: List[str] = []
    for group in root.iterfind(".//tei:teiHeader/tei:profileDesc/tei:textClass/tei:keywords", NS):
        terms = group.findall("tei:term", NS)
        if terms:
            keywords.extend(_text(term) for term in terms)
        else:
            keywords.extend(k.strip() for k in _text(group).translate(_KEYWORD_SEPARATORS).split(","))
    return _unique(k.strip(" .") for k in keywords)


def _institution_name(affiliation: ET.Element) -> str:
    for org_type in _ORG_TYPES:
        name = _text(affiliation.find(f"tei:orgName[@type='{org_type}']", NS))
        if name:
            return name
    return _text(affiliation.find("tei:orgName", NS))


def _authors(root: ET.Element) -> List[dict]:
    authors: List[dict] = []
    seen = set()
    analytic_authors = root.iterfind(
        ".//tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:biblStruct/tei:analytic/tei:author", NS
    )
    for author in analytic_authors:
        pers_name = author.find("tei:persName", NS)
        if pers_name is None:
            continue  # GROBID emits affiliation-only <author> entries; they are not people.
        name = _person_name(pers_name)
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        institutions = _unique(_institution_name(aff) for aff in author.iterfind("tei:affiliation", NS))
        authors.append({"nom": name, "institutions": [{"nom": inst} for inst in institutions]})
    return authors


def _sections(root: ET.Element) -> List[dict]:
    body = root.find("tei:text/tei:body", NS)
    divs = list(body.iterfind("tei:div", NS)) if body is not None else []
    divs += root.findall("tei:text/tei:back/tei:div[@type='annex']/tei:div", NS)

    sections: List[dict] = []
    for div in divs:
        head = div.find("tei:head", NS)
        paragraphs = [_text(el) for el in div if el.tag in (f"{{{TEI_NS}}}p", f"{{{TEI_NS}}}formula")]
        paragraphs = [p for p in paragraphs if p]
        if head is None and sections:
            # Heading-less divs are continuations (text after a figure, a page break, ...).
            sections[-1]["paragraph"].extend(paragraphs)
        elif head is not None or paragraphs:
            sections.append({"header": _text(head), "paragraph": paragraphs})
    return sections


def _person_name(pers_name: ET.Element) -> str:
    parts = [_text(p) for p in pers_name if p.tag in (f"{{{TEI_NS}}}forename", f"{{{TEI_NS}}}surname")]
    return " ".join(p for p in parts if p) or _text(pers_name)


def _pages(imprint: Optional[ET.Element]) -> str:
    scope = imprint.find("tei:biblScope[@unit='page']", NS) if imprint is not None else None
    if scope is None:
        return ""
    first, last = scope.get("from"), scope.get("to")
    if first and last:
        return f"{first}-{last}"
    return first or _text(scope)


def format_reference(bibl: ET.Element, number: Optional[int] = None) -> str:
    """Render one bibliography `<biblStruct>` as a single human-readable line.

    Falls back to GROBID's raw reference string (`includeRawCitations=1`) when
    structured parsing yielded neither authors nor title.
    """
    analytic = bibl.find("tei:analytic", NS)
    monogr = bibl.find("tei:monogr", NS)
    imprint = monogr.find("tei:imprint", NS) if monogr is not None else None

    authors = ", ".join(
        _person_name(p) for p in bibl.iterfind("tei:analytic/tei:author/tei:persName", NS)
    ) or ", ".join(_person_name(p) for p in bibl.iterfind("tei:monogr/tei:author/tei:persName", NS))

    title = _text(analytic.find("tei:title", NS)) if analytic is not None else ""
    venue = ""
    if monogr is not None:
        monogr_title = _text(monogr.find("tei:title[@level='j']", NS)) or _text(monogr.find("tei:title", NS))
        if title:
            venue = monogr_title
        else:
            title = monogr_title  # a book or report cited as a whole
    # For reports/preprints GROBID sometimes leaves <title/> empty and puts the
    # title in <note type="report_type">, e.g. "Layer normalization. arXiv preprint".
    title = title or _text(bibl.find("tei:note[@type='report_type']", NS))

    parts = [authors] if authors else []
    if title:
        parts.append(f'"{title}"')
    if venue:
        volume = _text(imprint.find("tei:biblScope[@unit='volume']", NS)) if imprint is not None else ""
        issue = _text(imprint.find("tei:biblScope[@unit='issue']", NS)) if imprint is not None else ""
        pages = _pages(imprint)
        if volume:
            venue += f" {volume}" + (f"({issue})" if issue else "")
        if pages:
            venue += f": {pages}"
        parts.append(venue)
    if imprint is not None:
        publisher = _text(imprint.find("tei:publisher", NS))
        if publisher:
            parts.append(publisher)
        date = imprint.find("tei:date", NS)
        year = (date.get("when") or _text(date))[:4] if date is not None else ""
        if year:
            parts.append(year)

    if authors or title:
        text = ". ".join(parts)
        doi = _text(bibl.find(".//tei:idno[@type='DOI']", NS))
        arxiv = _text(bibl.find(".//tei:idno[@type='arXiv']", NS))
        if doi:
            text += f". doi:{doi}"
        elif arxiv:
            text += f". {arxiv if arxiv.startswith('arXiv:') else 'arXiv:' + arxiv}"
    else:
        text = _text(bibl.find("tei:note[@type='raw_reference']", NS))

    if not text:
        return ""
    return f"[{number}] {text}" if number is not None else text


def _references(root: ET.Element) -> List[str]:
    bibl_structs = root.iterfind("tei:text/tei:back//tei:listBibl/tei:biblStruct", NS)
    refs = (format_reference(bibl, number=i) for i, bibl in enumerate(bibl_structs, start=1))
    return [ref for ref in refs if ref]
