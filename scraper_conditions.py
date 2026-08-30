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
SQLITE_DB_PATH = os.path.join(WORKSPACE_DIR, "tcm_conditions.db")
OUTPUT_JSON_PATH = os.path.join(WORKSPACE_DIR, "tcm_conditions_details.json")
MARKDOWN_DIR = os.path.join(WORKSPACE_DIR, "conditions")

BASE_URL = "https://www.meandqi.com"
CATALOG_URL = BASE_URL + "/api/conditions-search/data"
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

# Parse details from single condition HTML
def parse_condition_details(html_content, cond_basic):
    details = {
        "id": cond_basic.get("id"),
        "name": cond_basic.get("name", ""),
        "url": cond_basic.get("url", ""),
        "kind": cond_basic.get("kind", ""),
        "pinyin": cond_basic.get("pinyin", ""),
        "chinese_name": cond_basic.get("chineseName", ""),
        "preview_text": cond_basic.get("previewText", ""),
        "categories": cond_basic.get("categories", []),
        "body_regions": cond_basic.get("bodyRegions", []),
        "synonyms": cond_basic.get("synonyms", []),
        
        "conventional_description": "",
        "conventional_treatments": "",
        "conventional_limitations": "",
        "tcm_understanding": "",
        "classical_quote": "",
        "classical_translation": "",
        "classical_source": "",
        "tcm_diagnosis": "",
        
        "patterns_details": [],
        "faqs": [],
        "research": []
    }
    
    if not html_content:
        return details

    # 1. Parse JSON-LD blocks for FAQs & research
    json_ld_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_content, re.DOTALL)
    for block in json_ld_blocks:
        try:
            data = json.loads(block.strip())
            type_name = data.get("@type")
            if type_name == "FAQPage":
                for item in data.get("mainEntity", []):
                    if item.get("@type") == "Question":
                        q = item.get("name", "").strip()
                        a = item.get("acceptedAnswer", {}).get("text", "").strip()
                        if q and a:
                            details["faqs"].append({"question": q, "answer": a})
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

    # 2. Extract conventional medicine context card
    western_match = re.search(r'id="western-context-body"[^>]*>(.*?)</div>\s*</div>', html_content, re.DOTALL)
    if western_match:
        western_body = western_match.group(1)
        desc_match = re.search(r'<div class="prose prose-sm[^"]*">(.*?)</div>', western_body, re.DOTALL)
        if desc_match:
            details["conventional_description"] = clean_html(desc_match.group(1))
            
        treat_match = re.search(r'Conventional treatments</h4>\s*<div class="prose prose-sm[^"]*">(.*?)</div>', western_body, re.DOTALL)
        if treat_match:
            details["conventional_treatments"] = clean_html(treat_match.group(1))
            
        limit_match = re.search(r'Where conventional treatment falls short</h4>\s*<div class="prose prose-sm[^"]*">(.*?)</div>', western_body, re.DOTALL)
        if limit_match:
            details["conventional_limitations"] = clean_html(limit_match.group(1))

    # 3. Extract How TCM understands
    tcm_under_m = re.search(r'How TCM understands[^<]*</h2>\s*<div class="condition-rich-text prose max-w-none text-text-primary[^"]*">(.*?)</div>', html_content, re.DOTALL)
    if tcm_under_m:
        details["tcm_understanding"] = clean_html(tcm_under_m.group(1))

    # 4. Extract classical texts block
    classical_match = re.search(r'<figure class="condition-classical-feature[^"]*">.*?<blockquote[^>]*>\s*<p[^>]*>(.*?)</p>\s*<p[^>]*>(.*?)</p>\s*</blockquote>.*?<figcaption[^>]*>.*?&mdash;\s*(.*?)\s*</figcaption>', html_content, re.DOTALL)
    if classical_match:
        details["classical_quote"] = clean_html(classical_match.group(1))
        details["classical_translation"] = clean_html(classical_match.group(2))
        details["classical_source"] = clean_html(classical_match.group(3))

    # 5. Extract practitioner diagnosis
    diag_match = re.search(r'How a TCM practitioner diagnoses[^<]*</h3>.*?Inside the consultation</p>\s*<div class="condition-rich-text prose max-w-none text-text-primary[^"]*">(.*?)</div>', html_content, re.DOTALL)
    if diag_match:
        details["tcm_diagnosis"] = clean_html(diag_match.group(1))

    # 6. Extract Pattern details
    pattern_blocks = html_content.split('id="pattern-card-')[1:]
    for block in pattern_blocks:
        card_html = block.split('<!-- Accent bar -->')[0]
        name_m = re.search(r'data-pattern-name="([^"]+)"', block)
        if not name_m:
            continue
        p_name = name_m.group(1).strip()
        
        is_common = 1 if 'Very common' in card_html or 'Very common' in block[:500] else 0
        
        slug_m = re.search(r'href="/knowledge-base/patterns/([^"]+)"', block)
        p_slug = slug_m.group(1).strip() if slug_m else ""
        
        symptoms = []
        symptoms_container = re.search(r'data-pattern-symptoms>(.*?)</div>', block, re.DOTALL)
        if symptoms_container:
            symptoms = re.findall(r'<span[^>]*>([^<]+)</span>', symptoms_container.group(1))
            symptoms = [s.strip() for s in symptoms if s.strip()]
            
        worse_with = ""
        worse_m = re.search(r'Worse with</span>\s*<span class="text-red-900">([^<]+)</span>', block)
        if worse_m:
            worse_with = worse_m.group(1).strip()
            
        better_with = ""
        better_m = re.search(r'Better with</span>\s*<span class="text-green-900">([^<]+)</span>', block)
        if better_m:
            better_with = better_m.group(1).strip()
            
        why_happens = ""
        why_m = re.search(r'Why this happens</h4>\s*<div class="condition-rich-text prose prose-sm max-w-none text-text-primary[^"]*">(.*?)</div>', block, re.DOTALL)
        if why_m:
            why_happens = clean_html(why_m.group(1))
            
        tongue_pulse = ""
        tp_m = re.search(r'Tongue &amp; Pulse.*?</h4>\s*<p class="text-text-primary text-sm mb-0">(.*?)</p>', block, re.DOTALL)
        if tp_m:
            tongue_pulse = clean_html(tp_m.group(1))
            
        why_triggers = ""
        wt_m = re.search(r'Why these triggers and reliefs work</h4>\s*<p class="text-text-primary text-sm[^"]*">(.*?)</p>', block, re.DOTALL)
        if wt_m:
            why_triggers = clean_html(wt_m.group(1))
            
        diet_lifestyle = ""
        dl_m = re.search(r'Diet &amp; lifestyle for this pattern[^<]*</h4>\s*<div class="condition-rich-text prose prose-sm[^"]*">(.*?)</div>', block, re.DOTALL)
        if dl_m:
            diet_lifestyle = clean_html(dl_m.group(1))

        # Formulas inside pattern
        formulas = []
        formula_sections = block.split('<div class="treatment-product-card treatment-product-formula">')[1:]
        for f_sec in formula_sections:
            f_sec = f_sec.split('<div class="treatment-product-card')[0]
            name_url_m = re.search(r'href="/knowledge-base/formulas/([^"]+)"[^>]*>\s*(.*?)\s*</a>', f_sec, re.DOTALL)
            if name_url_m:
                f_url = "/knowledge-base/formulas/" + name_url_m.group(1).strip()
                f_name = clean_html(name_url_m.group(2))
                
                trans_m = re.search(r'<span class="block text-xs text-text-tertiary mt-0.5">([^<]+)</span>', f_sec)
                f_trans = trans_m.group(1).strip() if trans_m else ""
                
                tags = re.findall(r'<span class="treatment-product-tag[^>]*>([^<]+)</span>', f_sec)
                f_props = ", ".join([t.strip() for t in tags])
                
                desc_m = re.search(r'<p class="text-sm text-text-secondary mt-2.5 mb-0 leading-relaxed">([^<]+)</p>', f_sec)
                f_desc = desc_m.group(1).strip() if desc_m else ""
                
                formulas.append({
                    "name": f_name,
                    "url": f_url,
                    "translation": f_trans,
                    "properties": f_props,
                    "description": f_desc
                })

        # Herbs inside pattern
        herbs = []
        herb_sections = block.split('<div class="treatment-product-card treatment-product-herb">')[1:]
        for h_sec in herb_sections:
            h_sec = h_sec.split('<div class="treatment-product-card')[0]
            name_url_m = re.search(r'href="/knowledge-base/herbs/([^"]+)"[^>]*>\s*(.*?)\s*</a>', h_sec, re.DOTALL)
            if name_url_m:
                h_url = "/knowledge-base/herbs/" + name_url_m.group(1).strip()
                h_name = clean_html(name_url_m.group(2))
                
                trans_m = re.search(r'<span class="block text-xs text-text-tertiary mt-0.5">([^<]+)</span>', h_sec)
                h_trans = trans_m.group(1).strip() if trans_m else ""
                
                tags = re.findall(r'<span class="treatment-product-tag[^>]*>([^<]+)</span>', h_sec)
                h_props = ", ".join([t.strip() for t in tags])
                
                desc_m = re.search(r'<p class="text-sm text-text-secondary mt-1.5 mb-0 leading-relaxed">([^<]+)</p>', h_sec)
                h_desc = desc_m.group(1).strip() if desc_m else ""
                
                herbs.append({
                    "name": h_name,
                    "url": h_url,
                    "translation": h_trans,
                    "properties": h_props,
                    "description": h_desc
                })

        # Acupoints inside pattern
        acupoints = []
        acu_sections = block.split('<a href="/knowledge-base/acupuncture/')[1:]
        for a_sec in acu_sections:
            a_sec = a_sec.split('<a href="/knowledge-base/acupuncture/')[0]
            url_end = a_sec.find('"')
            if url_end == -1:
                continue
            a_slug = a_sec[:url_end].strip()
            a_url = "/knowledge-base/acupuncture/" + a_slug
            
            code_m = re.search(r'<span class="absolute[^>]*>([^<]+)</span>', a_sec)
            a_code = code_m.group(1).strip() if code_m else ""
            
            name_m = re.search(r'<p class="text-sm font-bold text-text-primary[^>]*>([^<]+)</p>', a_sec)
            a_name = clean_html(name_m.group(1)) if name_m else ""
            
            trans_m = re.search(r'<p class="text-xs text-text-tertiary[^>]*>([^<]+)</p>', a_sec)
            a_trans = trans_m.group(1).strip() if trans_m else ""
            
            tags = re.findall(r'<span class="text-xs px-2.5 py-0.5 rounded-full[^>]*>([^<]+)</span>', a_sec)
            a_props = ", ".join([t.strip() for t in tags])
            
            desc_m = re.search(r'<p class="text-sm text-text-secondary leading-relaxed[^>]*>([^<]+)</p>', a_sec)
            a_desc = desc_m.group(1).strip() if desc_m else ""
            
            if not any(x["code"] == a_code for x in acupoints) and a_code:
                acupoints.append({
                    "code": a_code,
                    "name": a_name,
                    "url": a_url,
                    "translation": a_trans,
                    "properties": a_props,
                    "description": a_desc
                })

        details["patterns_details"].append({
            "pattern_name": p_name,
            "pattern_slug": p_slug,
            "is_common": is_common,
            "symptoms": symptoms,
            "worse_with": worse_with,
            "better_with": better_with,
            "why_this_happens": why_happens,
            "tongue_and_pulse": tongue_pulse,
            "why_triggers_reliefs_work": why_triggers,
            "diet_and_lifestyle": diet_lifestyle,
            "formulas": formulas,
            "herbs": herbs,
            "acupoints": acupoints
        })
        
    return details

