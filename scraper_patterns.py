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
SQLITE_DB_PATH = os.path.join(WORKSPACE_DIR, "tcm_patterns.db")
OUTPUT_JSON_PATH = os.path.join(WORKSPACE_DIR, "tcm_patterns_details.json")
MARKDOWN_DIR = os.path.join(WORKSPACE_DIR, "patterns")

BASE_URL = "https://www.meandqi.com"
CATALOG_URL = BASE_URL + "/api/patterns-search/data"
CONCURRENCY = 5  # Polite concurrency
MAX_RETRIES = 3

# Make directories
os.makedirs(MARKDOWN_DIR, exist_ok=True)

# Helper to check if string contains Chinese characters
def is_chinese(s):
    return any('\u4e00' <= char <= '\u9fff' for char in s)

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

# Parse Four Examinations from single pattern HTML
def parse_four_examinations(html_content):
    exam = {
        "inspection": {
            "tongue_summary": "",
            "tongue_grid": {},
            "tongue_explanation": "",
            "vitality_grid": {}
        },
        "listening_smelling": {
            "grid": {}
        },
        "palpation": {
            "pulse_qualities": [],
            "pulse_explanation": "",
            "palpation_grid": {}
        }
    }
    
    # 1. Inspection
    insp_m = re.search(r'Inspection\s*<span class="text-sm font-normal text-text-tertiary ml-2">Wang Zhen 望诊</span>.*?</h3>\s*<p[^>]*>.*?</p>(.*?)<!-- ── Listening', html_content, re.DOTALL)
    if insp_m:
        insp_html = insp_m.group(1)
        # Tongue summary
        tongue_sum_m = re.search(r'Tongue</p>\s*<p class="text-sm text-text-secondary mb-3">(.*?)</p>', insp_html, re.DOTALL)
        if tongue_sum_m:
            exam["inspection"]["tongue_summary"] = clean_html(tongue_sum_m.group(1))
        
        # Tongue grid
        tongue_grid_html_m = re.search(r'Tongue</p>.*?<div class="divide-y divide-border-divider">(.*?)</div>\s*<p class="text-sm text-text-secondary mt-3">', insp_html, re.DOTALL)
        if tongue_grid_html_m:
            grid_html = tongue_grid_html_m.group(1)
            items = re.findall(r'<span class="text-sm text-text-tertiary">(.*?)</span>\s*<span class="text-sm text-text-primary font-medium">(.*?)</span>', grid_html)
            exam["inspection"]["tongue_grid"] = {clean_html(k): clean_html(v) for k, v in items}
            
        # Tongue explanation
        tongue_exp_m = re.search(r'Tongue</p>.*?<p class="text-sm text-text-secondary mt-3">(.*?)</p>', insp_html, re.DOTALL)
        if tongue_exp_m:
            exam["inspection"]["tongue_explanation"] = clean_html(tongue_exp_m.group(1))
            
        # Vitality grid
        vitality_grid_m = re.search(r'Overall vitality.*?<div class="divide-y divide-border-divider sm:ml-11">(.*?)</div>\s*</div>', insp_html, re.DOTALL)
        if not vitality_grid_m:
            vitality_grid_m = re.search(r'<div class="divide-y divide-border-divider sm:ml-11">(.*?)</div>\s*</div>\s*</div>', insp_html, re.DOTALL)
        if vitality_grid_m:
            grid_html = vitality_grid_m.group(1)
            items = re.findall(r'<span class="text-sm text-text-tertiary">(.*?)</span>\s*<span class="text-sm text-text-primary font-medium">(.*?)</span>', grid_html)
            exam["inspection"]["vitality_grid"] = {clean_html(k): clean_html(v) for k, v in items}

    # 2. Listening & Smelling
    list_m = re.search(r'Listening &amp; Smelling\s*<span class="text-sm font-normal text-text-tertiary ml-2">Wen Zhen 闻诊</span>.*?</h3>\s*<p[^>]*>.*?</p>(.*?)<!-- ── Palpation', html_content, re.DOTALL)
    if list_m:
        list_html = list_m.group(1)
        items = re.findall(r'<span class="text-sm text-text-tertiary">(.*?)</span>\s*<span class="text-sm text-text-primary font-medium">(.*?)</span>', list_html)
        exam["listening_smelling"]["grid"] = {clean_html(k): clean_html(v) for k, v in items}
        
    palp_m = re.search(r'Palpation\s*<span class="text-sm font-normal text-text-tertiary ml-2">Qie Zhen 切诊</span>.*?</h3>\s*<p[^>]*>.*?</p>(.*?)(?:<!-- ── DIFFERENTIATION|<!-- ══════════════════════════════════════════════════════════════════\s*DIFFERENTIATION)', html_content, re.DOTALL)
    if palp_m:
        palp_html = palp_m.group(1)
        # Pulse qualities
        qualities_m = re.search(r'<p class="text-sm font-semibold text-text-primary mb-2">Pulse</p>\s*<div class="flex flex-wrap gap-1.5 mb-2">(.*?)</div>', palp_html, re.DOTALL)
        if qualities_m:
            exam["palpation"]["pulse_qualities"] = [clean_html(q) for q in re.findall(r'<span[^>]*>(.*?)</span>', qualities_m.group(1))]
        
        # Pulse explanation
        pulse_exp_m = re.search(r'Pulse</p>.*?<p class="text-sm text-text-secondary leading-relaxed mt-2">(.*?)</p>', palp_html, re.DOTALL)
        if pulse_exp_m:
            exam["palpation"]["pulse_explanation"] = clean_html(pulse_exp_m.group(1))
            
        # Palpation grid (Channels, Abdomen)
        palp_grid_m = re.search(r'<div class="divide-y divide-border-divider sm:ml-11">(.*?)</div>', palp_html, re.DOTALL)
        if palp_grid_m:
            grid_html = palp_grid_m.group(1)
            items = re.findall(r'<span class="text-sm text-text-tertiary[^"]*">(.*?)</span>\s*<span class="text-sm text-text-primary font-medium[^"]*">(.*?)</span>', grid_html)
            exam["palpation"]["palpation_grid"] = {clean_html(k): clean_html(v) for k, v in items}
            
    return exam

