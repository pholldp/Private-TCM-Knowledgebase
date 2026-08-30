import sqlite3
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import sys
import os

DB_FILE = 'tcm_formulas.db'
DB_FILE_TH = 'tcm_formulas_th.db'

def get_db(lang='en'):
    db_file = DB_FILE_TH if lang == 'th' else DB_FILE
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    # Attach other databases
    conn.execute("ATTACH DATABASE 'tcm_herbs.db' AS herbs_db;")
    conn.execute("ATTACH DATABASE 'tcm_conditions.db' AS conditions_db;")
    conn.execute("ATTACH DATABASE 'tcm_patterns.db' AS patterns_db;")
    return conn

FILTERS_CACHE = {}

def get_filters(lang='en'):
    if lang not in FILTERS_CACHE:
        FILTERS_CACHE[lang] = load_filters(lang)
    return FILTERS_CACHE[lang]

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


def make_search_condition(search_str, columns):
    if not search_str:
        return "", []
    terms = search_str.strip().split()
    clauses = []
    params = []
    for term in terms:
        term_clause = []
        for col in columns:
            term_clause.append(f"{col} LIKE ?")
            params.append(f"%{term}%")
        clauses.append("(" + " OR ".join(term_clause) + ")")
    return " AND ".join(clauses), params

def query_formulas(params, lang='en'):
    conn = get_db(lang)
    cursor = conn.cursor()
    
    where_clauses = []
    sql_params = []
    
    search = params.get('search')
    if search:
        clause, p = make_search_condition(search, ['name', 'chinese_name', 'english_name', 'summary', 'tcm_actions', 'typical_duration', 'other_names'])
        if clause:
            where_clauses.append(clause)
            sql_params.extend(p)
            
    cats = params.get('categories')
    if cats:
        cat_list = [c.strip() for c in cats.split(',') if c.strip()]
        if cat_list:
            where_clauses.append("(" + " OR ".join(["categories LIKE ?" for _ in cat_list]) + ")")
            sql_params.extend([f'%"{c}"%' for c in cat_list])
            
    focus = params.get('therapeuticFocus')
    if focus:
        focus_list = [f.strip() for f in focus.split(',') if f.strip()]
        if focus_list:
            where_clauses.append("(" + " OR ".join(["therapeutic_focus LIKE ?" for _ in focus_list]) + ")")
            sql_params.extend([f'%"{f}"%' for f in focus_list])
            
    organs = params.get('targetOrgans')
    if organs:
        org_list = [o.strip() for o in organs.split(',') if o.strip()]
        if org_list:
            where_clauses.append("(" + " OR ".join(["target_organs LIKE ?" for _ in org_list]) + ")")
            sql_params.extend([f'%"{o}"%' for o in org_list])
            
    temps = params.get('temperature')
    if temps:
        temp_list = [t.strip() for t in temps.split(',') if t.strip()]
        if temp_list:
            where_clauses.append("(" + " OR ".join(["temperature = ?" for _ in temp_list]) + ")")
            sql_params.extend(temp_list)
            
    preps = params.get('preparationForm')
    if preps:
        prep_list = [p.strip() for p in preps.split(',') if p.strip()]
        if prep_list:
            where_clauses.append("(" + " OR ".join(["preparation_form = ?" for _ in prep_list]) + ")")
            sql_params.extend(prep_list)
            
    conds = params.get('conditions')
    if conds:
        cond_list = [c.strip() for c in conds.split(',') if c.strip()]
        if cond_list:
            where_clauses.append("(" + " OR ".join(["conditions LIKE ?" for _ in cond_list]) + ")")
            sql_params.extend([f'%"{c}"%' for c in cond_list])
            
    herbs = params.get('herbs')
    if herbs:
        herb_list = [h.strip() for h in herbs.split(',') if h.strip()]
        for h in herb_list:
            where_clauses.append("id IN (SELECT formula_id FROM formula_ingredients WHERE herb_name = ?)")
            sql_params.append(h)
            
    where_stmt = ""
    if where_clauses:
        where_stmt = "WHERE " + " AND ".join(where_clauses)
        
    sort = params.get('sort', 'name-asc')
    order_stmt = "ORDER BY name ASC"
    if sort == 'name-desc':
        order_stmt = "ORDER BY name DESC"
    elif sort == 'category':
        order_stmt = "ORDER BY categories ASC, name ASC"
    elif sort == 'relevance' and search:
        order_stmt = f"ORDER BY (CASE WHEN name LIKE ? THEN 0 WHEN name LIKE ? THEN 1 ELSE 2 END) ASC, name ASC"
        search_terms = search.strip().split()
        first_term = search_terms[0] if search_terms else ""
        sql_params.extend([f"{first_term}%", f"%{first_term}%"])
        
    page = int(params.get('page', 1))
    limit = int(params.get('limit', 15))
    offset = (page - 1) * limit
    
    count_query = f"SELECT COUNT(*) FROM formulas {where_stmt}"
    cursor.execute(count_query, sql_params[:len(sql_params) - (2 if sort == 'relevance' and search else 0)])
    total_count = cursor.fetchone()[0]
    
    data_query = f"SELECT * FROM formulas {where_stmt} {order_stmt} LIMIT ? OFFSET ?"
    cursor.execute(data_query, sql_params + [limit, offset])
    rows = cursor.fetchall()
    
    result = []
    for row in rows:
        f_id = row['id']
        cursor.execute("SELECT herb_name, english_name, role, dosage FROM formula_ingredients WHERE formula_id = ?", (f_id,))
        ingredients = [dict(r) for r in cursor.fetchall()]
        item = dict(row)
        item['ingredients_list'] = ingredients
        result.append(item)
        
    conn.close()
    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "results": result
    }

