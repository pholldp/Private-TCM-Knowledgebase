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
INPUT_JSON_PATH = os.path.join(WORKSPACE_DIR, "tcm_patterns_details.json")
SQLITE_DB_PATH = os.path.join(WORKSPACE_DIR, "tcm_patterns_th.db")
OUTPUT_JSON_PATH = os.path.join(WORKSPACE_DIR, "tcm_patterns_details_th.json")
MARKDOWN_DIR = os.path.join(WORKSPACE_DIR, "patterns_th")

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
    "San Jiao (Triple Burner)": "ซานเจียว (Triple Burner)",
    "San Jiao": "ซานเจียว",
    "Uterus": "มดลูก",
    "Pericardium": "เยื่อหุ้มหัวใจ",
    "Brain": "สมอง",
    
    # Nature
    "Empty": "พร่อง (Empty)",
    "Full": "แกร่ง (Full)",
    "Empty-Cold": "หนาวเย็นแบบพร่อง",
    "Empty-Heat": "ร้อนแบบพร่อง",
    "Full-Cold": "หนาวเย็นแบบแกร่ง",
    "Full-Heat": "ร้อนแบบแกร่ง",
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

# Helper to check if string contains Thai characters
def is_thai(s):
    return any('\u0e00' <= char <= '\u0e7f' for char in s)

# Translation call via Chrome Extension endpoint
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
        
        # If mismatch, fallback to translating sequentially
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

# Recursive helper to collect strings
def collect_strings(data, path, collected):
    if isinstance(data, str):
        if data.strip():
            collected.append((path, data))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            collect_strings(item, path + [idx], collected)
    elif isinstance(data, dict):
        for k, v in data.items():
            collect_strings(v, path + [k], collected)

# Helper to set value at path
def set_nested_val(data, path, val):
    curr = data
    for step in path[:-1]:
        curr = curr[step]
    curr[path[-1]] = val

# Translate a single pattern
def translate_pattern(p):
    # Create copy to avoid mutating cache
    p = json.loads(json.dumps(p))
    
    collected = []
    
    # 1. Collect standard fields
    collect_strings(p.get("name", ""), ["name"], collected)
    collect_strings(p.get("description", ""), ["description"], collected)
    collect_strings(p.get("also_known_as", ""), ["also_known_as"], collected)
    collect_strings(p.get("key_signs", []), ["key_signs"], collected)
    collect_strings(p.get("worse_with", []), ["worse_with"], collected)
    collect_strings(p.get("better_with", []), ["better_with"], collected)
    collect_strings(p.get("timing_worsening_explanation", ""), ["timing_worsening_explanation"], collected)
    collect_strings(p.get("practitioner_notes", ""), ["practitioner_notes"], collected)
    collect_strings(p.get("pathophysiology", ""), ["pathophysiology"], collected)
    collect_strings(p.get("treatment_principle", ""), ["treatment_principle"], collected)
    collect_strings(p.get("typical_timeline", ""), ["typical_timeline"], collected)
    collect_strings(p.get("formula_modifications", ""), ["formula_modifications"], collected)
    
    # 2. Collect formulas descriptions
    for idx, f in enumerate(p.get("formulas", [])):
        collect_strings(f.get("description", ""), ["formulas", idx, "description"], collected)
        
    # 3. Collect herbs descriptions
    for idx, h in enumerate(p.get("herbs", [])):
        collect_strings(h.get("description", ""), ["herbs", idx, "description"], collected)
        
    # 4. Collect acupoints descriptions
    for idx, a in enumerate(p.get("acupoints", [])):
        collect_strings(a.get("description", ""), ["acupoints", idx, "description"], collected)
        
    # 5. Collect differential diagnosis explanations
    for idx, d in enumerate(p.get("differential_diagnosis", [])):
        collect_strings(d.get("explanation", ""), ["differential_diagnosis", idx, "explanation"], collected)
        
    # 6. Collect classical texts translations
    for idx, c in enumerate(p.get("classical_texts", [])):
        collect_strings(c.get("translation", ""), ["classical_texts", idx, "translation"], collected)
        
    # 7. Collect faqs questions and answers
    for idx, faq in enumerate(p.get("faqs", [])):
        collect_strings(faq.get("question", ""), ["faqs", idx, "question"], collected)
        collect_strings(faq.get("answer", ""), ["faqs", idx, "answer"], collected)
        
    # 8. Collect clinical advice titles and content
    for idx, ca in enumerate(p.get("clinical_advice", [])):
        collect_strings(ca.get("title", ""), ["clinical_advice", idx, "title"], collected)
        collect_strings(ca.get("content", ""), ["clinical_advice", idx, "content"], collected)
        
    # 9. Collect four examinations values
    collect_strings(p.get("four_examinations", {}), ["four_examinations"], collected)
    
    # 10. Collect causes details titles and explanations
    for idx, cause in enumerate(p.get("causes_details", [])):
        collect_strings(cause.get("cause_title", ""), ["causes_details", idx, "cause_title"], collected)
        collect_strings(cause.get("explanation", ""), ["causes_details", idx, "explanation"], collected)
        
    # Translate all collected texts in batch
    texts_to_translate = [val for path, val in collected]
    translated_texts = translate_batch(texts_to_translate)
    
    # Put back translated values
    for (path, original_val), trans_val in zip(collected, translated_texts):
        set_nested_val(p, path, trans_val)
        
    # Post-process dictionaries lookup for organs and nature
    p["nature"] = translate_term(p.get("nature", ""))
    p["organs"] = translate_list_terms(p.get("organs", []))
    p["by_vital_substance"] = translate_list_terms(p.get("by_vital_substance", []))
    p["by_pathogenic_factor"] = translate_list_terms(p.get("by_pathogenic_factor", []))
    
    return p

