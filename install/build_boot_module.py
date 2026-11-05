"""Embed the reviewed Python helper for delivery over raw REPL."""
from pathlib import Path
import json
root=Path(__file__).resolve().parent
(root/'boot-control.mjs').write_text('export const BOOT_CODE='+json.dumps((root/'boot_control.py').read_text(encoding='utf-8'))+';\n',encoding='utf-8')
