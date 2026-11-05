"""Validate the generated artifact's links and exclude private/development files."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]/'_site'


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.language=None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'html':self.language=attrs.get('lang')
        for key in ('href','src'):
            if attrs.get(key):self.links.append(attrs[key])


pages=0
for path in ROOT.rglob('*'):
    if not path.is_file():continue
    assert not any(x in path.parts for x in ('tests','runs','__pycache__','.git')),path
    assert path.suffix not in ('.log','.zip','.mp3','.pyc'),path
    if path.suffix=='.py':assert path.name=='stick_vario_ram.py',path
    text=path.read_text(encoding='utf-8')
    assert not re.search(r'(?i)[A-Z]:[\\/]Users[\\/]|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN .*PRIVATE KEY',text),path
    if path.suffix=='.svg':ET.parse(path)
    if path.suffix!='.html':continue
    parser=Page();parser.feed(text);pages+=1
    for href in parser.links:
        url=urlsplit(href)
        if url.scheme or url.netloc or not url.path:continue
        assert not url.path.startswith('/'),(path,href,'root paths break repository Pages URLs')
        target=(path.parent/unquote(url.path)).resolve()
        assert target.is_relative_to(ROOT.resolve()),(path,href)
        assert target.exists(),(path,href)
    if path.parent.name in ('en','it'):
        assert parser.language==path.parent.name
        assert 'id="language"' in text
    else:
        if path.name=='index.html' and path.parent.name!='guide':
            assert 'i18n/ui.js' in text,path
print(f'Public artifact checks passed: {pages} HTML pages, local links and SVGs.')
