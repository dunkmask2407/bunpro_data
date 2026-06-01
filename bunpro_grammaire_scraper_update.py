"""
Bunpro Grammaire Scraper — Version DOM-directe
===============================================
Extraction par ID HTML (#structure, #details, #examples, #online, #offline).
Sauvegarde automatique après chaque leçon terminée.

INSTALLATION :  pip install playwright && playwright install chromium
UTILISATION  :  python bunpro_grammaire_scraper.py [--login]
"""

import csv, json, os, re, sys, time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

CSV_FILE = "bunpro_grammaire_complet_new.csv"
OUT_JSON = "bunpro_grammaire.json"
DELAY    = 1.3
TIMEOUT  = 30000

# ══════════════════════════════════════════════════════════════════════════════
# JAVASCRIPT
# ══════════════════════════════════════════════════════════════════════════════

FURIGANA_JS = """() => {
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
}"""

# EXTRACT_DOM_JS = """() => {
#   const res = { has_poli: false, détails: {}, exemples: [], en_ligne: [], hors_ligne: [] };

#   // Structure : Standard/Poli ?
#   const sh = document.querySelector('header[id="structure"]');
#   if (sh) {
#     const btns = [...(sh.querySelector('ul') || { querySelectorAll:()=>[] }).querySelectorAll('button')];
#     res.has_poli = btns.some(b => b.textContent.trim() === 'Poli');
#     const std = btns.find(b => b.textContent.trim() === 'Standard');
#     if (std) std.click();
#   }

#   // Détails
#   const dh = document.querySelector('header[id="details"]');
#   if (dh) {
#     const sec = dh.closest('section') || dh.parentElement;
#     sec.querySelectorAll(':scope li').forEach(li => {
#       const lbl = li.querySelector('h4');
#       const val = li.querySelector('p');
#       if (lbl && val) {
#         const key = lbl.innerText.trim().toLowerCase();
#         if (key) res.détails[key] = val.innerText.trim();
#       }
#     });
#   }

#   // Exemples
#   document.querySelectorAll('li[id^="study-question-"]').forEach(li => {
#     const jp = li.querySelector('p[data-force-furigana], p.bp-ddw');
#     const en = li.querySelector('p.bp-sdw');
#     if (jp && en) {
#       const j = jp.innerText.trim(), e = en.innerText.trim();
#       if (j && e) res.exemples.push({ jp: j, en: e });
#     }
#   });

#   // En ligne
#   const oh = document.querySelector('header[id="online"]');
#   if (oh) {
#     const parent = oh.closest('li') || oh.parentElement;
#     parent.querySelectorAll('li[id^="SupplementalLink"]').forEach(li => {
#       const a   = li.querySelector('h3 a');
#       const sp  = a ? a.querySelector('span') : null;
#       const src = li.querySelector('p');
#       res.en_ligne.push({
#         titre:  (sp || a) ? (sp || a).innerText.trim() : '',
#         url:    a ? a.href : '',
#         source: src ? src.innerText.trim() : '',
#       });
#     });
#   }

#   // Hors ligne
#   const ofh = document.querySelector('header[id="offline"]');
#   if (ofh) {
#     const parent = ofh.closest('li') || ofh.parentElement;
#     parent.querySelectorAll('li[id^="OfflineResource"]').forEach(li => {
#       const sp  = li.querySelector('h3 span');
#       const ref = li.querySelector('p');
#       res.hors_ligne.push({
#         titre:     sp  ? sp.innerText.trim()  : '',
#         référence: ref ? ref.innerText.trim() : '',
#       });
#     });
#   }

#   return res;
# }"""

