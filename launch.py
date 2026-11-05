"""Serve only the static app on loopback; computation stays in the browser."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import webbrowser


class DevelopmentHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control','no-store, no-cache, must-revalidate')
        self.send_header('Pragma','no-cache')
        self.send_header('Expires','0')
        super().end_headers()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--open', action='store_true', help='Open the preview in your default browser')
    args = ap.parse_args()
    root = Path(__file__).resolve().parent
    import runpy
    runpy.run_path(str(root/'tools/build_guides.py'),run_name='__main__')
    url = f'http://127.0.0.1:{args.port}/'
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(DevelopmentHandler, directory=str(root)))
    except OSError as exc:
        raise SystemExit(f'Impossibile avviare {url}: {exc}. Se la preview Ã¨ giÃ  attiva, apri quel link.')
    print(f'Vario Lab: {url}\nSolo file statici locali. Ctrl+C per terminare.', flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
