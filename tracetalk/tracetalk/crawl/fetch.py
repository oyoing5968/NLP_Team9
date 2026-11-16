"""Crawler step 1, fetch (docs/CRAWLER.md): get the pages on an explicit list of addresses, nothing else.

Rules, all checked here (the Mac also runs this inside mac/sandbox/crawl.sb; other machines have no such sandbox, so the
code's own checks are what holds there):
- an address is fetched only when it is https and on the allowlist (data/crawl/sources.txt); no link is followed (0.9: the
  allowlisted index pages may name new posts, which then come here as a list under these same rules);
- the host's addresses are looked up first and a private, local, link-local, multicast or reserved one is refused,
  and the connection goes to exactly the address that was checked (no second lookup), with the certificate checked
  for the host name;
- a redirect is followed only to another allowlisted https address (at most 3); robots.txt is obeyed;
- only text/html (or xml) up to MAX bytes in 20 seconds; one request every 5 seconds;
- files are written only inside OUT, which must lie inside this project folder: the page as <hash>.html and one
  manifest row (address, time, size, sha256, type, status). Nothing is run, unpacked or rendered.
"""
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from tracetalk.crawl.extract import MAX_PAGE, allowed
from tracetalk.db.lexicon import ROOT

AGENT = "TraceTalk-student-project/0.9 (school NLP prototype; reads public newsletter posts slowly)"
TYPES = ("text/html", "application/xhtml+xml", "application/xml", "text/xml", "text/plain")
TIMEOUT, PAUSE, REDIRECTS = 20, 5.0, 3


class Refused(ValueError):
    pass


def inside_project(path, root=ROOT):
    """The output folder, resolved; refused when it is (or links to) anywhere outside the project."""
    p = Path(path)
    resolved = p.resolve()
    if p.is_symlink() or not str(resolved).startswith(str(Path(root).resolve()) + "/"):
        raise Refused(f"출력 폴더는 이 프로젝트 폴더 안이어야 합니다: {path}")
    return resolved


def public_address(host, port=443, resolve=socket.getaddrinfo):
    """One checked address for the host: every address it resolves to must be public."""
    infos = resolve(host, port, type=socket.SOCK_STREAM)
    addrs = sorted({i[4][0] for i in infos})
    if not addrs:
        raise Refused(f"주소를 찾지 못함: {host}")
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified or (ip.version == 6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global)):
            raise Refused(f"공용 주소가 아님: {host} -> {a}")
    return addrs[0]