# Initialize SQLite database
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

# Generate Thai Markdown File
def generate_markdown_file(p):
    safe_name = p["url"].split("/")[-1]
    file_path = os.path.join(MARKDOWN_DIR, f"{safe_name}.md")
    
    organs = ", ".join(p.get("organs", []))
    key_signs = ", ".join(p.get("key_signs", []))
    
    content = f"""# {p["name"]} ({p["chinese_name"]})
**ชื่อพินอิน (Pinyin)**: {p["pinyin"]} | **ลักษณะกลุ่มอาการ (Nature)**: {p["nature"]} | **อวัยวะที่ได้รับผลกระทบ (Affected Organs)**: {organs}  
**ชื่อเรียกอื่นๆ (Also Known As)**: {p.get("also_known_as", "")}

---

## บทสรุปกลุ่มอาการ (Summary)
{p["description"]}

---

## สัญญาณและอาการทางคลินิก (Clinical Signs & Symptoms)
- **อาการสำคัญ (Key Signs)**: {key_signs}

### ปัจจัยกระตุ้นให้ดีขึ้นหรือแย่ลง (What Makes It Better/Worse)
- **แย่ลงเมื่อ (Worse with)**: 
"""
    for item in p.get("worse_with", []):
        content += f"  - {item}\n"
    if not p.get("worse_with"):
        content += "  *ไม่มีระบุ*\n"
        
    content += "- **ดีขึ้นเมื่อ (Better with)**: \n"
    for item in p.get("better_with", []):
        content += f"  - {item}\n"
    if not p.get("better_with"):
        content += "  *ไม่มีระบุ*\n"
        
    if p.get("timing_worsening_explanation"):
        content += f"\n**รายละเอียดช่วงเวลาที่อาการแย่ลง**: {p['timing_worsening_explanation']}\n"
        
    content += f"""
---

## มุมมองการแพทย์แผนจีน (Traditional Chinese Medicine View)
- **กลไกการเกิดโรค (Pathophysiology)**: {p.get("pathophysiology", "")}
- **บันทึกจากผู้ปฏิบัติงาน (Practitioner Notes)**: {p.get("practitioner_notes", "")}

### การตรวจทั้งสี่ (Four Examinations)
"""
    fe = p.get("four_examinations", {})
    insp = fe.get("inspection", {})
    tongue_grid = insp.get("tongue_grid", {})
    vitality_grid = insp.get("vitality_grid", {})
    
    content += "#### การดู (Inspection)\n"
    if insp.get("tongue_summary"):
        content += f"- **สรุปลักษณะลิ้น (Tongue Summary)**: {insp['tongue_summary']}\n"
    if tongue_grid:
        content += "- **คุณสมบัติของลิ้น (Tongue Properties)**:\n"
        for k, v in tongue_grid.items():
            content += f"  - **{k}**: {v}\n"
    if insp.get("tongue_explanation"):
        content += f"- **คำอธิบายลักษณะลิ้น**: {insp['tongue_explanation']}\n"
    if vitality_grid:
        content += "- **สภาพร่างกายและสีหน้า (Vitality & Complexion)**:\n"
        for k, v in vitality_grid.items():
            content += f"  - **{k}**: {v}\n"
            
    ls = fe.get("listening_smelling", {})
    content += "\n#### การฟังและการดมกลิ่น (Listening & Smelling)\n"
    if ls.get("grid"):
        for k, v in ls["grid"].items():
            content += f"- **{k}**: {v}\n"
    else:
        content += "*ไม่มีอาการเฉพาะระบุไว้.*\n"
        
    palp = fe.get("palpation", {})
    content += "\n#### การคลำ (Palpation)\n"
    if palp.get("pulse_qualities"):
        content += f"- **ลักษณะชีพจร (Pulse Qualities)**: {', '.join(palp['pulse_qualities'])}\n"
    if palp.get("pulse_explanation"):
        content += f"- **คำอธิบายชีพจร**: {palp['pulse_explanation']}\n"
    if palp.get("palpation_grid"):
        for k, v in palp["palpation_grid"].items():
            content += f"- **{k}**: {v}\n"
            
    content += f"""
---

## การรักษาและคำแนะนำ (Treatment & Recommendations)
- **หลักการรักษา (Treatment Principle)**: {p.get("treatment_principle", "")}
- **ระยะเวลาการรักษาโดยทั่วไป (Typical Timeline)**: {p.get("typical_timeline", "")}

### ตำรับยาที่แนะนำ (Recommended Formulas)
| ชื่อตำรับยา (Formula Name) | คำอธิบายตำรับยา (Description) |
| :--- | :--- |
"""
    if p.get("formulas"):
        for form in p["formulas"]:
            name_link = f"[{form['name']}]({BASE_URL}{form['url']})" if form.get("url") else form["name"]
            content += f"| **{name_link}** | {form['description']} |\n"
    else:
        content += "| - | *ไม่มีตำรับยาแนะนำระบุไว้* |\n"
        
    if p.get("formula_modifications"):
        content += f"\n#### การปรับปรุงตำรับยาเฉพาะบุคคล (How Practitioners Personalise These Formulas)\n{p['formula_modifications']}\n"
        
    content += """
### สมุนไพรเดี่ยวที่แนะนำ (Recommended Herbs)
| ชื่อสมุนไพร (Herb Name) | คำอธิบายสมุนไพร (Description) |
| :--- | :--- |
"""
    if p.get("herbs"):
        for herb in p["herbs"]:
            name_link = f"[{herb['name']}]({BASE_URL}{herb['url']})" if herb.get("url") else herb["name"]
            content += f"| **{name_link}** | {herb['description']} |\n"
    else:
        content += "| - | *ไม่มีสมุนไพรแนะนำระบุไว้* |\n"
        
    content += """
### จุดฝังเข็มที่แนะนำ (Recommended Acupuncture Points)
| รหัสจุด (Point Code) | ชื่อจุดฝังเข็ม (Point Name) | คำอธิบายจุดฝังเข็ม (Description) |
| :--- | :--- | :--- |
"""
    if p.get("acupoints"):
        for acu in p["acupoints"]:
            name_link = f"[{acu['name']}]({BASE_URL}{acu['url']})" if acu.get("url") else acu["name"]
            content += f"| **{acu['code']}** | {name_link} | {acu['description']} |\n"
    else:
        content += "| - | - | *ไม่มีจุดฝังเข็มแนะนำระบุไว้* |\n"
        
    content += "\n---\n\n## การวินิจฉัยแยกโรค (Differential Diagnosis)\n"
    if p.get("differential_diagnosis"):
        for d in p["differential_diagnosis"]:
            content += f"### เทียบกับ {d['target_pattern_name']}\n{d['explanation']}\n\n"
    else:
        content += "*ไม่มีระบุวินิจฉัยแยกโรค.*\n\n"
        
    content += "---\n\n## เอกสารอ้างอิง (References)\n"
    if p.get("classical_texts"):
        content += "### คัมภีร์ดั้งเดิม (Classical Texts)\n"
        for t in p["classical_texts"]:
            content += f"#### {t['source']}\n{t['translation']}\n\n"
            
    if p.get("research"):
        content += "### งานวิจัยทางวิทยาศาสตร์สมัยใหม่ (Modern Scientific Research)\n"
        for idx, r in enumerate(p["research"], 1):
            url_str = f" ([ลิงก์]({r['url']}))" if r.get("url") else ""
            content += f"{idx}. **{r['title']}**{url_str}\n"
            if r.get("periodical"):
                content += f"   *วารสารวิชาการ: {r['periodical']}*\n"
            content += f"   {r['description']}\n\n"
            
    content += f"\n---\n*ลิงก์ต้นฉบับภาษาอังกฤษ: [{BASE_URL}{p['url']}]({BASE_URL}{p['url']})*"
    
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)

