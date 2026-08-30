import os
import re
import json
import urllib.request
import urllib.error
import sqlite3
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Directory and Paths
WORKSPACE_DIR = "/Users/phol/Desktop/Antigravity Project/TCM database"
SQLITE_DB_PATH = os.path.join(WORKSPACE_DIR, "tcm_herbs.db")
OUTPUT_JSON_PATH = os.path.join(WORKSPACE_DIR, "tcm_herbs_details.json")
MARKDOWN_DIR = os.path.join(WORKSPACE_DIR, "herbs")

BASE_URL = "https://www.meandqi.com"
CATALOG_URL = BASE_URL + "/api/herbs-search/data"
CONCURRENCY = 5  # Polite concurrency
MAX_RETRIES = 3

# Make directories
os.makedirs(MARKDOWN_DIR, exist_ok=True)

# Helper to clean HTML tags and entities
def clean_html(text):
    if not text:
        return ""
    # Replace common HTML tags with text formatting
    text = re.sub(r"<li>(.*?)</li>", r"- \1\n", text)
    text = re.sub(r"<ul[^>]*>(.*?)</ul>", r"\1\n", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n\n", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    # Normalize whitespaces
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join([l for l in lines if l]).strip()

# Fetch page with retry logic
def fetch_url(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    req = urllib.request.Request(url, headers=headers)
    
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read().decode('utf-8')
        except urllib.error.URLError as e:
            if attempt == MAX_RETRIES - 1:
                print(f"Failed to fetch {url} after {MAX_RETRIES} attempts: {e}")
                return None
            time.sleep(1 + attempt * 2)
    return None

# Parse details from single herb HTML
def parse_herb_details(html_content, herb_basic):
    details = {
        "name": herb_basic.get("name", ""),
        "chinese_name": herb_basic.get("chineseName", ""),
        "english_name": herb_basic.get("englishName", ""),
        "scientific_name": herb_basic.get("scientificName", ""),
        "pharmaceutical_name": herb_basic.get("pharmaceuticalName", ""),
        "category": herb_basic.get("category", ""),
        "categories": herb_basic.get("categories", []),
        "temperature": herb_basic.get("temperature", ""),
        "tastes": herb_basic.get("tastes", []),
        "organ_affinities": herb_basic.get("organAffinities", []),
        "parts_used": "",
        "toxicity": herb_basic.get("toxicity", "Non-toxic"),
        "toxicity_details": "",
        "summary": herb_basic.get("summary", ""),
        "image_url": herb_basic.get("imageUrl", ""),
        "alternative_names": herb_basic.get("alternativeNames", []),
        "how_actions_work": "",
        "standard_dosage": "",
        "maximum_dosage": "",
        "dosage_notes": "",
        "preparation": "",
        "identity_adulterants": "",
        "classical_incompatibilities": "",
        "pregnancy_warning": "",
        "breastfeeding_warning": "",
        "children_warning": "",
        "drug_interactions": "",
        "dietary_advice": "",
        "botanical_description": "",
        "harvesting_season": "",
        "primary_growing_regions": "",
        "quality_indicators": "",
        "historical_context": "",
        "url": herb_basic.get("url", ""),
        "therapeutic_focus": herb_basic.get("therapeuticFocus", []),
        "tcm_actions": herb_basic.get("tcmActions", []),
        "key_formulas": herb_basic.get("keyFormulas", []),
        
        # Nested tables
        "patterns": [],
        "conditions": [],
        "processed_forms": [],
        "herb_pairs": [],
        "research": [],
        "classical_texts": []
    }
    
    if not html_content:
        return details

    # 1. Parse JSON-LD blocks for metadata & research
    json_ld_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_content, re.DOTALL)
    for block in json_ld_blocks:
        try:
            data = json.loads(block.strip())
            type_name = data.get("@type")
            if type_name == "MedicalEntity":
                # Extract parts used if available
                if "additionalProperty" in data:
                    for prop in data["additionalProperty"]:
                        if prop["name"] == "Parts Used":
                            details["parts_used"] = prop["value"]
                            
            elif type_name == "ScholarlyArticle":
                periodical = ""
                if data.get("isPartOf") and isinstance(data["isPartOf"], dict):
                    periodical = data["isPartOf"].get("name", "")
                
                details["research"].append({
                    "title": data.get("name", ""),
                    "description": data.get("description", ""),
                    "url": data.get("url", ""),
                    "periodical": periodical
                })
        except Exception:
            pass

    # 2. Extract "How these actions work" prose
    actions_work_m = re.search(r"How these actions work</h3>\s*<div class=\"prose prose-sm text-text-primary max-w-none\">(.*?)</div>", html_content, re.DOTALL)
    if actions_work_m:
        details["how_actions_work"] = clean_html(actions_work_m.group(1))

    # 3. Extract Patterns Addressed and details
    patterns_section_m = re.search(r'Patterns Addressed</h2>(.*?)Commonly Used For</h2>', html_content, re.DOTALL)
    if patterns_section_m:
        patterns_html = patterns_section_m.group(1)
        pattern_parts = patterns_html.split("onclick=\"formulaToggle('herb-pattern-")[1:]
        for part in pattern_parts:
            header_m = re.search(r'<a href="/knowledge-base/patterns/([^"]+)"[^>]*>(.*?)</a>', part, re.DOTALL)
            if header_m:
                slug = header_m.group(1).strip()
                name = clean_html(header_m.group(2))
                
                why_m = re.search(r'Why\s+[\w\s\']+\s+addresses this pattern</h3>\s*<div class="prose prose-sm text-text-primary max-w-none">(.*?)</div>', part, re.DOTALL)
                explanation = clean_html(why_m.group(1)) if why_m else ""
                
                signs = []
                signs_matches = re.findall(r'<div class="py-2 border-l-2 border-tertiary-light pl-3">\s*(?:<a href="/knowledge-base/conditions/[^"]+"[^>]*>([^<]+)</a>|<span class="[^"]+">([^<]+)</span>)\s*<p class="text-xs text-text-secondary mt-0.5 mb-0 leading-relaxed">([^<]+)</p>', part, re.DOTALL)
                for s_link, s_span, s_desc in signs_matches:
                    s_name = s_link if s_link else s_span
                    signs.append({"name": s_name.strip(), "description": s_desc.strip()})
                    
                details["patterns"].append({
                    "pattern_name": name,
                    "pattern_slug": slug,
                    "explanation": explanation,
                    "signs": signs
                })

    # 4. Extract Commonly Used For (conditions deep dive)
    conditions_section_m = re.search(r'Commonly Used For</h2>(.*?)Herb Properties</h2>', html_content, re.DOTALL)
    if conditions_section_m:
        conditions_html = conditions_section_m.group(1)
        condition_parts = conditions_html.split("onclick=\"formulaToggle('herb-insight-")[1:]
        for part in condition_parts:
            header_m = re.search(r'<a href="/knowledge-base/conditions/([^"]+)"[^>]*>(.*?)</a>', part, re.DOTALL)
            if header_m:
                slug = header_m.group(1).strip()
                name = clean_html(header_m.group(2))
                
                arises_section_start = part.find('Arises from:')
                arises_patterns = []
                if arises_section_start != -1:
                    next_h3 = part.find('<h3', arises_section_start)
                    arises_chunk = part[arises_section_start:next_h3] if next_h3 != -1 else part[arises_section_start:arises_section_start+500]
                    arises_patterns = re.findall(r'<a href="/knowledge-base/patterns/[^"]+"[^>]*>\s*<span>([^<]+)</span>', arises_chunk)
                    
                tcm_m = re.search(r'TCM Interpretation</h3>\s*<div class="prose prose-sm text-text-primary max-w-none">(.*?)</div>', part, re.DOTALL)
                tcm_interpretation = clean_html(tcm_m.group(1)) if tcm_m else ""
                
                helps_m = re.search(r'Why\s+[\w\s\']+\s+Helps</h3>\s*<div class="prose prose-sm text-text-primary max-w-none">(.*?)</div>', part, re.DOTALL)
                why_helps = clean_html(helps_m.group(1)) if helps_m else ""
                
                details["conditions"].append({
                    "condition_name": name,
                    "condition_slug": slug,
                    "arises_patterns": arises_patterns,
                    "tcm_interpretation": tcm_interpretation,
                    "why_helps": why_helps
                })

    # 5. Extract Dosage & Preparation fields
    for term in ["Standard dosage", "Maximum dosage", "Dosage notes", "Preparation"]:
        m = re.search(rf'<span class="text-xs font-semibold text-text-tertiary uppercase tracking-wide">{term}</span>\s*</div>\s*<p class="[^"]*">(.*?)</p>', html_content, re.DOTALL)
        if m:
            details[term.lower().replace(" ", "_")] = clean_html(m.group(1))

    # 6. Extract Processing Methods
    processing_headers = re.findall(r'onclick="formulaToggle\(\'processing-(\d+)\'\)".*?<span class="text-base font-medium text-text-primary">([^<]+)</span>', html_content, re.DOTALL)
    for idx_str, name in processing_headers:
        idx = int(idx_str)
        block_start = html_content.find(f'id="processing-{idx}"')
        if block_start != -1:
            next_block = html_content.find('id="processing-', block_start + 20)
            chunk = html_content[block_start:next_block] if next_block != -1 else html_content[block_start:block_start+4000]
            
            method_m = re.search(r'Processing method</h3>\s*<p class="[^"]*">(.*?)</p>', chunk, re.DOTALL)
            changes_m = re.search(r'How it changes properties</h3>\s*<p class="[^"]*">(.*?)</p>', chunk, re.DOTALL)
            use_m = re.search(r'When to use this form</h3>\s*<p class="[^"]*">(.*?)</p>', chunk, re.DOTALL)
            
            details["processed_forms"].append({
                "name": name.strip(),
                "method": clean_html(method_m.group(1)) if method_m else "",
                "changes": clean_html(changes_m.group(1)) if changes_m else "",
                "when_to_use": clean_html(use_m.group(1)) if use_m else ""
            })

    # 7. Extract Common Herb Pairs
    combinations_start = html_content.find('id="herb-combinations"')
    if combinations_start != -1:
        cards = html_content[combinations_start:].split('<div class="p-4 bg-background-secondary rounded-lg">')[1:]
        for card_html in cards:
            if 'id="herb-safety"' in card_html:
                card_html = card_html.split('id="herb-safety"')[0]
                
            name_m = re.search(r'(?:<span class="text-base font-semibold text-text-primary">|<a href="/knowledge-base/herbs/[^"]+" class="text-base font-semibold[^"]*">)(.*?)(?:</span>|</a>)', card_html, re.DOTALL)
            if name_m:
                name = clean_html(name_m.group(1))
                ratio_m = re.search(r'<span class="inline-flex items-center px-2 py-0.5 mt-1 bg-neutral-lightest text-text-secondary text-xs font-medium rounded-full border border-border-divider">([^<]+)</span>', card_html)
                ratio = ratio_m.group(1).strip() if ratio_m else ""
                
                desc_m = re.search(r'<p class="text-sm text-text-primary mb-0 leading-relaxed[^"]*">(.*?)</p>', card_html, re.DOTALL)
                description = clean_html(desc_m.group(1)) if desc_m else ""
                
                when_m = re.search(r'<strong class="text-text-secondary">When to use:</strong>\s*(.*?)</p>', card_html, re.DOTALL)
                when_to_use = clean_html(when_m.group(1)) if when_m else ""
                
                if description and "When to use:" in description:
                    description = description.split("When to use:")[0].strip()
                    
                details["herb_pairs"].append({
                    "name": name,
                    "ratio": ratio,
                    "description": description,
                    "when_to_use": when_to_use
                })

    # 8. Extract Identity & Adulterants
    identity_m = re.search(r'Identity & Adulterants</h2>.*?<div class="px-6 py-6">\s*<p class="[^"]*">(.*?)</p>', html_content, re.DOTALL)
    if identity_m:
        details["identity_adulterants"] = clean_html(identity_m.group(1))

    # 9. Extract Toxicity Classification details
    tox_m = re.search(r'Toxicity Classification</h2>.*?<div class="px-6 py-6">.*?<p class="[^"]*">(.*?)</p>', html_content, re.DOTALL)
    if tox_m:
        details["toxicity_details"] = clean_html(tox_m.group(1))

    # 10. Extract Contraindications list
    contra_section_m = re.search(r'Contraindications</h2>(.*?)Classical Incompatibilities</h2>', html_content, re.DOTALL)
    if contra_section_m:
        contra_html = contra_section_m.group(1)
        contra_matches = re.findall(r'<div class="flex items-start gap-3 p-4 bg-background-secondary rounded-lg">.*?<span class="inline-flex items-center px-2 py-0.5 bg-warning/10 text-warning text-xs font-medium rounded-full mb-1.5">([^<]+)</span>\s*<p class="text-sm text-text-primary mb-0 leading-relaxed">(.*?)</p>', contra_html, re.DOTALL)
        for level, text in contra_matches:
            details["contraindications"] = details.get("contraindications", [])
            details["contraindications"].append({
                "level": level.strip(),
                "text": clean_html(text)
            })

    # 11. Extract Classical Incompatibilities
    class_m = re.search(r'Classical Incompatibilities</h2>.*?<div class="px-6 py-6">\s*<p class="[^"]*">(.*?)</p>', html_content, re.DOTALL)
    if class_m:
        details["classical_incompatibilities"] = clean_html(class_m.group(1))

    # 12. Extract Special Populations
    for pop in ["Pregnancy", "Breastfeeding", "Children"]:
        pop_m = re.search(rf'{pop}</h3>\s*</div>\s*<p class="text-sm text-text-secondary mb-0 leading-relaxed[^"]*">(.*?)</p>', html_content, re.DOTALL)
        if pop_m:
            details[f"{pop.lower()}_warning"] = clean_html(pop_m.group(1))

    # 13. Extract Drug Interactions details
    drug_m = re.search(r'Drug Interactions</h2>.*?<div class="prose prose-sm prose-headings:text-sm prose-headings:font-semibold text-text-primary max-w-none">(.*?)</div>', html_content, re.DOTALL)
    if drug_m:
        details["drug_interactions"] = clean_html(drug_m.group(1))

    # 14. Extract Dietary Advice
    diet_m = re.search(r'Dietary Advice</h2>.*?<div class="px-6 py-6">\s*<p class="[^"]*">(.*?)</p>', html_content, re.DOTALL)
    if diet_m:
        details["dietary_advice"] = clean_html(diet_m.group(1))

    # 15. Extract Botanical Description
    bot_m = re.search(r'Botanical Description</h2>.*?<div class="prose prose-sm prose-headings:text-sm prose-headings:font-semibold text-text-primary max-w-none">(.*?)</div>', html_content, re.DOTALL)
    if bot_m:
        details["botanical_description"] = clean_html(bot_m.group(1))

    # 16. Extract Sourcing & Harvesting
    for term in ["Harvesting season", "Primary growing regions", "Quality indicators"]:
        m = re.search(rf'<h3[^>]*>.*?{term}.*?</h3>\s*<p class="[^"]*">(.*?)</p>', html_content, re.DOTALL)
        if m:
            details[term.lower().replace(" ", "_")] = clean_html(m.group(1))

    # 17. Extract Classical Texts
    texts_m = re.search(r'Classical Texts</h2>.*?<div class="prose prose-sm prose-constrained text-text-primary max-w-none">(.*?)</div>', html_content, re.DOTALL)
    if texts_m:
        texts_html = texts_m.group(1)
        text_blocks = texts_html.split("<hr>")
        for block in text_blocks:
            title_m = re.search(r'<h4>(.*?)</h4>', block)
            orig_m = re.search(r'<p><strong>Original:</strong>\s*(.*?)</p>', block, re.DOTALL)
            trans_m = re.search(r'<p><strong>Translation:</strong>\s*(.*?)</p>', block, re.DOTALL)
            if title_m:
                details["classical_texts"].append({
                    "source": title_m.group(1).strip(),
                    "original": clean_html(orig_m.group(1)) if orig_m else "",
                    "translation": clean_html(trans_m.group(1)) if trans_m else ""
                })

    # 18. Extract Historical Context
    hist_m = re.search(r'Historical Context</h2>.*?<div class="prose prose-sm prose-headings:text-sm prose-headings:font-semibold text-text-primary max-w-none">(.*?)</div>', html_content, re.DOTALL)
    if hist_m:
        details["historical_context"] = clean_html(hist_m.group(1))

    return details

# Task to process a single herb
def scrape_herb_task(herb_basic, idx, total):
    url = BASE_URL + herb_basic["url"]
    print(f"[{idx}/{total}] Scraping: {herb_basic['name']} ...")
    html_content = fetch_url(url)
    
    if not html_content:
        print(f"Error fetching: {herb_basic['name']}")
        return parse_herb_details("", herb_basic)
        
    try:
        parsed = parse_herb_details(html_content, herb_basic)
        return parsed
    except Exception as e:
        print(f"Error parsing: {herb_basic['name']}: {e}")
        return parse_herb_details("", herb_basic)

# Database Setup
def init_sqlite_db():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    
    # Create herbs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS herbs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            chinese_name TEXT,
            english_name TEXT,
            scientific_name TEXT,
            pharmaceutical_name TEXT,
            category TEXT,
            categories TEXT,
            temperature TEXT,
            tastes TEXT,
            organ_affinities TEXT,
            parts_used TEXT,
            toxicity TEXT,
            toxicity_details TEXT,
            summary TEXT,
            image_url TEXT,
            alternative_names TEXT,
            how_actions_work TEXT,
            standard_dosage TEXT,
            maximum_dosage TEXT,
            dosage_notes TEXT,
            preparation TEXT,
            identity_adulterants TEXT,
            classical_incompatibilities TEXT,
            pregnancy_warning TEXT,
            breastfeeding_warning TEXT,
            children_warning TEXT,
            drug_interactions TEXT,
            dietary_advice TEXT,
            botanical_description TEXT,
            harvesting_season TEXT,
            primary_growing_regions TEXT,
            quality_indicators TEXT,
            historical_context TEXT,
            url TEXT UNIQUE,
            therapeutic_focus TEXT,
            tcm_actions TEXT,
            key_formulas TEXT
        )
    """)
    
    # Create herb_patterns table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS herb_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            herb_id INTEGER,
            pattern_name TEXT NOT NULL,
            pattern_slug TEXT,
            explanation TEXT,
            signs TEXT,
            FOREIGN KEY(herb_id) REFERENCES herbs(id) ON DELETE CASCADE
        )
    """)
    
    # Create herb_conditions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS herb_conditions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            herb_id INTEGER,
            condition_name TEXT NOT NULL,
            condition_slug TEXT,
            arises_patterns TEXT,
            tcm_interpretation TEXT,
            why_helps TEXT,
            FOREIGN KEY(herb_id) REFERENCES herbs(id) ON DELETE CASCADE
        )
    """)
    
    # Create herb_processed_forms table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS herb_processed_forms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            herb_id INTEGER,
            form_name TEXT NOT NULL,
            method TEXT,
            changes TEXT,
            when_to_use TEXT,
            FOREIGN KEY(herb_id) REFERENCES herbs(id) ON DELETE CASCADE
        )
    """)
    
    # Create herb_pairs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS herb_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            herb_id INTEGER,
            pair_name TEXT NOT NULL,
            ratio TEXT,
            description TEXT,
            when_to_use TEXT,
            FOREIGN KEY(herb_id) REFERENCES herbs(id) ON DELETE CASCADE
        )
    """)
    
    # Create herb_research table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS herb_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            herb_id INTEGER,
            title TEXT,
            description TEXT,
            url TEXT,
            periodical TEXT,
            FOREIGN KEY(herb_id) REFERENCES herbs(id) ON DELETE CASCADE
        )
    """)
    
    # Create herb_classical_texts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS herb_classical_texts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            herb_id INTEGER,
            source TEXT,
            original TEXT,
            translation TEXT,
            FOREIGN KEY(herb_id) REFERENCES herbs(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    return conn

# Insert parsed herb into SQLite
def insert_herb_into_db(conn, h):
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO herbs (
                name, chinese_name, english_name, scientific_name, pharmaceutical_name,
                category, categories, temperature, tastes, organ_affinities, parts_used,
                toxicity, toxicity_details, summary, image_url, alternative_names,
                how_actions_work, standard_dosage, maximum_dosage, dosage_notes, preparation,
                identity_adulterants, classical_incompatibilities, pregnancy_warning,
                breastfeeding_warning, children_warning, drug_interactions, dietary_advice,
                botanical_description, harvesting_season, primary_growing_regions,
                quality_indicators, historical_context, url, therapeutic_focus, tcm_actions,
                key_formulas
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            h["name"],
            h["chinese_name"],
            h["english_name"],
            h["scientific_name"],
            h["pharmaceutical_name"],
            h["category"],
            json.dumps(h["categories"], ensure_ascii=False),
            h["temperature"],
            json.dumps(h["tastes"], ensure_ascii=False),
            json.dumps(h["organ_affinities"], ensure_ascii=False),
            h["parts_used"],
            h["toxicity"],
            h["toxicity_details"],
            h["summary"],
            h["image_url"],
            json.dumps(h["alternative_names"], ensure_ascii=False),
            h["how_actions_work"],
            h["standard_dosage"],
            h["maximum_dosage"],
            h["dosage_notes"],
            h["preparation"],
            h["identity_adulterants"],
            h["classical_incompatibilities"],
            h["pregnancy_warning"],
            h["breastfeeding_warning"],
            h["children_warning"],
            h["drug_interactions"],
            h["dietary_advice"],
            h["botanical_description"],
            h["harvesting_season"],
            h["primary_growing_regions"],
            h["quality_indicators"],
            h["historical_context"],
            h["url"],
            json.dumps(h["therapeutic_focus"], ensure_ascii=False),
            json.dumps(h["tcm_actions"], ensure_ascii=False),
            json.dumps(h["key_formulas"], ensure_ascii=False)
        ))
        
        herb_id = cursor.lastrowid
        
        # Remove old rows if updating
        cursor.execute("DELETE FROM herb_patterns WHERE herb_id = ?", (herb_id,))
        for p in h["patterns"]:
            cursor.execute("""
                INSERT INTO herb_patterns (herb_id, pattern_name, pattern_slug, explanation, signs)
                VALUES (?, ?, ?, ?, ?)
            """, (herb_id, p["pattern_name"], p["pattern_slug"], p["explanation"], json.dumps(p["signs"], ensure_ascii=False)))
            
        cursor.execute("DELETE FROM herb_conditions WHERE herb_id = ?", (herb_id,))
        for c in h["conditions"]:
            cursor.execute("""
                INSERT INTO herb_conditions (herb_id, condition_name, condition_slug, arises_patterns, tcm_interpretation, why_helps)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (herb_id, c["condition_name"], c["condition_slug"], json.dumps(c["arises_patterns"], ensure_ascii=False), c["tcm_interpretation"], c["why_helps"]))
            
        cursor.execute("DELETE FROM herb_processed_forms WHERE herb_id = ?", (herb_id,))
        for pf in h["processed_forms"]:
            cursor.execute("""
                INSERT INTO herb_processed_forms (herb_id, form_name, method, changes, when_to_use)
                VALUES (?, ?, ?, ?, ?)
            """, (herb_id, pf["name"], pf["method"], pf["changes"], pf["when_to_use"]))
            
        cursor.execute("DELETE FROM herb_pairs WHERE herb_id = ?", (herb_id,))
        for hp in h["herb_pairs"]:
            cursor.execute("""
                INSERT INTO herb_pairs (herb_id, pair_name, ratio, description, when_to_use)
                VALUES (?, ?, ?, ?, ?)
            """, (herb_id, hp["name"], hp["ratio"], hp["description"], hp["when_to_use"]))
            
        cursor.execute("DELETE FROM herb_research WHERE herb_id = ?", (herb_id,))
        for r in h["research"]:
            cursor.execute("""
                INSERT INTO herb_research (herb_id, title, description, url, periodical)
                VALUES (?, ?, ?, ?, ?)
            """, (herb_id, r["title"], r["description"], r["url"], r["periodical"]))
            
        cursor.execute("DELETE FROM herb_classical_texts WHERE herb_id = ?", (herb_id,))
        for t in h["classical_texts"]:
            cursor.execute("""
                INSERT INTO herb_classical_texts (herb_id, source, original, translation)
                VALUES (?, ?, ?, ?)
            """, (herb_id, t["source"], t["original"], t["translation"]))
            
        conn.commit()
    except Exception as e:
        print(f"Database insertion error for {h['name']}: {e}")
        conn.rollback()

# Generate Markdown File
def generate_markdown_file(h):
    safe_name = h["url"].split("/")[-1]
    file_path = os.path.join(MARKDOWN_DIR, f"{safe_name}.md")
    
    categories = ", ".join(h["categories"])
    tastes = ", ".join(h["tastes"])
    organs = ", ".join(h["organ_affinities"])
    alternative_names = ", ".join(h["alternative_names"])
    focus = ", ".join(h["therapeutic_focus"])
    actions = ", ".join(h["tcm_actions"])
    formulas = ", ".join(h["key_formulas"])
    
    content = f"""# {h["name"]} ({h["chinese_name"]})
**English Name**: {h["english_name"]}  
**Category**: {categories}  
**Scientific Name**: {h["scientific_name"]}  
**Pharmaceutical Name**: {h["pharmaceutical_name"]}  
**Toxicity**: {h["toxicity"]}  
**Temperature**: {h["temperature"]} | **Taste**: {tastes}  
**Channels Entered**: {organs}  
**Parts Used**: {h["parts_used"]}  

---

## Summary
{h["summary"]}

---

## What This Herb Does
- **Therapeutic Focus**: {focus}
- **TCM Actions**: {actions}

### How these actions work
{h["how_actions_work"]}

---

## Patterns Addressed
"""
    if h["patterns"]:
        for p in h["patterns"]:
            content += f"### {p['pattern_name']}\n"
            content += f"- **Explanation**: {p['explanation']}\n"
            content += "- **Clinical Signs & Symptoms**:\n"
            for s in p["signs"]:
                content += f"  - **{s['name']}**: {s['description']}\n"
            content += "\n"
    else:
        content += "*No specific patterns listed.*\n\n"

    content += "---\n\n## Commonly Used For\n"
    if h["conditions"]:
        for c in h["conditions"]:
            content += f"### {c['condition_name']}\n"
            if c['arises_patterns']:
                content += f"- **Arises from**: {', '.join(c['arises_patterns'])}\n"
            content += f"- **TCM Interpretation**: {c['tcm_interpretation']}\n"
            content += f"- **Why it Helps**: {c['why_helps']}\n\n"
    else:
        content += "*No specific conditions listed.*\n\n"

    content += "---\n\n## Dosage & Preparation\n"
    content += f"- **Standard Dosage**: {h['standard_dosage']}\n"
    content += f"- **Maximum Dosage**: {h['maximum_dosage']}\n"
    content += f"- **Dosage Notes**: {h['dosage_notes']}\n"
    content += f"- **Preparation**: {h['preparation']}\n\n"

    content += "---\n\n## Processing Methods\n"
    if h["processed_forms"]:
        for pf in h["processed_forms"]:
            content += f"### {pf['name']}\n"
            content += f"- **Processing Method**: {pf['method']}\n"
            content += f"- **How it Changes Properties**: {pf['changes']}\n"
            content += f"- **When to Use**: {pf['when_to_use']}\n\n"
    else:
        content += "*No specific processing methods listed.*\n\n"

    content += "---\n\n## Common Herb Pairs\n"
    if h["herb_pairs"]:
        for hp in h["herb_pairs"]:
            content += f"### {hp['name']} (Ratio: {hp['ratio']})\n"
            content += f"- **Description**: {hp['description']}\n"
            content += f"- **When to Use**: {hp['when_to_use']}\n\n"
    else:
        content += "*No specific herb pairs listed.*\n\n"

    content += "---\n\n## Key Formulas\n"
    if formulas:
        content += f"{formulas}\n\n"
    else:
        content += "*No formulas listed.*\n\n"

    content += "---\n\n## Safety & Warnings\n"
    content += f"### Toxicity Classification\n{h['toxicity']}\n{h['toxicity_details']}\n\n"
    
    content += "### Contraindications\n"
    if h.get("contraindications"):
        for contra in h["contraindications"]:
            content += f"- **[{contra['level']}]** {contra['text']}\n"
        content += "\n"
    else:
        content += "*No specific contraindications listed.*\n\n"
        
    content += f"### Classical Incompatibilities\n{h['classical_incompatibilities']}\n\n"
    
    content += "### Special Populations\n"
    if h.get("pregnancy_warning"):
        content += f"- **Pregnancy**: {h['pregnancy_warning']}\n"
    if h.get("breastfeeding_warning"):
        content += f"- **Breastfeeding**: {h['breastfeeding_warning']}\n"
    if h.get("children_warning"):
        content += f"- **Children**: {h['children_warning']}\n"
    if not (h.get("pregnancy_warning") or h.get("breastfeeding_warning") or h.get("children_warning")):
        content += "*No specific special populations warnings listed.*\n"
    content += "\n"

    content += f"### Drug Interactions\n{h['drug_interactions']}\n\n"
    content += f"### Dietary Advice\n{h['dietary_advice']}\n\n"

    content += "---\n\n## Botanical & Sourcing\n"
    content += f"### Botanical Description\n{h['botanical_description']}\n\n"
    content += "### Sourcing & Harvesting\n"
    content += f"- **Harvesting Season**: {h['harvesting_season']}\n"
    content += f"- **Primary Growing Regions**: {h['primary_growing_regions']}\n"
    content += f"- **Quality Indicators**: {h['quality_indicators']}\n\n"
    content += f"### Identity & Adulterants\n{h['identity_adulterants']}\n\n"

    content += "---\n\n## References\n"
    if h["classical_texts"]:
        content += "### Classical Texts\n"
        for t in h["classical_texts"]:
            content += f"#### {t['source']}\n"
            content += f"- **Original**: {t['original']}\n"
            content += f"- **Translation**: {t['translation']}\n\n"
            
    if h["historical_context"]:
        content += f"### Historical Context\n{h['historical_context']}\n\n"

    if h["research"]:
        content += "### Modern Scientific Research\n"
        for idx, res in enumerate(h["research"], 1):
            content += f"{idx}. **[{res['title']}]({res['url']})**\n"
            if res['periodical']:
                content += f"   *Journal: {res['periodical']}*\n"
            content += f"   {res['description']}\n\n"
            
    content += f"\n---\n*Original URL: [{BASE_URL}{h['url']}]({BASE_URL}{h['url']})*"
    
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)

def main():
    start_time = time.time()
    
    print("Fetching herbs search catalog from:", CATALOG_URL)
    catalog_raw = fetch_url(CATALOG_URL)
    if not catalog_raw:
        print("Failed to fetch catalog from API.")
        return
        
    try:
        catalog_data = json.loads(catalog_raw)
    except Exception as e:
        print("Failed to parse catalog JSON:", e)
        return
        
    all_herbs_basic = catalog_data.get("allHerbs", [])
    total_herbs = len(all_herbs_basic)
    print(f"Loaded {total_herbs} herbs from catalog.")
    
    # Initialize SQLite database
    conn = init_sqlite_db()
    
    # Scraped data list for JSON
    scraped_results = []
    
    print(f"Starting multi-threaded scraping with concurrency={CONCURRENCY}...")
    
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        # Submit tasks
        futures = {
            executor.submit(scrape_herb_task, h_basic, idx, total_herbs): h_basic 
            for idx, h_basic in enumerate(all_herbs_basic, 1)
        }
        
        # Gather results as they complete
        for future in as_completed(futures):
            h_basic = futures[future]
            try:
                detailed_herb = future.result()
                scraped_results.append(detailed_herb)
                
                # Write to SQLite
                insert_herb_into_db(conn, detailed_herb)
                
                # Write to Markdown
                generate_markdown_file(detailed_herb)
                
            except Exception as exc:
                print(f"Task for {h_basic['name']} generated an exception: {exc}")
                
    # Close SQLite Connection
    conn.close()
    
    # Write to single large JSON file
    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(scraped_results, f, indent=2, ensure_ascii=False)
        
    elapsed = time.time() - start_time
    print("\n==================================================")
    print("CLONING PROCESS COMPLETE!")
    print(f"Processed: {len(scraped_results)} of {total_herbs} herbs.")
    print(f"Saved SQLite DB to: {SQLITE_DB_PATH}")
    print(f"Saved JSON Data to: {OUTPUT_JSON_PATH}")
    print(f"Generated Markdown files in: {MARKDOWN_DIR}")
    print(f"Total time elapsed: {elapsed:.2f} seconds.")
    print("==================================================")

if __name__ == "__main__":
    main()