# Task to process a single condition
def scrape_condition_task(cond_basic, idx, total):
    url = BASE_URL + cond_basic["url"]
    print(f"[{idx}/{total}] Scraping: {cond_basic['name']} ...")
    html_content = fetch_url(url)
    
    if not html_content:
        print(f"Error fetching: {cond_basic['name']}")
        return parse_condition_details("", cond_basic)
        
    try:
        parsed = parse_condition_details(html_content, cond_basic)
        return parsed
    except Exception as e:
        print(f"Error parsing: {cond_basic['name']}: {e}")
        return parse_condition_details("", cond_basic)

# Database Setup
def init_sqlite_db():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # Create conditions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conditions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT UNIQUE,
            kind TEXT,
            pinyin TEXT,
            chinese_name TEXT,
            preview_text TEXT,
            categories TEXT,
            body_regions TEXT,
            synonyms TEXT,
            conventional_description TEXT,
            conventional_treatments TEXT,
            conventional_limitations TEXT,
            tcm_understanding TEXT,
            classical_quote TEXT,
            classical_translation TEXT,
            classical_source TEXT,
            tcm_diagnosis TEXT
        )
    """)
    
    # Create condition_patterns table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS condition_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id INTEGER,
            pattern_name TEXT NOT NULL,
            pattern_slug TEXT,
            is_common INTEGER,
            symptoms TEXT,
            worse_with TEXT,
            better_with TEXT,
            why_this_happens TEXT,
            tongue_and_pulse TEXT,
            why_triggers_reliefs_work TEXT,
            diet_and_lifestyle TEXT,
            FOREIGN KEY(condition_id) REFERENCES conditions(id) ON DELETE CASCADE
        )
    """)
    
    # Create condition_pattern_formulas table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS condition_pattern_formulas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER,
            formula_name TEXT NOT NULL,
            formula_url TEXT,
            translation TEXT,
            properties TEXT,
            description TEXT,
            FOREIGN KEY(pattern_id) REFERENCES condition_patterns(id) ON DELETE CASCADE
        )
    """)
    
    # Create condition_pattern_herbs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS condition_pattern_herbs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER,
            herb_name TEXT NOT NULL,
            herb_url TEXT,
            translation TEXT,
            properties TEXT,
            description TEXT,
            FOREIGN KEY(pattern_id) REFERENCES condition_patterns(id) ON DELETE CASCADE
        )
    """)
    
    # Create condition_pattern_acupoints table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS condition_pattern_acupoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER,
            acupoint_code TEXT NOT NULL,
            acupoint_name TEXT NOT NULL,
            acupoint_url TEXT,
            translation TEXT,
            properties TEXT,
            description TEXT,
            FOREIGN KEY(pattern_id) REFERENCES condition_patterns(id) ON DELETE CASCADE
        )
    """)
    
    # Create condition_faqs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS condition_faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id INTEGER,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            FOREIGN KEY(condition_id) REFERENCES conditions(id) ON DELETE CASCADE
        )
    """)
    
    # Create condition_research table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS condition_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id INTEGER,
            title TEXT,
            description TEXT,
            url TEXT,
            periodical TEXT,
            FOREIGN KEY(condition_id) REFERENCES conditions(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    return conn

# Insert parsed condition into SQLite
def insert_condition_into_db(conn, c):
    cursor = conn.cursor()
    try:
        # First check if the condition already exists to delete its children (in case of re-run)
        cursor.execute("SELECT id FROM conditions WHERE url = ?", (c["url"],))
        row = cursor.fetchone()
        if row:
            cond_id = row[0]
            cursor.execute("DELETE FROM condition_patterns WHERE condition_id = ?", (cond_id,))
            cursor.execute("DELETE FROM condition_faqs WHERE condition_id = ?", (cond_id,))
            cursor.execute("DELETE FROM condition_research WHERE condition_id = ?", (cond_id,))
            cursor.execute("DELETE FROM condition_pattern_formulas WHERE pattern_id NOT IN (SELECT id FROM condition_patterns)")
            cursor.execute("DELETE FROM condition_pattern_herbs WHERE pattern_id NOT IN (SELECT id FROM condition_patterns)")
            cursor.execute("DELETE FROM condition_pattern_acupoints WHERE pattern_id NOT IN (SELECT id FROM condition_patterns)")
        
        cursor.execute("""
            INSERT OR REPLACE INTO conditions (
                name, url, kind, pinyin, chinese_name, preview_text, categories, body_regions, synonyms,
                conventional_description, conventional_treatments, conventional_limitations,
                tcm_understanding, classical_quote, classical_translation, classical_source, tcm_diagnosis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            c["name"],
            c["url"],
            c["kind"],
            c["pinyin"],
            c["chinese_name"],
            c["preview_text"],
            json.dumps(c["categories"], ensure_ascii=False),
            json.dumps(c["body_regions"], ensure_ascii=False),
            json.dumps(c["synonyms"], ensure_ascii=False),
            c["conventional_description"],
            c["conventional_treatments"],
            c["conventional_limitations"],
            c["tcm_understanding"],
            c["classical_quote"],
            c["classical_translation"],
            c["classical_source"],
            c["tcm_diagnosis"]
        ))
        
        cond_id = cursor.lastrowid
        
        # Insert FAQs
        for faq in c["faqs"]:
            cursor.execute("""
                INSERT INTO condition_faqs (condition_id, question, answer)
                VALUES (?, ?, ?)
            """, (cond_id, faq["question"], faq["answer"]))
            
        # Insert Research
        for res in c["research"]:
            cursor.execute("""
                INSERT INTO condition_research (condition_id, title, description, url, periodical)
                VALUES (?, ?, ?, ?, ?)
            """, (cond_id, res["title"], res["description"], res["url"], res["periodical"]))
            
        # Insert Patterns
        for pat in c["patterns_details"]:
            cursor.execute("""
                INSERT INTO condition_patterns (
                    condition_id, pattern_name, pattern_slug, is_common, symptoms, worse_with, better_with,
                    why_this_happens, tongue_and_pulse, why_triggers_reliefs_work, diet_and_lifestyle
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cond_id,
                pat["pattern_name"],
                pat["pattern_slug"],
                pat["is_common"],
                json.dumps(pat["symptoms"], ensure_ascii=False),
                pat["worse_with"],
                pat["better_with"],
                pat["why_this_happens"],
                pat["tongue_and_pulse"],
                pat["why_triggers_reliefs_work"],
                pat["diet_and_lifestyle"]
            ))
            
            pattern_id = cursor.lastrowid
            
            # Formulas
            for form in pat["formulas"]:
                cursor.execute("""
                    INSERT INTO condition_pattern_formulas (pattern_id, formula_name, formula_url, translation, properties, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (pattern_id, form["name"], form["url"], form["translation"], form["properties"], form["description"]))
                
            # Herbs
            for herb in pat["herbs"]:
                cursor.execute("""
                    INSERT INTO condition_pattern_herbs (pattern_id, herb_name, herb_url, translation, properties, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (pattern_id, herb["name"], herb["url"], herb["translation"], herb["properties"], herb["description"]))
                
            # Acupoints
            for ac in pat["acupoints"]:
                cursor.execute("""
                    INSERT INTO condition_pattern_acupoints (pattern_id, acupoint_code, acupoint_name, acupoint_url, translation, properties, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (pattern_id, ac["code"], ac["name"], ac["url"], ac["translation"], ac["properties"], ac["description"]))
                
        conn.commit()
    except Exception as e:
        print(f"Database insertion error for {c['name']}: {e}")
        conn.rollback()

# Generate Markdown File
def generate_markdown_file(c):
    safe_name = c["url"].split("/")[-1]
    file_path = os.path.join(MARKDOWN_DIR, f"{safe_name}.md")
    
    categories = ", ".join(c["categories"])
    synonyms = ", ".join(c["synonyms"])
    body_regions = ", ".join(c["body_regions"])
    
    content = f"""# {c["name"]} ({c["chinese_name"]})
**Pinyin**: {c["pinyin"]} | **Kind**: {c["kind"]} | **Category**: {categories}  
**Synonyms**: {synonyms} | **Body Regions**: {body_regions}

---

## Preview Summary
{c["preview_text"]}

---

"""

    if c["conventional_description"] or c["conventional_treatments"] or c["conventional_limitations"]:
        content += "## Conventional Medicine View\n"
        if c["conventional_description"]:
            content += f"### Description\n{c['conventional_description']}\n\n"
        if c["conventional_treatments"]:
            content += f"### Treatments\n{c['conventional_treatments']}\n\n"
        if c["conventional_limitations"]:
            content += f"### Where Conventional Treatment Falls Short\n{c['conventional_limitations']}\n\n"
        content += "---\n\n"

    if c["tcm_understanding"] or c["tcm_diagnosis"] or c["classical_quote"]:
        content += "## Traditional Chinese Medicine View\n"
        if c["tcm_understanding"]:
            content += f"### TCM Understanding\n{c['tcm_understanding']}\n\n"
        if c["tcm_diagnosis"]:
            content += f"### Practitioner Diagnosis\n{c['tcm_diagnosis']}\n\n"
        if c["classical_quote"]:
            content += f"### Classical Reference\n"
            content += f"> **Original**: {c['classical_quote']}\n"
            content += f"> \n"
            content += f"> **Translation**: {c['classical_translation']}\n"
            content += f"> \n"
            content += f"> — Source: *{c['classical_source']}*\n\n"
        content += "---\n\n"

    content += "## TCM Patterns and Treatment\n\n"
    for pat in c["patterns_details"]:
        common_tag = " [Very Common]" if pat["is_common"] else ""
        content += f"### {pat['pattern_name']}{common_tag}\n"
        if pat["pattern_slug"]:
            content += f"*Pattern Link: [Detailed Pattern Page](/knowledge-base/patterns/{pat['pattern_slug']})*\n\n"
            
        symptoms_str = ", ".join(pat["symptoms"])
        content += f"- **Clinical Signs & Symptoms**: {symptoms_str}\n"
        if pat["worse_with"]:
            content += f"- **Worse with**: {pat['worse_with']}\n"
        if pat["better_with"]:
            content += f"- **Better with**: {pat['better_with']}\n"
        if pat["why_this_happens"]:
            content += f"- **Why this happens (Mechanism)**:\n  {pat['why_this_happens']}\n"
        if pat["tongue_and_pulse"]:
            content += f"- **Tongue & Pulse**: {pat['tongue_and_pulse']}\n"
        if pat["why_triggers_reliefs_work"]:
            content += f"- **Triggers & Relief Explanation**: {pat['why_triggers_reliefs_work']}\n"
        if pat["diet_and_lifestyle"]:
            content += f"- **Diet & Lifestyle**: {pat['diet_and_lifestyle']}\n"
            
        content += "\n"
        
        # Formulas table
        if pat["formulas"]:
            content += "#### Recommended Formulas\n"
            content += "| Formula Name | Translation | Actions & Properties | Description |\n"
            content += "| :--- | :--- | :--- | :--- |\n"
            for form in pat["formulas"]:
                name_link = f"[{form['name']}]({BASE_URL}{form['url']})" if form['url'] else form['name']
                content += f"| **{name_link}** | {form['translation']} | {form['properties']} | {form['description']} |\n"
            content += "\n"
            
        # Herbs table
        if pat["herbs"]:
            content += "#### Recommended Herbs\n"
            content += "| Herb Name | Translation | Properties | Description |\n"
            content += "| :--- | :--- | :--- | :--- |\n"
            for herb in pat["herbs"]:
                name_link = f"[{herb['name']}]({BASE_URL}{herb['url']})" if herb['url'] else herb['name']
                content += f"| **{name_link}** | {herb['translation']} | {herb['properties']} | {herb['description']} |\n"
            content += "\n"
            
        # Acupoints table
        if pat["acupoints"]:
            content += "#### Recommended Acupuncture Points\n"
            content += "| Point Code | Point Name | Translation | Properties | Description |\n"
            content += "| :--- | :--- | :--- | :--- | :--- |\n"
            for ac in pat["acupoints"]:
                name_link = f"[{ac['name']}]({BASE_URL}{ac['url']})" if ac['url'] else ac['name']
                content += f"| **{ac['code']}** | {name_link} | {ac['translation']} | {ac['properties']} | {ac['description']} |\n"
            content += "\n"
            
        content += "---\n\n"

    if c["faqs"]:
        content += "## Frequently Asked Questions\n"
        for faq in c["faqs"]:
            content += f"### {faq['question']}\n{faq['answer']}\n\n"
        content += "---\n\n"

    if c["research"]:
        content += "## Modern Scientific Research\n"
        for idx, res in enumerate(c["research"], 1):
            url_str = f" ([Link]({res['url']}))" if res['url'] else ""
            content += f"{idx}. **{res['title']}**{url_str}\n"
            if res['periodical']:
                content += f"   *Journal/Publication: {res['periodical']}*\n"
            content += f"   {res['description']}\n\n"
        content += "---\n\n"
        
    content += f"*Original URL: [{BASE_URL}{c['url']}]({BASE_URL}{c['url']})*"
    
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)

def main():
    start_time = time.time()
    
    # 1. Fetch search catalog
    print("Fetching catalog from:", CATALOG_URL)
    catalog_raw = fetch_url(CATALOG_URL)
    if not catalog_raw:
        print("Failed to fetch catalog.")
        return
        
    try:
        catalog_data = json.loads(catalog_raw)
    except Exception as e:
        print("Failed to parse catalog JSON:", e)
        return
        
    all_conds_basic = catalog_data.get("allConditions", [])
    total_conds = len(all_conds_basic)
    print(f"Loaded {total_conds} conditions from catalog.")
    
    # Check if this is a dry run (controlled by DRY_RUN env var)
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    if dry_run:
        # subset of 5 conditions
        all_conds_basic = all_conds_basic[:5]
        total_conds = len(all_conds_basic)
        print(f"DRY RUN ENABLED: Limiting to first {total_conds} conditions.")
    
    # Initialize SQLite database
    conn = init_sqlite_db()
    
    # Scraped data list for JSON
    scraped_results = []
    
    print(f"Starting multi-threaded scraping with concurrency={CONCURRENCY}...")
    
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        # Submit tasks
        futures = {
            executor.submit(scrape_condition_task, c_basic, idx, total_conds): c_basic 
            for idx, c_basic in enumerate(all_conds_basic, 1)
        }
        
        # Gather results as they complete
        for future in as_completed(futures):
            c_basic = futures[future]
            try:
                detailed_cond = future.result()
                scraped_results.append(detailed_cond)
                
                # Write to SQLite
                insert_condition_into_db(conn, detailed_cond)
                
                # Write to Markdown
                generate_markdown_file(detailed_cond)
                
            except Exception as exc:
                print(f"Task for {c_basic['name']} generated an exception: {exc}")
                
    # Close SQLite Connection
    conn.close()
    
    # Write to JSON file (only overwrite completely if not dry_run)
    json_out_path = OUTPUT_JSON_PATH
    if dry_run:
        json_out_path = os.path.join(WORKSPACE_DIR, "tcm_conditions_details_dryrun.json")
        
    with open(json_out_path, "w", encoding="utf-8") as f:
        json.dump(scraped_results, f, indent=2, ensure_ascii=False)
        
    elapsed = time.time() - start_time
    print("\n==================================================")
    print("CLONING PROCESS COMPLETE!")
    print(f"Processed: {len(scraped_results)} of {total_conds} conditions.")
    print(f"Saved SQLite DB to: {SQLITE_DB_PATH}")
    print(f"Saved JSON Data to: {json_out_path}")
    print(f"Generated Markdown files in: {MARKDOWN_DIR}")
    print(f"Total time elapsed: {elapsed:.2f} seconds.")
    print("==================================================")

if __name__ == "__main__":
    main()
