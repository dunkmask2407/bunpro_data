"""
Bunpro Vocab Scraper — Script Unifié
=====================================
N5, N4, N3, N2, N1, Onomatopées → un seul JSON {deck: {leçon: [entrées]}}.

MODES :
  Sans login (rapide, ~5 exemples/mot via HTML statique) :
      python bunpro_vocab_scraper.py

  Avec login (Playwright, tous les exemples) :
      python bunpro_vocab_scraper.py --login

INSTALLATION :
    pip install requests beautifulsoup4 playwright
    playwright install chromium   # seulement pour --login
"""

import json, os, re, sys, time
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────
DECKS = [
    ("N5",           "https://bunpro.jp/decks/resqiy/bunpro-n5-vocab"),
    ("N4",           "https://bunpro.jp/decks/lh0vxb/bunpro-n4-vocab"),
    ("N3",           "https://bunpro.jp/decks/mvt76c/bunpro-n3-vocab"),
    ("N2",           "https://bunpro.jp/decks/dxbsvk/bunpro-n2-vocab"),
    ("N1",           "https://bunpro.jp/decks/qqovik/bunpro-n1-vocab"),
    ("Onomatopoeia", "https://bunpro.jp/decks/onoma/onomatopoeia"),
]
OUT_JSON = "bunpro_vocab.json"
BASE     = "https://bunpro.jp"
DELAY    = 0.55
TIMEOUT  = 25
HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr,fr-FR;q=0.9,en;q=0.8",
    # "Accept-Language": "en-US,en;q=0.9",
}

# ══════════════════════════════════════════════════════════════════════════════
# JAVASCRIPT (mode Playwright)
# ══════════════════════════════════════════════════════════════════════════════

# Convertit les ruby dans le DOM + extrait les exemples via li[id^="study-question-"]
VOCAB_EXTRACT_JS = """() => {
  // ── Furigana ──────────────────────────────────────────────────────────────
  document.querySelectorAll('ruby').forEach(ruby => {
    let r = '', base = '';
    for (const n of [...ruby.childNodes]) {
      if (n.nodeType === 3) base += n.textContent;
      else if (n.nodeName === 'RT') {
        const f = n.textContent.trim(), b = base.trim();
        r += (b && f) ? b+'('+f+')' : base; base = '';
      } else if (n.nodeName === 'RB') base += n.textContent;
      else if (n.nodeName !== 'RP')   base += n.textContent;
    }
    if (base.trim()) r += base.trim();
    ruby.replaceWith(document.createTextNode(r));
  });

  // ── Exemples : li[id^="study-question-"] ─────────────────────────────────
  const examples = [];
  document.querySelectorAll('li[id^="study-question-"]').forEach(li => {
    const jp = li.querySelector('p[data-force-furigana], p.bp-ddw');
    const en = li.querySelector('p.bp-sdw');
    if (jp && en) {
      const j = jp.innerText.trim(), e = en.innerText.trim();
      if (j && e) examples.push({ jp: j, en: e });
    }
  });

  return examples;
}"""

# Clique sur le bouton Fréquence et lit le menu déroulant (mode Playwright)
FREQ_READ_JS = """() => {
  const items = [];
  const selectors = [
    '[role="tooltip"]',
    '[data-radix-popper-content-wrapper] li',
    '[data-state="open"] li',
    '[role="menu"] [role="menuitem"]',
    '[role="menu"] li',
  ];
  for (const sel of selectors) {
    document.querySelectorAll(sel).forEach(el => {
      const t = el.innerText.trim();
      if (t) items.push(t);
    });
    if (items.length) break;
  }
  return items;
}"""
# FREQ_CLICK_JS = """() => {
#   const btn = [...document.querySelectorAll('button[aria-haspopup="menu"]')]
#     .find(b => {
#       const sp = b.querySelector('span');
#       return sp && (sp.textContent.includes('quence') || sp.textContent.includes('Freq'));
#     });
#   if (!btn) return false;
#   btn.click();
#   return true;
# }"""

# FREQ_READ_JS = """() => {
#   const items = [];
#   const selectors = [
#     '[role="menu"] [role="menuitem"]',
#     '[data-radix-popper-content-wrapper] li',
#     '[role="listbox"] [role="option"]',
#     '[role="menu"] li',
#   ];
#   for (const sel of selectors) {
#     document.querySelectorAll(sel).forEach(el => {
#       const t = el.innerText.trim();
#       if (t) items.push(t);
#     });
#     if (items.length) break;
#   }
#   return items;
# }"""

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS COMMUNS
# ══════════════════════════════════════════════════════════════════════════════

