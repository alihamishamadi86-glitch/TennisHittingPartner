"""Pull a phone number, email and court-booking link out of a club's web pages. Pure functions.

Preference order is by reliability: `tel:` / `mailto:` links first, then numbers in visible
text near a phone keyword. Phones are validated and formatted with libphonenumber using the
club's country as the default region.
"""

import re
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import phonenumbers
from bs4 import BeautifulSoup

# Hosted court-booking platforms clubs commonly link to.
BOOKING_PLATFORMS = (
    "playtomic.io",
    "courtreserve.com",
    "clubspark",
    "lta.org.uk",
    "matchi.se",
    "bookteq.com",
    "skedda.com",
    "teamreach",
    "clubautomation.com",
    "tennisbookings.com",
    "easysportbooking",
    "reservaspadelytenis",
    "tpcbooking",
    "anybuddyapp.com",
    "book.tennis",
    "matchpoint.com",
    "padelclick",
    "doinsport",
    "ubookme",
)
# Linked files can't be booking pages (e.g. a PDF with a "reservar" link text).
FILE_LINK = re.compile(r"\.(pdf|docx?|xlsx?|jpe?g|png|gif|zip)(\?|$)", re.IGNORECASE)
BOOKING_WORDS = re.compile(
    r"\b(book(ing)?\s*(a\s*)?(court|pista)|court\s*booking|reserv(e|ar|a|as)(\s*(a\s*)?(court|pista|cancha))?|"
    r"reserve\s*now|book\s*now|book\s*online)\b",
    re.IGNORECASE,
)
CONTACT_WORDS = re.compile(
    r"contact|contacto|kontakt|contatti|about|sobre|club-info", re.IGNORECASE
)
PHONE_HINT = re.compile(r"(tel|phone|tel[eé]fono|call|llama|m[oó]vil|whatsapp)", re.IGNORECASE)
PHONE_CANDIDATE = re.compile(r"\+?\(?\d[\d\s().-]{6,18}\d")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


@dataclass(frozen=True)
class Contacts:
    phone: str | None = None
    email: str | None = None
    booking_url: str | None = None


def parse_phone(raw: str, region: str) -> str | None:
    """First valid number in `raw` (OSM may list several, separated by ; or ,), formatted
    internationally — or None."""
    for candidate in re.split(r"[;,/]", raw or ""):
        try:
            number = phonenumbers.parse(candidate.strip(), region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(number):
            return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    return None


def _same_site(a: str, b: str) -> bool:
    def root(url: str) -> str:
        host = (urlsplit(url).hostname or "").lower()
        return host.removeprefix("www.")

    return root(a) == root(b)


def contact_page_links(html: str, base_url: str, limit: int = 2) -> list[str]:
    """Same-site links that look like contact pages, to fetch after the homepage."""
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        text = a.get_text(" ", strip=True)
        if not (CONTACT_WORDS.search(href) or CONTACT_WORDS.search(text)):
            continue
        url = urljoin(base_url, href).split("#")[0]
        if url.startswith("http") and _same_site(url, base_url) and url not in found:
            found.append(url)
        if len(found) >= limit:
            break
    return found


def extract_contacts(pages: list[tuple[str, str]], country_code: str) -> Contacts:
    """`pages` are (url, html) pairs from one site."""
    tel_links: Counter[str] = Counter()
    text_phones: Counter[str] = Counter()
    emails: Counter[str] = Counter()
    booking: str | None = None
    booking_by_word: str | None = None

    for url, html in pages:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = str(a["href"]).strip()
            lower = href.lower()
            if lower.startswith("tel:"):
                if phone := parse_phone(href[4:], country_code):
                    tel_links[phone] += 1
            elif lower.startswith("mailto:"):
                address = href[7:].split("?")[0].strip()
                if EMAIL.fullmatch(address):
                    emails[address.lower()] += 1
            else:
                absolute = urljoin(url, href)
                if not absolute.startswith("http") or FILE_LINK.search(absolute):
                    continue
                if booking is None and any(p in absolute.lower() for p in BOOKING_PLATFORMS):
                    booking = absolute
                elif booking_by_word is None and BOOKING_WORDS.search(a.get_text(" ", strip=True)):
                    booking_by_word = absolute

        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        text = soup.get_text(" ", strip=True)
        for match in PHONE_CANDIDATE.finditer(text):
            window = text[max(0, match.start() - 40) : match.start()]
            if PHONE_HINT.search(window) and (phone := parse_phone(match.group(), country_code)):
                text_phones[phone] += 1
        for match in EMAIL.finditer(text):
            emails[match.group().lower()] += 0  # seen, but mailto links rank higher

    phone = (tel_links or text_phones).most_common(1)[0][0] if (tel_links or text_phones) else None
    email = emails.most_common(1)[0][0] if emails else None
    return Contacts(phone=phone, email=email, booking_url=booking or booking_by_word)
