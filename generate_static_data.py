import sqlite3
import json
import os
import sys

def get_db(lang='en'):
    db_file = 'tcm_formulas_th.db' if lang == 'th' else 'tcm_formulas.db'
    if not os.path.exists(db_file):
        print(f"Error: Database file {db_file} not found.")
        sys.exit(1)
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    
    # Attach other databases
    herbs_db = 'tcm_herbs.db'
    conditions_db = 'tcm_conditions_th.db' if lang == 'th' else 'tcm_conditions.db'
    patterns_db = 'tcm_patterns_th.db' if lang == 'th' else 'tcm_patterns.db'
    
    conn.execute(f"ATTACH DATABASE '{herbs_db}' AS herbs_db;")
    conn.execute(f"ATTACH DATABASE '{conditions_db}' AS conditions_db;")
    conn.execute(f"ATTACH DATABASE '{patterns_db}' AS patterns_db;")
    return conn

def load_filters(lang='en'):
    conn = get_db(lang)
    
    # Formulas
    formula_categories = set()
    formula_focus = set()
    formula_organs = set()
    formula_conditions = set()
    
    cursor = conn.cursor()
    cursor.execute("SELECT categories, therapeutic_focus, target_organs, conditions FROM formulas")
    for r in cursor.fetchall():
        for col_set, val in [(formula_categories, r[0]), (formula_focus, r[1]), (formula_organs, r[2]), (formula_conditions, r[3])]:
            if val:
                try:
                    lst = json.loads(val)
                    if isinstance(lst, list):
                        col_set.update(lst)
                    else:
                        col_set.add(lst)
                except Exception:
                    col_set.add(val)
                    
    cursor.execute("SELECT DISTINCT temperature FROM formulas WHERE temperature IS NOT NULL AND temperature != ''")
    formula_temps = [r[0] for r in cursor.fetchall()]
    
    cursor.execute("SELECT DISTINCT preparation_form FROM formulas WHERE preparation_form IS NOT NULL AND preparation_form != ''")
    formula_preps = [r[0] for r in cursor.fetchall()]
    
    cursor.execute("SELECT DISTINCT herb_name FROM formula_ingredients WHERE herb_name IS NOT NULL AND herb_name != ''")
    formula_herbs = [r[0] for r in cursor.fetchall()]
    
    # Herbs
    herb_categories = set()
    herb_tastes = set()
    herb_organs = set()
    
    cursor.execute("SELECT categories, tastes, organ_affinities FROM herbs_db.herbs")
    for r in cursor.fetchall():
        for col_set, val in [(herb_categories, r[0]), (herb_tastes, r[1]), (herb_organs, r[2])]:
            if val:
                try:
                    lst = json.loads(val)
                    if isinstance(lst, list):
                        col_set.update(lst)
                    else:
                        col_set.add(lst)
                except Exception:
                    col_set.add(val)
                    
    cursor.execute("SELECT DISTINCT temperature FROM herbs_db.herbs WHERE temperature IS NOT NULL AND temperature != ''")
    herb_temps = [r[0] for r in cursor.fetchall()]
    
    cursor.execute("SELECT DISTINCT toxicity FROM herbs_db.herbs WHERE toxicity IS NOT NULL AND toxicity != ''")
    herb_toxicities = [r[0] for r in cursor.fetchall()]
    
    # Conditions
    cond_categories = set()
    cond_regions = set()
    
    cursor.execute("SELECT categories, body_regions FROM conditions_db.conditions")
    for r in cursor.fetchall():
        for col_set, val in [(cond_categories, r[0]), (cond_regions, r[1])]:
            if val:
                try:
                    lst = json.loads(val)
                    if isinstance(lst, list):
                        col_set.update(lst)
                    else:
                        col_set.add(lst)
                except Exception:
                    col_set.add(val)
                    
    # Patterns
    pat_organs = set()
    pat_substances = set()
    pat_factors = set()
    
    cursor.execute("SELECT organs, by_vital_substance, by_pathogenic_factor FROM patterns_db.patterns")
    for r in cursor.fetchall():
        for col_set, val in [(pat_organs, r[0]), (pat_substances, r[1]), (pat_factors, r[2])]:
            if val:
                try:
                    lst = json.loads(val)
                    if isinstance(lst, list):
                        col_set.update(lst)
                    else:
                        col_set.add(lst)
                except Exception:
                    col_set.add(val)
                    
    cursor.execute("SELECT DISTINCT nature FROM patterns_db.patterns WHERE nature IS NOT NULL AND nature != ''")
    pat_natures = [r[0] for r in cursor.fetchall()]
    
    conn.close()
    
    return {
        "formulas": {
            "categories": sorted(list(formula_categories)),
            "therapeuticFocus": sorted(list(formula_focus)),
            "targetOrgans": sorted(list(formula_organs)),
            "temperature": sorted(formula_temps),
            "preparationForm": sorted(formula_preps),
            "conditions": sorted(list(formula_conditions)),
            "herbs": sorted(formula_herbs)
        },
        "herbs": {
            "categories": sorted(list(herb_categories)),
            "temperature": sorted(herb_temps),
            "tastes": sorted(list(herb_tastes)),
            "organAffinities": sorted(list(herb_organs)),
            "toxicity": sorted(herb_toxicities)
        },
        "conditions": {
            "categories": sorted(list(cond_categories)),
            "bodyRegions": sorted(list(cond_regions))
        },
        "patterns": {
            "nature": sorted(pat_natures),
            "organs": sorted(list(pat_organs)),
            "byVitalSubstance": sorted(list(pat_substances)),
            "byPathogenicFactor": sorted(list(pat_factors))
        }
    }