EXTRACT_DOM_JS = """() => {
  const res = {
    has_poli: false, label: {}, détails: {},
    exemples: [], en_ligne: [], hors_ligne: [],
    synonymes: [], antonymes: [], en_lien: [],
    à_propos_groupes: []
  };

  // ── Label (1er header de main) ─────────────────────────────────────────
  const mainGrid = document.querySelector(
    'main div.grid.gap-24.text-center, [role="main"] div.grid.gap-24.text-center'
  );
  if (mainGrid) {
    const h1 = mainGrid.querySelector('h1');
    if (h1) {
      const formeEl = h1.querySelector('[data-force-furigana], .bp-ddw');
      const tradEl  = h1.querySelector('.mt-4.block, .text-primary-contrast');
      res.label.forme_jp   = formeEl ? formeEl.innerText.trim() : '';
      res.label.traduction = tradEl  ? tradEl.innerText.trim()  : '';
    }
    const warnEl = mainGrid.querySelector('p.text-warning .bp-sdw, p.text-warning em');
    if (warnEl) res.label.avertissement = warnEl.innerText.trim();
  }

  // ── Structure : Standard/Poli ? ────────────────────────────────────────
  const sh = document.querySelector('header[id="structure"]');
  if (sh) {
    const btns = [...(sh.querySelector('ul') || {querySelectorAll:()=>[]}).querySelectorAll('button')];
    res.has_poli = btns.some(b => ['Poli','Polite'].includes(b.textContent.trim()));
    const std = btns.find(b => b.textContent.trim() === 'Standard');
    if (std) std.click();
  }

  // ── Détails ────────────────────────────────────────────────────────────
  const dh = document.querySelector('header[id="details"]');
  if (dh) {
    const sec = dh.closest('section') || dh.parentElement;
    sec.querySelectorAll(':scope li').forEach(li => {
      const lbl = li.querySelector('h4'), val = li.querySelector('p');
      if (lbl && val) {
        const key = lbl.innerText.trim().toLowerCase();
        if (key) res.détails[key] = val.innerText.trim();
      }
    });
  }

  // ── Exemples (section Examples) ────────────────────────────────────────
  document.querySelectorAll('li[id^="study-question-"]').forEach(li => {
    const jp = li.querySelector('p[data-force-furigana], p.bp-ddw');
    const en = li.querySelector('p.bp-sdw');
    if (jp && en) {
      const j = jp.innerText.trim(), e = en.innerText.trim();
      if (j && e) res.exemples.push({ jp: j, en: e });
    }
  });

  // ── En ligne ───────────────────────────────────────────────────────────
  const oh = document.querySelector('header[id="online"]');
  if (oh) {
    const parent = oh.closest('li') || oh.parentElement;
    parent.querySelectorAll('li[id^="SupplementalLink"]').forEach(li => {
      const a = li.querySelector('h3 a'), sp = a ? a.querySelector('span') : null;
      const src = li.querySelector('p');
      res.en_ligne.push({
        titre: (sp || a) ? (sp || a).innerText.trim() : '',
        url: a ? a.href : '',
        source: src ? src.innerText.trim() : '',
      });
    });
  }

  // ── Hors ligne ─────────────────────────────────────────────────────────
  const ofh = document.querySelector('header[id="offline"]');
  if (ofh) {
    const parent = ofh.closest('li') || ofh.parentElement;
    parent.querySelectorAll('li[id^="OfflineResource"]').forEach(li => {
      const sp = li.querySelector('h3 span'), ref = li.querySelector('p');
      res.hors_ligne.push({
        titre: sp ? sp.innerText.trim() : '',
        référence: ref ? ref.innerText.trim() : '',
      });
    });
  }

  // ── Synonymes / Antonymes / En lien (DOM structuré) ────────────────────
  function extractRelated(headerId) {
    const hdr = document.querySelector(`header[id="${headerId}"]`);
    if (!hdr) return [];
    const art = hdr.closest('article');
    if (!art) return [];
    const out = [];
    art.querySelectorAll('li[id^="related-content-"]').forEach(li => {
      const regle   = li.querySelector('h4');
      const trad    = li.querySelector('p.line-clamp-1.text-secondary-fg');
      const niveauEl= li.querySelector('[class*="bg-subheader"] span');
      const desc    = li.querySelector('p[data-force-furigana]');
      const a       = li.querySelector('a[href]');
      out.push({
        regle:       regle   ? regle.innerText.trim()   : '',
        traduction:  trad    ? trad.innerText.trim()    : '',
        niveau:      niveauEl? niveauEl.innerText.trim(): '',
        description: desc    ? desc.innerText.trim()    : '',
        url:         a       ? a.href                   : '',
      });
    });
    return out;
  }
  res.synonymes = extractRelated('synonyms');
  res.antonymes = extractRelated('antonyms');
  res.en_lien   = extractRelated('related');

  // ── Exemples inline de à_propos (.writeup-examples--holder) ───────────
  document.querySelectorAll('.writeup-examples--holder').forEach(holder => {
    const grp = [];
    holder.querySelectorAll('li[data-study-question]').forEach(li => {
      const jpEl = li.querySelector('p[data-force-furigana]');
      const enEl = li.querySelector('p.bp-sdw');
      if (!jpEl || !enEl) return;
      const jpHl = [...jpEl.querySelectorAll('.text-primary-accent, [data-gp-id]')]
                     .map(e => e.innerText.trim()).filter(Boolean);
      const enHl = [...enEl.querySelectorAll('strong')]
                     .map(e => e.innerText.trim()).filter(Boolean);
      const noteEl = li.querySelector('p.text-extra-small [data-force-furigana], p.text-tertiary-fg span[data-force-furigana]');
      grp.push({
        jp:           jpEl.innerText.trim(),
        en:           enEl.innerText.trim(),
        jp_highlight: jpHl,
        en_highlight: enHl,
        note:         noteEl ? noteEl.innerText.trim() : '',
      });
    });
    if (grp.length) res.à_propos_groupes.push(grp);
  });

  return res;
}"""

