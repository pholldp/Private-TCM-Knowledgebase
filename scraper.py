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
CATALOG_JSON_PATH = os.path.join(WORKSPACE_DIR, "formulas_catalog.json")
SQLITE_DB_PATH = os.path.join(WORKSPACE_DIR, "tcm_formulas.db")
OUTPUT_JSON_PATH = os.path.join(WORKSPACE_DIR, "tcm_formulas_details.json")
MARKDOWN_DIR = os.path.join(WORKSPACE_DIR, "formulas")

BASE_URL = "https://www.meandqi.com"
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

# Parse details from single formula HTML
def parse_formula_details(html_content, formula_basic):
    details = {
        "name": formula_basic.get("name", ""),
        "chinese_name": formula_basic.get("chineseName", ""),
        "english_name": formula_basic.get("englishName", ""),
        "url": formula_basic.get("url", ""),
        "summary": formula_basic.get("summary", ""),
        "categories": formula_basic.get("categories", []),
        "tcm_actions": formula_basic.get("tcmActions", []),
        "therapeutic_focus": formula_basic.get("therapeuticFocus", []),
        "target_organs": formula_basic.get("targetOrgans", []),
        "temperature": formula_basic.get("temperature", ""),
        "preparation_form": formula_basic.get("preparationForm", ""),
        "dynasty": formula_basic.get("dynasty", ""),
        "conditions": formula_basic.get("conditions", []),
        "patterns": formula_basic.get("patterns", []),
        "other_names": formula_basic.get("otherNames", []),
        "pregnancy": "",
        "breastfeeding": "",
        "children": "",
        "drug_interactions": "",
        "best_time_to_take": "",
        "typical_duration": "",
        "dietary_advice": "",
        "ingredients_details": [],
        "research": []
    }
    
    if not html_content:
        return details

    # 1. Parse JSON-LD blocks for metadata & research
    json_ld_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_content, re.DOTALL)
    for block in json_ld_blocks:
        try:
            data = json.loads(block.strip())
            type_name = data.get("@type")
            if type_name == "MedicalTherapy":
                # Fill in any missing basic fields
                if not details["chinese_name"] and data.get("alternateName"):
                    details["chinese_name"] = data["alternateName"][0] if isinstance(data["alternateName"], list) else data["alternateName"]
                if not details["summary"] and data.get("description"):
                    details["summary"] = data["description"]
                    
                # Extract guideline/dynasty source if available
                if data.get("guideline") and isinstance(data["guideline"], dict):
                    details["dynasty"] = data["guideline"].get("name", details["dynasty"])
            
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
        except Exception as e:
            pass

    # 2. Parse Special Populations (Pregnancy, Breastfeeding, Children)
    preg_m = re.search(r"Pregnancy</h3>\s*</div>\s*<p class=\"[^\"]*whitespace-pre-line\">(.*?)</p>", html_content, re.DOTALL)
    breast_m = re.search(r"Breastfeeding</h3>\s*</div>\s*<p class=\"[^\"]*whitespace-pre-line\">(.*?)</p>", html_content, re.DOTALL)
    child_m = re.search(r"Children</h3>\s*</div>\s*<p class=\"[^\"]*whitespace-pre-line\">(.*?)</p>", html_content, re.DOTALL)

    details["pregnancy"] = clean_html(preg_m.group(1)) if preg_m else ""
    details["breastfeeding"] = clean_html(breast_m.group(1)) if breast_m else ""
    details["children"] = clean_html(child_m.group(1)) if child_m else ""

    # 3. Parse Drug Interactions
    drug_m = re.search(r"Drug Interactions</h2>.*?<div class=\"prose prose-sm prose-headings:text-sm prose-headings:font-semibold text-text-primary max-w-none\">(.*?)</div>", html_content, re.DOTALL)
    details["drug_interactions"] = clean_html(drug_m.group(1)) if drug_m else ""

    # 4. Parse Usage Guidance
    best_time_m = re.search(r"Best time to take\s*</h3>\s*<p class=\"text-sm text-text-primary mb-0 leading-relaxed\">(.*?)</p>", html_content, re.DOTALL)
    duration_m = re.search(r"Typical duration\s*</h3>\s*<p class=\"text-sm text-text-primary mb-0 leading-relaxed\">(.*?)</p>", html_content, re.DOTALL)
    dietary_m = re.search(r"Dietary advice\s*</h3>\s*<p class=\"text-sm text-text-primary mb-0 leading-relaxed\">(.*?)</p>", html_content, re.DOTALL)

    details["best_time_to_take"] = clean_html(best_time_m.group(1)) if best_time_m else ""
    details["typical_duration"] = clean_html(duration_m.group(1)) if duration_m else ""
    details["dietary_advice"] = clean_html(dietary_m.group(1)) if dietary_m else ""

    # 5. Parse Ingredients details (hierarchy, dosages, roles)
    starts = [m.start() for m in re.finditer(r'<div class="formula-herb-card [^"]+">', html_content)]
    for i, start in enumerate(starts):
        end = starts[i+1] if i+1 < len(starts) else html_content.find('</article>', start)
        card_html = html_content[start:end]
        
        name_m = re.search(r"<h3 class=\"formula-herb-name\">([^<]+)</h3>", card_html)
        if name_m:
            name = name_m.group(1).strip()
            english_m = re.search(r"<p class=\"formula-herb-english\">([^<]+)</p>", card_html)
            english = english_m.group(1).strip() if english_m else ""
            
            role_m = re.search(r"formula-herb-hierarchy-marker\s+(\w+)", card_html)
            role = role_m.group(1).strip().capitalize() if role_m else "Unknown"
            
            dosage_m = re.search(r"Dosage</span>\s*<span class=\"formula-herb-property-value\">([^<]+)</span>", card_html)
            dosage = dosage_m.group(1).strip() if dosage_m else ""
            
            temp_m = re.search(r"Temperature</span>\s*<span class=\"formula-herb-property-value\">([^<]+)</span>", card_html)
            temp = temp_m.group(1).strip() if temp_m else ""
            
            taste_m = re.search(r"Taste</span>\s*<span class=\"formula-herb-property-value\">([^<]+)</span>", card_html)
            taste = taste_m.group(1).strip() if taste_m else ""
            
            affinity_m = re.search(r"Organ Affinity</span>\s*<span class=\"formula-herb-property-value\">([^<]+)</span>", card_html)
            affinity = affinity_m.group(1).strip() if affinity_m else ""
            
            func_m = re.search(r"<h4 class=\"formula-herb-functions-title\">Role in [^<]+</h4>\s*<div class=\"text-text-primary text-sm prose prose-sm\">(.*?)</div>", card_html, re.DOTALL)
            func = clean_html(func_m.group(1)) if func_m else ""
            
            details["ingredients_details"].append({
                "herb_name": name,
                "english_name": english,
                "role": role,
                "dosage": dosage,
                "temperature": temp,
                "taste": taste,
                "organ_affinity": affinity,
                "role_description": func
            })
            
    return details