# Parse details from single pattern HTML
def parse_pattern_details(html_content, p_basic):
    p = {
        "name": p_basic.get("name", ""),
        "url": p_basic.get("url", ""),
        "pinyin": p_basic.get("pinyinName", ""),
        "chinese_name": p_basic.get("chineseName", ""),
        "nature": p_basic.get("nature", ""),
        "is_general_pattern": p_basic.get("isGeneralPattern", False),
        "organs": p_basic.get("organs", []),
        "by_vital_substance": p_basic.get("byVitalSubstance", []),
        "by_pathogenic_factor": p_basic.get("byPathogenicFactor", []),
        "description": p_basic.get("summary", ""),
        
        "also_known_as": "",
        "key_signs": [],
        "worse_with": [],
        "better_with": [],
        "timing_worsening_explanation": "",
        "practitioner_notes": "",
        "pathophysiology": "",
        "treatment_principle": "",
        "typical_timeline": "",
        "formula_modifications": "",
        
        "formulas": [],
        "herbs": [],
        "acupoints": [],
        "differential_diagnosis": [],
        "classical_texts": [],
        "faqs": [],
        "research": [],
        "clinical_advice": [],
        "four_examinations": {},
        "causes_details": []
    }
    
    if not html_content:
        return p
        
    # 1. Parse JSON-LD blocks
    json_ld_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_content, re.DOTALL)
    for block in json_ld_blocks:
        try:
            data = json.loads(block.strip())
            type_name = data.get("@type")
            if type_name == "MedicalCondition":
                if "alternateName" in data:
                    alt_names = data["alternateName"]
                    if isinstance(alt_names, list):
                        for alt in alt_names:
                            if is_chinese(alt):
                                p["chinese_name"] = alt
                            else:
                                p["pinyin"] = alt
                                
                if "signOrSymptom" in data:
                    p["key_signs"] = [item["name"] for item in data["signOrSymptom"] if "name" in item]
                
                if "pathophysiology" in data:
                    p["pathophysiology"] = data["pathophysiology"]
                
                if "description" in data and not p["description"]:
                    p["description"] = data["description"]
                    
            elif type_name == "FAQPage":
                for item in data.get("mainEntity", []):
                    if item.get("@type") == "Question":
                        q = item.get("name", "").strip()
                        a = item.get("acceptedAnswer", {}).get("text", "").strip()
                        if q and a:
                            p["faqs"].append({"question": q, "answer": a})
                            
            elif type_name == "ScholarlyArticle":
                periodical = ""
                if data.get("isPartOf") and isinstance(data["isPartOf"], dict):
                    periodical = data["isPartOf"].get("name", "")
                p["research"].append({
                    "title": data.get("name", ""),
                    "description": data.get("description", ""),
                    "url": data.get("url", ""),
                    "periodical": periodical
                })
        except Exception:
            pass

    # 2. Extract "Also known as"
    aka_m = re.search(r'Also known as:\s*(.*?)</p>', html_content)
    if aka_m:
        p["also_known_as"] = clean_html(aka_m.group(1))

    # 3. Extract Brief Description (if description is empty)
    if not p["description"]:
        desc_m = re.search(r'BriefDescription[^>]*-->\s*<p class="text-lg leading-relaxed text-text-primary">(.*?)</p>', html_content, re.DOTALL)
        if desc_m:
            p["description"] = clean_html(desc_m.group(1))

    # 4. Extract Key Signs from HTML (fallback)
    if not p["key_signs"]:
        ks_m = re.search(r'Key signs:</span>\s*<span class="text-sm text-text-primary leading-relaxed">(.*?)</span>', html_content, re.DOTALL)
        if ks_m:
            cleaned_ks = clean_html(ks_m.group(1))
            p["key_signs"] = [item.strip() for item in cleaned_ks.split("/") if item.strip()]

    # 5. Extract Worse with and Better with lists
    worse_m = re.search(r'Worse with</span>\s*</div>\s*<div class="flex flex-wrap gap-1\.5">(.*?)</div>', html_content, re.DOTALL)
    if worse_m:
        spans = re.findall(r'<span[^>]*>(.*?)</span>', worse_m.group(1))
        p["worse_with"] = [clean_html(s) for s in spans]
        
    better_m = re.search(r'Better with</span>\s*</div>\s*<div class="flex flex-wrap gap-1\.5">(.*?)</div>', html_content, re.DOTALL)
    if better_m:
        spans = re.findall(r'<span[^>]*>(.*?)</span>', better_m.group(1))
        p["better_with"] = [clean_html(s) for s in spans]

    # 6. Extract Timing/Worsening Explanation
    timing_m = re.search(r'Better with</span>.*?<p class="text-sm text-text-secondary leading-relaxed">(.*?)</p>', html_content, re.DOTALL)
    if timing_m:
        p["timing_worsening_explanation"] = clean_html(timing_m.group(1))

    # 7. Extract Practitioner Notes
    notes_m = re.search(r'Practitioner\'s Notes\s*</h3>\s*<div class="prose prose-sm max-w-none text-text-secondary sm:ml-11[^"]*">(.*?)</div>', html_content, re.DOTALL)
    if notes_m:
        p["practitioner_notes"] = clean_html(notes_m.group(1))

    # 8. Extract Four Examinations
    p["four_examinations"] = parse_four_examinations(html_content)

    # 9. Extract Causes Details
    cause_blocks = html_content.split('onclick="patToggle(\'cause-')[1:]
    for block in cause_blocks:
        name_m = re.search(r'<span class="text-sm font-medium text-text-primary[^"]*">(.*?)</span>', block, re.DOTALL)
        if not name_m:
            continue
        c_name = clean_html(name_m.group(1))
        
        desc_m = re.search(r'<div class="prose prose-sm[^>]*>(.*?)</div>', block, re.DOTALL)
        if desc_m:
            c_desc = clean_html(desc_m.group(1))
            p["causes_details"].append({
                "cause_title": c_name,
                "explanation": c_desc
            })

    # 10. Extract Treatment Details
    tp_m = re.search(r'The goal of treatment</p>\s*<p class="text-lg italic text-text-primary leading-relaxed">(.*?)</p>', html_content, re.DOTALL)
    if tp_m:
        p["treatment_principle"] = clean_html(tp_m.group(1))
        
    timeline_m = re.search(r'Typical timeline:\s*<span class="font-medium text-text-primary">(.*?)</span>', html_content, re.DOTALL)
    if timeline_m:
        p["typical_timeline"] = clean_html(timeline_m.group(1))

    # Formulas
    formulas_section_m = re.search(r'Classical Formulas</h3>(.*?)Key Individual Herbs</h3>', html_content, re.DOTALL)
    if formulas_section_m:
        formula_parts = formulas_section_m.group(1).split('href="/knowledge-base/formulas/')[1:]
        for part in formula_parts:
            slug_end = part.find('"')
            if slug_end == -1:
                continue
            f_slug = part[:slug_end].strip()
            f_url = "/knowledge-base/formulas/" + f_slug
            
            name_m = re.search(r'text-sm font-bold text-text-primary[^>]*>(.*?)</p>', part)
            f_name = clean_html(name_m.group(1)) if name_m else ""
            
            desc_m = re.search(r'text-sm text-text-secondary leading-relaxed[^>]*>(.*?)</p>', part, re.DOTALL)
            f_desc = clean_html(desc_m.group(1)) if desc_m else ""
            
            p["formulas"].append({
                "name": f_name,
                "url": f_url,
                "description": f_desc
            })

    # Modifications
    mod_m = re.search(r'How Practitioners Personalise These Formulas</h3>.*?<div class="prose prose-sm max-w-none text-text-secondary[^"]*">(.*?)</div>', html_content, re.DOTALL)
    if mod_m:
        p["formula_modifications"] = clean_html(mod_m.group(1))

    # Herbs
    herbs_section_m = re.search(r'Key Individual Herbs</h3>(.*?)How Acupuncture Helps</h2>', html_content, re.DOTALL)
    if herbs_section_m:
        herb_parts = herbs_section_m.group(1).split('href="/knowledge-base/herbs/')[1:]
        for part in herb_parts:
            slug_end = part.find('"')
            if slug_end == -1:
                continue
            h_slug = part[:slug_end].strip()
            h_url = "/knowledge-base/herbs/" + h_slug
            
            name_m = re.search(r'text-sm font-bold text-text-primary[^>]*>(.*?)</p>', part)
            h_name = clean_html(name_m.group(1)) if name_m else ""
            
            desc_m = re.search(r'text-sm text-text-secondary leading-relaxed[^>]*>(.*?)</p>', part, re.DOTALL)
            h_desc = clean_html(desc_m.group(1)) if desc_m else ""
            
            p["herbs"].append({
                "name": h_name,
                "url": h_url,
                "description": h_desc
            })

    # Acupoints
    acu_parts = html_content.split('href="/knowledge-base/acupuncture/')[1:]
    for part in acu_parts:
        slug_end = part.find('"')
        if slug_end == -1:
            continue
        a_slug = part[:slug_end].strip()
        if '/' not in a_slug:
            continue
        a_url = "/knowledge-base/acupuncture/" + a_slug
        
        code_m = re.search(r'text-white bg-primary/85[^>]*>(.*?)</span>', part)
        a_code = clean_html(code_m.group(1)) if code_m else ""
        
        name_m = re.search(r'text-sm font-bold text-text-primary[^>]*>(.*?)</p>', part)
        a_name = clean_html(name_m.group(1)) if name_m else ""
        
        desc_m = re.search(r'text-sm text-text-secondary leading-relaxed[^>]*>(.*?)</p>', part, re.DOTALL)
        a_desc = clean_html(desc_m.group(1)) if desc_m else ""
        
        p["acupoints"].append({
            "code": a_code,
            "name": a_name,
            "url": a_url,
            "description": a_desc
        })

    # 11. Extract Clinical Advice
    clinical_m = re.search(r'<div id="pat-clinical"[^>]*>(.*?)</div>\s*</div>', html_content, re.DOTALL)
    if clinical_m:
        clinical_html = clinical_m.group(1)
        blocks = clinical_html.split('<h4>')[1:]
        for block in blocks:
            title_end = block.find('</h4>')
            if title_end == -1:
                continue
            title = clean_html(block[:title_end])
            desc = clean_html(block[title_end+5:])
            p["clinical_advice"].append({
                "title": title,
                "content": desc
            })

    # 12. Extract Differential Diagnosis
    diffs_m = html_content.split('vs. ')[1:]
    for block in diffs_m:
        name_end = block.find('</span>')
        if name_end == -1:
            continue
        vs_name = clean_html(block[:name_end])
        
        desc_m = re.search(r'<p class="prose prose-sm[^>]*>(.*?)</p>', block, re.DOTALL)
        if desc_m:
            vs_desc = clean_html(desc_m.group(1))
            
            link_m = re.search(r'href="/knowledge-base/patterns/([^"]+)"', block)
            slug = link_m.group(1).strip() if link_m else ""
            
            p["differential_diagnosis"].append({
                "target_pattern_name": vs_name,
                "target_pattern_slug": slug,
                "explanation": vs_desc
            })

    # 13. Extract Classical Sources
    class_m = re.search(r'Classical Sources</h2>.*?<div class="prose prose-sm max-w-none text-text-secondary[^"]*">(.*?)</div>', html_content, re.DOTALL)
    if class_m:
        class_html = class_m.group(1)
        blocks = class_html.split('<h4>')[1:]
        for block in blocks:
            title_end = block.find('</h4>')
            if title_end == -1:
                continue
            title = clean_html(block[:title_end])
            desc = clean_html(block[title_end+5:])
            p["classical_texts"].append({
                "source": title,
                "original": "",
                "translation": desc
            })

    return p