def query_herbs(params, lang='en'):
    conn = get_db(lang)
    cursor = conn.cursor()
    
    where_clauses = []
    sql_params = []
    
    search = params.get('search')
    if search:
        clause, p = make_search_condition(search, ['name', 'chinese_name', 'english_name', 'scientific_name', 'pharmaceutical_name', 'alternative_names', 'summary', 'tcm_actions'])
        if clause:
            where_clauses.append(clause)
            sql_params.extend(p)
            
    cats = params.get('categories')
    if cats:
        cat_list = [c.strip() for c in cats.split(',') if c.strip()]
        if cat_list:
            where_clauses.append("(" + " OR ".join(["categories LIKE ?" for _ in cat_list]) + ")")
            sql_params.extend([f'%"{c}"%' for c in cat_list])
            
    temps = params.get('temperature')
    if temps:
        temp_list = [t.strip() for t in temps.split(',') if t.strip()]
        if temp_list:
            where_clauses.append("(" + " OR ".join(["temperature = ?" for _ in temp_list]) + ")")
            sql_params.extend(temp_list)
            
    tastes = params.get('tastes')
    if tastes:
        taste_list = [t.strip() for t in tastes.split(',') if t.strip()]
        if taste_list:
            where_clauses.append("(" + " OR ".join(["tastes LIKE ?" for _ in taste_list]) + ")")
            sql_params.extend([f'%"{t}"%' for t in taste_list])
            
    organs = params.get('organAffinities')
    if organs:
        org_list = [o.strip() for o in organs.split(',') if o.strip()]
        if org_list:
            where_clauses.append("(" + " OR ".join(["organ_affinities LIKE ?" for _ in org_list]) + ")")
            sql_params.extend([f'%"{o}"%' for o in org_list])
            
    tox = params.get('toxicity')
    if tox:
        tox_list = [t.strip() for t in tox.split(',') if t.strip()]
        if tox_list:
            where_clauses.append("(" + " OR ".join(["toxicity = ?" for _ in tox_list]) + ")")
            sql_params.extend(tox_list)
            
    conds = params.get('conditions')
    if conds:
        cond_list = [c.strip() for c in conds.split(',') if c.strip()]
        for c in cond_list:
            where_clauses.append("id IN (SELECT herb_id FROM herbs_db.herb_conditions WHERE condition_name = ?)")
            sql_params.append(c)
            
    pats = params.get('patterns')
    if pats:
        pat_list = [p.strip() for p in pats.split(',') if p.strip()]
        for p in pat_list:
            where_clauses.append("id IN (SELECT herb_id FROM herbs_db.herb_patterns WHERE pattern_name = ?)")
            sql_params.append(p)
            
    where_stmt = ""
    if where_clauses:
        where_stmt = "WHERE " + " AND ".join(where_clauses)
        
    sort = params.get('sort', 'name-asc')
    order_stmt = "ORDER BY name ASC"
    if sort == 'name-desc':
        order_stmt = "ORDER BY name DESC"
    elif sort == 'category':
        order_stmt = "ORDER BY categories ASC, name ASC"
    elif sort == 'relevance' and search:
        order_stmt = f"ORDER BY (CASE WHEN name LIKE ? THEN 0 WHEN name LIKE ? THEN 1 ELSE 2 END) ASC, name ASC"
        search_terms = search.strip().split()
        first_term = search_terms[0] if search_terms else ""
        sql_params.extend([f"{first_term}%", f"%{first_term}%"])
        
    page = int(params.get('page', 1))
    limit = int(params.get('limit', 15))
    offset = (page - 1) * limit
    
    count_query = f"SELECT COUNT(*) FROM herbs_db.herbs {where_stmt}"
    cursor.execute(count_query, sql_params[:len(sql_params) - (2 if sort == 'relevance' and search else 0)])
    total_count = cursor.fetchone()[0]
    
    data_query = f"SELECT * FROM herbs_db.herbs {where_stmt} {order_stmt} LIMIT ? OFFSET ?"
    cursor.execute(data_query, sql_params + [limit, offset])
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "results": rows
    }