# Task to process a single formula
def scrape_formula_task(formula_basic, idx, total):
    url = BASE_URL + formula_basic["url"]
    print(f"[{idx}/{total}] Scraping: {formula_basic['name']} ...")
    html_content = fetch_url(url)
    
    if not html_content:
        print(f"Error fetching: {formula_basic['name']}")
        return parse_formula_details("", formula_basic)
        
    try:
        parsed = parse_formula_details(html_content, formula_basic)
        return parsed
    except Exception as e:
        print(f"Error parsing: {formula_basic['name']}: {e}")
        return parse_formula_details("", formula_basic)

# Database Setup
def init_sqlite_db():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    
    # Create formulas table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS formulas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            chinese_name TEXT,
            english_name TEXT,
            url TEXT UNIQUE,
            summary TEXT,
            categories TEXT,
            tcm_actions TEXT,
            therapeutic_focus TEXT,
            target_organs TEXT,
            temperature TEXT,
            preparation_form TEXT,
            dynasty TEXT,
            conditions TEXT,
            patterns TEXT,
            other_names TEXT,
            pregnancy TEXT,
            breastfeeding TEXT,
            children TEXT,
            drug_interactions TEXT,
            best_time_to_take TEXT,
            typical_duration TEXT,
            dietary_advice TEXT
        )
    """)
    
    # Create formula_ingredients table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS formula_ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            formula_id INTEGER,
            herb_name TEXT NOT NULL,
            english_name TEXT,
            role TEXT,
            dosage TEXT,
            temperature TEXT,
            taste TEXT,
            organ_affinity TEXT,
            role_description TEXT,
            FOREIGN KEY(formula_id) REFERENCES formulas(id) ON DELETE CASCADE
        )
    """)
    
    # Create formula_research table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS formula_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            formula_id INTEGER,
            title TEXT,
            description TEXT,
            url TEXT,
            periodical TEXT,
            FOREIGN KEY(formula_id) REFERENCES formulas(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    return conn

# Insert parsed formula into SQLite
def insert_formula_into_db(conn, f):
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO formulas (
                name, chinese_name, english_name, url, summary, categories, tcm_actions,
                therapeutic_focus, target_organs, temperature, preparation_form, dynasty,
                conditions, patterns, other_names, pregnancy, breastfeeding, children,
                drug_interactions, best_time_to_take, typical_duration, dietary_advice
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f["name"],
            f["chinese_name"],
            f["english_name"],
            f["url"],
            f["summary"],
            json.dumps(f["categories"], ensure_ascii=False),
            json.dumps(f["tcm_actions"], ensure_ascii=False),
            json.dumps(f["therapeutic_focus"], ensure_ascii=False),
            json.dumps(f["target_organs"], ensure_ascii=False),
            f["temperature"],
            f["preparation_form"],
            f["dynasty"],
            json.dumps(f["conditions"], ensure_ascii=False),
            json.dumps(f["patterns"], ensure_ascii=False),
            json.dumps(f["other_names"], ensure_ascii=False),
            f["pregnancy"],
            f["breastfeeding"],
            f["children"],
            f["drug_interactions"],
            f["best_time_to_take"],
            f["typical_duration"],
            f["dietary_advice"]
        ))
        
        formula_id = cursor.lastrowid
        
        # Remove old ingredient rows if updating
        cursor.execute("DELETE FROM formula_ingredients WHERE formula_id = ?", (formula_id,))
        # Insert ingredients
        for ing in f["ingredients_details"]:
            cursor.execute("""
                INSERT INTO formula_ingredients (
                    formula_id, herb_name, english_name, role, dosage, temperature, taste, organ_affinity, role_description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                formula_id,
                ing["herb_name"],
                ing["english_name"],
                ing["role"],
                ing["dosage"],
                ing["temperature"],
                ing["taste"],
                ing["organ_affinity"],
                ing["role_description"]
            ))
            
        # Remove old research rows if updating
        cursor.execute("DELETE FROM formula_research WHERE formula_id = ?", (formula_id,))
        # Insert research articles
        for res in f["research"]:
            cursor.execute("""
                INSERT INTO formula_research (
                    formula_id, title, description, url, periodical
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                formula_id,
                res["title"],
                res["description"],
                res["url"],
                res["periodical"]
            ))
            
        conn.commit()
    except Exception as e:
        print(f"Database insertion error for {f['name']}: {e}")
        conn.rollback()