STRUCTURE_READ_JS = """() => {
  const sh = document.querySelector('header[id="structure"]');
  if (!sh) return '';
  const sec = sh.closest('section');
  const p = sec ? sec.querySelector('p[data-force-furigana], p.bp-ddw') : null;
  return p ? p.innerText.trim() : '';
}"""

CLICK_STRUCTURE_JS = """(variant) => {
  const sh = document.querySelector('header[id="structure"]');
  if (!sh) return false;
  const btn = [...(sh.querySelector('ul')||{querySelectorAll:()=>[]}).querySelectorAll('button')]
    .find(b => b.textContent.trim() === variant);
  if (btn) { btn.click(); return true; }
  return false;
}"""

# EXPAND_JS = """() => {
#   let n = 0;
#   const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
#   const els = []; let node;
#   while ((node = walker.nextNode()))
#     if (node.textContent.trim() === 'Tout développer') els.push(node.parentElement);
#   els.forEach(el => { try { (el.closest('button,a,[onclick]') || el).click(); n++; } catch(e){} });
#   return n;
# }"""

EXPAND_JS = """() => {
  let n = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const els = []; let node;
  while ((node = walker.nextNode()))
    if (['Tout développer','Expand all','Expand All'].includes(node.textContent.trim())) els.push(node.parentElement);
  els.forEach(el => { try { (el.closest('button,a,[onclick]') || el).click(); n++; } catch(e){} });
  return n;
}"""

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

NOISE = {
    # Français
    'Tout développer','Tout réduire','Réduire tout','Bachotage rapide',
    'Ajouter aux Révisions','Marquer comme Maîtrisé','Ajouter une note',
    'Ajouter à un Paquet','Ajouter une phrase personnalisée',
    'Tout marquer comme lu','Ne plus afficher ce message','nous contacter',
    'Anglais','Japonais',
    # Anglais
    'Expand all','Expand All','Collapse all','Quick Study',
    'Add to Reviews','Mark as Mastered','Add Note',
    'Add to Deck','Add custom sentence',
    'Mark all as read','Stop showing this','contact us',
    'English','Japanese',
}

def clean(text):
    if not text: return ''
    lines = [l.strip() for l in str(text).splitlines()]
    out, prev = [], False
    for l in lines:
        if l: out.append(l); prev = False
        elif not prev: out.append(''); prev = True
    return '\n'.join(out).strip()

def inject(page):
    try: page.evaluate(FURIGANA_JS)
    except: pass

def save(output):
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

def to_array(s):
    """Convertit une string multiligne en liste de lignes non vides."""
    return [l.strip() for l in (s or '').splitlines() if l.strip()]

# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURE Standard + Poli
# ══════════════════════════════════════════════════════════════════════════════

def get_structure_variants(page, has_poli):
    std = poli = ''
    try:
        page.wait_for_timeout(400)
        inject(page)
        std = clean(page.evaluate(STRUCTURE_READ_JS) or '')
        if has_poli:
            # page.evaluate(CLICK_STRUCTURE_JS, 'Poli')
            poli_label = 'Polite' if page.evaluate("() => !![...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Polite')") else 'Poli'
            page.evaluate(CLICK_STRUCTURE_JS, poli_label)
            page.wait_for_timeout(400)
            inject(page)
            poli = clean(page.evaluate(STRUCTURE_READ_JS) or '')
            page.evaluate(CLICK_STRUCTURE_JS, 'Standard')
            page.wait_for_timeout(200)
    except: pass
    # return std, poli
    return to_array(std), to_array(poli)

# ══════════════════════════════════════════════════════════════════════════════
# SECTIONS TEXTUELLES (à_propos, synonymes, antonymes, en_lien)
# ══════════════════════════════════════════════════════════════════════════════

def parse_text_sections(text):
    lines  = [l.strip() for l in text.splitlines() if l.strip()]
    result = {}
    MARKERS = [
        ('à_propos',  lambda l: l.startswith('À propos de') or l.startswith('About ')),
        ('synonymes', lambda l: l in ('Synonymes','Synonyms')),
        ('antonymes', lambda l: l in ('Antonymes','Antonyms')),
        ('en_lien',   lambda l: l in ('En lien','Related')),
    ]
    occ = {k: [] for k, _ in MARKERS}
    for i, line in enumerate(lines):
        for key, fn in MARKERS:
            if fn(line): occ[key].append(i)
    ordered = [(occ[k][0], k) for k, _ in MARKERS if occ[k]]
    ordered.sort()
    for i, (start, key) in enumerate(ordered):
        end     = ordered[i+1][0] if i+1 < len(ordered) else len(lines)
        content = [l for l in lines[start+1:end] if l not in NOISE]
        result[key] = clean('\n'.join(content))
    return result

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPING D'UNE PAGE
# ══════════════════════════════════════════════════════════════════════════════

def scrape_page(pw_page, url):
    # res = {
    #     'structure_standard':'', 'structure_poli':'',
    #     'détails':{}, 'à_propos':'',
    #     'synonymes':'', 'antonymes':'', 'en_lien':'',
    #     'exemples':[], 'en_ligne':[], 'hors_ligne':[],
    # }
    res = {
        'label':{},
        'structure_standard':[], 'structure_poli':[],
        'détails':{}, 'à_propos':[],
        'synonymes':[], 'antonymes':[], 'en_lien':'',
        'en_ligne':[], 'hors_ligne':[], 'exemples':[],
    }
    try:
        pw_page.goto(url, wait_until='networkidle', timeout=TIMEOUT)
    except PWTimeout:
        try:
            pw_page.goto(url, wait_until='domcontentloaded', timeout=TIMEOUT)
            pw_page.wait_for_timeout(2500)
        except: return res

    inject(pw_page)
    pw_page.wait_for_timeout(300)

    try:
        dom = pw_page.evaluate(EXTRACT_DOM_JS) or {}
        res['détails']    = dom.get('détails',   {})
        res['exemples']   = dom.get('exemples',  [])
        res['en_ligne']   = dom.get('en_ligne',  [])
        res['hors_ligne'] = dom.get('hors_ligne',[])
        has_poli          = dom.get('has_poli',  False)
    except: has_poli = False

    std, poli = get_structure_variants(pw_page, has_poli)
    res['structure_standard'] = std
    res['structure_poli']     = poli

    try:
        n = pw_page.evaluate(EXPAND_JS)
        if n: pw_page.wait_for_timeout(700); inject(pw_page)
    except: pass

    try:
        res.update(parse_text_sections(pw_page.inner_text('body')))
    except: pass
    
    try:
        # Label depuis DOM
        if dom.get('label'):
            res['label'] = dom['label']
        # Synonymes / antonymes / en_lien depuis DOM (écrasent la version texte)
        if dom.get('synonymes'): res['synonymes'] = dom['synonymes']
        if dom.get('antonymes'): res['antonymes'] = dom['antonymes']
        if dom.get('en_lien'):   res['en_lien']   = dom['en_lien']
        # à_propos → liste de paragraphes
        if isinstance(res.get('à_propos'), str):
            res['à_propos'] = [p.strip() for p in res['à_propos'].split('\n\n') if p.strip()]
        # Exemples inline → à_propos1, à_propos2…
        for n, grp in enumerate(dom.get('à_propos_groupes', []), start=1):
            res[f'à_propos{n}'] = grp
    except: pass

    return res

