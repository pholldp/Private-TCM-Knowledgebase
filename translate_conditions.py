import os
import json
import sqlite3
import time
from deep_translator import GoogleTranslator
from concurrent.futures import ThreadPoolExecutor, as_completed

WORKSPACE_DIR = "/Users/phol/Desktop/Antigravity Project/TCM database"
INPUT_JSON_PATH = os.path.join(WORKSPACE_DIR, "tcm_conditions_details.json")
OUTPUT_JSON_PATH = os.path.join(WORKSPACE_DIR, "tcm_conditions_details_th.json")
SQLITE_DB_PATH = os.path.join(WORKSPACE_DIR, "tcm_conditions_th.db")
MARKDOWN_DIR = os.path.join(WORKSPACE_DIR, "conditions_th")

os.makedirs(MARKDOWN_DIR, exist_ok=True)

# Helper to chunk list of strings by character count to avoid Google Translate URL limits
def chunk_list_by_chars(strings, max_chars=4000):
    chunks = []
    current_chunk = []
    current_len = 0
    for s in strings:
        s_clean = s.strip() if s else ""
        if not s_clean:
            # Keep index mapping intact with empty placeholder if necessary
            s_clean = " "
        if len(s_clean) + current_len > max_chars:
            chunks.append(current_chunk)
            current_chunk = [s_clean]
            current_len = len(s_clean)
        else:
            current_chunk.append(s_clean)
            current_len += len(s_clean)
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

# Batch translator with retry logic
def translate_batch_with_retry(translator, batch, max_retries=3):
    cleaned_batch = [s.replace("&", "and") for s in batch]
    for attempt in range(max_retries):
        try:
            return translator.translate_batch(cleaned_batch)
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Translation batch failed, falling back to individual translation. Error: {e}")
                results = []
                for s in cleaned_batch:
                    for i_attempt in range(max_retries):
                        try:
                            results.append(translator.translate(s))
                            break
                        except Exception as ie:
                            if i_attempt == max_retries - 1:
                                print(f"Individual translation failed for '{s}': {ie}")
                                results.append(s)
                            time.sleep(0.5)
                return results
            time.sleep(1 + attempt * 2)