# Generate Markdown File
def generate_markdown_file(f):
    # Use URL slug to prevent name collisions for formulas with identical names
    safe_name = f["url"].split("/")[-1]
    file_path = os.path.join(MARKDOWN_DIR, f"{safe_name}.md")
    
    categories = ", ".join(f["categories"])
    actions = ", ".join(f["tcm_actions"])
    focus = ", ".join(f["therapeutic_focus"])
    organs = ", ".join(f["target_organs"])
    conditions = ", ".join(f["conditions"])
    patterns = ", ".join(f["patterns"])
    other_names = ", ".join(f["other_names"])
    
    content = f"""# {f["name"]} ({f["chinese_name"]})
**English Name**: {f["english_name"]}  
**Category**: {categories}  
**Dynasty/Source**: {f["dynasty"]}  
**Temperature**: {f["temperature"]} | **Form**: {f["preparation_form"]}

---

## Summary
{f["summary"]}

---

## Key Metadata
- **TCM Actions**: {actions}
- **Therapeutic Focus**: {focus}
- **Target Organs**: {organs}
- **Patterns Addressed**: {patterns}
- **Conditions Treated**: {conditions}
- **Other Names**: {other_names}

---

## Ingredients Composition
| Herb Name | English Name | Role | Dosage | Properties & Affinity | Role Summary |
| :--- | :--- | :--- | :--- | :--- | :--- |
"""

    if f["ingredients_details"]:
        for ing in f["ingredients_details"]:
            props = f"Temp: {ing['temperature']}<br>Taste: {ing['taste']}<br>Affinity: {ing['organ_affinity']}"
            desc = ing['role_description'].replace('\n', '<br>')
            content += f"| **{ing['herb_name']}** | {ing['english_name']} | *{ing['role']}* | {ing['dosage']} | {props} | {desc} |\n"
    else:
        # Fallback to catalog allIngredients
        for ing_name in f.get("allIngredients", []):
            is_key = "Yes" if ing_name in f.get("keyIngredients", []) else "No"
            content += f"| **{ing_name}** | - | - | - | - | Key Herb: {is_key} |\n"
            
    content += "\n---\n\n## Special Populations & Safety\n"
    
    if f["pregnancy"]:
        content += f"### Pregnancy\n{f['pregnancy']}\n\n"
    if f["breastfeeding"]:
        content += f"### Breastfeeding\n{f['breastfeeding']}\n\n"
    if f["children"]:
        content += f"### Children\n{f['children']}\n\n"
    if not (f["pregnancy"] or f["breastfeeding"] or f["children"]):
        content += "*No specific safety warnings listed.*\n\n"
        
    if f["drug_interactions"]:
        content += f"## Drug Interactions\n{f['drug_interactions']}\n\n"
        
    content += "## Usage & Dosage Guidance\n"
    if f["best_time_to_take"]:
        content += f"- **Best Time to Take**: {f['best_time_to_take']}\n"
    if f["typical_duration"]:
        content += f"- **Typical Duration**: {f['typical_duration']}\n"
    if f["dietary_advice"]:
        content += f"- **Dietary Advice**: \n{f['dietary_advice']}\n\n"
    if not (f["best_time_to_take"] or f["typical_duration"] or f["dietary_advice"]):
        content += "*Standard usage guidelines apply.*\n\n"

    if f["research"]:
        content += "## Modern Scientific Research\n"
        for idx, res in enumerate(f["research"], 1):
            content += f"{idx}. **[{res['title']}]({res['url']})**\n"
            if res['periodical']:
                content += f"   *Journal: {res['periodical']}*\n"
            content += f"   {res['description']}\n\n"
            
    content += f"\n---\n*Original URL: [{BASE_URL}{f['url']}]({BASE_URL}{f['url']})*"
    
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)