def query_conditions(params, lang='en'):
    conn = get_db(lang)
    cursor = conn.cursor()
    
    where_clauses = []
    sql_params = []
    
    search = params.get('search')
    if search:
        clause, p = make_search_condition(search, ['name', 'chinese_name', 'pinyin', 'preview_text', 'synonyms', 'tcm_understanding', 'tcm_diagnosis'])
        if clause:
            where_clauses.append(clause)
            sql_params.extend(p)
            
    cats = params.get('categories')
    if cats:
        cat_list = [c.strip() for c in cats.split(',') if c.strip()]
        if cat_list:
            where_clauses.append("(" + " OR ".join(["categories LIKE ?" for _ in cat_list]) + ")")
            sql_params.extend([f'%"{c}"%' for c in cat_list])
            
    regions = params.get('bodyRegions')
    if regions:
        region_list = [r.strip() for r in regions.split(',') if r.strip()]
        if region_list:
            where_clauses.append("(" + " OR ".join(["body_regions LIKE ?" for _ in region_list]) + ")")
            sql_params.extend([f'%"{r}"%' for r in region_list])
            
    where_stmt = ""
    if where_clauses:
        where_stmt = "WHERE " + " AND ".join(where_clauses)
        
    sort = params.get('sort', 'name-asc')
    order_stmt = "ORDER BY name ASC"
    if sort == 'name-desc':
        order_stmt = "ORDER BY name DESC"
    elif sort == 'category':
        order_stmt = "ORDER BY categories ASC, name ASC"
    elif sort == 'relevance' and search:
        order_stmt = f"ORDER BY (CASE WHEN name LIKE ? THEN 0 WHEN name LIKE ? THEN 1 ELSE 2 END) ASC, name ASC"
        search_terms = search.strip().split()
        first_term = search_terms[0] if search_terms else ""
        sql_params.extend([f"{first_term}%", f"%{first_term}%"])
        
    page = int(params.get('page', 1))
    limit = int(params.get('limit', 15))
    offset = (page - 1) * limit
    
    count_query = f"SELECT COUNT(*) FROM conditions_db.conditions {where_stmt}"
    cursor.execute(count_query, sql_params[:len(sql_params) - (2 if sort == 'relevance' and search else 0)])
    total_count = cursor.fetchone()[0]
    
    data_query = f"SELECT * FROM conditions_db.conditions {where_stmt} {order_stmt} LIMIT ? OFFSET ?"
    cursor.execute(data_query, sql_params + [limit, offset])
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "results": rows
    }

