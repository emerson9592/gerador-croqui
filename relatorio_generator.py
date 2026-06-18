import io
import base64
from flask import Flask, render_template_string, request, send_file, redirect, url_for, jsonify, session, Blueprint, flash
from reportlab.pdfgen import canvas
from pdfrw import PdfReader, PdfWriter, PageMerge
from pathlib import Path
import re, random, os, json
import xml.etree.ElementTree as ET
import asyncio
import textwrap
import threading
from telethon import TelegramClient

# --- IMPORTAÇÃO DO ROBÔ SIGITM ---
# Certifique-se de importar a nova função do Captcha aqui!
from scraper_vivo import buscar_dados_ta_sigitm, gerar_sessao_interativa

# --- BIBLIOTECAS FIREBASE ---
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db as firebase_db

# --- BIBLIOTECAS DE MAPA ---
from geopy.geocoders import Nominatim, ArcGIS, GoogleV3

app = Flask(__name__)
app.secret_key = "1307"

# --- CONFIGURAÇÕES GERAIS ---
GOOGLE_API_KEY = "AIzaSyCZXAgi1EQntbx7U3SyZI3I4xWj25E2sq0"
TEMPLATE_PDF = "CROQUI.pdf"
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

# Garante a pasta static para o Captcha
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(exist_ok=True)

# CONFIG KML
KML_PATH = os.path.join('static', 'SMTXSP_Sites_2023104.kml')

# SENHA PARA ACESSAR A PÁGINA /admin
ADMIN_PASSWORD = "vivo"

# ==========================================
# CONFIGURAÇÕES DO FIREBASE (NUVEM)
# ==========================================
FIREBASE_DB_URL = 'https://nuvemgeradordecroqui-default-rtdb.firebaseio.com/tecnicos'

if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("firebase-key.json")
        firebase_admin.initialize_app(cred, {
            'databaseURL': FIREBASE_DB_URL
        })
        print("✅ Conectado ao Firebase com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao conectar ao Firebase: {e}")

# ==========================================
# CONFIGURAÇÕES DO TELEGRAM
# ==========================================
TELEGRAM_API_ID = 33091552
TELEGRAM_API_HASH = 'd09dcafbf4b9ba5427d80e5b4cad5837'
TELEGRAM_GROUP_IDS = [-4209680542, -4112543320]
TELEGRAM_SESSION = 'sessao_usuario'

# --- BANCO DE DADOS LOCAL (BACKUP/ALIASES) ---
DB_ALIASES = {
    "edenilson": "edenilson santos", "edenilson de souza": "edenilson santos",
    "cleber": "cleiton irani rodrigues benfica"
}


# --- FUNÇÕES DE COMUNICAÇÃO FIREBASE ---
def load_db():
    try:
        # A MÁGICA: Baixamos gaveta por gaveta.
        # O sistema NUNCA toca na pasta 'pdfs_pesados' aqui.
        db_data = {
            "tecnicos": firebase_db.reference('/tecnicos').get() or {},
            "veiculos": firebase_db.reference('/veiculos').get() or {},
            "locais_kml": firebase_db.reference('/locais_kml').get() or {},
            "croquis": firebase_db.reference('/croquis').get() or {}
        }
        return db_data
    except Exception as e:
        print(f"Erro na carga seletiva: {e}")
        # Retorna estrutura vazia para o site não quebrar
        return {"tecnicos": {}, "veiculos": {}, "locais_kml": {}, "croquis": {}}

def save_db(data):
    try:
        ref = firebase_db.reference('/')
        ref.set(data)
    except Exception as e:
        print(f"Erro Save Firebase: {e}")

# --- CONFIGURAÇÕES DE PDF ---
COORDS = {
    'or_ot': (0.20, 0.212), # <-- LINHA NOVA AQUI
    'codigo_obra': (0.18, 0.039), 'ta': (0.20, 0.182), 'causa': (0.17, 0.152),
    'endereco': (0.17, 0.125), 'localidade': (0.11, 0.096), 'es': (0.28, 0.096),
    'at': (0.34, 0.096), 'tronco': (0.10, 0.067), 'veiculo': (0.47, 0.040),
    'supervisor': (0.63, 0.040), 'data': (0.83, 0.049), 'materials_block': (0.045, 0.33),
    'croqui_rect': (0.02, 0.65, 0.95, 0.90)
}

EXEC_CONFIG = {'name_x': 0.47, 're_x': 0.65, 'start_y': 0.212, 'step_y': 0.028, 'max_rows': 6}
FILTRO_LANCAMENTO = ["metr", "lancado", "lançado", "lancamento", "lançamento"]


