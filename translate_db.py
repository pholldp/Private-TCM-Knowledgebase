import os
import re
import json
import urllib.request
import urllib.parse
import sqlite3
import html
import time
import random

# Paths
WORKSPACE_DIR = "/Users/phol/Desktop/Antigravity Project/TCM database"
INPUT_JSON_PATH = os.path.join(WORKSPACE_DIR, "tcm_formulas_details.json")
SQLITE_DB_PATH = os.path.join(WORKSPACE_DIR, "tcm_formulas_th.db")
OUTPUT_JSON_PATH = os.path.join(WORKSPACE_DIR, "tcm_formulas_details_th.json")
MARKDOWN_DIR = os.path.join(WORKSPACE_DIR, "formulas_th")

BASE_URL = "https://www.meandqi.com"
os.makedirs(MARKDOWN_DIR, exist_ok=True)

# 1. Dictionary of standard TCM terms for high quality Thai equivalents
DICT_TCM = {
    # Temperature
    "Hot": "ร้อน",
    "Warm": "อุ่น",
    "Slightly Warm": "อุ่นเล็กน้อย",
    "Neutral": "เป็นกลาง (สุขุม)",
    "Cool": "เย็น",
    "Slightly Cool": "เย็นเล็กน้อย",
    "Cold": "หนาวเย็น",
    
    # Organs
    "Spleen": "ม้าม",
    "Stomach": "กระเพาะอาหาร",
    "Lungs": "ปอด",
    "Lung": "ปอด",
    "Heart": "หัวใจ",
    "Kidneys": "ไต",
    "Kidney": "ไต",
    "Liver": "ตับ",
    "Gallbladder": "ถุงน้ำดี",
    "Urinary Bladder": "กระเพาะปัสสาวะ",
    "Bladder": "กระเพาะปัสสาวะ",
    "Large Intestine": "ลำไส้ใหญ่",
    "Small Intestine": "ลำไส้เล็ก",
    "San Jiao (Triple Burner)": "ซานเจียว (ซานเจียว/Triple Burner)",
    "San Jiao": "ซานเจียว",
    "Uterus": "มดลูก",
    "Pericardium": "เยื่อหุ้มหัวใจ",
    "Brain": "สมอง",
    
    # Preparation Form
    "Decoction (Tang)": "ยาต้ม (ถัง / Tang)",
    "Decoction": "ยาต้ม",
    "Powder (San)": "ยาผง (ซ่าน / San)",
    "Powder": "ยาผง",
    "Pill (Wan)": "ยาเม็ดลูกกลอน (หวาน / Wan)",
    "Pill": "ยาเม็ด",
    "Honey pill (Mi Wan)": "ยาเม็ดลูกกลอนน้ำผึ้ง (มี่หวาน / Mi Wan)",
    "Honey pill": "ยาเม็ดลูกกลอนน้ำผึ้ง",
    "Water-drip pill (Shui Wan)": "ยาเม็ดลูกกลอนน้ำ (สุ่ยหวาน / Shui Wan)",
    "Water-drip pill": "ยาเม็ดลูกกลอนน้ำ",
    "Concentrated pills": "ยาเม็ดลูกกลอนเข้มข้น",
    "Capsule": "แคปซูล",
    "Granule": "แกรนูล",
    "Tablet": "ยาเม็ดแบน",
    "Ointment": "ขี้ผึ้ง (ยาทา)",
    "Plaster": "พลาสเตอร์ยา",
    
    # Roles
    "King": "ราชา (King)",
    "Deputy": "ขุนนาง (Deputy)",
    "Assistant": "ผู้ช่วย (Assistant)",
    "Envoy": "ผู้ส่งสาร (Envoy)",
    "Unknown": "ไม่ระบุ",
}

# Helper to look up terms in translation dictionary
def translate_term(term):
    if not term:
        return ""
    term_stripped = term.strip()
    return DICT_TCM.get(term_stripped, term_stripped)

def translate_list_terms(term_list):
    if not term_list:
        return []
    return [translate_term(t) for t in term_list]