def query_patterns(params, lang='en'):
    conn = get_db(lang)
    cursor = conn.cursor()
    
    where_clauses = []
    sql_params = []
    
    search = params.get('search')
    if search:
        clause, p = make_search_condition(search, ['name', 'chinese_name', 'pinyin', 'description', 'also_known_as', 'key_signs'])
        if clause:
            where_clauses.append(clause)
            sql_params.extend(p)
            
    natures = params.get('nature')
    if natures:
        nature_list = [n.strip() for n in natures.split(',') if n.strip()]
        if nature_list:
            where_clauses.append("(" + " OR ".join(["nature = ?" for _ in nature_list]) + ")")
            sql_params.extend(nature_list)
            
    organs = params.get('organs')
    if organs:
        org_list = [o.strip() for o in organs.split(',') if o.strip()]
        if org_list:
            where_clauses.append("(" + " OR ".join(["organs LIKE ?" for _ in org_list]) + ")")
            sql_params.extend([f'%"{o}"%' for o in org_list])
            
    substances = params.get('byVitalSubstance')
    if substances:
        sub_list = [s.strip() for s in substances.split(',') if s.strip()]
        if sub_list:
            where_clauses.append("(" + " OR ".join(["by_vital_substance LIKE ?" for _ in sub_list]) + ")")
            sql_params.extend([f'%"{s}"%' for s in sub_list])
            
    factors = params.get('byPathogenicFactor')
    if factors:
        fac_list = [f.strip() for f in factors.split(',') if f.strip()]
        if fac_list:
            where_clauses.append("(" + " OR ".join(["by_pathogenic_factor LIKE ?" for _ in fac_list]) + ")")
            sql_params.extend([f'%"{f}"%' for f in fac_list])
            
    where_stmt = ""
    if where_clauses:
        where_stmt = "WHERE " + " AND ".join(where_clauses)
        
    sort = params.get('sort', 'name-asc')
    order_stmt = "ORDER BY name ASC"
    if sort == 'name-desc':
        order_stmt = "ORDER BY name DESC"
    elif sort == 'relevance' and search:
        order_stmt = f"ORDER BY (CASE WHEN name LIKE ? THEN 0 WHEN name LIKE ? THEN 1 ELSE 2 END) ASC, name ASC"
        search_terms = search.strip().split()
        first_term = search_terms[0] if search_terms else ""
        sql_params.extend([f"{first_term}%", f"%{first_term}%"])
        
    page = int(params.get('page', 1))
    limit = int(params.get('limit', 15))
    offset = (page - 1) * limit
    
    count_query = f"SELECT COUNT(*) FROM patterns_db.patterns {where_stmt}"
    cursor.execute(count_query, sql_params[:len(sql_params) - (2 if sort == 'relevance' and search else 0)])
    total_count = cursor.fetchone()[0]
    
    data_query = f"SELECT * FROM patterns_db.patterns {where_stmt} {order_stmt} LIMIT ? OFFSET ?"
    cursor.execute(data_query, sql_params + [limit, offset])
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "results": rows
    }

