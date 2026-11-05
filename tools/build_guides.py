"""Build the static EN/IT guide from its single Markdown source tree.

Dependency-free renderer for the headings, links, images, tables, lists and
emphasis used in these authored guides. No raw HTML or remote fetches.
"""
from pathlib import Path
import html
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
PAGES = ('index', 'components', 'assembly', 'installation', 'usage', 'design')
LABELS = {
    'en': ('Project', 'Parts', 'Assembly', 'Install', 'Use', 'Design'),
    'it': ('Progetto', 'Componenti', 'Montaggio', 'Installa', 'Uso', 'Scelte'),
}


def target(url):
    if url.lower().startswith(('javascript:', 'data:')):
        raise ValueError('Unsupported link scheme')
    return re.sub(r'\.md(?=#|$)', '.html', url)


def inline(text):
    text = html.escape(text, quote=True)
    text = re.sub(r'!\[([^]]*)\]\(([^)]+)\)',
                  lambda m: f'<img src="{target(m[2])}" alt="{m[1]}" loading="lazy">', text)
    text = re.sub(r'\[([^]]*)\]\(([^)]+)\)',
                  lambda m: f'<a href="{target(m[2])}">{m[1]}</a>', text)
    for pattern, tag in ((r'`([^`]+)`', 'code'), (r'\*\*(.+?)\*\*', 'strong'),
                         (r'~~(.+?)~~', 'del')):
        text = re.sub(pattern, lambda m: f'<{tag}>{m[1]}</{tag}>', text)
    return text


def render(source):
    result = []
    for block in re.split(r'\n\s*\n', source.strip()):
        lines = block.splitlines()
        if all(re.match(r'^#{1,3} ', line) for line in lines):
            for line in lines:
                level = len(line) - len(line.lstrip('#'))
                result.append(f'<h{level}>{inline(line[level:].strip())}</h{level}>')
        elif lines[0].startswith('|'):
            cells = lambda line: [inline(x.strip()) for x in line.strip('|').split('|')]
            head = '<tr>' + ''.join(f'<th scope="col">{x}</th>' for x in cells(lines[0])) + '</tr>'
            rows = ['<tr>' + ''.join(f'<td>{x}</td>' for x in cells(line)) + '</tr>'
                    for line in lines[2:]]
            result.append('<div class="table-scroll"><table><thead>' + head
                          + '</thead><tbody>' + ''.join(rows) + '</tbody></table></div>')
        elif re.match(r'^(?:- |\d+\. )', lines[0]):
            ordered = lines[0][0].isdigit()
            items = []
            for line in lines:
                if re.match(r'^(?:- |\d+\. )', line):
                    items.append(re.sub(r'^(?:- |\d+\. )', '', line))
                else:
                    items[-1] += ' ' + line
            tag = 'ol' if ordered else 'ul'
            result.append(f'<{tag}>' + ''.join(f'<li>{inline(x)}</li>' for x in items) + f'</{tag}>')
        elif lines[0].startswith('!['):
            result.append('<figure>' + inline(' '.join(lines)) + '</figure>')
        else:
            result.append('<p>' + inline(' '.join(lines)) + '</p>')
    return '\n'.join(result)


def build():
    assets=ROOT/'guide/assets'
    assets.mkdir(parents=True,exist_ok=True)
    for source in (ROOT/'docs/assets').iterdir():
        if source.is_file():shutil.copyfile(source,assets/source.name)
    for lang in ('en', 'it'):
        folder = ROOT / 'guide' / lang
        folder.mkdir(parents=True, exist_ok=True)
        for page in PAGES:
            source = (ROOT / 'docs' / lang / (page + '.md')).read_text(encoding='utf-8')
            title = source.splitlines()[0].lstrip('# ')
            nav = ''.join(f'<a href="{p}.html"' + (' aria-current="page"' if p == page else '')
                          + f'>{label}</a>' for p, label in zip(PAGES, LABELS[lang]))
            options = ''.join(f'<option value="../{value}/{page}.html"'
                              + (' selected' if value == lang else '') + f'>{label}</option>'
                              for value, label in (('en', 'English'), ('it', 'Italiano')))
            language_label = 'Language' if lang == 'en' else 'Lingua'
            footer = ('User guides: one Markdown source per language. Prototype under development.'
                      if lang == 'en' else 'Guide: una fonte Markdown per lingua. Prototipo in sviluppo.')
            document = f'''<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} | VibeVario</title><link rel="stylesheet" href="../style.css">
<link rel="alternate" hreflang="en" href="../en/{page}.html"><link rel="alternate" hreflang="it" href="../it/{page}.html">
<script defer src="../language.js"></script></head><body>
<header><a class="brand" href="index.html">VibeVario<span>by Liuk_ITA</span></a>
<label class="language">{language_label}<select id="language">{options}</select></label></header>
<nav aria-label="Guide">{nav}</nav><main>{render(source)}</main>
<footer>{footer}<br><a href="https://github.com/Liuk-ITA/vibevario">Firmware</a> Â·
<a href="../../install/">Installer</a> Â· <a href="../../config/">Configurator</a> Â· <a href="../../">Vario Lab</a></footer>
</body></html>'''
            (folder / (page + '.html')).write_text(document, encoding='utf-8')
    (ROOT / 'guide/index.html').write_text('''<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta http-equiv="refresh" content="0;url=en/index.html">
<title>VibeVario guide</title></head><body><a href="en/index.html">English guide</a>
<a href="it/index.html">Guida italiana</a></body></html>''', encoding='utf-8')
    print('Built 12 bilingual guide pages; English default.')


if __name__ == '__main__':
    build()