# Translation call via Chrome Extension endpoint (generous rate limits)
def translate_single(text, target_lang="th", source_lang="en"):
    if not text or not text.strip():
        return ""
    
    encoded_text = urllib.parse.quote(text)
    url = f"https://clients5.google.com/translate_a/t?client=dict&sl={source_lang}&tl={target_lang}&q={encoded_text}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    req = urllib.request.Request(url, headers=headers)
    
    backoff = 2
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                res_data = response.read().decode('utf-8')
                parsed = json.loads(res_data)
                # clients5 returns a flat list ['translated_text']
                if parsed and isinstance(parsed, list) and len(parsed) > 0:
                    return parsed[0]
                return text
        except urllib.error.HTTPError as e:
            if e.code == 429:
                sleep_time = 15 * backoff + random.random() * 5
                print(f"Rate limited (429). Sleeping for {sleep_time:.1f} seconds...")
                time.sleep(sleep_time)
                backoff *= 2
            else:
                print(f"HTTP Error {e.code} during translation: {e}")
                time.sleep(1 + attempt)
        except Exception as e:
            print(f"Translation exception: {e}")
            time.sleep(1 + attempt)
            
    return text

# Translate a batch of texts sequentially using separator
def translate_batch(texts, target_lang="th", source_lang="en"):
    if not texts:
        return []
        
    cleaned_texts = []
    for t in texts:
        if t is None:
            cleaned_texts.append("EMPTY_PLACEHOLDER")
        elif isinstance(t, list):
            cleaned_texts.append(", ".join(t))
        elif not str(t).strip():
            cleaned_texts.append("EMPTY_PLACEHOLDER")
        else:
            cleaned_texts.append(str(t).strip())
            
    delimiter = "\n===\n"
    
    # Split list into 3000-character chunks
    chunks = []
    current_chunk = []
    current_len = 0
    for text in cleaned_texts:
        if current_len + len(text) + len(delimiter) > 3000:
            chunks.append(current_chunk)
            current_chunk = [text]
            current_len = len(text)
        else:
            current_chunk.append(text)
            current_len += len(text) + len(delimiter)
    if current_chunk:
        chunks.append(current_chunk)
        
    translated_all = []
    for chunk in chunks:
        joined = delimiter.join(chunk)
        translation = translate_single(joined, target_lang, source_lang)
        
        # Split back
        parts = re.split(r'\s*===\s*', translation)
        parts = [p.strip() for p in parts]
        
        # If mismatch, fallback to translating one-by-one (sequentially)
        if len(parts) != len(chunk):
            print(f"Warning: Batch length mismatch ({len(parts)} vs {len(chunk)}). Using sequential fallback.")
            parts = []
            for item in chunk:
                if item == "EMPTY_PLACEHOLDER":
                    parts.append("")
                else:
                    parts.append(translate_single(item, target_lang, source_lang))
                    time.sleep(0.5)
        
        # Restore empty items
        for idx, item in enumerate(chunk):
            if item == "EMPTY_PLACEHOLDER":
                parts[idx] = ""
                
        translated_all.extend(parts)
        
    return translated_all

# Translate a single formula dictionary
def translate_formula(f):
    # Batch fields to translate (free-form texts only, keeping research in English)
    batch_fields = [
        f.get("summary", ""),
        f.get("pregnancy", ""),
        f.get("breastfeeding", ""),
        f.get("children", ""),
        f.get("drug_interactions", ""),
        f.get("best_time_to_take", ""),
        f.get("typical_duration", ""),
        f.get("dietary_advice", "")
    ]
    
    # Ingredient english names and descriptions
    ing_offset = len(batch_fields)
    for ing in f.get("ingredients_details", []):
        batch_fields.append(ing.get("english_name", ""))
        batch_fields.append(ing.get("role_description", ""))
        
    # List fields (append as strings joined by commas)
    list_offset = len(batch_fields)
    batch_fields.append(", ".join(f.get("categories", [])))
    batch_fields.append(", ".join(f.get("tcm_actions", [])))
    batch_fields.append(", ".join(f.get("therapeutic_focus", [])))
    batch_fields.append(", ".join(f.get("conditions", [])))
    batch_fields.append(", ".join(f.get("patterns", [])))
    
    # Run a single batch translation for the entire formula
    translated = translate_batch(batch_fields)
    
    if len(translated) >= len(batch_fields):
        f["summary"] = translated[0]
        f["pregnancy"] = translated[1]
        f["breastfeeding"] = translated[2]
        f["children"] = translated[3]
        f["drug_interactions"] = translated[4]
        f["best_time_to_take"] = translated[5]
        f["typical_duration"] = translated[6]
        f["dietary_advice"] = translated[7]
        
        # Ingredients details
        idx = ing_offset
        for ing in f.get("ingredients_details", []):
            ing["english_name"] = translated[idx]
            ing["role_description"] = translated[idx+1]
            # Translate other metadata using lookup dictionary
            ing["role"] = translate_term(ing.get("role", ""))
            ing["temperature"] = translate_term(ing.get("temperature", ""))
            ing["taste"] = ", ".join(translate_list_terms(ing.get("taste", "").split(", ")))
            ing["organ_affinity"] = ", ".join(translate_list_terms(ing.get("organ_affinity", "").split(", ")))
            idx += 2
            
        # Lists (extract and split back)
        idx = list_offset
        f["categories"] = [x.strip() for x in translated[idx].split(", ")] if translated[idx] else []
        f["tcm_actions"] = [x.strip() for x in translated[idx+1].split(", ")] if translated[idx+1] else []
        f["therapeutic_focus"] = [x.strip() for x in translated[idx+2].split(", ")] if translated[idx+2] else []
        f["conditions"] = [x.strip() for x in translated[idx+3].split(", ")] if translated[idx+3] else []
        f["patterns"] = [x.strip() for x in translated[idx+4].split(", ")] if translated[idx+4] else []
        
    f["target_organs"] = translate_list_terms(f.get("target_organs", []))
    f["temperature"] = translate_term(f.get("temperature", ""))
    f["preparation_form"] = translate_term(f.get("preparation_form", ""))
    
    return f