def query_details(item_type, key, lang='en'):
    conn = get_db(lang)
    cursor = conn.cursor()
    
    is_id = False
    try:
        val_id = int(key)
        is_id = True
    except ValueError:
        val_name = key
        
    res = {}
    
    if item_type == 'formula':
        if is_id:
            cursor.execute("SELECT * FROM formulas WHERE id = ?", (val_id,))
        else:
            cursor.execute("SELECT * FROM formulas WHERE name = ?", (val_name,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        res = dict(row)
        f_id = row['id']
        f_name = row['name']
        
        cursor.execute("SELECT * FROM formula_ingredients WHERE formula_id = ?", (f_id,))
        res['ingredients'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM formula_research WHERE formula_id = ?", (f_id,))
        res['research'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT pattern_id, name FROM patterns_db.pattern_formulas WHERE name = ?", (f_name,))
        res['associated_patterns'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT condition_id, pattern_name, formula_name FROM conditions_db.condition_patterns JOIN conditions_db.condition_pattern_formulas ON condition_patterns.id = condition_pattern_formulas.pattern_id WHERE formula_name = ?", (f_name,))
        res['associated_conditions'] = [dict(r) for r in cursor.fetchall()]
        
    elif item_type == 'herb':
        if is_id:
            cursor.execute("SELECT * FROM herbs_db.herbs WHERE id = ?", (val_id,))
        else:
            cursor.execute("SELECT * FROM herbs_db.herbs WHERE name = ?", (val_name,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        res = dict(row)
        h_id = row['id']
        h_name = row['name']
        
        cursor.execute("SELECT * FROM herbs_db.herb_patterns WHERE herb_id = ?", (h_id,))
        res['patterns'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM herbs_db.herb_conditions WHERE herb_id = ?", (h_id,))
        res['conditions'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM herbs_db.herb_processed_forms WHERE herb_id = ?", (h_id,))
        res['processed_forms'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM herbs_db.herb_pairs WHERE herb_id = ?", (h_id,))
        res['pairs'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM herbs_db.herb_research WHERE herb_id = ?", (h_id,))
        res['research'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM herbs_db.herb_classical_texts WHERE herb_id = ?", (h_id,))
        res['classical_texts'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT DISTINCT formulas.id, formulas.name, formulas.english_name FROM formulas JOIN formula_ingredients ON formulas.id = formula_ingredients.formula_id WHERE herb_name = ?", (h_name,))
        res['containing_formulas'] = [dict(r) for r in cursor.fetchall()]
        
    elif item_type == 'condition':
        if is_id:
            cursor.execute("SELECT * FROM conditions_db.conditions WHERE id = ?", (val_id,))
        else:
            cursor.execute("SELECT * FROM conditions_db.conditions WHERE name = ?", (val_name,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        res = dict(row)
        c_id = row['id']
        
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
            
        res['patterns'] = patterns
        
        cursor.execute("SELECT * FROM conditions_db.condition_faqs WHERE condition_id = ?", (c_id,))
        res['faqs'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM conditions_db.condition_research WHERE condition_id = ?", (c_id,))
        res['research'] = [dict(r) for r in cursor.fetchall()]
        
    elif item_type == 'pattern':
        if is_id:
            cursor.execute("SELECT * FROM patterns_db.patterns WHERE id = ?", (val_id,))
        else:
            cursor.execute("SELECT * FROM patterns_db.patterns WHERE name = ?", (val_name,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        res = dict(row)
        p_id = row['id']
        p_name = row['name']
        
        cursor.execute("SELECT * FROM patterns_db.pattern_formulas WHERE pattern_id = ?", (p_id,))
        res['formulas'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM patterns_db.pattern_herbs WHERE pattern_id = ?", (p_id,))
        res['herbs'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM patterns_db.pattern_acupoints WHERE pattern_id = ?", (p_id,))
        res['acupoints'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM patterns_db.pattern_classical_texts WHERE pattern_id = ?", (p_id,))
        res['classical_texts'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM patterns_db.pattern_faqs WHERE pattern_id = ?", (p_id,))
        res['faqs'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM patterns_db.pattern_research WHERE pattern_id = ?", (p_id,))
        res['research'] = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT DISTINCT conditions.id, conditions.name FROM conditions_db.conditions JOIN conditions_db.condition_patterns ON conditions.id = condition_patterns.condition_id WHERE pattern_name = ?", (p_name,))
        res['associated_conditions'] = [dict(r) for r in cursor.fetchall()]
        
    conn.close()
    return res

class TCMRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)
        params = {k: v[0] for k, v in query.items()}
        lang = params.get('lang', 'en')
        
        if path == '/api/filters':
            try:
                filters = get_filters(lang)
                self.send_json_response(filters)
            except Exception as e:
                self.send_error_response(500, str(e))
                
        elif path == '/api/formulas':
            try:
                res = query_formulas(params, lang)
                self.send_json_response(res)
            except Exception as e:
                self.send_error_response(500, str(e))
                
        elif path == '/api/herbs':
            try:
                res = query_herbs(params, lang)
                self.send_json_response(res)
            except Exception as e:
                self.send_error_response(500, str(e))
                
        elif path == '/api/conditions':
            try:
                res = query_conditions(params, lang)
                self.send_json_response(res)
            except Exception as e:
                self.send_error_response(500, str(e))
                
        elif path == '/api/patterns':
            try:
                res = query_patterns(params, lang)
                self.send_json_response(res)
            except Exception as e:
                self.send_error_response(500, str(e))
                
        elif path == '/api/details':
            item_type = params.get('type')
            key = params.get('key')
            if not item_type or not key:
                self.send_error_response(400, "Missing 'type' or 'key' parameter")
                return
            try:
                res = query_details(item_type, key, lang)
                if res is None:
                    self.send_error_response(404, "Item not found")
                else:
                    self.send_json_response(res)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_error_response(500, str(e))
                
        elif path in ('/', '/index.html'):
            try:
                with open('index.html', 'r', encoding='utf-8') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            except Exception as e:
                self.send_error_response(500, f"Error reading index.html: {e}")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            
    def send_json_response(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        
    def send_error_response(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode('utf-8'))

def run(port=8000):
    server_address = ('', port)
    httpd = HTTPServer(server_address, TCMRequestHandler)
    print(f"Starting TCM search server on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == '__main__':
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    run(port)
