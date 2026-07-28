# -*- coding: utf-8 -*-
"""Extrae el <script> de index.html para validar sintaxis con `node --check`
antes de commitear -- nunca se publica un index.html con JS roto."""
import re

HTML_PATH = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\index.html"
OUT_PATH = r"C:\SoccerAnalyticsExtractor\atlas_lab_mockup\pipeline\_work\extracted.js"

with open(HTML_PATH, encoding="utf-8") as f:
    html = f.read()
m = re.search(r"<script>(.*)</script>", html, re.S)
with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(m.group(1))
print("extracted", len(m.group(1)))