# Helper to process single pattern translation task
def translate_task(p, idx, total):
    print(f"[{idx}/{total}] Translating: {p['name']} ...")
    try:
        return translate_pattern(p)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error translating: {p['name']}: {e}")
        return p

def main():
    start_time = time.time()
    
    if not os.path.exists(INPUT_JSON_PATH):
        print(f"English patterns JSON file not found at {INPUT_JSON_PATH}.")
        return
        
    with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
        patterns_details = json.load(f)
        
    total_patterns = len(patterns_details)
    print(f"Loaded {total_patterns} patterns.")
    
    # Check if this is a dry run
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    if dry_run:
        patterns_details = patterns_details[:5]
        total_patterns = len(patterns_details)
        print(f"DRY RUN ENABLED: Limiting translation to {total_patterns} patterns.")
        
    # Load translation cache from existing Thai JSON file (if available)
    translated_cache = {}
    cache_json_path = OUTPUT_JSON_PATH
    if dry_run:
        cache_json_path = os.path.join(WORKSPACE_DIR, "tcm_patterns_details_th_dryrun.json")
        
    if os.path.exists(cache_json_path):
        try:
            with open(cache_json_path, "r", encoding="utf-8") as f_th:
                cached_data = json.load(f_th)
                for item in cached_data:
                    desc = item.get("description", "")
                    if is_thai(desc):
                        translated_cache[item["url"]] = item
            print(f"Loaded {len(translated_cache)} translated patterns from cache.")
        except Exception as e:
            print(f"Could not load cache: {e}")
            
    # Initialize Thai DB
    conn = init_sqlite_db()
    
    translated_results = []
    
    print("Translating patterns sequentially with resume support...")
    for idx, p in enumerate(patterns_details, 1):
        url = p["url"]
        
        if url in translated_cache:
            translated_p = translated_cache[url]
            print(f"[{idx}/{total_patterns}] Re-using cached: {p['name']}")
        else:
            translated_p = translate_task(p, idx, total_patterns)
            # Polite delay to prevent rate limits (0.8s to 1.3s)
            time.sleep(0.8 + random.random() * 0.5)
            
        translated_results.append(translated_p)
        
        # Write to SQLite
        insert_pattern_into_db(conn, translated_p)
        
        # Write to Markdown
        generate_markdown_file(translated_p)
        
        # Write to JSON to preserve progress
        with open(cache_json_path, "w", encoding="utf-8") as out_f:
            json.dump(translated_results, out_f, indent=2, ensure_ascii=False)
                
    conn.close()
    
    elapsed = time.time() - start_time
    print("\n==================================================")
    print("THAI TRANSLATION OF PATTERNS COMPLETE!")
    print(f"Processed: {len(translated_results)} patterns.")
    print(f"Saved Thai SQLite DB to: {SQLITE_DB_PATH}")
    print(f"Saved Thai JSON Data to: {cache_json_path}")
    print(f"Generated Thai Markdown files in: {MARKDOWN_DIR}")
    print(f"Total time elapsed: {elapsed:.2f} seconds.")
    print("==================================================")

if __name__ == "__main__":
    main()