# ══════════════════════════════════════════════════════════════════════════════
# CSV + MAIN
# ══════════════════════════════════════════════════════════════════════════════

def load_csv(path):
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f): rows.append(row)
    return rows

def build_entry(row, data):
    # return {
    #     'position':           row.get('Position',''),
    #     'forme_jp':           row.get('Forme_JP',''),
    #     'traduction_en':      row.get('Traduction_EN',''),
    #     'traduction_fr':      row.get('Traduction_FR',''),
    #     'url_fr':             row.get('URL_FR',''),
    #     'url_en':             row.get('URL_EN',''),
    #     'url_ja':             row.get('URL_JA',''),
    #     'structure_standard': data.get('structure_standard',''),
    #     'structure_poli':     data.get('structure_poli',''),
    #     'détails':            data.get('détails',{}),
    #     'à_propos':           data.get('à_propos',''),
    #     'synonymes':          data.get('synonymes',''),
    #     'antonymes':          data.get('antonymes',''),
    #     'en_lien':            data.get('en_lien',''),
    #     'exemples':           data.get('exemples',[]),
    #     'en_ligne':           data.get('en_ligne',[]),
    #     'hors_ligne':         data.get('hors_ligne',[]),
    # }
    # structure finale de à_propos
    a_propos = {
        'en': (
            data.get('à_propos', [None])[0]
            if data.get('à_propos')
            else ''
        )
    }
    
    # récupérer les à_propos1, à_propos2...
    for k, v in data.items():

        if k.startswith('à_propos') and k != 'à_propos':

            suffixe = k.replace('à_propos', '')
            new_key = f'à_propos_exemples_{suffixe}'

            a_propos[new_key] = v
    # a_propos_ex = []
    
    entry = {
        'position':           row.get('Position',''),
        'label':              data.get('label', {
                                  'forme_jp':   row.get('Forme_JP',''),
                                  'traduction': row.get('Traduction_FR',''),
                              }),
        'traduction_en':      row.get('Traduction_EN',''),
        'traduction_fr':      row.get('Traduction_FR',''),
        'url':               data.get('url', {
                                  'url_fr':             row.get('URL_FR',''),
                                  'url_en':             row.get('URL_EN',''),
                                  'url_ja':             row.get('URL_JA',''),
                              }),
        'structure_standard': data.get('structure_standard',[]),
        'structure_poli':     data.get('structure_poli',[]),
        'détails':            data.get('détails',{}),
        'à_propos':           a_propos,
        'synonymes':          data.get('synonymes',[]),
        'antonymes':          data.get('antonymes',[]),
        'en_lien':            data.get('en_lien',[]),
        'en_ligne':           data.get('en_ligne',[]),
        'hors_ligne':         data.get('hors_ligne',[]),
        'exemples':           data.get('exemples',[]),
    }
    # Ajouter à_propos1, à_propos2… si présents
    # for k, v in data.items():
    #     if k.startswith('à_propos') and k != 'à_propos':
    #         entry[k] = v
    # =====================================================================
    # for k, v in data.items():
    #     if k.startswith('à_propos') and k != 'à_propos':

    #         # ajouter dans la liste principale
    #         a_propos_ex.extend(v)

    #         # renommer la clé
    #         suffixe = k.replace('à_propos', '')
    #         new_key = f'à_propos_exemples_{suffixe}'

            # entry[new_key] = v

    # fusion finale
    # entry['à_propos'] += a_propos_ex
    return entry