def clean(text):
    if not text: return ''
    lines = [l.strip() for l in str(text).splitlines()]
    out, prev = [], False
    for l in lines:
        if l: out.append(l); prev = False
        elif not prev: prev = True
    return '\n'.join(out).strip()

def save(output):
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

# ── HTTP (mode sans login) ────────────────────────────────────────────────────
def get(url):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status(); return r
        except requests.exceptions.RequestException as e:
            if attempt == 2: raise
            time.sleep(2 ** attempt)

# ── Furigana BeautifulSoup (mode sans login) ──────────────────────────────────
def process_ruby(soup):
    for ruby in soup.find_all('ruby'):
        parts, base = [], ''
        for child in ruby.children:
            if isinstance(child, NavigableString): base += str(child)
            elif isinstance(child, Tag):
                if child.name == 'rt':
                    furi = child.get_text(strip=True); b = base.strip()
                    parts.append(f"{b}({furi})" if (b and furi) else base); base = ''
                elif child.name == 'rb': base += child.get_text()
                elif child.name != 'rp': base += child.get_text()
        if base.strip(): parts.append(base.strip())
        ruby.replace_with(''.join(parts))
    return soup

# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTION DOM DIRECTE (BeautifulSoup)
# ══════════════════════════════════════════════════════════════════════════════

def parse_pitch_accent_from_soup(soup):
    """
    Extrait l'accent tonique avec ton Haut/Bas depuis le HTML.
    Source : attribut title="Haut"/"Bas" sur les <p> de chaque mora,
             ou position de la <span> (top-0 = Haut, bottom-0 = Bas).

    Retourne une liste de {"char": "わ", "tone": "Bas"}.
    Ex : [{"char":"わ","tone":"Bas"},{"char":"た","tone":"Haut"},{"char":"し","tone":"Haut"}]
    """
    div = soup.find('div', class_=lambda c: c and 'DetailsPitchAccent' in c)
    if not div:
        return []

    items = []
    for li in div.find_all('li'):
        p_el   = li.find('p')
        span_el = li.find('span', attrs={'aria-hidden': 'true'})
        if not p_el:
            continue
        char = p_el.get_text(strip=True)
        if not char:
            continue

        # 1er choix : attribut title (le plus fiable)
        tone = p_el.get('title', '')

        # Fallback : classe CSS de la span (top-0 = Haut, bottom-0 = Bas)
        if not tone and span_el:
            cls = ' '.join(span_el.get('class', []))
            if 'top-0' in cls:
                tone = 'Haut'
            elif 'bottom-0' in cls:
                tone = 'Bas'

        items.append({'char': char, 'tone': tone})

    return items

# ancien => prend en compte q'une forme de definition
# def parse_definitions_from_soup(soup):
#     """
#     Extrait les définitions structurées depuis le HTML.

#     Structure HTML ciblée :
#       <ol class="...pb-8...">          ← groupe POS
#         <li>
#           <p class="...text-tertiary-fg...">Pronom</p>   ← nature
#           <ol class="grid gap-4">
#             <li><p>1.</p><div><p> je, moi</p></div></li> ← sens
#           </ol>
#         </li>
#       </ol>

#     Si la page affiche "Aucune définition trouvée...", retourne [].
#     """
#     definitions = []

#     # Les <ol class="...pb-8..."> contiennent les groupes de définitions
#     for outer_ol in soup.find_all('ol', class_=lambda c: c and 'pb-8' in c):
#         for top_li in outer_ol.find_all('li', recursive=False):
#             # Nature (POS)
#             pos_p  = top_li.find('p', class_=lambda c: c and 'text-tertiary-fg' in c)
#             nature = pos_p.get_text(strip=True) if pos_p else ''

#             # Définitions
#             inner_ol = top_li.find('ol')
#             sens = []
#             if inner_ol:
#                 for def_li in inner_ol.find_all('li', recursive=False):
#                     div = def_li.find('div')
#                     if div:
#                         text = div.get_text(strip=True)
#                         if text:
#                             sens.append(text)

