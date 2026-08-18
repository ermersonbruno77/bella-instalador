#!/usr/bin/env python3
"""Ferramenta web GRATIS pro agente (sem chave). Uso:
  python3 web.py search "consulta"      -> resultados do DuckDuckGo
  python3 web.py fetch "https://url"     -> texto limpo da pagina
"""
import sys

def do_search(q, n=6):
    from ddgs import DDGS
    with DDGS() as d:
        for i, r in enumerate(d.text(q, max_results=n), 1):
            print(f"{i}. {r.get('title','')}\n   {r.get('href','')}\n   {r.get('body','')[:200]}\n")

def do_fetch(url):
    import requests, html2text
    r = requests.get(url, timeout=25, headers={'User-Agent':'Mozilla/5.0'})
    h = html2text.HTML2Text(); h.ignore_links=False; h.ignore_images=True; h.body_width=0
    txt = h.handle(r.text)
    print(txt[:6000])

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('uso: web.py search "q" | web.py fetch "url"'); sys.exit(2)
    if sys.argv[1] == 'search': do_search(sys.argv[2])
    elif sys.argv[1] == 'fetch': do_fetch(sys.argv[2])
    else: print('acao invalida')
