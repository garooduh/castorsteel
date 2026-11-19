from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import quote, unquote, urljoin, urlsplit
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[2]
SITE = "https://castorsteel.ru/"
HOST = urlsplit(SITE).hostname
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
IMAGE_METADATA = {"og:image", "og:image:url", "og:image:secure_url", "twitter:image"}
CSS_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s)]+))\s*\)", re.I)


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.anchors = set()
        self.references = []
        self.feed(path.read_text(encoding="utf-8"))
        self.close()

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if attrs.get("id"):
            self.anchors.add(attrs["id"])
        if tag == "a" and attrs.get("name"):
            self.anchors.add(attrs["name"])
        for name in ("href", "src", "poster"):
            if attrs.get(name):
                self.references.append((self.getpos()[0], attrs[name]))
        if tag == "meta" and (attrs.get("property") or attrs.get("name")) in IMAGE_METADATA:
            if attrs.get("content"):
                self.references.append((self.getpos()[0], attrs["content"]))


def local_target(url):
    target = ROOT / unquote(url.path).lstrip("/")
    if url.path.endswith("/") or target.is_dir():
        target /= "index.html"
    return target.resolve()


def check_reference(source, reference, pages):
    url = urlsplit(urljoin(SITE + quote(source.as_posix()), reference))
    if url.scheme not in {"http", "https"} or url.hostname != HOST:
        return None
    target = local_target(url)
    if not target.is_relative_to(ROOT) or not target.is_file():
        return f"missing file for {reference!r}"
    if url.fragment and target in pages and unquote(url.fragment) not in pages[target].anchors:
        return f"missing anchor for {reference!r}"
    return None


def check_sitemap(pages):
    try:
        sitemap = ElementTree.parse(ROOT / "sitemap.xml").getroot()
    except (ElementTree.ParseError, OSError) as error:
        return [f"sitemap.xml: {error}"]
    if sitemap.tag != f"{SITEMAP_NS}urlset" or not len(sitemap):
        return ["sitemap.xml: expected a non-empty sitemap urlset"]

    errors = []
    for entry in sitemap:
        address = entry.findtext(f"{SITEMAP_NS}loc", "").strip()
        url = urlsplit(address)
        if url.scheme != "https" or url.netloc != HOST or url.query or url.fragment:
            errors.append(f"sitemap.xml: invalid site URL {address!r}")
        elif local_target(url) not in pages:
            errors.append(f"sitemap.xml: missing page for {address!r}")
    return errors


def main():
    pages = {path: Page(path) for path in sorted(ROOT.glob("**/*.html"))}
    errors = check_sitemap(pages)
    for path, page in pages.items():
        source = path.relative_to(ROOT)
        for line, reference in page.references:
            if error := check_reference(source, reference, pages):
                errors.append(f"{source}:{line}: {error}")
    for path in sorted(ROOT.glob("*.css")):
        for line, content in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in CSS_URL.finditer(content):
                reference = next(value for value in match.groups() if value is not None)
                if reference and (error := check_reference(Path(path.name), reference, pages)):
                    errors.append(f"{path.name}:{line}: {error}")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Checked links and assets for {len(pages)} pages and validated sitemap.xml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
