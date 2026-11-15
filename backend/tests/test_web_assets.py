"""A new JS deployment must invalidate cached HTML even if index.html itself did not change."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.web_assets import WebAssets


def test_html_versions_local_assets_and_revalidates_after_js_only_update(tmp_path):
    (tmp_path / 'index.html').write_text('<script src="app.js"></script><link href="style.css" rel="stylesheet"><script src="https://example.org/lib.js"></script>')
    (tmp_path / 'app.js').write_text('window.version=1;')
    (tmp_path / 'style.css').write_text('body{color:red}')
    app = FastAPI()
    app.mount('/', WebAssets(directory=tmp_path, html=True))
    with TestClient(app) as client:
        a = client.get('/')
        assert a.headers['cache-control'] == 'no-cache' and 'app.js?v=' in a.text and 'style.css?v=' in a.text
        assert 'https://example.org/lib.js"' in a.text
        same = client.get('/', headers={'If-None-Match': a.headers['etag']})
        assert same.status_code == 304 and same.headers['cache-control'] == 'no-cache'
        (tmp_path / 'app.js').write_text('window.version=2;')
        b = client.get('/', headers={'If-None-Match': a.headers['etag']})
        assert b.status_code == 200 and b.headers['etag'] != a.headers['etag'] and b.text != a.text
        assert client.get('/app.js').headers['cache-control'] == 'no-cache'
        head = client.head('/')
        assert head.content == b'' and head.headers['etag'] == b.headers['etag']


def test_release_version_depends_on_contents_not_install_path(tmp_path):
    roots = [tmp_path / 'a', tmp_path / 'b']
    for root in roots:
        root.mkdir(); (root / 'index.html').write_text('<script src="app.js"></script>'); (root / 'app.js').write_text('hello')
    assert WebAssets(directory=roots[0]).version() == WebAssets(directory=roots[1]).version()