class _Pinned(http.client.HTTPSConnection):
    """HTTPS to the address that was checked, with the certificate checked for the host name."""

    def __init__(self, host, address, **kw):
        super().__init__(host, timeout=TIMEOUT, context=ssl.create_default_context(), **kw)
        self._address = address

    def connect(self):
        sock = socket.create_connection((self._address, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def get(url, sources, opener=None):
    """(final url, content type, body bytes) for an allowlisted https address; Refused otherwise."""
    opener = opener or _open
    for _ in range(REDIRECTS + 1):
        if not allowed(url, sources):
            raise Refused(f"허용 목록 밖 또는 https가 아님: {url}")
        status, headers, body = opener(url)
        if status in (301, 302, 303, 307, 308):
            url = urljoin(url, headers.get("location", ""))
            continue
        if status != 200:
            raise Refused(f"응답 {status}: {url}")
        ctype = (headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype not in TYPES:
            raise Refused(f"글이 아닌 형식 {ctype or '없음'}: {url}")
        if len(body) > MAX_PAGE:
            raise Refused(f"너무 큼(>{MAX_PAGE}바이트): {url}")
        return url, ctype, body
    raise Refused(f"리다이렉트가 너무 많음: {url}")


def _open(url):
    parts = urlsplit(url)
    conn = _Pinned(parts.hostname, public_address(parts.hostname))
    try:
        conn.request("GET", (parts.path or "/") + (f"?{parts.query}" if parts.query else ""),
                     headers={"User-Agent": AGENT, "Accept": "text/html", "Accept-Encoding": "identity"})
        resp = conn.getresponse()
        body = resp.read(MAX_PAGE + 1)
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, body
    finally:
        conn.close()


def robots_allow(url, sources, opener=None, cache=None):
    cache = {} if cache is None else cache
    parts = urlsplit(url)
    if parts.hostname not in cache:
        rp = RobotFileParser()
        try:
            _, _, body = get(f"https://{parts.hostname}/robots.txt", [(parts.hostname, "/robots.txt")], opener)
            rp.parse(body.decode("utf-8", errors="replace").splitlines())
        except Refused:
            rp.parse([])  # no robots.txt (or not text): nothing disallowed
        cache[parts.hostname] = rp
    return cache[parts.hostname].can_fetch(AGENT, url)


POST_PATHS = {"maily.so": re.compile(r"^/(trendaword|farmingletter)/posts/[a-z0-9]+/?$"), "letter.wepick.kr": re.compile(r"^/post/\d+/?$"),
              "gogumafarm.kr": re.compile(r"^/(?!category/|tag/|page/|wp-|author/|feed/|about|contact|privacy)[^/?#]{8,}/?$")}
POST_PATHS["www.gogumafarm.kr"] = POST_PATHS["gogumafarm.kr"]


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def post_links(body, base, sources):
    """The addresses of posts an index page links to: on the allowlist, on the same host, and shaped like that site's posts.
    Nothing here is fetched: the list goes through fetch_all and every rule above."""
    parser = _Links()
    parser.feed(body.decode("utf-8", errors="replace"))
    host = urlsplit(base).hostname
    found = []
    for href in parser.links:
        url = urljoin(base, href.strip()).split("#")[0]
        parts = urlsplit(url)
        pattern = POST_PATHS.get(parts.hostname or "")
        if parts.hostname == host and pattern and pattern.match(parts.path) and allowed(url, sources) and url not in found:
            found.append(url)
    return found


def discover(indexes, sources, known=(), opener=None, pause=PAUSE, sleep=time.sleep, each=10):
    """0.9: what is new on the allowlisted sites: their index pages (data/crawl/index_pages.txt), robots.txt obeyed, up to `each`
    posts per index that `known` does not have -> (addresses, report). Reads only the index pages."""
    known, robots, out, report = set(known), {}, [], []
    for i, index in enumerate(dict.fromkeys(u.strip() for u in indexes if u.strip() and not u.startswith("#"))):
        if i:
            sleep(pause)
        try:
            if not allowed(index, sources) or not robots_allow(index, sources, opener, robots):
                raise Refused("허용 목록 밖이거나 robots.txt가 금지함")
            final, _, body = get(index, sources, opener)
            links = post_links(body, final, sources)
            new = [u for u in links if u not in known and u not in out][:each]
            out += new
            report.append({"index": index, "links": len(links), "new": len(new)})
        except (Refused, OSError, ssl.SSLError, http.client.HTTPException) as exc:
            report.append({"index": index, "why": f"{type(exc).__name__}: {exc}"[:200]})
    return out, report


def fetch_all(urls, out, sources, opener=None, pause=PAUSE, sleep=time.sleep, now=None):
    """Fetch each listed address once into OUT (inside the project); the manifest says what happened to each."""
    out = inside_project(out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.jsonl"
    robots, rows = {}, []
    for i, url in enumerate(dict.fromkeys(u.strip() for u in urls if u.strip() and not u.startswith("#"))):
        if i:
            sleep(pause)
        row = {"url": url, "at": (now or datetime.now)().astimezone().isoformat(timespec="seconds")}
        try:
            if not allowed(url, sources):
                raise Refused(f"허용 목록 밖 또는 https가 아님: {url}")
            if not robots_allow(url, sources, opener, robots):
                raise Refused("robots.txt가 금지함")
            final, ctype, body = get(url, sources, opener)
            name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".html"
            target = out / name
            with target.open("xb") as handle:  # never overwritten
                handle.write(body)
            row.update(status="ok", final_url=final, file=name, bytes=len(body), type=ctype,
                       sha256=hashlib.sha256(body).hexdigest())
        except (Refused, OSError, ssl.SSLError, http.client.HTTPException) as exc:
            row.update(status="refused", why=f"{type(exc).__name__}: {exc}"[:300])
        rows.append(row)
        with manifest.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows
