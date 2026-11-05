# User documentation

This is the single source of truth for public project guides.

- `en/`: default English guide.
- `it/`: Italian translation, with the same page filenames.
- `assets/`: shared original component illustrations and BOM.

Run `python tools/build_guides.py` from this repository to produce `guide/en/`
and `guide/it/`. `launch.py` also builds guides before serving the preview.
The generated static pages work on GitHub Pages without a runtime or CDN.
Do not edit generated HTML or the generated guide/assets copies. The language selector links to the same page in
the other language, and `/guide/` opens English by default.

The dependency-free renderer supports the Markdown subset used here: headings,
paragraphs, lists, tables, links, images, bold, strikethrough and inline code.
Tool interfaces use the shared i18n/catalog.js and i18n/ui.js layer. English is
the default; the top-right selector changes display text without reloading a session.
Protocol data, input values and raw technical logs are not translated.