def generate_static_data():
    os.makedirs('api/details/formula/en', exist_ok=True)
    os.makedirs('api/details/formula/th', exist_ok=True)
    os.makedirs('api/details/herb/en', exist_ok=True)
    os.makedirs('api/details/herb/th', exist_ok=True)
    os.makedirs('api/details/condition/en', exist_ok=True)
    os.makedirs('api/details/condition/th', exist_ok=True)
    os.makedirs('api/details/pattern/en', exist_ok=True)
    os.makedirs('api/details/pattern/th', exist_ok=True)
    
    for lang in ['en', 'th']:
        print(f"Generating catalogs and filters for language: {lang}...")
        filters = load_filters(lang)
        with open(f'api/filters_{lang}.json', 'w', encoding='utf-8') as f:
            json.dump(filters, f, ensure_ascii=False, indent=2)
            
        conn = get_db(lang)
        cursor = conn.cursor()
        
        # 1. Formulas catalog and details
        print(f"[{lang}] Processing formulas...")
        cursor.execute("SELECT * FROM formulas")
        formulas = [dict(r) for r in cursor.fetchall()]
        
        formulas_catalog = []
        for formula in formulas:
            f_id = formula['id']
            f_name = formula['name']
            
            # Get ingredients for catalog
            cursor.execute("SELECT herb_name, english_name, role, dosage FROM formula_ingredients WHERE formula_id = ?", (f_id,))
            ingredients_list = [dict(r) for r in cursor.fetchall()]
            
            # Add to catalog
            catalog_item = {
                "id": f_id,
                "name": formula.get("name"),
                "chinese_name": formula.get("chinese_name"),
                "english_name": formula.get("english_name"),
                "thai_name": formula.get("thai_name"),
                "url": formula.get("url"),
                "categories": formula.get("categories"),
                "temperature": formula.get("temperature"),
                "summary": formula.get("summary"),
                "tcm_actions": formula.get("tcm_actions"),
                "therapeutic_focus": formula.get("therapeutic_focus"),
                "target_organs": formula.get("target_organs"),
                "preparation_form": formula.get("preparation_form"),
                "conditions": formula.get("conditions"),
                "patterns": formula.get("patterns"),
                "ingredients_list": ingredients_list
            }
            formulas_catalog.append(catalog_item)
            
            # Fetch full details
            details = dict(formula)
            details['ingredients'] = ingredients_list
            
            cursor.execute("SELECT * FROM formula_research WHERE formula_id = ?", (f_id,))
            details['research'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT pattern_id, name FROM patterns_db.pattern_formulas WHERE name = ?", (f_name,))
            details['associated_patterns'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT condition_id, pattern_name, formula_name FROM conditions_db.condition_patterns JOIN conditions_db.condition_pattern_formulas ON condition_patterns.id = condition_pattern_formulas.pattern_id WHERE formula_name = ?", (f_name,))
            details['associated_conditions'] = [dict(r) for r in cursor.fetchall()]
            
            # Write detail file
            with open(f'api/details/formula/{lang}/{f_id}.json', 'w', encoding='utf-8') as f:
                json.dump(details, f, ensure_ascii=False, indent=2)
                
        # 2. Herbs catalog and details
        print(f"[{lang}] Processing herbs...")
        cursor.execute("SELECT * FROM herbs_db.herbs")
        herbs = [dict(r) for r in cursor.fetchall()]
        
        herbs_catalog = []
        for herb in herbs:
            h_id = herb['id']
            h_name = herb['name']
            
            catalog_item = {
                "id": h_id,
                "name": herb.get("name"),
                "chinese_name": herb.get("chinese_name"),
                "scientific_name": herb.get("scientific_name"),
                "categories": herb.get("categories"),
                "temperature": herb.get("temperature"),
                "summary": herb.get("summary"),
                "tastes": herb.get("tastes"),
                "organ_affinities": herb.get("organ_affinities"),
                "toxicity": herb.get("toxicity"),
                "standard_dosage": herb.get("standard_dosage")
            }
            herbs_catalog.append(catalog_item)
            
            # Full details
            details = dict(herb)
            
            cursor.execute("SELECT * FROM herbs_db.herb_patterns WHERE herb_id = ?", (h_id,))
            details['patterns'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM herbs_db.herb_conditions WHERE herb_id = ?", (h_id,))
            details['conditions'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM herbs_db.herb_processed_forms WHERE herb_id = ?", (h_id,))
            details['processed_forms'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM herbs_db.herb_pairs WHERE herb_id = ?", (h_id,))
            details['pairs'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM herbs_db.herb_research WHERE herb_id = ?", (h_id,))
            details['research'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM herbs_db.herb_classical_texts WHERE herb_id = ?", (h_id,))
            details['classical_texts'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT DISTINCT formulas.id, formulas.name, formulas.english_name FROM formulas JOIN formula_ingredients ON formulas.id = formula_ingredients.formula_id WHERE herb_name = ?", (h_name,))
            details['containing_formulas'] = [dict(r) for r in cursor.fetchall()]
            
            with open(f'api/details/herb/{lang}/{h_id}.json', 'w', encoding='utf-8') as f:
                json.dump(details, f, ensure_ascii=False, indent=2)
                
        # 3. Conditions catalog and details
        print(f"[{lang}] Processing conditions...")
        cursor.execute("SELECT * FROM conditions_db.conditions")
        conditions = [dict(r) for r in cursor.fetchall()]
        
        conditions_catalog = []
        for cond in conditions:
            c_id = cond['id']
            
            catalog_item = {
                "id": c_id,
                "name": cond.get("name"),
                "chinese_name": cond.get("chinese_name"),
                "pinyin": cond.get("pinyin"),
                "categories": cond.get("categories"),
                "body_regions": cond.get("body_regions"),
                "preview_text": cond.get("preview_text"),
                "synonyms": cond.get("synonyms")
            }
            conditions_catalog.append(catalog_item)
            
            # Details
            details = dict(cond)
            
            cursor.execute("SELECT * FROM conditions_db.condition_patterns WHERE condition_id = ?", (c_id,))
            patterns = [dict(r) for r in cursor.fetchall()]
            for p in patterns:
                p_id = p['id']
                cursor.execute("SELECT * FROM conditions_db.condition_pattern_formulas WHERE pattern_id = ?", (p_id,))
                p['formulas'] = [dict(r) for r in cursor.fetchall()]
                
                cursor.execute("SELECT * FROM conditions_db.condition_pattern_herbs WHERE pattern_id = ?", (p_id,))
                p['herbs'] = [dict(r) for r in cursor.fetchall()]
                
                cursor.execute("SELECT * FROM conditions_db.condition_pattern_acupoints WHERE pattern_id = ?", (p_id,))
                p['acupoints'] = [dict(r) for r in cursor.fetchall()]
                
            details['patterns'] = patterns
            
            cursor.execute("SELECT * FROM conditions_db.condition_faqs WHERE condition_id = ?", (c_id,))
            details['faqs'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM conditions_db.condition_research WHERE condition_id = ?", (c_id,))
            details['research'] = [dict(r) for r in cursor.fetchall()]
            
            with open(f'api/details/condition/{lang}/{c_id}.json', 'w', encoding='utf-8') as f:
                json.dump(details, f, ensure_ascii=False, indent=2)
                
        # 4. Patterns catalog and details
        print(f"[{lang}] Processing patterns...")
        cursor.execute("SELECT * FROM patterns_db.patterns")
        patterns = [dict(r) for r in cursor.fetchall()]
        
        patterns_catalog = []
        for pat in patterns:
            p_id = pat['id']
            p_name = pat['name']
            
            catalog_item = {
                "id": p_id,
                "name": pat.get("name"),
                "chinese_name": pat.get("chinese_name"),
                "pinyin": pat.get("pinyin"),
                "nature": pat.get("nature"),
                "organs": pat.get("organs"),
                "by_vital_substance": pat.get("by_vital_substance"),
                "by_pathogenic_factor": pat.get("by_pathogenic_factor"),
                "description": pat.get("description"),
                "key_signs": pat.get("key_signs")
            }
            patterns_catalog.append(catalog_item)
            
            # Details
            details = dict(pat)
            
            cursor.execute("SELECT * FROM patterns_db.pattern_formulas WHERE pattern_id = ?", (p_id,))
            details['formulas'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM patterns_db.pattern_herbs WHERE pattern_id = ?", (p_id,))
            details['herbs'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM patterns_db.pattern_acupoints WHERE pattern_id = ?", (p_id,))
            details['acupoints'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM patterns_db.pattern_classical_texts WHERE pattern_id = ?", (p_id,))
            details['classical_texts'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM patterns_db.pattern_faqs WHERE pattern_id = ?", (p_id,))
            details['faqs'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM patterns_db.pattern_research WHERE pattern_id = ?", (p_id,))
            details['research'] = [dict(r) for r in cursor.fetchall()]
            
            cursor.execute("SELECT DISTINCT conditions.id, conditions.name FROM conditions_db.conditions JOIN conditions_db.condition_patterns ON conditions.id = condition_patterns.condition_id WHERE pattern_name = ?", (p_name,))
            details['associated_conditions'] = [dict(r) for r in cursor.fetchall()]
            
            with open(f'api/details/pattern/{lang}/{p_id}.json', 'w', encoding='utf-8') as f:
                json.dump(details, f, ensure_ascii=False, indent=2)
                
        # Write catalog JSON
        catalog = {
            "formulas": formulas_catalog,
            "herbs": herbs_catalog,
            "conditions": conditions_catalog,
            "patterns": patterns_catalog
        }
        with open(f'api/catalog_{lang}.json', 'w', encoding='utf-8') as f:
            json.dump(catalog, f, ensure_ascii=False) # minified for load speed
            
        conn.close()
        print(f"[{lang}] Done!")

if __name__ == '__main__':
    generate_static_data()