# --- FUNÇÃO TELEGRAM ---
async def search_telegram_message(ta_number):
    try:
        ta_str = str(ta_number).strip()
        async with TelegramClient(TELEGRAM_SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
            await client.get_dialogs()
            for group_id in TELEGRAM_GROUP_IDS:
                try:
                    entity = await client.get_entity(group_id)
                    async for message in client.iter_messages(entity, search=ta_str, limit=20):
                        if message.text and ("RESPOSTA" in message.text.upper() or "SIGLA" in message.text.upper()):
                            if re.search(r'\b' + re.escape(ta_str) + r'\b', message.text):
                                return message.text
                except Exception:
                    continue
    except Exception as e:
        print(f"Erro Telegram: {e}")
    return None


# --- FUNÇÕES DE BUSCA E FORMATAÇÃO ---
def buscar_endereco_gps(lat, lon):
    rua, numero, cidade, estado = "", "", "", "SP"
    if GOOGLE_API_KEY:
        try:
            gmaps = GoogleV3(api_key=GOOGLE_API_KEY)
            location = gmaps.reverse(f"{lat}, {lon}", timeout=5)
            if location:
                best_res = location[0] if isinstance(location, list) else location
                if hasattr(best_res, 'raw'):
                    components = best_res.raw.get('address_components', [])
                    for comp in components:
                        if 'route' in comp['types']: rua = comp['long_name']
                        if 'street_number' in comp['types']: numero = comp['long_name']
                        if 'administrative_area_level_2' in comp['types']: cidade = comp['long_name']
                        if 'administrative_area_level_1' in comp['types']: estado = comp['short_name']
                if rua: return (f"{rua}, {numero}" if numero else f"{rua}, S/N"), f"{cidade} - {estado}"
        except:
            pass
    try:
        geo_arc = ArcGIS(user_agent="sistema_croqui_v1")
        loc_arc = geo_arc.reverse(f"{lat}, {lon}", timeout=5)
        if loc_arc and loc_arc.raw.get('address'):
            full_text = loc_arc.raw['address']
            parts = full_text.split(',')
            if len(parts) > 0: rua = parts[0].strip()
            if len(parts) > 1:
                possible_num = parts[1].strip()
                if re.match(r"^\d+(?:-\d+)?$", possible_num): numero = possible_num
            if not cidade and len(parts) >= 3: cidade = parts[-3].strip()
    except:
        pass
    end_parts = []
    if rua: end_parts.append(rua)
    if numero:
        end_parts.append(f", {numero}")
    elif rua:
        end_parts.append(", S/N")
    if not rua: return None, None
    return "".join(end_parts), f"{cidade} - {estado}" if cidade else ""


def formatar_texto(texto):
    if not texto: return ""
    texto = str(texto).strip().capitalize()
    siglas = ["SP", "MG", "RJ", "ES", "SC", "PR", "RS", "MS", "MT", "GO", "DF", "TO", "BA", "SE", "AL", "PE", "PB",
              "RN", "CE", "PI", "MA", "PA", "AP", "AM", "RR", "RO", "AC", "TA", "SGM", "CEO", "CTOP", "OTDR", "VT",
              "PP", "XC", "CS"]
    for sigla in siglas:
        pattern = re.compile(r'\b' + re.escape(sigla) + r'\b', re.IGNORECASE)
        texto = pattern.sub(sigla, texto)
    placas = re.findall(r'\b[a-zA-Z]{3}[-]?[0-9][a-zA-Z0-9][0-9]{2}\b', texto, re.IGNORECASE)
    for p in placas: texto = texto.replace(p, p.upper())
    return texto


def pct_to_pt(xpct, ypct, width_pt, height_pt):
    return xpct * width_pt, ypct * height_pt


def organizar_tratativas(texto_bruto):
    texto = re.sub(r'\b(?:feito|realizado)\b', ' ', texto_bruto, flags=re.IGNORECASE)
    texto = re.sub(r'(?=\b(?:lan[cç]ado|lan[cç]amento)\b)', '\n', texto, flags=re.IGNORECASE)
    padrao_num = r'(?=\b(?:\d{1,4}\s*(?:fus[ãa]o|fus[õo]es|testes?|emendas?|ceo|caixas?|aberturas?|reaberturas?|ptro)|vt\s+sobressalente)\b)'
    texto = re.sub(padrao_num, '\n', texto, flags=re.IGNORECASE)
    return texto


def extrair_tronco_seguro(text):
    # 1. Limpa asteriscos soltos que atrapalham a leitura (ex: *NÚMERO DO CABO:*)
    texto_limpo = text.replace('*', '')

    # 2. Remove linhas de capacidade para o robô não pescar "24" (da quantidade de fibras) por engano
    texto_limpo = re.sub(r"CAPACIDADE.*?(\n|$)", "\n", texto_limpo, flags=re.IGNORECASE)

    # 3. Padrão Unificado de Alta Precisão
    # Lida com:
    # - Mesma linha: "NUMERO DO CABO: C#63" ou "NUMERO DO CABO C TRONCO 01"
    # - Quebra de linha: "20) NÚMERO DO CABO;\nRESPOSTA: C#63;"
    padrao_principal = r"N[UÚuú]MERO\s+DO\s+CABO(?:[^\n]*[\r\n]+[^\n]{0,15}?RESPOSTA[^\n]{0,25}?|[^\n]{0,25}?)([Cc]?\s*#?\s*\d+)"

    validos = []

    # Usamos finditer para escanear o texto inteiro de cima a baixo
    for m in re.finditer(padrao_principal, texto_limpo, re.IGNORECASE):
        # Captura o número bruto e remove qualquer espaço no meio (Ex: "C # 63" vira "C#63")
        m_limpo = re.sub(r'\s+', '', m.group(1)).upper()
        if m_limpo and m_limpo != "0":
            validos.append(m_limpo)

    # Se encontrou no padrão principal, retorna o último da lista
    if validos:
        return validos[-1]

    # 4. Fallback: Se o técnico escreveu de um jeito completamente bizarro,
    # o robô procura apenas por TR ou CABO isolados.
    padroes_fallback = [
        r"\bTR[\s:;\-#]*([Cc]?\s*#?\s*\d+)",
        r"\bCABO[\s:;\-#]*([Cc]?\s*#?\s*\d+)"
    ]

    for padrao in padroes_fallback:
        for m in re.finditer(padrao, texto_limpo, re.IGNORECASE):
            m_limpo = re.sub(r'\s+', '', m.group(1)).upper()
            if m_limpo and m_limpo != "0":
                validos.append(m_limpo)

    if validos:
        return validos[-1]

    return ""


def extrair_executantes_seguro(text, db):
    exec_list = []
    found_set = set()

    # 1. TENTATIVA POR ID (RE) - Rigoroso
    encontrados_id = re.findall(r"(?:Id|ID|RE)[\s:;\-#]*(\d{6,12})", text, re.IGNORECASE)
    for tec_id in encontrados_id:
        tec_id_str = str(tec_id).strip()
        for db_name, info in db['tecnicos'].items():
            if info.get('re') == tec_id_str and db_name not in found_set:
                found_set.add(db_name)
                exec_list.append({'name': db_name.title(), 're': tec_id_str})

    # 2. TENTATIVA POR NOME (Limpando telefones) - Rigoroso
    encontrados_nome = re.findall(r"(?:Técnico|NOME TÉCNICO):\s*([^\n]+)", text, re.IGNORECASE)
    for nome_bruto in encontrados_nome:
        nome_limpo = re.sub(r"[\d\-\(\)\+]+", "", nome_bruto).strip().lower()
        if not nome_limpo: continue

        matched_name = None
        if nome_limpo in db['tecnicos']:
            matched_name = nome_limpo
        else:
            for alias, db_name in DB_ALIASES.items():
                if nome_limpo in alias or alias in nome_limpo:
                    matched_name = db_name
                    break
            if not matched_name:
                for db_name in db['tecnicos']:
                    if nome_limpo in db_name or db_name in nome_limpo:
                        matched_name = db_name
                        break

        if matched_name and matched_name not in found_set:
            found_set.add(matched_name)
            exec_list.append({'name': matched_name.title(), 're': db['tecnicos'][matched_name].get('re', '')})

    # 3. FALLBACK: Procura nomes do banco soltos no texto (modo antigo para colagem manual)
    if not exec_list:
        text_lower = text.lower()
        for db_name in db['tecnicos']:
            if re.search(r"\b" + re.escape(db_name) + r"\b", text_lower) and db_name not in found_set:
                found_set.add(db_name)
                exec_list.append({'name': db_name.title(), 're': db['tecnicos'][db_name].get('re', '')})
        for alias, db_name in DB_ALIASES.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", text_lower) and db_name not in found_set:
                found_set.add(db_name)
                exec_list.append({'name': db_name.title(), 're': db['tecnicos'][db_name].get('re', '')})

    return exec_list


def extrair_siglas_seguro(text):
    padroes = [
        r"SIGLA(?:[ \t]+DO[ \t]+TRECHO)?[\s:;\-]+RESPOSTA[\s:;\-]+([A-Z]{3,4})\.([A-Z0-9]{2,3})",
        r"SIGLA[ \t\w]*[\s:;\-]+([A-Z]{3,4})\.([A-Z0-9]{2,3})",
        r"(?:ROTA[ \t\w]+CABO|CENTRAL)[\s:;\-]+([A-Z]{3,4})\.([A-Z0-9]{2,3})"
    ]
    for padrao in padroes:
        matches = re.findall(padrao, text, re.IGNORECASE)
        if matches:
            return matches[-1][0].upper(), matches[-1][1].upper()

    m_loose = re.findall(r"\b([A-Z]{3,4})\.([A-Z0-9]{2,3})\b", text, re.IGNORECASE)
    if m_loose:
        return m_loose[-1][0].upper(), m_loose[-1][1].upper()
    return "", ""


def extract_fields_sigitm(text, db):
    data = {key: '' for key in
            ['ta', 'codigo_obra', 'causa', 'endereco', 'localidade', 'es', 'at', 'tronco', 'veiculo', 'data',
             'supervisor', 'lat', 'lon']}

    m_sgm = re.search(r"(?:SGM|OBRA)[\s:\-]*(\d{8,})", text, re.IGNORECASE)
    if m_sgm: data['codigo_obra'] = m_sgm.group(1)

    m_causa = re.search(r"Causa:\s*([^\n]+)", text, re.IGNORECASE)
    if m_causa: data['causa'] = m_causa.group(1).strip()

    m_gps = re.search(r"Lat\s*([-.\d]+)\s*Long\s*([-.\d]+)", text, re.IGNORECASE)
    if m_gps:
        data['lat'], data['lon'] = m_gps.group(1), m_gps.group(2)
        end_gps, loc_gps = buscar_endereco_gps(data['lat'], data['lon'])
        if end_gps: data['endereco'] = end_gps
        if loc_gps: data['localidade'] = loc_gps

    data['es'], data['at'] = extrair_siglas_seguro(text)
    data['tronco'] = extrair_tronco_seguro(text)

    m_data = re.search(r"Data:\s*(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
    if m_data: data['data'] = m_data.group(1)

    m_super = re.search(r"Supervisor:\s*([^\n]+)", text, re.IGNORECASE)
    if m_super:
        # Pega o texto bruto
        sup_bruto = m_super.group(1).strip()
        # Corta na barra '/' e pega só a primeira parte (o nome)
        sup_limpo = sup_bruto.split('/')[0].strip().title()

        # Se você quiser que apareça RIGOROSAMENTE apenas o primeiro nome,
        # apague o '#' da linha de baixo:
        sup_limpo = sup_limpo.split()[0]

        data['supervisor'] = sup_limpo

    data['executantes_parsed'] = extrair_executantes_seguro(text, db)

    if data['executantes_parsed']:
        p_primeiro = data['executantes_parsed'][0]['name'].lower()
        if p_primeiro in db['veiculos']:
            data['veiculo'] = db['veiculos'][p_primeiro]
        info_tec = db['tecnicos'].get(p_primeiro, {})
        if not data['supervisor'] and info_tec.get('supervisor'):
            data['supervisor'] = info_tec['supervisor']

    m_acao = re.search(r"Ação de Recuperação:\s*(.*?)(?=\nMaterial utilizado:|\nData:|\Z)", text,
                       re.DOTALL | re.IGNORECASE)
    raw_mat = m_acao.group(1).strip() if m_acao else ""

    return data, raw_mat


def extract_fields(text, db):
    data = {key: '' for key in
            ['ta', 'codigo_obra', 'causa', 'endereco', 'localidade', 'es', 'at', 'tronco', 'veiculo', 'data',
             'supervisor', 'lat', 'lon']}
    text = text.replace('\r\n', '\n').strip()

    m_ta = re.search(r"(?:TA|T\.A\.?|TICKET)\s*[:\-]?\s*\*?(\d{8,})\*?", text, re.IGNORECASE)
    if m_ta:
        data['ta'] = m_ta.group(1)
    else:
        m_loose_start = re.search(r"^\s*(\d{8,11})\b", text)
        if m_loose_start:
            data['ta'] = m_loose_start.group(1)
        else:
            m_loose = re.search(r"\b([34]\d{8})\b", text)
            if m_loose: data['ta'] = m_loose.group(1)

    m_sgm = re.search(r"(?:SGM|Obra)[\s:\-]*(\d{8,})", text, re.IGNORECASE)
    if m_sgm:
        data['codigo_obra'] = m_sgm.group(1)
    else:
        m_sgm_after_material = re.search(r"Material\s+utilizado:[\s\S]*?\b(\d{9,12})\b", text, re.IGNORECASE)
        if m_sgm_after_material:
            data['codigo_obra'] = m_sgm_after_material.group(1)
        else:
            m_sgm_loose = re.search(r"\b(20[2-9]\d{7})\b", text)
            if m_sgm_loose: data['codigo_obra'] = m_sgm_loose.group(1)

    data['es'], data['at'] = extrair_siglas_seguro(text)
    data['tronco'] = extrair_tronco_seguro(text)

    m_dt_cria = re.search(r"(?:DATA|CRIACAO).*?(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
    if m_dt_cria:
        data['data'] = m_dt_cria.group(1)
    elif not data['data']:
        m_prev = re.search(r"Previs[ãa]o.*?(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
        if m_prev:
            ymd = m_prev.group(1).split('-')
            data['data'] = f"{ymd[2]}/{ymd[1]}/{ymd[0]}"
        else:
            m_simple = re.search(r"(\d{2}/\d{2}/\d{4})", text)
            if m_simple: data['data'] = m_simple.group(1)

    patterns = [(r"(?:causa|motivo)\s*[:;\-]?\s*(.+)", 'causa'),
                (r"(?:localidade|cidade)\s*[:;\-]?\s*(.+)", 'localidade'),
                (r"ve[ií]culo\s*[:;\-]?\s*(\S+)", 'veiculo')]
    for pat, key in patterns:
        if not data[key]:
            m = re.search(r"(?m)^.*?" + pat, text, re.IGNORECASE)
            if m: data[key] = m.group(1).strip().rstrip('.,;')

    match_gps = re.search(r"(-2\d\.\d+)[^\d\-]+(-4\d\.\d+)", text)
    if match_gps:
        data['lat'], data['lon'] = match_gps.group(1), match_gps.group(2)
        end_gps, loc_gps = buscar_endereco_gps(data['lat'], data['lon'])
        if end_gps:
            if not data['endereco'] or len(data['endereco']) < 5: data['endereco'] = end_gps
            if not data['localidade'] and loc_gps: data['localidade'] = loc_gps

    data['executantes_parsed'] = extrair_executantes_seguro(text, db)

    if data['executantes_parsed']:
        p_primeiro = data['executantes_parsed'][0]['name'].lower()
        if not data['veiculo'] and p_primeiro in db['veiculos']:
            data['veiculo'] = db['veiculos'][p_primeiro]
        info_tec = db['tecnicos'].get(p_primeiro, {})
        if info_tec.get('supervisor'):
            data['supervisor'] = info_tec['supervisor']

    m_gen = re.search(r"Ação de Recuperação:[\s\S]*?(?=\nMaterial|\nData|\Z|OBRA|SGM|Causa)", text, re.IGNORECASE)
    if m_gen:
        raw_mat = re.sub(r"Ação de Recuperação:\s*", "", m_gen.group(0), flags=re.IGNORECASE)
    else:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        tmp = []
        for l in lines:
            if not any(x in l.lower() for x in ['ta', 'data', 'lat', 'long', 'previsão', 'causa', 'obra']):
                tmp.append(l)
        raw_mat = "\n".join(tmp)

    return data, raw_mat


def detect_launch(material_lines):
    joined = " ".join(material_lines).lower()
    if "repuxad" in joined: return None
    patterns = [r"(\d{1,4})\s*(?:m\b|mt|mts|metr[ao]s?)", r"(\d{1,4})\s*(?:lan[cç]ad[oa]|lan[cç]amento)",
                r"(?:lan[cç]ad[oa]|lan[cç]amento)\s*(\d{1,4})"]
    for p in patterns:
        m = re.search(p, joined)
        if m: return int(m.group(1))
    return None


def detect_double_point(material_lines):
    joined = " ".join(material_lines).lower()
    if re.search(r"\b(?:02|2)\s*(?:reabertura|abertura|ceo|caixa|ctop|emenda)", joined): return True
    return False


def extrair_vt_sobressalente(linhas_ou_texto):
    vts = []
    if isinstance(linhas_ou_texto, list):
        texto = " ".join(linhas_ou_texto)
    else:
        texto = str(linhas_ou_texto)

    padroes_vt = [
        r'vt[\s\S]{0,15}sobress?alente[\s\S]{0,20}?(\d+)\s*(?:m\b|mt|mts|metros)',
        r'(\d+)\s*(?:m\b|mt|mts|metros)[\s\S]{0,20}vt[\s\S]{0,15}sobress?alente'
    ]

    for padrao in padroes_vt:
        matches = re.finditer(padrao, texto, re.IGNORECASE)
        for m in matches:
            vt_len = int(m.group(1))
            inicio = max(0, m.start() - 40)
            fim = min(len(texto), m.end() + 40)
            trecho = texto[inicio:fim]

            m_xc = re.search(r'(?:xc|cs|poste)\s*[-:]?\s*(\d+)', trecho, re.IGNORECASE)
            xc_idx = int(m_xc.group(1)) if m_xc else 1

            if not any(v['len'] == vt_len and v['xc'] == xc_idx for v in vts):
                vts.append({'len': vt_len, 'xc': xc_idx})
    return vts


def generate_pps(total_length, vt_each=15, extra_vt=0):
    usable = total_length - (2 * vt_each) - extra_vt
    if usable <= 0: return []
    num_spans = max(1, round(usable / 40))
    base_span = usable // num_spans
    resto = usable % num_spans
    spans = [base_span] * num_spans
    for i in range(resto): spans[i] += 1
    return spans


def dividir_tratativas(material_lines):
    divs = ["fus", "fusão", "fusões", "fusao", "tubo", "loose", "teste", "otdr"]
    esps = ["ceo", "ptro", "abertura", "reabertura", "caixa", "emenda", "emendas"]
    p1, p2 = [], []
    itens = []
    for l in material_lines:
        t = l.strip()
        low = t.lower()
        m = re.match(r"(\d+)\s*[-xX]?\s*(.+)", low)
        if not m: itens.append({"qtd": 1, "nome": low, "orig": t}); continue
        itens.append({"qtd": int(m.group(1)), "nome": m.group(2).strip(), "orig": t})

    esps_unit = [i for i in itens if i["qtd"] == 1 and any(k in i["nome"] for k in esps)]
    if len(esps_unit) == 2:
        p1.append(esps_unit[0]["orig"])
        p2.append(esps_unit[1]["orig"])
        rest = [i for i in itens if i not in esps_unit]
    else:
        rest = itens.copy()

    for i in rest:
        qtd, nome, orig = i["qtd"], i["nome"], i["orig"]
        if any(f in nome for f in FILTRO_LANCAMENTO): p1.append(orig); continue
        if any(k in nome for k in esps):
            if qtd == 1:
                p1.append(orig)
            else:
                md = qtd // 2
                rs = qtd - md
                if md > 0: p1.append(f"{md} {nome}")
                if rs > 0: p2.append(f"{rs} {nome}")
            continue
        if any(k in nome for k in divs):
            md = qtd // 2
            rs = qtd - md
            if md > 0: p1.append(f"{md} {nome}")
            if rs > 0: p2.append(f"{rs} {nome}")
            continue
        p1.append(orig)
    return p1, p2


def create_overlay(parsed, materials_raw, pp_list, vts_extra=None):
    if vts_extra is None: vts_extra = []

    packet = io.BytesIO()  # Cria um "arquivo falso" na memória RAM

    if not os.path.exists(TEMPLATE_PDF):
        w_pt, h_pt = 595.27, 841.89
    else:
        tpl = PdfReader(TEMPLATE_PDF)
        p0 = tpl.pages[0]
        mb = p0.MediaBox
        w_pt = float(mb[2]) - float(mb[0])
        h_pt = float(mb[3]) - float(mb[1])

    c = canvas.Canvas(packet, pagesize=(w_pt, h_pt))

    def put_xy(key, text, size=9, manual=None):
        if not text: return
        xp, yp = manual if manual else COORDS.get(key, (0, 0))
        if xp == 0: return
        x, y = pct_to_pt(xp, yp, w_pt, h_pt)
        c.setFont("Helvetica", size)
        for idx, ln in enumerate(str(text).split('\n')): c.drawString(x, y - (idx * (size + 2)), ln)

    for k, v in parsed.items():
        if k != 'executantes_parsed': put_xy(k, v)

    for i, item in enumerate(parsed.get('executantes_parsed', [])):
        if i >= EXEC_CONFIG['max_rows']: break
        cy = EXEC_CONFIG['start_y'] - (i * EXEC_CONFIG['step_y'])
        put_xy(f"nm_{i}", item['name'], 9, (EXEC_CONFIG['name_x'], cy))
        if item['re']: put_xy(f"re_{i}", item['re'], 9, (EXEC_CONFIG['re_x'], cy))

    def quebrar_limite(linhas, limite=42):
        nova_lista = []
        for linha in linhas: nova_lista.extend(textwrap.wrap(linha, width=limite))
        return nova_lista

    mx, my = pct_to_pt(COORDS['materials_block'][0], COORDS['materials_block'][1], w_pt, h_pt)
    c.setFont('Helvetica', 8)
    mat_lateral = quebrar_limite(materials_raw, 42)
    for i, ln in enumerate(mat_lateral[:20]): c.drawString(mx, my - (i * 10), ln)

    l_pct, b_pct, r_pct, t_pct = COORDS['croqui_rect']
    dy = h_pt * ((t_pct + b_pct) / 2)
    lx = w_pt * (l_pct + 0.05)
    rx = w_pt * (r_pct - 0.05)

    c.setLineWidth(2)
    c.setDash(4, 2)
    c.line(lx, dy, rx, dy)
    c.setDash([])

    if parsed.get('endereco'):
        addr = parsed['endereco']
        c.setFont('Helvetica-Bold', 10)
        tw = c.stringWidth(addr, 'Helvetica-Bold', 10)
        cx = (lx + rx) / 2
        c.drawString(cx - (tw / 2), dy - 100, addr)

    def draw_box(x, y, w, h, t, lines):
        c.rect(x, y, w, h, fill=0)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 5, y + h - 10, t)
        c.setFont("Helvetica", 8)
        for i, l in enumerate(lines): c.drawString(x + 5, y + h - 20 - (i * 10), l)

    joined_materials = " ".join(materials_raw).lower()
    is_subt = "subterraneo" in joined_materials or "subterrâneo" in joined_materials
    pfx = "CS" if is_subt else "XC"

    if len(pp_list) == 0:
        tot_w = rx - lx
        mid = lx + tot_w / 2
        c.circle(lx, dy, 4, fill=1)
        c.drawString(lx - 12, dy - 20, "Início")
        c.circle(mid, dy, 4, fill=1)
        c.drawString(mid - 8, dy - 20, pfx)
        c.circle(rx, dy, 4, fill=1)
        c.drawString(rx - 8, dy - 20, "Fim")

        bw, off = 220, 35
        mat_box = quebrar_limite(materials_raw, 42)
        bh = 15 + 12 + (len(mat_box) * 10)
        bx = mid - bw / 2
        by = dy + off
        draw_box(bx, by, bw, bh, "Tratativas", mat_box)
        c.line(mid, dy, mid, by)
        c.drawString(mid - 4, by - 10, "↑")
    else:
        p1, p2 = dividir_tratativas(materials_raw)
        p1_box = quebrar_limite(p1, 42)
        p2_box = quebrar_limite(p2, 42)

        off, bw = 180, 180
        h1 = 15 + 12 + (len(p1_box) * 10)
        bx1, by1 = lx - 20, dy + 30
        draw_box(bx1, by1, bw, h1, "Tratativas E1", p1_box)
        c.line(lx, dy, bx1 + bw / 2, by1)

        h2 = 15 + 12 + (len(p2_box) * 10)
        bx2, by2 = rx - bw + 20, dy + 30
        draw_box(bx2, by2, bw, h2, "Tratativas E2", p2_box)
        c.line(rx, dy, bx2 + bw / 2, by2)

        step = (rx - lx) / len(pp_list)
        cx = lx
        c.circle(cx, dy, 4, fill=1)
        has_cb = sum(pp_list) > 0
        if has_cb: c.drawString(cx - 10, dy + 15, "VT 15m")
        c.drawString(cx - 10, dy - 20, f"{pfx} Inicial")

        for i, dist in enumerate(pp_list):
            nx = cx + step
            mid = (cx + nx) / 2
            if dist > 0 and has_cb: c.drawString(mid - 15, dy + 5, f"PP {dist}m")
            c.circle(nx, dy, 4, fill=1)
            if i == len(pp_list) - 1:
                c.drawString(nx - 10, dy - 20, f"{pfx} Final")
                if has_cb: c.drawString(nx - 10, dy + 15, "VT 15m")
            else:
                c.drawString(nx - 8, dy - 20, pfx)
            cx = nx

    if vts_extra:
        for vt in vts_extra:
            xc_idx = vt['xc']
            vt_len = vt['len']
            if len(pp_list) > 0:
                max_idx = len(pp_list)
                if xc_idx > max_idx: xc_idx = max_idx
                step = (rx - lx) / len(pp_list)
                pole_x = lx + (xc_idx * step)
            else:
                pole_x = lx + (rx - lx) / 2

            box_w, box_h = 100, 18
            box_x = pole_x - (box_w / 2)
            box_y = dy - 60
            c.rect(box_x, box_y, box_w, box_h, fill=0)
            c.setFont("Helvetica-Bold", 8)
            texto_vt = f"VT Sobressal. {vt_len}m"
            tw = c.stringWidth(texto_vt, "Helvetica-Bold", 8)
            c.drawString(box_x + (box_w - tw) / 2, box_y + 6, texto_vt)
            c.setDash(2, 2)
            c.line(pole_x, dy, pole_x, box_y + box_h)
            c.setDash([])

    c.showPage()
    c.save()
    packet.seek(0)
    return packet


def merge_overlay(overlay_stream):
    out_stream = io.BytesIO()  # Arquivo de saída na RAM

    if not os.path.exists(TEMPLATE_PDF):
        out_stream.write(overlay_stream.read())
        out_stream.seek(0)
        return out_stream

    overlay = PdfReader(fdata=overlay_stream.read())
    template = PdfReader(TEMPLATE_PDF)

    if len(template.pages) > 0 and len(overlay.pages) > 0:
        merger = PageMerge(template.pages[0])
        merger.add(overlay.pages[0]).render()

    from pdfrw import PdfWriter
    PdfWriter(out_stream, trailer=template).write()
    out_stream.seek(0)

    return out_stream

# ==========================================
# FUNÇÕES E BLUEPRINT KML
# ==========================================
def remove_namespace(tree):
    for elem in tree.iter():
        if '}' in elem.tag: elem.tag = elem.tag.split('}', 1)[1]
    return tree


def read_kml(file_path):
    if not os.path.exists(file_path): return []
    tree = ET.parse(file_path)
    tree = remove_namespace(tree)
    root = tree.getroot()
    placemarks = root.findall(".//Placemark")
    places = []
    for pm in placemarks:
        name_tag = pm.find("name")
        coords_tag = pm.find(".//coordinates")
        place_name = name_tag.text.strip() if name_tag is not None and name_tag.text else "Sem Nome"
        if coords_tag is not None and coords_tag.text:
            try:
                lon, lat, *_ = coords_tag.text.strip().split(",")
                places.append({"name": place_name, "lat": lat.strip(), "lon": lon.strip()})
            except ValueError:
                print(f"Erro nas coordenadas de: {place_name}")
    return sorted(places, key=lambda p: p["name"].lower())


def add_placemark(file_path, name, lat, lon):
    tree = ET.parse(file_path)
    tree = remove_namespace(tree)
    root = tree.getroot()
    existing = root.findall(".//Placemark[name='%s']" % name)
    if existing: return False
    pm = ET.Element("Placemark")
    name_elem = ET.SubElement(pm, "name")
    name_elem.text = name
    point_elem = ET.SubElement(pm, "Point")
    coords_elem = ET.SubElement(point_elem, "coordinates")
    coords_elem.text = f"{lon},{lat},0"
    root.append(pm)
    tree.write(file_path, encoding='utf-8', xml_declaration=True)
    return True


def get_coordinates_from_link(link):
    regex = r"https:\/\/(?:www\.)?google\.com\/maps\/(?:[\w\-]+\/\@|\?q=|\?ll=)(-?\d+\.\d+),(-?\d+\.\d+)"
    match = re.search(regex, link)
    if match: return match.group(1), match.group(2)
    return None, None


mapa_bp = Blueprint('mapa', __name__, url_prefix='/mapa')


def clean_firebase_key(name):
    return str(name).replace('.', '_').replace('#', '_').replace('$', '_').replace('[', '_').replace(']', '_')


@mapa_bp.route('/')
def index_mapa():
    places_kml = read_kml(KML_PATH)
    db = load_db()
    locais_nuvem = db.get('locais_kml', {})
    places_nuvem = []
    deletados = set()
    nomes_na_nuvem = set()

    for safe_key, data in locais_nuvem.items():
        if isinstance(data, dict):
            nome_real = data.get('name', safe_key)
            if data.get('deleted'):
                deletados.add(nome_real)
            else:
                nomes_na_nuvem.add(nome_real)
                places_nuvem.append({"name": nome_real, "lat": data.get('lat', ''), "lon": data.get('lon', '')})

    todos_places = places_nuvem.copy()
    for p in places_kml:
        nome_kml = p['name']
        if nome_kml not in nomes_na_nuvem and nome_kml not in deletados:
            todos_places.append(p)

    todos_places = sorted(todos_places, key=lambda p: str(p.get("name", "")).lower())
    return render_template_string(KML_HTML, places=todos_places)


@mapa_bp.route('/add', methods=['POST'])
def add():
    name = request.form['name'].upper().strip()
    lat = request.form.get('lat', '').strip()
    lon = request.form.get('lon', '').strip()
    maps_link = request.form.get('mapsLink')

    if maps_link:
        lat, lon = get_coordinates_from_link(maps_link)
        if not lat or not lon:
            flash("Link do Google Maps inválido.", "error")
            return redirect(url_for('mapa.index_mapa'))

    if not lat or not lon:
        flash("Preencha as coordenadas ou cole um link do Maps.", "error")
        return redirect(url_for('mapa.index_mapa'))

    safe_name = clean_firebase_key(name)
    db = load_db()
    if safe_name in db['locais_kml'] and not db['locais_kml'][safe_name].get('deleted'):
        flash("Já existe um local com esse nome.", "error")
        return redirect(url_for('mapa.index_mapa'))

    places_kml = read_kml(KML_PATH)
    if any(p['name'] == name for p in places_kml) and safe_name not in db['locais_kml']:
        flash("Já existe um local com esse nome no arquivo original.", "error")
        return redirect(url_for('mapa.index_mapa'))

    db['locais_kml'][safe_name] = {'name': name, 'lat': lat, 'lon': lon}
    save_db(db)
    flash("Local adicionado com sucesso!", "success")
    return redirect(url_for('mapa.index_mapa'))


@mapa_bp.route('/edit', methods=['POST'])
def edit():
    orig_name = request.form.get('original_name', '').strip()
    new_name = request.form.get('name', '').upper().strip()
    lat = request.form.get('lat', '').strip()
    lon = request.form.get('lon', '').strip()
    maps_link = request.form.get('mapsLink')

    if maps_link:
        parsed_lat, parsed_lon = get_coordinates_from_link(maps_link)
        if parsed_lat and parsed_lon: lat, lon = parsed_lat, parsed_lon

    safe_orig = clean_firebase_key(orig_name)
    safe_new = clean_firebase_key(new_name)
    db = load_db()

    if safe_orig != safe_new: db['locais_kml'][safe_orig] = {'deleted': True, 'name': orig_name}
    db['locais_kml'][safe_new] = {'name': new_name, 'lat': lat, 'lon': lon}

    save_db(db)
    flash("Local atualizado com sucesso!", "success")
    return redirect(url_for('mapa.index_mapa'))


@mapa_bp.route('/delete', methods=['POST'])
def delete():
    name = request.form.get('name', '').strip()
    safe_name = clean_firebase_key(name)
    db = load_db()
    db['locais_kml'][safe_name] = {'deleted': True, 'name': name}
    save_db(db)
    flash(f"Local {name} apagado com sucesso!", "success")
    return redirect(url_for('mapa.index_mapa'))


app.register_blueprint(mapa_bp)

# --- HTML TEMPLATES ---
LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Login Administrativo</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0"><style>
body{font-family:'Segoe UI',sans-serif; background:#f0f2f5; text-align:center; padding-top:100px; margin:0;}
.box{background:#fff; padding:30px; border-radius:10px; display:inline-block; box-shadow:0 4px 10px rgba(0,0,0,0.1); width:90%; max-width:350px;}
input{padding:12px; margin-bottom:15px; width:100%; box-sizing:border-box; border:1px solid #ccc; border-radius:5px;}
button{padding:12px; width:100%; background:#007bff; color:white; border:none; border-radius:5px; font-weight:bold; cursor:pointer;}
</style></head><body><div class="box"><h2>Acesso Restrito</h2>
{% if erro %}<p style="color:#dc3545; font-weight:bold;">Senha Incorreta</p>{% endif %}
<form method="post"><input type="password" name="senha" placeholder="Digite a senha..." required><button type="submit">Entrar</button></form>
<br><a href="/" style="color:#666; text-decoration:none;">« Voltar ao Gerador</a></div></body></html>"""

ADMIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Painel Administrativo</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0"><style>
body{font-family:'Segoe UI',sans-serif; background:#f0f2f5; padding:20px; margin:0;}
.container{max-width:1100px; margin:auto; background:#fff; padding:25px; border-radius:10px; box-shadow:0 2px 10px rgba(0,0,0,0.1);}
table{width:100%; border-collapse:collapse; margin-top:10px;}
th, td{border:1px solid #eee; padding:12px; text-align:left; font-size:14px; vertical-align: middle;}
th{background:#f8f9fa; color:#555; font-weight:600;}
input.edit-input{padding:8px; border:1px solid #ccc; border-radius:4px; width:100%; box-sizing:border-box;}
.btn{padding:8px 12px; border:none; border-radius:4px; cursor:pointer; font-weight:bold; font-size:13px; margin-right:5px;}
.btn-add{background:#28a745; color:#fff; width:100%; padding:12px; font-size:16px; margin-top:15px;}
.btn-edit{background:#ffc107; color:#212529;}
.btn-save{background:#28a745; color:#fff;}
.btn-cancel{background:#6c757d; color:#fff;}
.btn-del{background:#dc3545; color:#fff;}
.form-grid{display:grid; grid-template-columns: 2fr 1fr 1fr 1fr 1fr; gap:15px;}
.actions-cell {white-space: nowrap; width: 150px;}
.search-container { display: flex; justify-content: space-between; align-items: center; margin-top: 30px; margin-bottom: 10px; }
.search-input { padding: 10px 15px; border: 1px solid #ccc; border-radius: 20px; width: 100%; max-width: 300px; outline: none; transition: 0.3s; font-size: 14px;}
.search-input:focus { border-color: #007bff; box-shadow: 0 0 5px rgba(0,123,255,0.3); }
/* Estilo das Abas */
.nav-tabs { display: flex; border-bottom: 2px solid #ddd; margin-bottom: 25px; }
.nav-tab { padding: 12px 25px; text-decoration: none; color: #555; font-weight: bold; font-size: 15px; margin-bottom: -2px; border-bottom: 3px solid transparent; transition: 0.2s; }
.nav-tab:hover { color: #007bff; }
.nav-tab.active { color: #007bff; border-bottom: 3px solid #007bff; }
@media (max-width: 768px) { .form-grid{grid-template-columns: 1fr;} table {display:block; overflow-x:auto;} }
</style><script>
function toggleEdit(rowId) {
    const row = document.getElementById(rowId);
    const spans = row.querySelectorAll('.view-data'); const inputs = row.querySelectorAll('.edit-input');
    const btnEdit = row.querySelector('.btn-edit'); const btnSave = row.querySelector('.btn-save');
    const btnCancel = row.querySelector('.btn-cancel'); const btnDel = row.querySelector('.btn-del');
    let isEditing = inputs[0].style.display !== 'none';
    if (isEditing) { spans.forEach(s => s.style.display = ''); inputs.forEach(i => i.style.display = 'none'); btnEdit.style.display = ''; btnSave.style.display = 'none'; btnCancel.style.display = 'none'; btnDel.style.display = '';
    } else { spans.forEach(s => s.style.display = 'none'); inputs.forEach(i => i.style.display = ''); btnEdit.style.display = 'none'; btnSave.style.display = ''; btnCancel.style.display = ''; btnDel.style.display = 'none'; }
}
document.addEventListener('DOMContentLoaded', () => {
    const searchAdmin = document.getElementById('search-admin');
    if (searchAdmin) {
        searchAdmin.addEventListener('input', function() {
            const filter = this.value.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
            const rows = document.querySelectorAll('#tecnicos-tbody tr');
            rows.forEach(row => { row.style.display = row.innerText.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").includes(filter) ? '' : 'none'; });
        });
    }
});
</script></head><body><div class="container">
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
<h2 style="margin:0; color:#333;">Nuvem de Operações</h2><div><a href="/" style="text-decoration:none; color:#007bff; margin-right:15px;">« Gerador</a> <a href="/logout" style="text-decoration:none; color:#dc3545;">Sair</a></div></div>

<div class="nav-tabs">
    <a href="/admin" class="nav-tab active">👷 Técnicos & Sistema</a>
    <a href="/relatorios" class="nav-tab">📋 Relatórios Salvos</a>
</div>

<div id="login-panel" style="background:#e0f7fa; padding:20px; border-radius:8px; border:1px solid #b2ebf2; margin-bottom:25px;">
    <h3 style="margin-top:0; color:#006064;">🤖 Renovação de Sessão SIGITM</h3>
    <div id="step-1" style="display:flex; gap:10px; align-items:center;"><input type="text" id="sigitm_user" class="edit-input" placeholder="Usuário Vivo (RE)" style="flex:1;"><input type="password" id="sigitm_pass" class="edit-input" placeholder="Senha" style="flex:1;"><button onclick="iniciarLogin()" class="btn" style="background:#00838f; margin:0; width:150px;">1. Acessar »</button></div>
    <div id="step-loading" style="display:none; text-align:center; color:#00838f; font-weight:bold; padding: 15px;"><p>⏳ Aguarde...</p></div>
    <div id="step-captcha" style="display:none; text-align:center; padding: 15px;"><p style="font-weight:bold; color: #d32f2f;">Resolva o Captcha da imagem abaixo:</p><img id="captcha-img" src="" style="border:2px solid #ccc; border-radius:5px; margin-bottom:15px; max-width: 100%; height: auto; display: block; margin-left: auto; margin-right: auto;"><br><div style="display:flex; gap:10px; align-items:center; justify-content:center; max-width: 400px; margin: 0 auto;"><input type="text" id="captcha_input" class="edit-input" placeholder="Ex: 79zx6" style="flex:1; text-align:center; font-size:18px; letter-spacing:2px; font-weight:bold;"><button onclick="enviarCaptcha()" class="btn" style="background:#28a745; margin:0; width:150px;">2. Enviar</button></div></div>
    <div id="step-msg" style="display:none; text-align:center; font-weight:bold; padding: 15px;"></div>
</div>
<script>
    let checkInterval;
    function iniciarLogin() { const u = document.getElementById('sigitm_user').value; const p = document.getElementById('sigitm_pass').value; if(!u || !p) return alert("Preencha usuário e senha!"); document.getElementById('step-1').style.display = 'none'; document.getElementById('step-msg').style.display = 'none'; document.getElementById('step-loading').style.display = 'block'; let formData = new FormData(); formData.append('user', u); formData.append('pwd', p); fetch('/api/iniciar_login', { method: 'POST', body: formData }).then(r => r.json()).then(data => { checkInterval = setInterval(checarStatus, 2000); }); }
    function checarStatus() { fetch('/api/status_login').then(r => r.json()).then(data => { if (data.status === 'esperando_captcha') { clearInterval(checkInterval); document.getElementById('step-loading').style.display = 'none'; document.getElementById('step-captcha').style.display = 'block'; document.getElementById('captcha-img').src = data.img + '?v=' + new Date().getTime(); } else if (data.status === 'finalizado') { clearInterval(checkInterval); document.getElementById('step-loading').style.display = 'none'; document.getElementById('step-captcha').style.display = 'none'; const msgBox = document.getElementById('step-msg'); msgBox.style.display = 'block'; if (data.resultado === 'SUCESSO') { msgBox.style.color = '#28a745'; msgBox.innerHTML = '✅ Sessão atualizada!'; setTimeout(() => { location.reload(); }, 3000); } else { msgBox.style.color = '#dc3545'; msgBox.innerHTML = '❌ Erro: ' + data.resultado; document.getElementById('step-1').style.display = 'flex'; } } }); }
    function enviarCaptcha() { const resp = document.getElementById('captcha_input').value; if(!resp) return alert("Digite as letras!"); document.getElementById('step-captcha').style.display = 'none'; document.getElementById('step-loading').style.display = 'block'; document.getElementById('step-loading').innerHTML = '<p>⏳ Enviando...</p>'; let formData = new FormData(); formData.append('captcha', resp); fetch('/api/enviar_captcha', { method: 'POST', body: formData }).then(r => { checkInterval = setInterval(checarStatus, 2000); }); }
</script>

<form method="post" style="background:#f8f9fa; padding:20px; border-radius:8px; border:1px solid #eee;">
<h3 style="margin-top:0; color:#444; margin-bottom:15px;">Adicionar Novo Técnico</h3><input type="hidden" name="action" value="add">
<div class="form-grid"><input type="text" name="nome" class="edit-input" placeholder="Nome Completo" required style="padding:12px;"><input type="text" name="re" class="edit-input" placeholder="RE" style="padding:12px;"><input type="text" name="area" class="edit-input" placeholder="Área" style="padding:12px;"><input type="text" name="placa" class="edit-input" placeholder="Placa" style="padding:12px;"><input type="text" name="supervisor" class="edit-input" placeholder="Supervisor" style="padding:12px;"></div>
<button type="submit" class="btn btn-add">+ Salvar Técnico</button></form>
<div class="search-container"><h3 style="color:#444; margin:0;">👷 Técnicos Cadastrados</h3><input type="text" id="search-admin" class="search-input" placeholder="🔍 Buscar por nome, RE ou placa..."></div>
<div style="max-height: 400px; overflow-y: auto; border: 1px solid #eee; border-radius: 4px; margin-bottom: 10px;">
<table style="margin-top:0; border:none;">
<thead style="position: sticky; top: 0; z-index: 10;">
<tr><th>Nome</th><th>RE</th><th>Área</th><th>Veículo</th><th>Supervisor</th><th style="text-align:center;">Ações</th></tr></thead>
<tbody id="tecnicos-tbody">
{% for nome, info in tecnicos.items() %}<tr id="row-{{ loop.index }}">
<form method="post"><input type="hidden" name="action" value="edit"><input type="hidden" name="original_nome" value="{{ nome }}">
<td><span class="view-data">{{ nome.title() }}</span><input class="edit-input" name="new_nome" value="{{ nome.title() }}" style="display:none;" required></td><td><span class="view-data">{{ info.re }}</span><input class="edit-input" name="re" value="{{ info.re }}" style="display:none;"></td><td><span class="view-data">{{ info.area }}</span><input class="edit-input" name="area" value="{{ info.area }}" style="display:none;"></td><td><span class="view-data">{{ veiculos.get(nome, '-') }}</span><input class="edit-input" name="placa" value="{{ veiculos.get(nome, '') }}" style="display:none;"></td><td><span class="view-data">{{ info.supervisor|default('-', true) }}</span><input class="edit-input" name="supervisor" value="{{ info.supervisor|default('', true) }}" style="display:none;"></td>
<td class="actions-cell" style="text-align:center;"><button type="button" class="btn btn-edit" onclick="toggleEdit('row-{{ loop.index }}')">Editar</button><button type="submit" class="btn btn-save" style="display:none;">Salvar</button><button type="button" class="btn btn-cancel" style="display:none;" onclick="toggleEdit('row-{{ loop.index }}')">Cancelar</button></td></form>
<td style="border-left:none; text-align:center; width: 60px;"><form method="post" style="display:inline;"><input type="hidden" name="action" value="delete"><input type="hidden" name="nome" value="{{ nome }}"><button type="submit" class="btn btn-del view-data">Excluir</button></form></td></tr>
{% endfor %}</tbody></table></div></div></body></html>"""

PASTE_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Colar Relatório</title><style>body{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:#f0f2f5;padding:20px;text-align:center;margin:0}.container{width:90%;max-width:700px;margin:20px auto;background:#fff;padding:25px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.1)}textarea{width:100%;height:180px;padding:15px;margin-bottom:20px;border:2px solid #ddd;border-radius:8px;font-size:16px;font-family:monospace;resize:vertical;background-color:#fafafa;box-sizing:border-box}textarea:focus{border-color:#007bff;outline:none;background:#fff}button{width:100%;padding:15px;font-size:18px;background:#007bff;color:#fff;border:none;border-radius:6px;cursor:pointer;transition:0.2s;font-weight:bold;margin-bottom:15px}button:hover{background:#0056b3}h2{color:#333;margin-bottom:10px}.manual-link{display:inline-block;margin-top:15px;color:#666;text-decoration:none;font-size:14px; margin-right:15px;}.manual-link:hover{text-decoration:underline;color:#007bff}.info{color:#666;font-size:14px;margin-bottom:20px}</style></head><body><div class="container"><h2>Gerador de Croquis</h2><p class="info">Digite apenas o <strong>Número da TA</strong> para busca automática ou cole o encerramento do <strong>GENESIS</strong>.</p><form method="post" action="/preencher"><textarea name="raw_text" placeholder="Digite a TA (ex: 363384900) ou cole o texto aqui..."></textarea><br><button type="submit">Processar Relatório »</button></form><div><a href="/form" class="manual-link">Preencher manualmente</a> | <a href="/admin" class="manual-link" style="color:#28a745;">☁️ Sistema</a> | <a href="/mapa/" target="_blank" class="manual-link" style="color:#17a2b8;">🗺️ Localizações</a></div></div></body></html>"""

FORM_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Confirmar Dados - Gerador de Croqui</title>
<style>body{font-family:'Segoe UI',sans-serif;background:#f0f2f5;padding:10px;margin:0} .container{width:95%;max-width:900px;margin:10px auto;background:#fff;padding:20px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.05);box-sizing:border-box} input,textarea{width:100%;padding:12px;margin-bottom:15px;border:1px solid #ccc;border-radius:5px;font-size:16px;box-sizing:border-box} textarea{height:150px;font-family:monospace} button{padding:15px;font-size:16px;border:none;border-radius:5px;cursor:pointer;font-weight:bold;color:#fff;width:100%;margin-bottom:10px} #btn-validate{background:#28a745} #btn-validate:hover{background:#218838} h3{margin-top:20px;border-bottom:2px solid #eee;padding-bottom:10px;color:#444;font-size:18px} label{font-weight:600;font-size:14px;color:#555;display:block;margin-bottom:5px} .error{border:2px solid #dc3545!important;background:#fff0f0} .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:15px} .grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:15px} @media(max-width:768px){.grid-2,.grid-3{grid-template-columns:1fr;gap:10px} .container{padding:15px;width:100%}} .modal-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:999;display:none;justify-content:center;align-items:center} .modal-content{background:#fff;padding:25px;border-radius:12px;width:90%;max-width:400px;box-shadow:0 5px 15px rgba(0,0,0,0.3)} .modal-title{font-size:1.2rem;font-weight:bold;margin-bottom:15px;color:#dc3545} .modal-list{margin-bottom:20px;padding-left:20px;color:#333} .modal-actions{display:flex;flex-direction:column;gap:10px} #btn-modal-back{background:#6c757d} #btn-modal-proceed{background:#007bff} .tag{display:inline-block;background:#e9ecef;color:#333;padding:8px 14px;border-radius:20px;margin:4px;font-size:14px;border:1px solid #ddd} .tag span{margin-left:10px;cursor:pointer;color:#dc3545;font-weight:bold} #exec-list{max-height:200px;overflow-y:auto;border:1px solid #eee;border-radius:4px;margin-bottom:10px} #exec-list div{padding:12px;border-bottom:1px solid #f0f0f0;cursor:pointer;display:flex;justify-content:space-between} #exec-list div:hover{background:#f8f9fa;color:#007bff} .area-badge{color:#999;font-size:0.9em} .back-btn{background:#007bff;text-decoration:none;display:block;color:white;padding:15px;border-radius:5px;text-align:center;margin-bottom:10px;font-weight:bold}</style></head>
<body><div id="modal-overlay" class="modal-overlay"><div class="modal-content"><div class="modal-title">Campos Vazios</div><p>Faltam preencher:</p><ul id="modal-list" class="modal-list"></ul><div class="modal-actions"><button id="btn-modal-back" type="button">Voltar</button><button id="btn-modal-proceed" type="button">Gerar Assim Mesmo</button></div></div></div>
<div class="container"><form method="post" action="/generate" target="_blank"><input type="hidden" name="lat" value="{{ data.get('lat','') }}"><input type="hidden" name="lon" value="{{ data.get('lon','') }}">
<div class="grid-3"><input type="hidden" name="or_ot" value="{{ data.get('or_ot','') }}"><div><label>TA</label><input name="ta" value="{{ data.get('ta','') }}"></div><div><label>Código Obra (SGM)</label><input name="codigo_obra" value="{{ data.get('codigo_obra','') }}"></div></div>
<label>Causa</label><input name="causa" value="{{ data.get('causa','') }}"><label>Endereço</label><input name="endereco" value="{{ data.get('endereco','') }}">
<div class="grid-3"><div><label>Localidade</label><input name="localidade" value="{{ data.get('localidade','') }}"></div><div><label>ES</label><input name="es" value="{{ data.get('es','') }}"></div><div><label>AT</label><input name="at" value="{{ data.get('at','') }}"></div></div>
<div class="grid-2"><div><label>Tronco</label><input name="tronco" value="{{ data.get('tronco','') }}"></div><div><label>Veículo</label><input name="veiculo" value="{{ data.get('veiculo','') }}"></div></div>
<div class="grid-2"><div><label>Supervisor</label><input name="supervisor" value="{{ data.get('supervisor','') }}"></div><div><label>Data</label><input name="data" value="{{ data.get('data','') }}"></div></div>
<h3>Executantes</h3><div id="exec-tags" style="margin-bottom:10px"></div><input id="exec-input" placeholder="Buscar técnico ou RE na nuvem..."><div id="exec-list"></div><input type="hidden" name="executantes" id="exec-hidden">
<h3>Tratativas</h3><textarea name="itens">{{ itens_texto }}</textarea><div style="margin-top:30px"><button id="btn-validate" type="submit">Gerar PDF Final</button><a href="/" class="back-btn">Voltar para Início</a></div></form></div>
<script>document.addEventListener('DOMContentLoaded', () => { let tecnicos = []; let selecionados = {{ executantes_list|tojson }}; let veiculosMap = {{ veiculos_map|tojson }}; fetch('/tecnicos').then(r => r.json()).then(d => { tecnicos = d; console.log("Base de técnicos carregada!"); }); const form = document.querySelector('form'); const input = document.getElementById('exec-input'); const list = document.getElementById('exec-list'); const hidden = document.getElementById('exec-hidden'); const tagsBox = document.getElementById('exec-tags'); const inputVeiculo = document.querySelector('input[name="veiculo"]'); const inputSupervisor = document.querySelector('input[name="supervisor"]'); const modalOverlay = document.getElementById('modal-overlay'); const modalList = document.getElementById('modal-list'); const btnValidate = document.getElementById('btn-validate'); const btnModalBack = document.getElementById('btn-modal-back'); const btnModalProceed = document.getElementById('btn-modal-proceed'); function atualizarHidden() { hidden.value = selecionados.join(', '); if (selecionados.length > 0) input.classList.remove('error'); } function renderTags() { tagsBox.innerHTML = ''; selecionados.forEach(nome => { const tag = document.createElement('div'); tag.className = 'tag'; tag.innerHTML = `${nome} <span>×</span>`; tag.querySelector('span').onclick = () => { selecionados = selecionados.filter(n => n !== nome); atualizarHidden(); renderTags(); }; tagsBox.appendChild(tag); }); } renderTags(); atualizarHidden(); input.addEventListener('input', () => { const v = input.value.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, ""); list.innerHTML = ''; if (!v) return; input.classList.remove('error'); const termosBusca = v.split(" ").filter(Boolean); tecnicos.filter(t => { const nomeNorm = t.name.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, ""); const partesNome = nomeNorm.split(" "); const bateuBuscaNome = termosBusca.every(termo => partesNome.some(parte => parte.startsWith(termo))); const reStr = (t.re || "").toLowerCase(); const bateuBuscaRe = termosBusca.some(termo => reStr.includes(termo)); return (bateuBuscaNome || bateuBuscaRe) && !selecionados.includes(t.name); }).slice(0, 8).forEach(t => { const div = document.createElement('div'); div.innerHTML = `<span>${t.name}</span> <span class="area-badge">RE: ${t.re} | Área ${t.area}</span>`; div.onclick = () => { selecionados.push(t.name); const nomeChave = t.name.toLowerCase(); if (veiculosMap[nomeChave] && inputVeiculo.value === "") { inputVeiculo.value = veiculosMap[nomeChave]; inputVeiculo.classList.remove('error'); } if (t.supervisor) { inputSupervisor.value = t.supervisor; inputSupervisor.classList.remove('error'); } atualizarHidden(); renderTags(); input.value = ''; list.innerHTML = ''; }; list.appendChild(div); }); }); document.querySelectorAll('input, textarea').forEach(el => { el.addEventListener('input', function() { if (this.value.trim() !== '') this.classList.remove('error'); }); }); btnValidate.addEventListener('click', (e) => { e.preventDefault(); let missing = []; const fields = [ {name: 'ta', label: 'TA'}, {name: 'codigo_obra', label: 'Código Obra'}, {name: 'causa', label: 'Causa'}, {name: 'endereco', label: 'Endereço'}, {name: 'localidade', label: 'Localidade'}, {name: 'tronco', label: 'Tronco'}, {name: 'veiculo', label: 'Veículo'}, {name: 'supervisor', label: 'Supervisor'}, {name: 'data', label: 'Data'}, {name: 'itens', label: 'Tratativas'} ]; fields.forEach(f => { const el = document.querySelector(`[name="${f.name}"]`); if (!el.value.trim()) { el.classList.add('error'); missing.push(f.label); } }); if (selecionados.length === 0) { input.classList.add('error'); missing.push('Executantes'); } if (missing.length > 0) { modalList.innerHTML = missing.map(i => `<li>${i}</li>`).join(''); modalOverlay.style.display = 'flex'; } else { form.submit(); } }); btnModalBack.addEventListener('click', () => { modalOverlay.style.display = 'none'; }); btnModalProceed.addEventListener('click', () => { modalOverlay.style.display = 'none'; form.submit(); }); });</script></body></html>"""

RELATORIOS_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Relatórios Salvos</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0"><style>
body{font-family:'Segoe UI',sans-serif; background:#f0f2f5; padding:20px; margin:0;}
.container{max-width:1100px; margin:auto; background:#fff; padding:25px; border-radius:10px; box-shadow:0 2px 10px rgba(0,0,0,0.1);}
table{width:100%; border-collapse:collapse; margin-top:10px;}
th, td{border:1px solid #eee; padding:12px; text-align:left; font-size:14px; vertical-align: middle;}
th{background:#f8f9fa; color:#555; font-weight:600;}
input.edit-input{padding:8px; border:1px solid #ccc; border-radius:4px; width:100%; box-sizing:border-box;}
.btn{padding:8px 12px; border:none; border-radius:4px; cursor:pointer; font-weight:bold; font-size:13px;}
.btn-edit{background:#ffc107; color:#212529;}
.btn-del{background:#dc3545; color:#fff;}
.search-container { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; margin-bottom: 20px; }
.search-input { padding: 10px 15px; border: 1px solid #ccc; border-radius: 20px; width: 100%; max-width: 300px; outline: none; transition: 0.3s; font-size: 14px;}
.search-input:focus { border-color: #007bff; box-shadow: 0 0 5px rgba(0,123,255,0.3); }
/* Estilo das Abas */
.nav-tabs { display: flex; border-bottom: 2px solid #ddd; margin-bottom: 25px; }
.nav-tab { padding: 12px 25px; text-decoration: none; color: #555; font-weight: bold; font-size: 15px; margin-bottom: -2px; border-bottom: 3px solid transparent; transition: 0.2s; }
.nav-tab:hover { color: #007bff; }
.nav-tab.active { color: #007bff; border-bottom: 3px solid #007bff; }
</style>
<script>
document.addEventListener('DOMContentLoaded', () => {
    const searchCroquis = document.getElementById('search-croquis');
    if (searchCroquis) {
        searchCroquis.addEventListener('input', function() {
            const filter = this.value.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
            const rows = document.querySelectorAll('#croquis-tbody tr');
            rows.forEach(row => {
                const rowText = row.innerText.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
                row.style.display = rowText.includes(filter) ? '' : 'none';
            });
        });
    }
});

function salvarOrOt(ta, inputElement) {
    let originalBg = inputElement.style.backgroundColor;
    inputElement.style.backgroundColor = '#fff3cd'; 
    let formData = new FormData();
    formData.append('ta', ta); formData.append('or_ot', inputElement.value);
    fetch('/api/update_or_ot', { method: 'POST', body: formData }).then(r => r.json()).then(data => {
        if(data.status === 'success') {
            inputElement.style.backgroundColor = '#d4edda'; 
            setTimeout(() => inputElement.style.backgroundColor = originalBg, 1500);
        } else { inputElement.style.backgroundColor = '#f8d7da'; }
    });
}

function uploadAnexo(ta, inputElement) {
    if(inputElement.files.length === 0) return;
    let formData = new FormData();
    formData.append('ta', ta);
    for(let i=0; i<inputElement.files.length; i++) formData.append('pdf_files', inputElement.files[i]);

    let originalBg = inputElement.parentElement.style.backgroundColor;
    inputElement.parentElement.style.backgroundColor = '#e2e3e5';

    fetch('/api/upload_anexo', { method: 'POST', body: formData }).then(r => r.json()).then(data => {
        if(data.status === 'success') location.reload();
        else { alert('Erro ao enviar anexo.'); inputElement.parentElement.style.backgroundColor = originalBg; }
    });
}

function limparAnexos(ta) {
    if(!confirm('Deseja remover todos os PDFs anexados desta TA?')) return;
    let formData = new FormData(); formData.append('ta', ta);
    fetch('/api/limpar_anexos', { method: 'POST', body: formData }).then(r => r.json()).then(data => {
        if(data.status === 'success') location.reload();
    });
}
</script></head><body><div class="container">

<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
<h2 style="margin:0; color:#333;">Nuvem de Operações</h2><div><a href="/" style="text-decoration:none; color:#007bff; margin-right:15px;">« Gerador</a> <a href="/logout" style="text-decoration:none; color:#dc3545;">Sair</a></div></div>

<div class="nav-tabs">
    <a href="/admin" class="nav-tab">👷 Técnicos & Sistema</a>
    <a href="/relatorios" class="nav-tab active">📋 Relatórios Salvos</a>
</div>

<div class="search-container"><h3 style="color:#444; margin:0;">📋 Gerenciador de Croquis</h3>
<input type="text" id="search-croquis" class="search-input" placeholder="🔍 Buscar por TA, Obra ou Localidade..."></div>
<div style="max-height: 500px; overflow-y: auto; border: 1px solid #eee; border-radius: 4px;">
<table style="margin-top:0; border:none;">
<thead style="position: sticky; top: 0; z-index: 10;">
<tr><th>OR / OT</th><th>TA</th><th>SGM / Obra</th><th>Endereço</th><th>Localidade</th><th style="text-align:center;">Ações</th></tr></thead>
<tbody id="croquis-tbody">
{% for ta, dados in croquis.items() %}
<tr>
    <td style="width: 120px;"><input type="text" class="edit-input" placeholder="Digitar OR..." value="{{ dados.parsed.get('or_ot', '') }}" onchange="salvarOrOt('{{ ta }}', this)" style="padding: 6px; text-align: center; font-weight: bold; color: #007bff;"></td>
    <td><strong>{{ ta }}</strong></td>
    <td>{{ dados.parsed.get('codigo_obra', '-') }}</td>
    <td>{{ dados.parsed.get('endereco', '-') }}</td>
    <td>{{ dados.parsed.get('localidade', '-') }}</td>
    <td style="text-align:center; white-space:nowrap;">
        <input type="file" id="file-{{ ta }}" multiple accept="application/pdf" style="display:none;" onchange="uploadAnexo('{{ ta }}', this)">
        <form method="post" action="/preencher" style="display:inline;" target="_blank"><input type="hidden" name="raw_text" value="{{ ta }}"><button type="submit" class="btn btn-edit" style="margin-right:2px; padding:6px 10px; background:#007bff; color:#fff;" title="Editar">✏️</button></form>
        <button type="button" class="btn" style="padding:6px 10px; background:#6c757d; margin-right:2px;" onclick="document.getElementById('file-{{ ta }}').click()" title="Anexar PDFs">📎 {{ dados.get('anexos', []) | length }}</button>
        {% if dados.get('anexos', []) | length > 0 %}
            <button type="button" class="btn" style="padding:6px 10px; background:#ffc107; color:#000; margin-right:2px;" onclick="limparAnexos('{{ ta }}')" title="Limpar Anexos">🧹</button>
        {% endif %}
        <a href="/gerar_completo/{{ ta }}" target="_blank" class="btn" style="padding:6px 10px; background:#28a745; text-decoration:none; color:#fff; margin-right:2px;" title="Gerar Croqui + Anexos">📄 PDF</a>
        <form method="post" style="display:inline;" onsubmit="return confirm('Apagar os dados da TA {{ ta }} permanentemente?');"><input type="hidden" name="action" value="delete_croqui"><input type="hidden" name="ta" value="{{ ta }}"><button type="submit" class="btn btn-del" style="padding:6px 10px;" title="Apagar do Banco">🗑️</button></form>
    </td>
</tr>
{% else %}<tr><td colspan="6" style="text-align:center; padding:20px; color:#666;">Nenhum croqui salvo na nuvem.</td></tr>{% endfor %}
</tbody></table></div></div></body></html>"""

KML_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gerenciador de KML</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background-color: #f4f4f9; color: #333; padding: 20px; margin: 0; }
        .container { max-width: 900px; margin: 0 auto; background: #fff; padding: 25px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }
        h1, h2, h3 { color: #2c3e50; margin-top: 0; }
        .alert { padding: 12px; margin-bottom: 20px; border-radius: 5px; font-weight: bold; }
        .alert-success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .alert-error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background-color: #2c3e50; color: white; position: sticky; top: 0; }
        tr:hover { background-color: #f5f5f5; }
        .map-link { color: #007bff; text-decoration: none; font-weight: bold; display: block; width: 100%; }
        .map-link:hover { text-decoration: underline; color: #0056b3; }
        .search-container { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; margin-top: 10px;}
        .search-input { padding: 10px 15px; border: 1px solid #ccc; border-radius: 20px; width: 100%; max-width: 350px; outline: none; transition: 0.3s; font-size: 14px;}
        .search-input:focus { border-color: #007bff; box-shadow: 0 0 5px rgba(0,123,255,0.3); }
        .btn-add-site { background-color: #f8f9fa; border: 1px solid #ced4da; color: #495057; font-size: 15px; font-weight: bold; padding: 8px 15px; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 8px; transition: all 0.2s ease-in-out; }
        .btn-add-site:hover { background-color: #e2e6ea; color: #212529; border-color: #adb5bd; }
        .btn-add-site .gear-icon { font-size: 18px; transition: transform 0.3s; }
        .btn-add-site:hover .gear-icon { transform: rotate(90deg); }
        .btn-icon { background: none; border: none; cursor: pointer; font-size: 18px; padding: 5px; transition: 0.2s; border-radius: 4px;}
        .btn-icon:hover { background-color: #e9ecef; transform: scale(1.1); }
        .modal-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 999; display: none; justify-content: center; align-items: center; }
        .modal-content { background: #fff; padding: 25px; border-radius: 12px; width: 90%; max-width: 500px; box-shadow: 0 5px 15px rgba(0,0,0,0.3); position: relative; }
        .close-btn { position: absolute; top: 15px; right: 20px; font-size: 24px; cursor: pointer; color: #888; font-weight: bold; }
        .close-btn:hover { color: #dc3545; }
        .form-group { margin-bottom: 15px; }
        label { display: block; font-weight: bold; margin-bottom: 5px; font-size: 14px;}
        input[type="text"] { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        .btn { background-color: #28a745; color: white; padding: 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; font-weight: bold; width: 100%; margin-top: 10px;}
        .btn:hover { background-color: #218838; }
        .btn-edit-save { background-color: #ffc107; color: #212529; }
        .btn-edit-save:hover { background-color: #e0a800; }
        .table-container { max-height: 60vh; overflow-y: auto; border: 1px solid #eee; border-radius: 4px;} 
    </style>
</head>
<body>

<div id="addModal" class="modal-overlay">
    <div class="modal-content">
        <span class="close-btn" id="closeAddModal">×</span>
        <h3 style="margin-top:0; color:#444; border-bottom: 2px solid #eee; padding-bottom: 10px;">Adicionar Novo Local</h3>
        <form action="{{ url_for('mapa.add') }}" method="POST">
            <div class="form-group"><label>Nome do Local:</label><input type="text" name="name" required placeholder="Ex: SITE_SP_01"></div>
            <div style="display: flex; gap: 10px;">
                <div class="form-group" style="flex: 1;"><label>Latitude:</label><input type="text" name="lat"></div>
                <div class="form-group" style="flex: 1;"><label>Longitude:</label><input type="text" name="lon"></div>
            </div>
            <p style="text-align: center; font-weight: bold; margin: 5px 0; color: #777;">OU</p>
            <div class="form-group"><label>Link do Google Maps:</label><input type="text" name="mapsLink" placeholder="Cole o link do mapa aqui..."></div>
            <button type="submit" class="btn">+ Salvar</button>
        </form>
    </div>
</div>

<div id="editModal" class="modal-overlay">
    <div class="modal-content">
        <span class="close-btn" id="closeEditModal">×</span>
        <h3 style="margin-top:0; color:#444; border-bottom: 2px solid #eee; padding-bottom: 10px;">Editar Local</h3>
        <form action="{{ url_for('mapa.edit') }}" method="POST">
            <input type="hidden" name="original_name" id="editOriginalName">
            <div class="form-group"><label>Nome do Local:</label><input type="text" name="name" id="editName" required></div>
            <div style="display: flex; gap: 10px;">
                <div class="form-group" style="flex: 1;"><label>Latitude:</label><input type="text" name="lat" id="editLat"></div>
                <div class="form-group" style="flex: 1;"><label>Longitude:</label><input type="text" name="lon" id="editLon"></div>
            </div>
            <p style="text-align: center; font-weight: bold; margin: 5px 0; color: #777;">OU</p>
            <div class="form-group"><label>Link do Google Maps (para atualizar coords):</label><input type="text" name="mapsLink" placeholder="Cole o novo link do mapa..."></div>
            <button type="submit" class="btn btn-edit-save">Salvar Alterações</button>
        </form>
    </div>
</div>

<div class="container">
    <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #eee; padding-bottom:15px; margin-bottom:20px;">
        <div style="display:flex; align-items:center; gap: 20px;">
            <h2 style="margin:0;">🗺️ Locais KML</h2>
            <button id="openAddModal" class="btn-add-site" title="Adicionar Novo Local"><span class="gear-icon">⚙️</span> Adicionar novo site</button>
        </div>
        <a href="/" style="text-decoration:none; color:#007bff; font-weight: bold;">« Voltar ao Início</a>
    </div>
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}
    <div class="search-container">
        <h3 style="color:#444; margin:0;">Base de Dados</h3>
        <input type="text" id="searchInput" class="search-input" placeholder="🔍 Buscar local pelo nome...">
    </div>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>Nome do Site</th>
                    <th style="text-align: right; width: 100px;">Ações</th>
                </tr>
            </thead>
            <tbody id="tableBody">
                {% for place in places %}
                <tr>
                    <td>
                        <a href="https://www.google.com/maps?q={{ place.lat }},{{ place.lon }}" target="_blank" class="map-link" title="Abrir no Google Maps">
                            {{ place.name }}
                        </a>
                    </td>
                    <td style="text-align: right; white-space: nowrap;">
                        <button class="btn-icon open-edit" data-name="{{ place.name }}" data-lat="{{ place.lat }}" data-lon="{{ place.lon }}" title="Editar Site">✏️</button>
                        <form action="{{ url_for('mapa.delete') }}" method="POST" style="display:inline;" onsubmit="return confirm('Tem certeza que deseja apagar o site {{ place.name }}?');">
                            <input type="hidden" name="name" value="{{ place.name }}">
                            <button type="submit" class="btn-icon" title="Apagar Site">🗑️</button>
                        </form>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="2" style="text-align: center;">Nenhum local encontrado.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<script>
    const addModal = document.getElementById("addModal");
    document.getElementById("openAddModal").onclick = () => addModal.style.display = "flex";
    document.getElementById("closeAddModal").onclick = () => addModal.style.display = "none";
    const editModal = document.getElementById("editModal");
    document.getElementById("closeEditModal").onclick = () => editModal.style.display = "none";
    document.querySelectorAll('.open-edit').forEach(btn => {
        btn.onclick = function() {
            document.getElementById('editOriginalName').value = this.dataset.name;
            document.getElementById('editName').value = this.dataset.name;
            document.getElementById('editLat').value = this.dataset.lat;
            document.getElementById('editLon').value = this.dataset.lon;
            editModal.style.display = "flex";
        }
    });
    window.onclick = function(event) {
        if (event.target == addModal) addModal.style.display = "none";
        if (event.target == editModal) editModal.style.display = "none";
    }
    document.getElementById('searchInput').addEventListener('input', function() {
        let filter = this.value.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim(); 
        let rows = document.querySelectorAll('#tableBody tr');
        rows.forEach(row => {
            let nomeSite = row.cells[0].textContent.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim();
            row.style.display = nomeSite.includes(filter) ? '' : 'none';
        });
    });
</script>

</body>
</html>"""


# ==========================================
# ROTAS INVISÍVEIS PARA O ROBÔ DO CAPTCHA
# ==========================================
def disparar_robo_login(user, pwd):
    """ Roda o motor do Playwright em uma Thread separada """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(gerar_sessao_interativa(user, pwd))
    loop.close()


@app.route('/api/iniciar_login', methods=['POST'])
def api_iniciar_login():
    user = request.form.get('user')
    pwd = request.form.get('pwd')
    # Limpa os restos mortais de sessões antigas
    for f in ['static/captcha.png', 'static/captcha_answer.txt', 'static/login_status.txt']:
        if os.path.exists(f): os.remove(f)

    # Inicia a Thread que roda o robô sem travar o seu site
    t = threading.Thread(target=disparar_robo_login, args=(user, pwd))
    t.start()
    return jsonify({"status": "ok"})


@app.route('/api/status_login')
def api_status_login():
    # Se o status existe, o robô já terminou o trabalho dele (com sucesso ou erro)
    if os.path.exists('static/login_status.txt'):
        with open('static/login_status.txt', 'r') as f:
            return jsonify({"status": "finalizado", "resultado": f.read().strip()})

    # Se a imagem do captcha existe, ele está parado esperando sua resposta
    if os.path.exists('static/captcha.png'):
        return jsonify({"status": "esperando_captcha", "img": "/static/captcha.png"})

    return jsonify({"status": "carregando"})


@app.route('/api/enviar_captcha', methods=['POST'])
def api_enviar_captcha():
    resposta = request.form.get('captcha')
    # Cria o arquivo texto com a sua resposta para o robô ler
    with open('static/captcha_answer.txt', 'w') as f:
        f.write(resposta)
    return jsonify({"status": "enviado"})


# --- ROTAS NOVAS (ADMINISTRAÇÃO FIREBASE) ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        senha_digitada = request.form.get('senha')
        if senha_digitada == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin'))
        else:
            return render_template_string(LOGIN_HTML, erro=True)
    return render_template_string(LOGIN_HTML, erro=False)


@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('index'))


@app.route('/api/update_or_ot', methods=['POST'])
def api_update_or_ot():
    db = load_db()
    ta = request.form.get('ta')
    or_ot = request.form.get('or_ot', '')

    if ta and 'croquis' in db and ta in db['croquis']:
        db['croquis'][ta]['parsed']['or_ot'] = or_ot
        save_db(db)
        return jsonify({"status": "success"})

    return jsonify({"status": "error"}), 400


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not session.get('admin_logged_in'): return redirect(url_for('login'))
    db = load_db()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            nome = request.form.get('nome', '').strip().lower()
            if nome:
                db['tecnicos'][nome] = {'re': request.form.get('re', '').strip(),
                                        'area': request.form.get('area', '').strip(),
                                        'supervisor': request.form.get('supervisor', '').strip().title()}
                placa = request.form.get('placa', '').strip().upper()
                if placa: db['veiculos'][nome] = placa
                save_db(db)
        elif action == 'edit':
            orig_nome = request.form.get('original_nome')
            new_nome = request.form.get('new_nome', '').strip().lower()
            if orig_nome and new_nome and orig_nome in db['tecnicos']:
                if new_nome != orig_nome:
                    del db['tecnicos'][orig_nome]
                    if orig_nome in db['veiculos']: del db['veiculos'][orig_nome]
                db['tecnicos'][new_nome] = {'re': request.form.get('re', '').strip(),
                                            'area': request.form.get('area', '').strip(),
                                            'supervisor': request.form.get('supervisor', '').strip().title()}
                placa = request.form.get('placa', '').strip().upper()
                if placa:
                    db['veiculos'][new_nome] = placa
                elif new_nome in db['veiculos']:
                    del db['veiculos'][new_nome]
                save_db(db)
        elif action == 'delete':
            nome = request.form.get('nome')
            if nome in db['tecnicos']: del db['tecnicos'][nome]
            if nome in db['veiculos']: del db['veiculos'][nome]
            save_db(db)
        return redirect(url_for('admin'))
    tecnicos_sorted = dict(sorted(db['tecnicos'].items()))
    return render_template_string(ADMIN_HTML, tecnicos=tecnicos_sorted, veiculos=db['veiculos'])


# === NOVA ROTA DA ABA DE RELATÓRIOS ===
@app.route('/relatorios', methods=['GET', 'POST'])
def relatorios():
    if not session.get('admin_logged_in'): return redirect(url_for('login'))
    db = load_db()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete_croqui':
            ta = request.form.get('ta')
            if ta and 'croquis' in db and ta in db['croquis']:
                del db['croquis'][ta]
                save_db(db)
        return redirect(url_for('relatorios'))

    # Ordena os croquis para os mais recentes ficarem no topo (opcional)
    croquis_salvos = dict(sorted(db.get('croquis', {}).items(), reverse=True))
    return render_template_string(RELATORIOS_HTML, croquis=croquis_salvos)

# --- ROTAS PRINCIPAIS ---
@app.route('/')
def index():
    return render_template_string(PASTE_HTML)


@app.route('/tecnicos')
def tecnicos():
    db = load_db()
    return json.dumps(
        [{'name': k, 're': v.get('re', ''), 'area': v.get('area', ''), 'supervisor': v.get('supervisor', '')} for k, v
         in
         db['tecnicos'].items()])


@app.route('/form')
def form_vazio():
    db = load_db()
    return render_template_string(FORM_HTML, data={}, itens_texto="", executantes_list=[], veiculos_map=db['veiculos'])


@app.route('/preencher', methods=['POST'])
def preencher():
    db = load_db()
    raw_text = request.form.get('raw_text', '').strip()

    # 1. VERIFICA SE JÁ EXISTE NA NUVEM (MODO DE EDIÇÃO)
    if raw_text.isdigit() and raw_text in db.get('croquis', {}):
        print(f"♻️ Carregando dados da TA {raw_text} da Nuvem para edição!")
        dados_salvos = db['croquis'][raw_text]
        parsed_data = dados_salvos['parsed']
        raw_mat = dados_salvos['itens_raw']

    # 2. SE NÃO EXISTE, BUSCA AUTOMATICAMENTE NO SIGITM
    elif raw_text.isdigit() and len(raw_text) >= 8:
        print(f"🚀 Iniciando busca automática no SIGITM para a TA: {raw_text}")
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            texto_completo_sigitm = loop.run_until_complete(buscar_dados_ta_sigitm(raw_text))
            loop.close()

            if texto_completo_sigitm:
                parsed_data, raw_mat = extract_fields_sigitm(texto_completo_sigitm, db)
                parsed_data['ta'] = raw_text
            else:
                flash("Sessão expirada ou erro no SIGITM. Cole o encerramento manualmente.", "error")
                return redirect(url_for('index'))

        except Exception as e:
            print(f"Erro durante a execução do Playwright: {e}")
            flash("Erro ao conectar ao SIGITM.", "error")
            return redirect(url_for('index'))

    # 3. MODO TRADICIONAL (COLANDO TEXTO)
    else:
        parsed_data, raw_mat = extract_fields(raw_text, db)
        ta_encontrada = parsed_data.get('ta')

        if ta_encontrada:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                texto_telegram = loop.run_until_complete(search_telegram_message(ta_encontrada))
                loop.close()

                if texto_telegram:
                    parsed_telegram, _ = extract_fields(texto_telegram, db)
                    for campo in ['es', 'at', 'tronco', 'data']:
                        if not parsed_data[campo] and parsed_telegram[campo]:
                            parsed_data[campo] = parsed_telegram[campo]
            except Exception as e:
                print(f"Erro Telegram: {e}")

    # Organização padronizada
    raw_mat = organizar_tratativas(raw_mat)
    material_lines = [formatar_texto(l.strip()) for l in raw_mat.splitlines() if l.strip()]

    exec_names = [e['name'].title() for e in parsed_data.get('executantes_parsed', [])]
    itens_texto = "\n".join(material_lines)

    return render_template_string(FORM_HTML,
                                  data=parsed_data,
                                  itens_texto=itens_texto,
                                  executantes_list=exec_names,
                                  veiculos_map=db['veiculos'])


@app.route('/generate', methods=['POST'])
def generate():
    db = load_db()
    execs_string = request.form.get('executantes', '')
    exec_list = []
    if execs_string:
        for nome in execs_string.split(','):
            clean = nome.strip().lower()
            if clean in db['tecnicos']:
                re_code = db['tecnicos'][clean].get('re', '')
                parts = clean.split()
                short_name = f"{parts[0].capitalize()} {parts[-1].capitalize()}" if len(
                    parts) > 1 else clean.capitalize()
                exec_list.append({'name': short_name, 're': re_code})
            else:
                exec_list.append({'name': clean.title(), 're': ''})

    parsed = {
        'or_ot': request.form.get('or_ot', ''),
        'ta': request.form.get('ta', ''), 'codigo_obra': request.form.get('codigo_obra', ''),
        'causa': request.form.get('causa', ''), 'endereco': request.form.get('endereco', ''),
        'localidade': request.form.get('localidade', ''), 'es': request.form.get('es', ''),
        'at': request.form.get('at', ''), 'tronco': request.form.get('tronco', ''),
        'veiculo': request.form.get('veiculo', ''), 'data': request.form.get('data', ''),
        'supervisor': request.form.get('supervisor', ''), 'executantes_parsed': exec_list,
        'lat': request.form.get('lat', ''), 'lon': request.form.get('lon', '')
    }

    itens_raw = request.form.get('itens', '')
    itens_raw = organizar_tratativas(itens_raw)
    material_lines = [formatar_texto(l.strip()) for l in itens_raw.splitlines() if l.strip()]

    final_materials = []
    for line in material_lines:
        if ',' in line:
            for p in line.split(','):
                if p.strip(): final_materials.append(formatar_texto(p.strip()))
        else:
            final_materials.append(line)
    material_lines = final_materials

    # === SALVANDO O ESTADO NA NUVEM PARA EDIÇÃO FUTURA ===
    codigo = re.sub(r'[^\w\-]', '', parsed.get('ta') or f"doc_{random.randint(1000, 9999)}")

    db['croquis'][codigo] = {
        'parsed': parsed,
        'itens_raw': itens_raw
    }
    save_db(db)
    # =====================================================

    vts_extra = extrair_vt_sobressalente(material_lines)
    total_extra_vt = sum(v['len'] for v in vts_extra)

    total_len = detect_launch(material_lines)
    is_double_point = False
    if total_len is None and detect_double_point(material_lines):
        is_double_point = True
        total_len = 0

    pp_list = generate_pps(total_len, extra_vt=total_extra_vt) if total_len is not None and total_len > 0 else (
        [0, 0, 0, 0] if is_double_point else [])

    # === GERANDO O PDF NA MEMÓRIA E ENVIANDO AO NAVEGADOR ===
    overlay_stream = create_overlay(parsed, material_lines, pp_list, vts_extra)
    final_pdf_stream = merge_overlay(overlay_stream)

    return send_file(
        final_pdf_stream,
        download_name=f"{codigo}.pdf",
        as_attachment=False,  # Abre no navegador. Se quiser que force download, mude para True.
        mimetype='application/pdf'
    )


# ==========================================
# ROTAS DE ANEXOS E GERAÇÃO COMPLETA
# ==========================================
@app.route('/api/upload_anexo', methods=['POST'])
def api_upload_anexo():
    ta = request.form.get('ta')
    files = request.files.getlist('pdf_files')
    db = load_db()

    if ta and 'croquis' in db and ta in db['croquis']:
        if 'anexos' not in db['croquis'][ta]:
            db['croquis'][ta]['anexos'] = []

        for f in files:
            if f and f.filename.lower().endswith('.pdf'):
                # Converte o arquivo PDF em texto Base64 para salvar no Firebase
                b64_str = base64.b64encode(f.read()).decode('utf-8')
                db['croquis'][ta]['anexos'].append(b64_str)

        save_db(db)
        return jsonify({"status": "success"})

    return jsonify({"status": "error"}), 400


@app.route('/api/limpar_anexos', methods=['POST'])
def api_limpar_anexos():
    ta = request.form.get('ta')
    db = load_db()
    if ta and 'croquis' in db and ta in db['croquis']:
        db['croquis'][ta]['anexos'] = []
        save_db(db)
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 400


@app.route('/gerar_completo/<ta>')
def gerar_completo(ta):
    db = load_db()
    if 'croquis' not in db or ta not in db['croquis']:
        return "Croqui não encontrado na nuvem.", 404

    dados = db['croquis'][ta]
    parsed = dados.get('parsed', {})
    itens_raw = dados.get('itens_raw', '')
    anexos = dados.get('anexos', [])

    # 1. Refaz os cálculos do Croqui a partir dos dados salvos
    material_lines = [formatar_texto(l.strip()) for l in itens_raw.splitlines() if l.strip()]
    final_materials = []
    for line in material_lines:
        if ',' in line:
            for p in line.split(','):
                if p.strip(): final_materials.append(formatar_texto(p.strip()))
        else:
            final_materials.append(line)
    material_lines = final_materials

    vts_extra = extrair_vt_sobressalente(material_lines)
    total_extra_vt = sum(v['len'] for v in vts_extra)
    total_len = detect_launch(material_lines)
    is_double_point = False

    if total_len is None and detect_double_point(material_lines):
        is_double_point = True
        total_len = 0

    pp_list = generate_pps(total_len, extra_vt=total_extra_vt) if total_len is not None and total_len > 0 else (
        [0, 0, 0, 0] if is_double_point else [])

    # 2. Desenha o Croqui na memória
    overlay_stream = create_overlay(parsed, material_lines, pp_list, vts_extra)
    base_pdf_stream = merge_overlay(overlay_stream)

    # 3. Costura os anexos (se existirem)
    if anexos:
        from pdfrw import PdfReader, PdfWriter
        writer = PdfWriter()

        # Adiciona a página do nosso Croqui
        writer.addpages(PdfReader(fdata=base_pdf_stream.read()).pages)

        # Decodifica e adiciona cada anexo que está no Firebase
        for b64 in anexos:
            try:
                pdf_bytes = base64.b64decode(b64)
                writer.addpages(PdfReader(fdata=pdf_bytes).pages)
            except Exception as e:
                print(f"Erro ao mesclar anexo: {e}")

        out_stream = io.BytesIO()
        writer.write(out_stream)
        out_stream.seek(0)
        final_pdf = out_stream
    else:
        base_pdf_stream.seek(0)
        final_pdf = base_pdf_stream

    return send_file(
        final_pdf,
        download_name=f"TA_{ta}_DOSSIE.pdf",
        as_attachment=False,
        mimetype='application/pdf'
    )

if __name__ == '__main__':
    if not os.path.exists(TEMPLATE_PDF):
        c = canvas.Canvas(TEMPLATE_PDF)
        c.drawString(100, 700, "TEMPLATE AUSENTE")
        c.save()
    app.run(debug=True, port=5000)