#             if nature or sens:
#                 definitions.append({'nature': nature, 'sens': sens})

#     return definitions

# nouveau => prend en cpmpte toute les formes de definition
def parse_definitions_from_soup(soup):
    """
    Compatible français (div simple) et anglais (métadonnées + bouton NSFW).

    Chaque entrée de `sens` :
      {"text": "...", "nsfw": False, "notes": "..."}
    `notes` : Abbreviation, Slang, See Also, Antonyms, etc.
    """
    definitions = []

    for outer_ol in soup.find_all('ol', class_=lambda c: c and 'pb-8' in c):
        for top_li in outer_ol.find_all('li', recursive=False):
            pos_p  = top_li.find('p', class_=lambda c: c and 'text-tertiary-fg' in c)
            nature = pos_p.get_text(strip=True) if pos_p else ''

            inner_ol = top_li.find('ol')
            sens = []
            if inner_ol:
                for def_li in inner_ol.find_all('li', recursive=False):
                    # ── NSFW : balise <button title="Unblur..."> ──────────
                    btn  = def_li.find('button', title=lambda t: t and 'NSFW' in t)
                    nsfw = btn is not None
                    container = btn if nsfw else def_li.find('div')
                    if not container:
                        continue

                    # ── Texte principal (premier <p>) ─────────────────────
                    main_p = container.find('p')
                    text   = main_p.get_text(strip=True) if main_p else ''
                    if not text:
                        continue

                    # ── Métadonnées (div.mt-4 : Abbreviation, See Also…) ──
                    notes_parts = []
                    meta_div = container.find('div', class_=lambda c: c and 'mt-4' in c)
                    if meta_div:
                        for child in meta_div.children:
                            if not hasattr(child, 'name'):
                                # NavigableStrings (virgules, espaces) → ignorer
                                continue
                            elif child.name == 'span':
                                t = child.get_text(strip=True)
                                if t: notes_parts.append(t)
                            elif child.name == 'div':   # "See Also:", "Antonyms:"…
                                label_p = child.find('p', class_='inline')
                                label   = label_p.get_text(strip=True) if label_p else ''
                                links   = [a.get_text(strip=True)
                                           for a in child.find_all('a')]
                                if label and links:
                                    notes_parts.append(f"{label} {', '.join(links)}")
                                elif label:
                                    notes_parts.append(label)

                    sens.append({
                        'text':  text,
                        'nsfw':  nsfw,
                        'notes': ', '.join(p for p in notes_parts if p),
                    })

            if nature or sens:
                definitions.append({'nature': nature, 'sens': sens})

    return definitions

def parse_freq_detail(raw_text):
    """
    Convertit le texte brut de l'overlay Fréquence en dict clé-valeur.
    Ex: "Fréquence\n\nListe\n\nClassement\n\nAnime\n\n35\n\nNetflix\n\n26"
     → {"Anime": "35", "Netflix": "26"}
    """
    if not raw_text:
        return {}
    SKIP = {'Fréquence', 'Frequency', 'Liste', 'List', 'Classement', 'Rank'}
    lines = [l.strip() for l in raw_text.splitlines()
             if l.strip() and l.strip() not in SKIP]
    result = {}
    for i in range(0, len(lines) - 1, 2):
        result[lines[i]] = lines[i + 1]
    return result

# ══════════════════════════════════════════════════════════════════════════════
# COLLECTE DES URLs D'UN DECK
# ══════════════════════════════════════════════════════════════════════════════

def get_page_count(deck_url):
    soup = BeautifulSoup(get(deck_url).text, 'html.parser')
    mx = 1
    for a in soup.find_all('a', href=True):
        m = re.search(r'[?&]page=(\d+)', a['href'])
        if m: mx = max(mx, int(m.group(1)))
    return mx