# Initialize Thai SQLite DB
def init_sqlite_db():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    
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

# Insert into Thai DB
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
        
        cursor.execute("DELETE FROM formula_ingredients WHERE formula_id = ?", (formula_id,))
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
            
        cursor.execute("DELETE FROM formula_research WHERE formula_id = ?", (formula_id,))
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

# Generate Thai Markdown File
def generate_markdown_file(f):
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
**ชื่อภาษาอังกฤษ (English Name)**: {f["english_name"]}  
**หมวดหมู่ตำรับยา (Category)**: {categories}  
**ราชวงศ์/คัมภีร์อ้างอิง (Source)**: {f["dynasty"]}  
**คุณสมบัติอุณหภูมิ (Temperature)**: {f["temperature"]} | **รูปแบบยา (Form)**: {f["preparation_form"]}

---

## บทสรุปตำรับยา (Summary)
{f["summary"]}

---

## ข้อมูลสำคัญทางแพทย์แผนจีน (TCM Metadata)
- **การออกฤทธิ์ทางแพทย์แผนจีน (TCM Actions)**: {actions}
- **จุดประสงค์การรักษา (Therapeutic Focus)**: {focus}
- **อวัยวะเป้าหมาย (Target Organs)**: {organs}
- **กลุ่มอาการที่รักษา (Patterns Addressed)**: {patterns}
- **โรค/อาการร่วมที่รักษา (Conditions Treated)**: {conditions}
- **ชื่อเรียกอื่นๆ (Other Names)**: {other_names}

---