def main():
    login_mode = '--login' in sys.argv
    print('╔' + '═'*65 + '╗')
    print('║  Bunpro Grammaire Scraper — DOM-directe                         ║')
    print('╚' + '═'*65 + '╝')
    if login_mode:
        print('\n  Mode LOGIN — connectez-vous puis appuyez sur ENTRÉE.\n')

    if not os.path.exists(CSV_FILE):
        print(f'ERREUR : {CSV_FILE} introuvable.'); return

    rows  = load_csv(CSV_FILE)
    total = len(rows)
    print(f'\n  {total} points chargés. Sortie : {OUT_JSON}\n')

    # Charger l'état existant si reprise
    if os.path.exists(OUT_JSON):
        with open(OUT_JSON, encoding='utf-8') as f:
            output = json.load(f)
        print(f'  Reprise depuis sauvegarde existante.\n')
    else:
        output = {}

    ok_count = err_count = 0
    cur_niv  = cur_lec = None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not login_mode, slow_mo=60 if login_mode else 0,
            args=['--lang=fr-FR'])
            # args=['--lang=en-US'])
        ctx = browser.new_context(
            locale='fr-FR',
            # locale='en-US',
            viewport={'width':1280,'height':900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36')
        page = ctx.new_page()

        if login_mode:
            page.goto('https://bunpro.jp/users/sign_in',
                      wait_until='networkidle', timeout=TIMEOUT)
            input('  Connectez-vous, puis appuyez sur ENTRÉE...')
            print('  Connexion validée.\n')

        for idx, row in enumerate(rows):
            i       = idx + 1
            niveau  = row['Niveau']
            lecon   = row['Leçon']
            forme   = row['Forme_JP']
            url_fr  = row.get('URL_FR','').strip()
            # url_fr  = row.get('URL_EN','').strip()

            # Structure de sortie
            if niveau not in output: output[niveau] = {}
            titre = row.get('Titre_Leçon','')
            cl    = f"{lecon} – {titre}" if titre else lecon
            if cl not in output[niveau]: output[niveau][cl] = []

            if niveau != cur_niv:
                cur_niv = niveau; cur_lec = None
                print(f'\n{"═"*55}\n  NIVEAU : {niveau}\n{"═"*55}')
            if lecon != cur_lec:
                cur_lec = lecon; print(f'  {cl}')

            print(f'    [{i:4d}/{total}] {forme[:50]:<50}', end=' … ', flush=True)

            if not url_fr:
                print('PAS D\'URL')
                e = build_entry(row, {}); e['erreur'] = 'no URL'
                output[niveau][cl].append(e); err_count += 1
            else:
                try:
                    data = scrape_page(page, url_fr)
                    e    = build_entry(row, data)
                    output[niveau][cl].append(e)
                    n_ex   = len(data.get('exemples',[]))
                    pol    = '✓poli ' if data.get('structure_poli') else ''
                    filled = sum(1 for k in ['structure_standard','détails','à_propos'] if data.get(k))
                    print(f'OK [{filled}/3] {pol}{n_ex}ex')
                    ok_count += 1
                except Exception as ex:
                    print(f'ERR {str(ex)[:55]}')
                    e = build_entry(row, {}); e['erreur'] = str(ex)
                    output[niveau][cl].append(e); err_count += 1

            # ── Sauvegarde après chaque leçon terminée ──────────────────
            is_last     = (i == total)
            next_niveau = rows[idx+1]['Niveau'] if not is_last else None
            next_lecon  = rows[idx+1]['Leçon']  if not is_last else None
            if is_last or next_niveau != niveau or next_lecon != lecon:
                save(output)
                print(f'    💾 Sauvegarde — {niveau} / {cl} terminé(e)')

            time.sleep(DELAY)
        browser.close()

    save(output)
    print(f'\n  ✓ OK:{ok_count}  Erreurs:{err_count}  → {OUT_JSON}')

if __name__ == '__main__': main()