# Task to process a single pattern
def scrape_pattern_task(p_basic, idx, total):
    url = BASE_URL + p_basic["url"]
    print(f"[{idx}/{total}] Scraping: {p_basic['name']} ...")
    html_content = fetch_url(url)
    
    if not html_content:
        print(f"Error fetching: {p_basic['name']}")
        return parse_pattern_details("", p_basic)
        
    try:
        parsed = parse_pattern_details(html_content, p_basic)
        return parsed
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error parsing: {p_basic['name']}: {e}")
        return parse_pattern_details("", p_basic)

# Database Setup
def init_sqlite_db():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # Create patterns table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT UNIQUE,
            pinyin TEXT,
            chinese_name TEXT,
            nature TEXT,
            is_general_pattern INTEGER,
            organs TEXT,
            by_vital_substance TEXT,
            by_pathogenic_factor TEXT,
            description TEXT,
            also_known_as TEXT,
            key_signs TEXT,
            worse_with TEXT,
            better_with TEXT,
            timing_worsening_explanation TEXT,
            practitioner_notes TEXT,
            pathophysiology TEXT,
            treatment_principle TEXT,
            typical_timeline TEXT,
            formula_modifications TEXT,
            clinical_advice TEXT,
            four_examinations TEXT,
            causes_details TEXT
        )
    """)
    
    # Create pattern_formulas table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pattern_formulas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER,
            name TEXT NOT NULL,
            url TEXT,
            description TEXT,
            FOREIGN KEY(pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
        )
    """)
    
    # Create pattern_herbs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pattern_herbs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER,
            name TEXT NOT NULL,
            url TEXT,
            description TEXT,
            FOREIGN KEY(pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
        )
    """)
    
    # Create pattern_acupoints table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pattern_acupoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            url TEXT,
            description TEXT,
            FOREIGN KEY(pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
        )
    """)
    
    # Create pattern_classical_texts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pattern_classical_texts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER,
            source TEXT NOT NULL,
            original TEXT,
            translation TEXT,
            FOREIGN KEY(pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
        )
    """)
    
    # Create pattern_faqs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pattern_faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            FOREIGN KEY(pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
        )
    """)
    
    # Create pattern_research table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pattern_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER,
            title TEXT,
            description TEXT,
            url TEXT,
            periodical TEXT,
            FOREIGN KEY(pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    return conn

# Insert parsed pattern into SQLite
def insert_pattern_into_db(conn, p):
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM patterns WHERE url = ?", (p["url"],))
        row = cursor.fetchone()
        if row:
            pattern_id = row[0]
            cursor.execute("DELETE FROM pattern_formulas WHERE pattern_id = ?", (pattern_id,))
            cursor.execute("DELETE FROM pattern_herbs WHERE pattern_id = ?", (pattern_id,))
            cursor.execute("DELETE FROM pattern_acupoints WHERE pattern_id = ?", (pattern_id,))
            cursor.execute("DELETE FROM pattern_classical_texts WHERE pattern_id = ?", (pattern_id,))
            cursor.execute("DELETE FROM pattern_faqs WHERE pattern_id = ?", (pattern_id,))
            cursor.execute("DELETE FROM pattern_research WHERE pattern_id = ?", (pattern_id,))
        
        cursor.execute("""
            INSERT OR REPLACE INTO patterns (
                name, url, pinyin, chinese_name, nature, is_general_pattern,
                organs, by_vital_substance, by_pathogenic_factor, description,
                also_known_as, key_signs, worse_with, better_with,
                timing_worsening_explanation, practitioner_notes, pathophysiology,
                treatment_principle, typical_timeline, formula_modifications,
                clinical_advice, four_examinations, causes_details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            p["name"],
            p["url"],
            p["pinyin"],
            p["chinese_name"],
            p["nature"],
            1 if p.get("is_general_pattern") else 0,
            json.dumps(p.get("organs", []), ensure_ascii=False),
            json.dumps(p.get("by_vital_substance", []), ensure_ascii=False),
            json.dumps(p.get("by_pathogenic_factor", []), ensure_ascii=False),
            p["description"],
            p.get("also_known_as", ""),
            json.dumps(p.get("key_signs", []), ensure_ascii=False),
            json.dumps(p.get("worse_with", []), ensure_ascii=False),
            json.dumps(p.get("better_with", []), ensure_ascii=False),
            p.get("timing_worsening_explanation", ""),
            p.get("practitioner_notes", ""),
            p.get("pathophysiology", ""),
            p.get("treatment_principle", ""),
            p.get("typical_timeline", ""),
            p.get("formula_modifications", ""),
            json.dumps(p.get("clinical_advice", []), ensure_ascii=False),
            json.dumps(p.get("four_examinations", {}), ensure_ascii=False),
            json.dumps(p.get("causes_details", []), ensure_ascii=False)
        ))
        
        pattern_id = cursor.lastrowid
        
        for form in p.get("formulas", []):
            cursor.execute("""
                INSERT INTO pattern_formulas (pattern_id, name, url, description)
                VALUES (?, ?, ?, ?)
            """, (pattern_id, form["name"], form["url"], form["description"]))
            
        for herb in p.get("herbs", []):
            cursor.execute("""
                INSERT INTO pattern_herbs (pattern_id, name, url, description)
                VALUES (?, ?, ?, ?)
            """, (pattern_id, herb["name"], herb["url"], herb["description"]))
            
        for acu in p.get("acupoints", []):
            cursor.execute("""
                INSERT INTO pattern_acupoints (pattern_id, code, name, url, description)
                VALUES (?, ?, ?, ?, ?)
            """, (pattern_id, acu["code"], acu["name"], acu["url"], acu["description"]))
            
        for text in p.get("classical_texts", []):
            cursor.execute("""
                INSERT INTO pattern_classical_texts (pattern_id, source, original, translation)
                VALUES (?, ?, ?, ?)
            """, (pattern_id, text["source"], text["original"], text["translation"]))
            
        for faq in p.get("faqs", []):
            cursor.execute("""
                INSERT INTO pattern_faqs (pattern_id, question, answer)
                VALUES (?, ?, ?)
            """, (pattern_id, faq["question"], faq["answer"]))
            
        for res in p.get("research", []):
            cursor.execute("""
                INSERT INTO pattern_research (pattern_id, title, description, url, periodical)
                VALUES (?, ?, ?, ?, ?)
            """, (pattern_id, res["title"], res["description"], res["url"], res["periodical"]))
            
        conn.commit()
    except Exception as e:
        print(f"Database insertion error for {p['name']}: {e}")
        conn.rollback()

# Generate Markdown File
def generate_markdown_file(p):
    safe_name = p["url"].split("/")[-1]
    file_path = os.path.join(MARKDOWN_DIR, f"{safe_name}.md")
    
    organs = ", ".join(p.get("organs", []))
    key_signs = ", ".join(p.get("key_signs", []))
    
    content = f"""# {p["name"]} ({p["chinese_name"]})
**Pinyin**: {p["pinyin"]} | **Nature**: {p["nature"]} | **Affected Organs**: {organs}  
**Also Known As**: {p.get("also_known_as", "")}

---

## Summary
{p["description"]}

---

## Clinical Signs & Symptoms
- **Key Signs**: {key_signs}

### What Makes It Better/Worse
- **Worse with**: 
"""
    for item in p.get("worse_with", []):
        content += f"  - {item}\n"
    if not p.get("worse_with"):
        content += "  *Not listed*\n"
        
    content += "- **Better with**: \n"
    for item in p.get("better_with", []):
        content += f"  - {item}\n"
    if not p.get("better_with"):
        content += "  *Not listed*\n"
        
    if p.get("timing_worsening_explanation"):
        content += f"\n**Timing/Worsening Details**: {p['timing_worsening_explanation']}\n"
        
    content += f"""
---

## Traditional Chinese Medicine View
- **Pathophysiology**: {p.get("pathophysiology", "")}
- **Practitioner Notes**: {p.get("practitioner_notes", "")}

### Four Examinations
"""
    fe = p.get("four_examinations", {})
    insp = fe.get("inspection", {})
    tongue_grid = insp.get("tongue_grid", {})
    vitality_grid = insp.get("vitality_grid", {})
    
    content += "#### Inspection\n"
    if insp.get("tongue_summary"):
        content += f"- **Tongue Summary**: {insp['tongue_summary']}\n"
    if tongue_grid:
        content += "- **Tongue Properties**:\n"
        for k, v in tongue_grid.items():
            content += f"  - **{k}**: {v}\n"
    if insp.get("tongue_explanation"):
        content += f"- **Tongue Explanation**: {insp['tongue_explanation']}\n"
    if vitality_grid:
        content += "- **Vitality & Complexion**:\n"
        for k, v in vitality_grid.items():
            content += f"  - **{k}**: {v}\n"
            
    ls = fe.get("listening_smelling", {})
    content += "\n#### Listening & Smelling\n"
    if ls.get("grid"):
        for k, v in ls["grid"].items():
            content += f"- **{k}**: {v}\n"
    else:
        content += "*No specific signs listed.*\n"
        
    palp = fe.get("palpation", {})
    content += "\n#### Palpation\n"
    if palp.get("pulse_qualities"):
        content += f"- **Pulse Qualities**: {', '.join(palp['pulse_qualities'])}\n"
    if palp.get("pulse_explanation"):
        content += f"- **Pulse Explanation**: {palp['pulse_explanation']}\n"
    if palp.get("palpation_grid"):
        for k, v in palp["palpation_grid"].items():
            content += f"- **{k}**: {v}\n"
            
    content += f"""
---

## Treatment & Recommendations
- **Treatment Principle**: {p.get("treatment_principle", "")}
- **Typical Timeline**: {p.get("typical_timeline", "")}

### Recommended Formulas
| Formula Name | Description |
| :--- | :--- |
"""
    if p.get("formulas"):
        for form in p["formulas"]:
            name_link = f"[{form['name']}]({BASE_URL}{form['url']})" if form.get("url") else form["name"]
            content += f"| **{name_link}** | {form['description']} |\n"
    else:
        content += "| - | *No formulas listed.* |\n"
        
    if p.get("formula_modifications"):
        content += f"\n#### How Practitioners Personalise These Formulas\n{p['formula_modifications']}\n"
        
    content += """
### Recommended Herbs
| Herb Name | Description |
| :--- | :--- |
"""
    if p.get("herbs"):
        for herb in p["herbs"]:
            name_link = f"[{herb['name']}]({BASE_URL}{herb['url']})" if herb.get("url") else herb["name"]
            content += f"| **{name_link}** | {herb['description']} |\n"
    else:
        content += "| - | *No herbs listed.* |\n"
        
    content += """
### Recommended Acupuncture Points
| Point Code | Point Name | Description |
| :--- | :--- | :--- |
"""
    if p.get("acupoints"):
        for acu in p["acupoints"]:
            name_link = f"[{acu['name']}]({BASE_URL}{acu['url']})" if acu.get("url") else acu["name"]
            content += f"| **{acu['code']}** | {name_link} | {acu['description']} |\n"
    else:
        content += "| - | - | *No points listed.* |\n"
        
    content += "\n---\n\n## Differential Diagnosis\n"
    if p.get("differential_diagnosis"):
        for d in p["differential_diagnosis"]:
            content += f"### vs. {d['target_pattern_name']}\n{d['explanation']}\n\n"
    else:
        content += "*None listed.*\n\n"
        
    content += "---\n\n## References\n"
    if p.get("classical_texts"):
        content += "### Classical Texts\n"
        for t in p["classical_texts"]:
            content += f"#### {t['source']}\n{t['translation']}\n\n"
            
    if p.get("research"):
        content += "### Modern Scientific Research\n"
        for idx, r in enumerate(p["research"], 1):
            url_str = f" ([Link]({r['url']}))" if r.get("url") else ""
            content += f"{idx}. **{r['title']}**{url_str}\n"
            if r.get("periodical"):
                content += f"   *Journal: {r['periodical']}*\n"
            content += f"   {r['description']}\n\n"
            
    content += f"\n---\n*Original URL: [{BASE_URL}{p['url']}]({BASE_URL}{p['url']})*"
    
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)

def main():
    start_time = time.time()
    
    print("Fetching patterns search catalog from:", CATALOG_URL)
    catalog_raw = fetch_url(CATALOG_URL)
    if not catalog_raw:
        print("Failed to fetch catalog.")
        return
        
    try:
        catalog_data = json.loads(catalog_raw)
    except Exception as e:
        print("Failed to parse catalog JSON:", e)
        return
        
    all_patterns_basic = catalog_data.get("allPatterns", [])
    total_patterns = len(all_patterns_basic)
    print(f"Loaded {total_patterns} patterns from catalog.")
    
    # Check if this is a dry run
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    if dry_run:
        all_patterns_basic = all_patterns_basic[:5]
        total_patterns = len(all_patterns_basic)
        print(f"DRY RUN ENABLED: Limiting to first {total_patterns} patterns.")
        
    # Initialize SQLite database
    conn = init_sqlite_db()
    
    scraped_results = []
    
    print(f"Starting multi-threaded scraping with concurrency={CONCURRENCY}...")
    
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {
            executor.submit(scrape_pattern_task, p_basic, idx, total_patterns): p_basic 
            for idx, p_basic in enumerate(all_patterns_basic, 1)
        }
        
        for future in as_completed(futures):
            p_basic = futures[future]
            try:
                detailed_pattern = future.result()
                scraped_results.append(detailed_pattern)
                
                # Write to SQLite
                insert_pattern_into_db(conn, detailed_pattern)
                
                # Write to Markdown
                generate_markdown_file(detailed_pattern)
                
            except Exception as exc:
                print(f"Task for {p_basic['name']} generated an exception: {exc}")
                
    conn.close()
    
    # Save JSON file
    json_out_path = OUTPUT_JSON_PATH
    if dry_run:
        json_out_path = os.path.join(WORKSPACE_DIR, "tcm_patterns_details_dryrun.json")
        
    with open(json_out_path, "w", encoding="utf-8") as f:
        json.dump(scraped_results, f, indent=2, ensure_ascii=False)
        
    elapsed = time.time() - start_time
    print("\n==================================================")
    print("CLONING PROCESS COMPLETE!")
    print(f"Processed: {len(scraped_results)} of {total_patterns} patterns.")
    print(f"Saved SQLite DB to: {SQLITE_DB_PATH}")
    print(f"Saved JSON Data to: {json_out_path}")
    print(f"Generated Markdown files in: {MARKDOWN_DIR}")
    print(f"Total time elapsed: {elapsed:.2f} seconds.")
    print("==================================================")

if __name__ == "__main__":
    main()
