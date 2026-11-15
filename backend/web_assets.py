"""Keep HTML and its scripts in one release, even when browsers cached an earlier deployment."""
import hashlib
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, MutableHeaders
from starlette.staticfiles import NotModifiedResponse

ASSET_REF = re.compile(r'(?P<prefix>\b(?:src|href)=["\'])(?P<url>[^"\']+\.(?:js|css)(?:\?[^"\']*)?)(?P<quote>["\'])')


class APINoStore:
    """Set API cache headers without buffering streams or wrapping cancelled browser requests."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def outgoing(message):
            if message['type'] == 'http.response.start' and scope.get('path', '').startswith('/api/'):
                MutableHeaders(scope=message)['Cache-Control'] = 'no-store'
            await send(message)
        await self.app(scope, receive, outgoing)


@lru_cache(maxsize=2)
def _version(root, signature):
    digest = hashlib.sha256()
    for filename, _, _ in signature:
        digest.update(Path(filename).relative_to(root).as_posix().encode())
        digest.update(Path(filename).read_bytes())
    return digest.hexdigest()[:16]


class WebAssets(StaticFiles):
    def version(self):
        files = sorted(p for p in Path(self.directory).rglob('*') if p.suffix in ('.html', '.js', '.css'))
        return _version(str(Path(self.directory).resolve()), tuple((str(p.resolve()), p.stat().st_mtime_ns, p.stat().st_size) for p in files))

    def file_response(self, full_path, stat_result, scope, status_code=200):
        if str(full_path).endswith('.html'):
            version = self.version()
            def stamp(match):
                url = urlsplit(match['url'])
                if url.scheme or url.netloc or url.path.startswith('//'):
                    return match[0]
                query = dict(parse_qsl(url.query))
                query['v'] = version
                return match['prefix'] + urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), url.fragment)) + match['quote']
            body = ASSET_REF.sub(stamp, Path(full_path).read_text(encoding='utf-8'))
            etag = '"' + hashlib.sha256(body.encode()).hexdigest() + '"'
            response = HTMLResponse(body, status_code=status_code, headers={
                'Cache-Control': 'no-cache', 'ETag': etag, 'X-Bezna-UI-Version': version})
            if self.is_not_modified(response.headers, Headers(scope=scope)):
                return NotModifiedResponse(response.headers)
            if scope['method'] == 'HEAD':
                response.body = b''
            return response
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers['Cache-Control'] = 'no-cache'
        return response