def init_sqlite_db():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    
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
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS condition_faqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id INTEGER,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            FOREIGN KEY(condition_id) REFERENCES conditions(id) ON DELETE CASCADE
        )
    """)
    
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

def insert_condition_into_db(conn, c):
    cursor = conn.cursor()
    try:
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
        
        for faq in c["faqs"]:
            cursor.execute("""
                INSERT INTO condition_faqs (condition_id, question, answer)
                VALUES (?, ?, ?)
            """, (cond_id, faq["question"], faq["answer"]))
            
        for res in c["research"]:
            cursor.execute("""
                INSERT INTO condition_research (condition_id, title, description, url, periodical)
                VALUES (?, ?, ?, ?, ?)
            """, (cond_id, res["title"], res["description"], res["url"], res["periodical"]))
            
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
            
            for form in pat["formulas"]:
                cursor.execute("""
                    INSERT INTO condition_pattern_formulas (pattern_id, formula_name, formula_url, translation, properties, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (pattern_id, form["name"], form["url"], form["translation"], form["properties"], form["description"]))
                
            for herb in pat["herbs"]:
                cursor.execute("""
                    INSERT INTO condition_pattern_herbs (pattern_id, herb_name, herb_url, translation, properties, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (pattern_id, herb["name"], herb["url"], herb["translation"], herb["properties"], herb["description"]))
                
            for ac in pat["acupoints"]:
                cursor.execute("""
                    INSERT INTO condition_pattern_acupoints (pattern_id, acupoint_code, acupoint_name, acupoint_url, translation, properties, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (pattern_id, ac["code"], ac["name"], ac["url"], ac["translation"], ac["properties"], ac["description"]))
                
        conn.commit()
    except Exception as e:
        print(f"Database insertion error for {c['name']}: {e}")
        conn.rollback()

def generate_markdown_file_th(c):
    safe_name = c["url"].split("/")[-1]
    file_path = os.path.join(MARKDOWN_DIR, f"{safe_name}.md")
    
    categories = ", ".join(c["categories"])
    synonyms = ", ".join(c["synonyms"])
    body_regions = ", ".join(c["body_regions"])
    
    content = f"""# {c["name"]} ({c["chinese_name"]})
**คำอ่านพินอิน**: {c["pinyin"]} | **ประเภท**: {c["kind"]} | **หมวดหมู่**: {categories}  
**ชื่อเรียกอื่นๆ**: {synonyms} | **บริเวณร่างกาย**: {body_regions}

---

## บทสรุปย่อ (Preview Summary)
{c["preview_text"]}

---

"""

    if c["conventional_description"] or c["conventional_treatments"] or c["conventional_limitations"]:
        content += "## มุมมองทางการแพทย์แผนปัจจุบัน (Conventional Medicine View)\n"
        if c["conventional_description"]:
            content += f"### คำอธิบาย (Description)\n{c['conventional_description']}\n\n"
        if c["conventional_treatments"]:
            content += f"### การรักษาหลัก (Treatments)\n{c['conventional_treatments']}\n\n"
        if c["conventional_limitations"]:
            content += f"### ข้อจำกัดของการแพทย์แผนปัจจุบัน (Where Conventional Treatment Falls Short)\n{c['conventional_limitations']}\n\n"
        content += "---\n\n"

    if c["tcm_understanding"] or c["tcm_diagnosis"] or c["classical_quote"]:
        content += "## มุมมองทางการแพทย์แผนจีน (Traditional Chinese Medicine View)\n"
        if c["tcm_understanding"]:
            content += f"### ความเข้าใจเกี่ยวกับการแพทย์แผนจีน (TCM Understanding)\n{c['tcm_understanding']}\n\n"
        if c["tcm_diagnosis"]:
            content += f"### การวินิจฉัยโดยแพทย์แผนจีน (Practitioner Diagnosis)\n{c['tcm_diagnosis']}\n\n"
        if c["classical_quote"]:
            content += f"### การอ้างอิงจากตำราแพทย์คลาสสิก (Classical Reference)\n"
            content += f"> **ต้นฉบับ**: {c['classical_quote']}\n"
            content += f"> \n"
            content += f"> **คำแปลภาษาอังกฤษ**: {c['classical_translation']}\n"
            content += f"> \n"
            content += f"> — แหล่งที่มา: *{c['classical_source']}*\n\n"
        content += "---\n\n"

    content += "## กลุ่มอาการการแพทย์แผนจีนและการรักษา (TCM Patterns and Treatment)\n\n"
    for pat in c["patterns_details"]:
        common_tag = " [พบบ่อยมาก]" if pat["is_common"] else ""
        content += f"### {pat['pattern_name']}{common_tag}\n"
        if pat["pattern_slug"]:
            content += f"*ลิงก์รายละเอียดกลุ่มอาการ: [หน้าหลักข้อมูลกลุ่มอาการ (ภาษาอังกฤษ)](https://www.meandqi.com/knowledge-base/patterns/{pat['pattern_slug']})*\n\n"
            
        symptoms_str = ", ".join(pat["symptoms"])
        content += f"- **สัญญาณและอาการทางคลินิก (Clinical Signs)**: {symptoms_str}\n"
        if pat["worse_with"]:
            content += f"- **สิ่งกระตุ้นให้อาการแย่ลง (Worse with)**: {pat['worse_with']}\n"
        if pat["better_with"]:
            content += f"- **สิ่งช่วยให้อาการดีขึ้น (Better with)**: {pat['better_with']}\n"
        if pat["why_this_happens"]:
            content += f"- **กลไกการเกิดอาการ (Why this happens)**:\n  {pat['why_this_happens']}\n"
        if pat["tongue_and_pulse"]:
            content += f"- **ลักษณะลิ้นและชีพจร (Tongue & Pulse)**: {pat['tongue_and_pulse']}\n"
        if pat["why_triggers_reliefs_work"]:
            content += f"- **อธิบายสิ่งกระตุ้นและการทุเลาอาการ (Triggers & Relief Explanation)**: {pat['why_triggers_reliefs_work']}\n"
        if pat["diet_and_lifestyle"]:
            content += f"- **คำแนะนำด้านอาหารและการดำเนินชีวิต (Diet & Lifestyle)**: {pat['diet_and_lifestyle']}\n"
            
        content += "\n"
        
        # Formulas table
        if pat["formulas"]:
            content += "#### ตำรับยาที่แนะนำ (Recommended Formulas)\n"
            content += "| ชื่อตำรับยา | คำแปลชื่อ | สรรพคุณและลักษณะทางเภสัชวิทยา | คำอธิบาย |\n"
            content += "| :--- | :--- | :--- | :--- |\n"
            for form in pat["formulas"]:
                name_link = f"[{form['name']}](https://www.meandqi.com{form['url']})" if form['url'] else form['name']
                content += f"| **{name_link}** | {form['translation']} | {form['properties']} | {form['description']} |\n"
            content += "\n"
            
        # Herbs table
        if pat["herbs"]:
            content += "#### สมุนไพรที่แนะนำ (Recommended Herbs)\n"
            content += "| ชื่อสมุนไพร | คำแปลชื่อ | ลักษณะรสและอุณหภูมิ | คำอธิบาย |\n"
            content += "| :--- | :--- | :--- | :--- |\n"
            for herb in pat["herbs"]:
                name_link = f"[{herb['name']}](https://www.meandqi.com{herb['url']})" if herb['url'] else herb['name']
                content += f"| **{name_link}** | {herb['translation']} | {herb['properties']} | {herb['description']} |\n"
            content += "\n"
            
        # Acupoints table
        if pat["acupoints"]:
            content += "#### จุดฝังเข็มที่แนะนำ (Recommended Acupuncture Points)\n"
            content += "| รหัสจุด | ชื่อจุดฝังเข็ม | คำแปลชื่อ | สรรพคุณ | คำอธิบาย |\n"
            content += "| :--- | :--- | :--- | :--- | :--- |\n"
            for ac in pat["acupoints"]:
                name_link = f"[{ac['name']}](https://www.meandqi.com{ac['url']})" if ac['url'] else ac['name']
                content += f"| **{ac['code']}** | {name_link} | {ac['translation']} | {ac['properties']} | {ac['description']} |\n"
            content += "\n"
            
        content += "---\n\n"

    if c["faqs"]:
        content += "## คำถามที่พบบ่อย (Frequently Asked Questions)\n"
        for faq in c["faqs"]:
            content += f"### {faq['question']}\n{faq['answer']}\n\n"
        content += "---\n\n"

    if c["research"]:
        content += "## การวิจัยทางวิทยาศาสตร์สมัยใหม่ (Modern Scientific Research)\n"
        for idx, res in enumerate(c["research"], 1):
            url_str = f" ([ลิงก์]({res['url']}))" if res['url'] else ""
            content += f"{idx}. **{res['title']}**{url_str}\n"
            if res['periodical']:
                content += f"   *วารสารวิชาการ: {res['periodical']}*\n"
            content += f"   {res['description']}\n\n"
        content += "---\n\n"
        
    content += f"*ลิงก์ข้อมูลต้นฉบับภาษาอังกฤษ: [Me & Qi Original Page](https://www.meandqi.com{c['url']})*"
    
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(content)

def main():
    start_time = time.time()
    
    if not os.path.exists(INPUT_JSON_PATH):
        print(f"Source JSON file not found at {INPUT_JSON_PATH}. Run the main conditions scraper first.")
        return
        
    print("Loading source database JSON...")
    with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
        conditions = json.load(f)
        
    print(f"Loaded {len(conditions)} conditions from JSON.")
    
    # Check if this is a dry run (controlled by DRY_RUN env var)
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    if dry_run:
        conditions = conditions[:5]
        print(f"DRY RUN ENABLED: Translating first {len(conditions)} conditions.")
        
    translator = GoogleTranslator(source="en", target="th")
    
    # 1. Translate unique categories
    print("Translating unique categories...")
    unique_cats = set()
    for c in conditions:
        unique_cats.update(c["categories"])
    unique_cats = sorted(list(unique_cats))
    
    cat_mapping = {}
    cat_chunks = chunk_list_by_chars(unique_cats)
    for idx, chunk in enumerate(cat_chunks, 1):
        print(f"Translating category chunk {idx}/{len(cat_chunks)}...")
        translated_chunk = translate_batch_with_retry(translator, chunk)
        for orig, trans in zip(chunk, translated_chunk):
            cat_mapping[orig] = trans
            
    # 2. Extract names and previews for translation
    print("Extracting names and previews for translation...")
    urls = []
    names = []
    previews = []
    for c in conditions:
        urls.append(c["url"])
        names.append(c["name"])
        previews.append(c["preview_text"])
        
    # Translate names in chunks
    name_mapping = {}
    name_chunks = chunk_list_by_chars(names)
    for idx, chunk in enumerate(name_chunks, 1):
        print(f"Translating name chunk {idx}/{len(name_chunks)}...")
        translated_chunk = translate_batch_with_retry(translator, chunk)
        for orig, trans in zip(chunk, translated_chunk):
            name_mapping[orig] = trans
            
    # Translate previews in chunks
    preview_mapping = {}
    preview_chunks = chunk_list_by_chars(previews)
    for idx, chunk in enumerate(preview_chunks, 1):
        print(f"Translating preview chunk {idx}/{len(preview_chunks)}...")
        translated_chunk = translate_batch_with_retry(translator, chunk)
        for orig, trans in zip(chunk, translated_chunk):
            preview_mapping[orig] = trans

    # 3. Rebuild translated data structure and write files
    print("Rebuilding translated database and generating files...")
    conn = init_sqlite_db()
    
    scraped_results_th = []
    
    for idx, c in enumerate(conditions, 1):
        # Apply translation
        translated_name = name_mapping.get(c["name"], c["name"])
        translated_preview = preview_mapping.get(c["preview_text"], c["preview_text"])
        translated_cats = [cat_mapping.get(cat, cat) for cat in c["categories"]]
        
        c_th = c.copy()
        c_th["name"] = translated_name
        c_th["preview_text"] = translated_preview
        c_th["categories"] = translated_cats
        
        scraped_results_th.append(c_th)
        
        # Save to SQLite
        insert_condition_into_db(conn, c_th)
        
        # Generate Thai Markdown
        generate_markdown_file_th(c_th)
        
        if idx % 100 == 0 or idx == len(conditions):
            print(f"Processed {idx}/{len(conditions)} translated conditions...")
            
    conn.close()
    
    # Save JSON file
    out_json_path = OUTPUT_JSON_PATH
    if dry_run:
        out_json_path = os.path.join(WORKSPACE_DIR, "tcm_conditions_details_th_dryrun.json")
        
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(scraped_results_th, f, indent=2, ensure_ascii=False)
        
    elapsed = time.time() - start_time
    print("\n==================================================")
    print("TRANSLATION COMPLETE!")
    print(f"Translated: {len(scraped_results_th)} conditions.")
    print(f"Saved SQLite DB to: {SQLITE_DB_PATH}")
    print(f"Saved JSON Data to: {out_json_path}")
    print(f"Generated Thai Markdown files in: {MARKDOWN_DIR}")
    print(f"Total time elapsed: {elapsed:.2f} seconds.")
    print("==================================================")

if __name__ == "__main__":
    main()