def get_vocab_urls(deck_url):
    """
    Retourne liste de (leçon, url, label).
    Dédup par (url, lesson) — une même URL peut apparaître dans deux leçons différentes.
    """
    n_pages = get_page_count(deck_url)
    print(f'    {n_pages} page(s) de pagination.')
    entries = []
    for p in range(1, n_pages + 1):
        url = f'{deck_url}?page={p}' if p > 1 else deck_url
        print(f'    Page {p}/{n_pages}…', end=' ', flush=True)
        soup   = BeautifulSoup(get(url).text, 'html.parser')
        lesson = '?'
        for tag in soup.find_all(True):
            txt = tag.get_text(strip=True)
            if re.match(r'^Lesson\s+\d+', txt, re.I) and tag.name in ('h1','h2','h3','h4','div','span','p'):
                if len(list(tag.children)) <= 3: lesson = txt.strip()
            elif tag.name == 'a' and tag.get('href','').startswith('/vocabs/'):
                entries.append((lesson, BASE + tag['href'], tag.get_text(' ', strip=True)))
        print('OK')
        time.sleep(DELAY)

    # Dédup par (url, leçon) — garde les doublons intentionnels dans des leçons différentes
    seen, unique = set(), []
    for lesson, url, label in entries:
        key = (url, lesson)
        if key not in seen:
            seen.add(key)
            unique.append((lesson, url, label))
    return unique

# ══════════════════════════════════════════════════════════════════════════════
# PARSING DU CONTENU D'UNE PAGE
# ══════════════════════════════════════════════════════════════════════════════

JLPT   = {'N1','N2','N3','N4','N5'}
POS_RE = re.compile(
    r'^(Noun|Pronoun|Verb|Adjective|い-[Aa]djective|な-[Aa]djective|'
    r'Adverb|Particle|Conjunction|Interjection|Suffix|Prefix|'
    r'Counter|Expression|Auxiliary|Numeral|Suru Verb|Godan Verb|Ichidan Verb)', re.I)
SKIP_LINES = {'--:--','Sentence','Translation','Phrase','Traduction',
              'Get more example sentences!','Try Bunpro','Self-Study Sentences',
              'Study your own way!','Bunpro','Simplifying Japanese'}
FOOTER     = {'Bunpro','© 2026','Official Apps','Join us!','Company'}