## ส่วนประกอบตำรับยา (Ingredients Composition)
| ชื่อสมุนไพรจีน (Herb Pinyin) | ชื่อภาษาไทย/อังกฤษ (Translated Name) | บทบาทในตำรับ (Role) | ปริมาณยา (Dosage) | คุณสมบัติ & เส้นลมปราณที่เข้า (Properties) | คำอธิบายบทบาท (Role Summary) |
| :--- | :--- | :--- | :--- | :--- | :--- |
"""

    if f["ingredients_details"]:
        for ing in f["ingredients_details"]:
            props = f"อุณหภูมิ: {ing['temperature']}<br>รสชาติ: {ing['taste']}<br>เข้าเส้นลมปราณ: {ing['organ_affinity']}"
            desc = ing['role_description'].replace('\n', '<br>')
            content += f"| **{ing['herb_name']}** | {ing['english_name']} | *{ing['role']}* | {ing['dosage']} | {props} | {desc} |\n"
    else:
        for ing_name in f.get("allIngredients", []):
            is_key = "ใช่" if ing_name in f.get("keyIngredients", []) else "ไม่ใช่"
            content += f"| **{ing_name}** | - | - | - | - | สมุนไพรหลัก: {is_key} |\n"
            
    content += "\n---\n\n## ข้อควรระวัง & ความปลอดภัยในกลุ่มพิเศษ (Special Populations & Safety)\n"
    
    if f["pregnancy"]:
        content += f"### สตรีมีครรภ์ (Pregnancy)\n{f['pregnancy']}\n\n"
    if f["breastfeeding"]:
        content += f"### สตรีให้นมบุตร (Breastfeeding)\n{f['breastfeeding']}\n\n"
    if f["children"]:
        content += f"### เด็ก (Children)\n{f['children']}\n\n"
    if not (f["pregnancy"] or f["breastfeeding"] or f["children"]):
        content += "*ไม่มีคำเตือนความปลอดภัยเฉพาะระบุไว้*\n\n"
        
    if f["drug_interactions"]:
        content += f"## ปฏิกิริยากับยาแผนปัจจุบัน (Drug Interactions)\n{f['drug_interactions']}\n\n"
        
    content += "## Usage & Dosage Guidance (คำแนะนำการใช้งาน & ปริมาณยา)\n"
    if f["best_time_to_take"]:
        content += f"- **เวลาที่ดีที่สุดในการรับประทาน**: {f['best_time_to_take']}\n"
    if f["typical_duration"]:
        content += f"- **ระยะเวลาการใช้ยาโดยทั่วไป**: {f['typical_duration']}\n"
    if f["dietary_advice"]:
        content += f"- **ข้อแนะนำเรื่องอาหารร่วมกับการใช้ยา**: \n{f['dietary_advice']}\n\n"
    if not (f["best_time_to_take"] or f["typical_duration"] or f["dietary_advice"]):
        content += "*ใช้วิธีรับประทานตามคำแนะนำมาตรฐานทั่วไป*\n\n"

    if f["research"]:
        content += "## งานวิจัยทางวิทยาศาสตร์สมัยใหม่ (Modern Scientific Research)\n"
        for idx, res in enumerate(f["research"], 1):
            content += f"{idx}. **[{res['title']}]({res['url']})**\n"
            if res['periodical']:
                content += f"   *วารสารวิชาการ: {res['periodical']}*\n"
            content += f"   {res['description']}\n\n"
            
    content += f"\n---\n*ลิงก์ต้นฉบับภาษาอังกฤษ: [Me & Qi Formulas]({BASE_URL}{f['url']})*"
    
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)

# Helper to process single formula and handle exceptions
def translate_task(f, idx, total):
    print(f"[{idx}/{total}] Translating: {f['name']} ...")
    try:
        return translate_formula(f)
    except Exception as e:
        print(f"Error translating: {f['name']}: {e}")
        return f

def main():
    start_time = time.time()
    
    if not os.path.exists(INPUT_JSON_PATH):
        print(f"English database file not found at {INPUT_JSON_PATH}.")
        return
        
    with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
        formulas_details = json.load(f)
        
    total_formulas = len(formulas_details)
    print(f"Loaded {total_formulas} formulas.")
    
    # Load translation cache from existing Thai JSON file (if available)
    translated_cache = {}
    if os.path.exists(OUTPUT_JSON_PATH):
        try:
            with open(OUTPUT_JSON_PATH, "r", encoding="utf-8") as f_th:
                cached_data = json.load(f_th)
                for item in cached_data:
                    summary = item.get("summary", "")
                    has_thai = any('\u0e00' <= char <= '\u0e7f' for char in summary)
                    if has_thai:
                        translated_cache[item["url"]] = item
            print(f"Loaded {len(translated_cache)} translated formulas from cache.")
        except Exception as e:
            print(f"Could not load cache: {e}")
            
    # Initialize Thai DB
    conn = init_sqlite_db()
    
    translated_results = []
    
    print("Translating formulas sequentially with resume support...")
    for idx, f in enumerate(formulas_details, 1):
        url = f["url"]
        
        if url in translated_cache:
            # Re-use cached translation
            translated_f = translated_cache[url]
            print(f"[{idx}/{total_formulas}] Re-using cached: {f['name']}")
        else:
            # Run translation
            translated_f = translate_task(f, idx, total_formulas)
            
            # Polite delay to prevent rate limits (0.8s to 1.3s)
            time.sleep(0.8 + random.random() * 0.5)
            
        translated_results.append(translated_f)
        
        # Write to SQLite immediately
        insert_formula_into_db(conn, translated_f)
        
        # Write to Markdown immediately
        generate_markdown_file(translated_f)
        
        # Write to JSON immediately to preserve progress
        with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as out_f:
            json.dump(translated_results, out_f, indent=2, ensure_ascii=False)
                
    conn.close()
    
    elapsed = time.time() - start_time
    print("\n==================================================")
    print("THAI TRANSLATION COMPLETE!")
    print(f"Processed: {len(translated_results)} formulas.")
    print(f"Saved Thai SQLite DB to: {SQLITE_DB_PATH}")
    print(f"Saved Thai JSON Data to: {OUTPUT_JSON_PATH}")
    print(f"Generated Thai Markdown files in: {MARKDOWN_DIR}")
    print(f"Total time elapsed: {elapsed:.2f} seconds.")
    print("==================================================")

if __name__ == "__main__":
    main()