def main():
    start_time = time.time()
    
    # Load basic catalog
    if not os.path.exists(CATALOG_JSON_PATH):
        print(f"Catalog file not found at {CATALOG_JSON_PATH}. Run the analyzer script first.")
        return
        
    with open(CATALOG_JSON_PATH, "r", encoding="utf-8") as f:
        catalog_data = json.load(f)
        
    all_formulas_basic = catalog_data.get("allFormulas", [])
    total_formulas = len(all_formulas_basic)
    print(f"Loaded {total_formulas} formulas from catalog.")
    
    # Initialize SQLite database
    conn = init_sqlite_db()
    
    # Scraped data list for JSON
    scraped_results = []
    
    print(f"Starting multi-threaded scraping with concurrency={CONCURRENCY}...")
    
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        # Submit tasks
        futures = {
            executor.submit(scrape_formula_task, f_basic, idx, total_formulas): f_basic 
            for idx, f_basic in enumerate(all_formulas_basic, 1)
        }
        
        # Gather results as they complete
        for future in as_completed(futures):
            f_basic = futures[future]
            try:
                detailed_formula = future.result()
                scraped_results.append(detailed_formula)
                
                # Write to SQLite
                insert_formula_into_db(conn, detailed_formula)
                
                # Write to Markdown
                generate_markdown_file(detailed_formula)
                
            except Exception as exc:
                print(f"Task for {f_basic['name']} generated an exception: {exc}")
                
    # Close SQLite Connection
    conn.close()
    
    # Write to single large JSON file
    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(scraped_results, f, indent=2, ensure_ascii=False)
        
    elapsed = time.time() - start_time
    print("\n==================================================")
    print("CLONING PROCESS COMPLETE!")
    print(f"Processed: {len(scraped_results)} of {total_formulas} formulas.")
    print(f"Saved SQLite DB to: {SQLITE_DB_PATH}")
    print(f"Saved JSON Data to: {OUTPUT_JSON_PATH}")
    print(f"Generated Markdown files in: {MARKDOWN_DIR}")
    print(f"Total time elapsed: {elapsed:.2f} seconds.")
    print("==================================================")

if __name__ == "__main__":
    main()