def has_jp(s): return bool(re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', s))
def has_en(s): return bool(re.search(r'[a-zA-Z]', s))

def parse_examples(lines, start):
    examples, cur_jp, cur_en, in_en = [], [], [], False
    for line in lines[start:]:
        if not line or line in SKIP_LINES: continue
        if line in FOOTER or line.startswith('© '): break
        if line.startswith('Get more') or line.startswith('Premium'): break
        if line in JLPT:
            if cur_jp or cur_en:
                examples.append({'jp':''.join(cur_jp), 'en':' '.join(cur_en)})
            cur_jp, cur_en, in_en = [], [], False
        elif not in_en:
            if has_en(line) and not has_jp(line): in_en = True; cur_en.append(line)
            elif has_jp(line) or (len(line) <= 3 and not has_en(line)): cur_jp.append(line)
        else: cur_en.append(line)
    if cur_jp or cur_en:
        examples.append({'jp':''.join(cur_jp), 'en':' '.join(cur_en)})
    return examples

def parse_vocab_page(url):
    soup = BeautifulSoup(get(url).text, 'html.parser')
    process_ruby(soup)
    for tag in soup.find_all(['script','style','svg','nav','footer','noscript']): tag.decompose()

    text  = soup.get_text('\n')
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    idx = {}
    # for i, l in enumerate(lines):
    #     if l == 'Bunpro Summary' and 'summary'  not in idx: idx['summary']  = i
    #     if l == 'All Forms'      and 'forms'    not in idx: idx['forms']    = i
    #     if l == 'Details'        and 'details'  not in idx: idx['details']  = i
    #     if l == 'Pitch Accent'   and 'pitch'    not in idx: idx['pitch']    = i
    #     if l == 'Frequency'      and 'freq'     not in idx: idx['freq']     = i
    #     if l == 'Examples'       and 'examples' not in idx: idx['examples'] = i
    
    for i, l in enumerate(lines):
        if l in ('Bunpro Summary', 'Résumé Bunpro')                  and 'summary'  not in idx: idx['summary']  = i
        if l in ('All Forms',      'Toutes les formes')              and 'forms'    not in idx: idx['forms']    = i
        if l in ('Details',        'Détails')                        and 'details'  not in idx: idx['details']  = i
        if l in ('Pitch Accent',   'Accent tonique')                 and 'pitch'    not in idx: idx['pitch']    = i
        if l in ('Frequency',      'Fréquence')                      and 'freq'     not in idx: idx['freq']     = i
        if l in ('Examples',       'Exemples')                       and 'examples' not in idx: idx['examples'] = i

    def between(a, *bs):
        start = idx.get(a)
        if start is None: return ''
        end = len(lines)
        for b in bs:
            if idx.get(b) and idx[b] > start: end = min(end, idx[b])
        chunk = []
        for l in lines[start+1:end]:
            if l in FOOTER or l.startswith('© '): break
            chunk.append(l)
        return clean('\n'.join(chunk))
    
    # ── all_forms : stop manuel au premier en-tête de section ──────────────
    _DETAIL_STOP = {'Details', 'Pitch Accent', 'Frequency', 'Examples',
                    'Accent tonique', 'Fréquence', 'Exemples'}
    _forms_raw   = between('forms')          # large, filtré manuellement
    _forms_lines = []
    for _l in _forms_raw.splitlines():
        if _l in _DETAIL_STOP:
            break
        _forms_lines.append(_l)
    forms_txt = clean('\n'.join(_forms_lines))

    # forms_txt = between('forms', 'details')
    # forms_txt = between('forms', 'details', 'examples')
    mot = lecture = ''
    if forms_txt:
        m = re.match(r'^(\S+)\s*[【\[]\s*(\S+)\s*[】\]]', forms_txt)
        if m: mot, lecture = m.group(1), m.group(2)
        else: mot = forms_txt.split('\n')[0]
    
    # ── bunpro_summary : stop avant la première ligne POS ou "1." ──────────
    _bs_raw   = between('summary', 'forms')
    _bs_lines = []
    for _l in _bs_raw.splitlines():
        if POS_RE.match(_l) or re.match(r'^\d+\s*\.', _l):
            break
        _bs_lines.append(_l)
    bunpro_summary = clean('\n'.join(_bs_lines))

    # bunpro_summary = between('summary', 'forms')
    # bunpro_summary = between('summary', 'forms', 'details', 'examples')

    # defs_text   = between('summary', 'forms') if 'forms' in idx else ''
    # definitions = []
    # cur_pos, cur_means = '', []
    # for line in defs_text.splitlines():
    #     l = line.strip()
    #     if not l or l in ('.', ',') or l.isdigit(): continue
    #     if POS_RE.match(l):
    #         if cur_pos or cur_means: definitions.append({'nature': cur_pos, 'sens': cur_means})
    #         cur_pos = l; cur_means = []
    #     elif l not in (bunpro_summary or '').split('\n') and len(l) > 1:
    #         cur_means.append(l)
    # if cur_pos or cur_means: definitions.append({'nature': cur_pos, 'sens': cur_means})

    # ex_start = idx.get('examples')
    
    # ── frequence : juste la première ligne ("Netflix Top 100") ────────────
    _freq_raw = between('freq')
    frequence = _freq_raw.split('\n')[0].strip() if _freq_raw else ''
    
    return {
        'url':            url,
        'mot':            mot,
        'lecture':        lecture,
        'bunpro_summary': bunpro_summary,
        # 'definitions':    definitions,
        'all_forms':      forms_txt,
        'pitch_accent':   between('pitch'),
        # 'pitch_accent':   between('pitch', 'freq', 'examples'),
        'frequence':      frequence,
        # 'frequence':      between('freq', 'examples'),
        # 'exemples':       parse_examples(lines, ex_start + 1) if ex_start is not None else [],
    }

# ══════════════════════════════════════════════════════════════════════════════
# MODE SANS LOGIN — requests + BeautifulSoup
# ══════════════════════════════════════════════════════════════════════════════

def parse_vocab_requests(url):
    soup = BeautifulSoup(get(url).text, 'html.parser')
    process_ruby(soup)

    # ── Extraction DOM (AVANT décomposition des balises) ─────────────────
    pitch_items = parse_pitch_accent_from_soup(soup)
    definitions = parse_definitions_from_soup(soup)
    
    # Supprimer les éléments parasites pour le parsing textuel
    for tag in soup.find_all(['script','style','svg','nav','footer','noscript']):
        tag.decompose()
        
    # text    = soup.get_text('\n')
    parsed  = parse_vocab_page(url)
    ex_start = parsed.pop('_examples_start')
    lines    = parsed.pop('_lines')
    parsed['exemples'] = parse_examples(lines, ex_start + 1) if ex_start is not None else []
    
    # Remplacer par les résultats DOM (plus précis que le parsing textuel)
    # parsed['pitch_accent'] = pitch_items
    # if definitions:
    #     parsed['definitions'] = definitions
    # else:
    #     parsed['definitions'] = []
    
    # parsed['url'] = url
    # return parsed
    
    return {
        'url':     url,
        'label':   '',   # renseigné par scrape_deck
        'mot':     parsed.get('mot', ''),
        'lecture': parsed.get('lecture', ''),
        'dictionary_definition': {
            'bunpro_summary': parsed.get('bunpro_summary', ''),
            'all_forms':      parsed.get('all_forms', ''),
            'definitions':    definitions,
        },
        'details': {
            'pitch_accent':    pitch_items,
            'frequence_detail': {
                'frequence': parsed.get('frequence', ''),
                'stats':     {},   # disponible uniquement en mode --login
            },
        },
        'exemples': parsed.get('exemples', []),
    }

# ══════════════════════════════════════════════════════════════════════════════
# MODE LOGIN — Playwright (tous les exemples)
# ══════════════════════════════════════════════════════════════════════════════

def parse_vocab_playwright(pw_page, url):
    """
    Navigue vers l'URL, extrait les exemples via DOM et le reste via inner_text.
    Extrait le contenu via Playwright (navigateur authentifié).
    - pitch_accent et definitions : BeautifulSoup sur le HTML de la page rendue
    - exemples : DOM JS (li[id^="study-question-"]) → tous les exemples
    - frequence_detail : menu déroulant cliqué (best-effort)
    """
    try:
        pw_page.goto(url, wait_until='networkidle', timeout=30000)
    except PWTimeout:
        try:
            pw_page.goto(url, wait_until='domcontentloaded', timeout=30000)
            pw_page.wait_for_timeout(2000)
        except:
            return None   # sera réessayé par l'appelant

    pw_page.wait_for_timeout(300)
    
    # ── Extraction DOM via BeautifulSoup sur HTML rendu ───────────────────
    try:
        html      = pw_page.content()
        soup_pw   = BeautifulSoup(html, 'html.parser')
        process_ruby(soup_pw)
        pitch_items = parse_pitch_accent_from_soup(soup_pw)
        definitions = parse_definitions_from_soup(soup_pw)
    except:
        pitch_items = []
        definitions = []

    # ── Exemples via DOM (tous, pas limités au HTML statique) ─────────────
    try:
        exemples = pw_page.evaluate(VOCAB_EXTRACT_JS) or []
    except:
        exemples = []
    
    # Fallback exemples sur inner_text si DOM JS vide
    # if not exemples:
    #     try:
    #         lines2  = [l.strip() for l in pw_page.inner_text('body').splitlines() if l.strip()]
    #         ex_idx  = next((i for i, l in enumerate(lines2) if l in ('Exemples','Examples')), None)
    #         if ex_idx is not None:
    #             exemples = parse_examples(lines2, ex_idx + 1)
    #     except: pass

    # ── Fréquence détaillée (clic sur le menu déroulant) ─────────────────
    # try:
    #     clicked = pw_page.evaluate(FREQ_CLICK_JS)
    #     if clicked:
    #         pw_page.wait_for_timeout(400)
    #         frequence_detail = pw_page.evaluate(FREQ_READ_JS) or []
    #         pw_page.keyboard.press('Escape')
    #         pw_page.wait_for_timeout(100)
    # except:
    #     frequence_detail = []
    try:
        freq_btn = pw_page.locator('button[aria-haspopup="menu"]').filter(has_text='quence').first
        freq_btn.hover()                                  # déclenche le tooltip au survol
        pw_page.wait_for_timeout(500)                    # attendre l'apparition de l'overlay
        frequence_detail = pw_page.evaluate(FREQ_READ_JS) or []
        pw_page.mouse.move(0, 0)                         # déplacer le curseur pour fermer l'overlay
        pw_page.wait_for_timeout(150)
        # print(pw_page.evaluate("() => document.body.innerHTML").count('data-state'))
    except:
        frequence_detail = []

    # ── Reste du contenu via inner_text ───────────────────────────────────
    try:
        # text   = pw_page.inner_text('body')
        parsed = parse_vocab_page(url)
        parsed.pop('_examples_start', None)
        parsed.pop('_lines', None)
    except:
        parsed = {
            'mot':'','lecture':'','bunpro_summary':'',
            'all_forms':'','frequence':'',
        }
        # parsed = {
        #     'mot':'','lecture':'','bunpro_summary':'',
        #     'definitions':[],'all_forms':'',
        #     'pitch_accent':'','frequence':'',
        # }

    # Si DOM n'a rien trouvé, fallback sur le parsing textuel
    if not exemples:
        try:
            text2  = pw_page.inner_text('body')
            lines2 = [l.strip() for l in text2.splitlines() if l.strip()]
            ex_idx = next((i for i, l in enumerate(lines2) if l in ('Exemples','Examples')), None)
            if ex_idx is not None:
                exemples = parse_examples(lines2, ex_idx + 1)
        except: pass

    # ── Assemblage final ──────────────────────────────────────────────────
    # parsed['url']      = url
    # parsed['pitch_accent']     = pitch_items
    # parsed['definitions']      = definitions
    # if frequence_detail:
    #     parsed['frequence_detail'] = frequence_detail
    # parsed['exemples'] = exemples
    # return parsed
    
    # Parser le texte brut de l'overlay fréquence
    freq_stats = {}
    if frequence_detail:
        raw = frequence_detail[0] if isinstance(frequence_detail, list) else frequence_detail
        freq_stats = parse_freq_detail(raw)

    return {
        'url':     url,
        'label':   '',
        'mot':     parsed.get('mot', ''),
        'lecture': parsed.get('lecture', ''),
        'dictionary_definition': {
            'bunpro_summary': parsed.get('bunpro_summary', ''),
            'all_forms':      parsed.get('all_forms', ''),
            'definitions':    definitions,
        },
        'details': {
            'pitch_accent':    pitch_items,
            'frequence_detail': {
                'frequence': parsed.get('frequence', ''),
                'stats':     freq_stats,
            },
        },
        'exemples': exemples,
    }

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPING D'UN DECK
# ══════════════════════════════════════════════════════════════════════════════

def scrape_deck(slug, deck_url, output, pw_page=None):
    login_mode = pw_page is not None
    mode_label = 'Playwright (login)' if login_mode else 'requests'
    print(f'\n{"═"*65}')
    print(f'  DECK : {slug.upper()}  [{mode_label}]')
    print(f'  {deck_url}')
    print(f'{"═"*65}')
    
    print('  Collecte des URLs…')
    entries = get_vocab_urls(deck_url)
    print(f'  → {len(entries)} mots uniques.')

    output[slug] = {}
    ok = err = 0

    for i, (lesson, url, label) in enumerate(entries):
        if lesson not in output[slug]:
            output[slug][lesson] = []
            print(f'\n  {lesson}')

        print(f'    [{i+1:4d}/{len(entries)}] {label[:55]:<55}', end=' … ', flush=True)
        try:         
            if login_mode:
                data=parse_vocab_playwright(pw_page,url)
                if data is None:
                    raise RuntimeError('navigation échouée')
                # Délai poli entre pages Playwright
                time.sleep(DELAY + 0.3)
            else:
                data = parse_vocab_requests(url)
                time.sleep(DELAY + (i % 4) * 0.1)
                
            data['label'] = label

            # ── Fallback mot : si parse_sections_from_text n'a pas trouvé le mot,
            #    utiliser le label du deck (ex : "レストラン", "私 【わたし】", etc.)
            # if not data.get('mot') and label:
            #     data['mot'] = re.split(r'[\s【\[]', label)[0].strip()
                
            # if not data.get('lecture') and data.get('mot'):
            #     # Pour les mots katakana purs, la lecture = le mot lui-même
            #     if re.fullmatch(r'[\u30a0-\u30ff\u30fc]+', data['mot']):
            #         data['lecture'] = data['mot']
                    
            output[slug][lesson].append(data)
            ex_count = len(data['exemples'])
            print(f'OK  ({ex_count} ex.)')
            ok += 1
        except Exception as e:
            print(f'ERR {str(e)[:50]}')
            # output[slug][lesson].append({
            #     'url':url,'label':label,'erreur':str(e),
            #     'mot':'','lecture':'','bunpro_summary':'',
            #     'definitions':[],'all_forms':'',
            #     'pitch_accent':'','frequence':'','exemples':[],
            # })
            
            output[slug][lesson].append({
                'url': url, 'label': label, 'erreur': str(e),
                'mot': '', 'lecture': '',
                'dictionary_definition': {
                    'bunpro_summary': '', 'all_forms': '', 'definitions': []},
                'details': {
                    'pitch_accent': [],
                    'frequence_detail': {'frequence': '', 'stats': {}}},
                'exemples': [],
            })
            err += 1

        # ── Sauvegarde après chaque leçon terminée ────────────────────────
        is_last    = (i + 1 >= len(entries))
        next_les   = entries[i+1][0] if not is_last else None
        if is_last or next_les != lesson:
            save(output)
            print(f'    💾 {lesson} terminé(e)')

        time.sleep(DELAY + (i % 4) * 0.1)

    print(f'\n  ✓ {slug.upper()} : {ok} OK, {err} erreurs.')
    return ok, err

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    login_mode = '--login' in sys.argv

    print('╔' + '═'*65 + '╗')
    print('║  Bunpro Vocab Scraper — Script Unifié                           ║')
    print('╚' + '═'*65 + '╝')
    if login_mode:
        print('\n  Mode LOGIN (Playwright) — tous les exemples seront extraits.')
        print('  Un navigateur va s\'ouvrir pour vous connecter.\n')
    else:
        print('\n  Mode rapide (requests) — ~5 exemples/mot.')
        print('  Utilisez --login pour accéder à tous les exemples.\n')

    print(f'  Decks  : {", ".join(s for s,_ in DECKS)}')
    print(f'  Sortie : {OUT_JSON}\n')

    # Reprise depuis sauvegarde existante
    if os.path.exists(OUT_JSON):
        with open(OUT_JSON, encoding='utf-8') as f:
            output = json.load(f)
        print('  Reprise depuis sauvegarde existante.\n')
    else:
        output = {}
    
    # ── Mode URL unique (test/debug) ──────────────────────────────────────
    single_url = None
    for arg in sys.argv[1:]:
        if arg.startswith('http'):
            single_url = arg
            break

    if single_url:
        print(f'  Mode URL unique : {single_url}\n')
        if login_mode:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=False, slow_mo=50, args=['--lang=fr-FR'])
                ctx = browser.new_context(locale='fr-FR', viewport={'width':1280,'height':900},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36')
                pw_page = ctx.new_page()
                pw_page.goto('https://bunpro.jp/users/sign_in', wait_until='networkidle', timeout=30000)
                input('  Connectez-vous puis appuyez sur ENTRÉE...')
                data = parse_vocab_playwright(pw_page, single_url)
                browser.close()
        else:
            data = parse_vocab_requests(single_url)

        if data:
            # data['label'] = single_url.split('/')[-1]
            data['label'] = unquote(single_url.split('/')[-1].split('?')[0])
        print(json.dumps(data, ensure_ascii=False, indent=2))
        with open('bunpro_vocab_test.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'\n  → bunpro_vocab_test.json')
        return
    # ── Fin mode URL unique ───────────────────────────────────────────────

    total_ok = total_err = 0

    if login_mode:
        # ── Mode Playwright ───────────────────────────────────────────────
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False,   # visible pour la connexion
                slow_mo=50,
                args=['--lang=fr-FR'],
            )
            ctx = browser.new_context(
                locale='fr-FR',
                viewport={'width': 1280, 'height': 900},
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36'
                ),
            )
            pw_page = ctx.new_page()

            # Connexion
            pw_page.goto('https://bunpro.jp/users/sign_in',
                         wait_until='networkidle', timeout=30000)
            input('  Connectez-vous dans le navigateur, puis appuyez sur ENTRÉE...')
            print('  Connexion validée. Démarrage du scraping...\n')

            for slug, deck_url in DECKS:
                ok, err = scrape_deck(slug, deck_url, output, pw_page=pw_page)
                total_ok += ok; total_err += err
                save(output)
                print(f'  💾 Deck {slug.upper()} sauvegardé.')

            browser.close()
    else:
        # ── Mode requests (sans login) ────────────────────────────────────
        for slug, deck_url in DECKS:
            ok, err = scrape_deck(slug, deck_url, output, pw_page=None)
            total_ok += ok; total_err += err
            save(output)
            print(f'  💾 Deck {slug.upper()} sauvegardé.')

    save(output)
    print(f'\n  ✓ Total : {total_ok} OK, {total_err} erreurs  → {OUT_JSON}')

if __name__ == '__main__':
    main()
