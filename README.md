# Vario Lab / VibeVario website

A browser laboratory to compare variometer filters and sounds on the same data,
with project guides, a firmware installer and a device configurator.

- **Lab:** replay a recording or receive USB/BLE samples, compare filters and listen.
- **Guides:** parts, illustrated assembly, installation, controls and design choices.
- **Configurator:** read, preview, apply and save device settings.
- **Installer:** try a MicroPython app in RAM or explicitly install it on UIFlow2.

English is the default. A top-right selector switches English/Italian without
reloading the tools or interrupting a connection. User recordings, input values,
protocol bytes and technical logs retain their original content.

## Local preview

```sh
python launch.py --open
```

Open `/` for the lab, `/guide/` for project guides, `/config/` for configuration
or `/install/` for installation. No Node.js, npm or backend is needed to use the
site. Device access needs a compatible browser on localhost or HTTPS.

## Build and verify

Use Python3 and Node.js20 or newer for development:

```sh
python verify.py
python build_site.py
python -m http.server 8767 --bind 127.0.0.1 --directory _site
```

`build_site.py` generates the bilingual guides from `docs/en` and `docs/it`, then
copies only public runtime assets into `_site/`. Author guides once in Markdown;
never hand-edit generated guide HTML. The parts list and original component SVGs
live in `docs/assets/` and are shared by both languages.

The bundled app and manifest under `install/firmware/` are a tested-build snapshot
from the [firmware repository](https://github.com/Liuk-ITA/vibevario), not a complete
ESP32 system image. The manifest SHA256 and byte count must match the app.
To update from a public firmware release:

```sh
python install/mirror_release.py Liuk-ITA/vibevario --tag latest
```

A firmware release asset should be mirrored into the site's own origin because
browser downloads directly from GitHub release URLs can be restricted by CORS.
The mirror helper validates board, size and SHA256. No private token is required.

## Publish on GitHub Pages

Repository name: **Liuk-ITA/vario-lab**. This keeps URLs aligned with the firmware
README. Set Settings ? Pages ? Source to **GitHub Actions**. Run the **Publish Pages**
workflow manually to deploy. Pushes and pull requests run checks; they do not deploy
automatically. The site supports the `/vario-lab/` repository subpath.

First verify the local build and its version before publishing. No network access,
GitHub account, deployment or firmware flashing happens as part of `build_site.py`.

## Boundaries and follow-up

No recordings are uploaded to a server. GitHub release lookups and the optional
ESP Web Tools system flasher fetch external resources only when requested.
There are no analytics or remote fonts. USB/BLE browser permissions remain explicit.
The demo has no GPS or absolute PC clocks. Its manual120cm reference is not true
instantaneous vertical speed. Optional Android HID pairing is still unresolved.

[Roadmap](ROADMAP.md) tracks the later Live/Record and experiment-panel redesign.
See [agent instructions](AGENTS.md), [credits](NOTICE.md) and [MIT license](LICENSE).
