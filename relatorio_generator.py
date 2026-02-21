from flask import Flask, render_template_string, request, send_from_directory, redirect, url_for, jsonify, session
from reportlab.pdfgen import canvas
from pdfrw import PdfReader, PdfWriter, PageMerge
from pathlib import Path
import re, random, os, json
import asyncio
import textwrap
from telethon import TelegramClient

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

# SENHA PARA ACESSAR A PÁGINA /admin
ADMIN_PASSWORD = "vivo"

# ==========================================
# CONFIGURAÇÕES DO FIREBASE (NUVEM)
# ==========================================
FIREBASE_DB_URL = 'https://geradorcroqui-default-rtdb.firebaseio.com/'

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
        ref = firebase_db.reference('/')
        data = ref.get()
        if not data: return {"tecnicos": {}, "veiculos": {}}
        if 'tecnicos' not in data: data['tecnicos'] = {}
        if 'veiculos' not in data: data['veiculos'] = {}
        return data
    except Exception as e:
        print(f"Erro Firebase: {e}")
        return {"tecnicos": {}, "veiculos": {}}


def save_db(data):
    try:
        ref = firebase_db.reference('/')
        ref.set(data)
    except Exception as e:
        print(f"Erro Save Firebase: {e}")


# --- CONFIGURAÇÕES DE PDF ---
COORDS = {
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
        async with TelegramClient(TELEGRAM_SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
            await client.get_dialogs()
            for group_id in TELEGRAM_GROUP_IDS:
                try:
                    entity = await client.get_entity(group_id)
                    async for message in client.iter_messages(entity, search=ta_number, limit=20):
                        if message.text: return message.text
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


def pct_to_pt(xpct, ypct, width_pt, height_pt): return xpct * width_pt, ypct * height_pt


def organizar_tratativas(texto_bruto):
    texto = re.sub(r'\b(?:feito|realizado)\b', ' ', texto_bruto, flags=re.IGNORECASE)
    texto = re.sub(r'(?=\b(?:lan[cç]ado|lan[cç]amento)\b)', '\n', texto, flags=re.IGNORECASE)
    padrao_num = r'(?=\b(?:\d{1,4}\s*(?:fus[ãa]o|fus[õo]es|testes?|emendas?|ceo|caixas?|aberturas?|reaberturas?|ptro)|vt\s+sobressalente)\b)'
    texto = re.sub(padrao_num, '\n', texto, flags=re.IGNORECASE)
    return texto


def extract_fields(text, db):
    data = {key: '' for key in
            ['ta', 'codigo_obra', 'causa', 'endereco', 'localidade', 'es', 'at', 'tronco', 'veiculo', 'data',
             'supervisor', 'lat', 'lon']}
    text = text.replace('\r\n', '\n').strip()

    m_ta = re.search(r"(?:TA|T\.A\.?|TICKET)\s*[:\-]?\s*\*?(\d{8,})\*?", text, re.IGNORECASE)
    if m_ta:
        data['ta'] = m_ta.group(1)
    else:
        m_loose = re.search(r"\b(35\d{7})\b", text)
        if m_loose: data['ta'] = m_loose.group(1)

    m_sgm = re.search(r"(?:SGM|Obra)[\s:\-]*(\d{8,})", text, re.IGNORECASE)
    if m_sgm: data['codigo_obra'] = m_sgm.group(1)

    m_sigla = re.search(r"\b([A-Z]{3})\.([A-Z0-9]{2})\b", text)
    if m_sigla:
        data['es'] = m_sigla.group(1).upper()
        data['at'] = m_sigla.group(2).upper()
    else:
        if not data['es']:
            m_es = re.search(r"ES\s*[:\-]?\s*([A-Za-z]{3,})", text, re.IGNORECASE)
            if m_es: data['es'] = m_es.group(1).upper()
        if not data['at']:
            m_at = re.search(r"AT\s*[:\-]\s*(\d+)", text, re.IGNORECASE)
            if m_at: data['at'] = m_at.group(1)

    m_cabo = re.search(r"(?:NÚMERO DO CABO|CABO|TRONCO)\s*[:\-]?\s*(\d+)", text, re.IGNORECASE)
    if m_cabo: data['tronco'] = m_cabo.group(1)

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

    data['supervisor'] = "Wellington"
    exec_list = []
    text_lower = text.lower()
    found = set()

    def try_add(term, official):
        if re.search(r"\b" + re.escape(term) + r"\b", text_lower):
            if official not in found:
                found.add(official)
                info = db['tecnicos'].get(official)
                if info: exec_list.append({'name': official, 're': info['re']})

    for off in db['tecnicos']: try_add(off, off)
    for alias, off in DB_ALIASES.items():
        if off not in found and off in db['tecnicos']: try_add(alias, off)

    data['executantes_parsed'] = exec_list

    if not data['veiculo'] and exec_list:
        p = exec_list[0]['name']
        if p in db['veiculos']: data['veiculo'] = db['veiculos'][p]

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


def extrair_vt_sobressalente(linhas):
    vts = []
    for linha in linhas:
        m = re.search(r'vt\s+sobressalente.*?(\d+)\s*(?:m|mt|mts|metros).*?(?:xc|cs)\s*(\d+)', linha, re.IGNORECASE)
        if m:
            vts.append({'len': int(m.group(1)), 'xc': int(m.group(2))})
    return vts


def generate_pps(total_length, vt_each=15, extra_vt=0):
    usable = total_length - (2 * vt_each) - extra_vt
    if usable <= 0: return []
    num_spans = max(1, round(usable / 40))
    return [round(usable / num_spans)] * num_spans


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


def create_overlay(parsed, materials_raw, pp_list, overlay_path, vts_extra=None):
    if vts_extra is None: vts_extra = []
    if not os.path.exists(TEMPLATE_PDF):
        w_pt, h_pt = 595.27, 841.89
    else:
        tpl = PdfReader(TEMPLATE_PDF)
        p0 = tpl.pages[0]
        mb = p0.MediaBox
        w_pt = float(mb[2]) - float(mb[0])
        h_pt = float(mb[3]) - float(mb[1])
    c = canvas.Canvas(str(overlay_path), pagesize=(w_pt, h_pt))

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
        for linha in linhas:
            nova_lista.extend(textwrap.wrap(linha, width=limite))
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

    # --- DETECTAR SUBTERRÂNEO AQUI ---
    joined_materials = " ".join(materials_raw).lower()
    is_subt = "subterraneo" in joined_materials or "subterrâneo" in joined_materials
    pfx = "CS" if is_subt else "XC"

    if len(pp_list) == 0:
        tot_w = rx - lx
        mid = lx + tot_w / 2
        c.circle(lx, dy, 4, fill=1)
        c.drawString(lx - 12, dy - 20, "Início")
        c.circle(mid, dy, 4, fill=1)
        c.drawString(mid - 8, dy - 20, pfx)  # Aplica o prefixo dinâmico
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

        off, bw = 30, 180
        h1 = 15 + 12 + (len(p1_box) * 10)
        bx1, by1 = lx - 20, dy + off
        draw_box(bx1, by1, bw, h1, "Tratativas E1", p1_box)
        c.line(lx, dy, bx1 + bw / 2, by1)

        h2 = 15 + 12 + (len(p2_box) * 10)
        bx2, by2 = rx - bw + 20, dy + off
        draw_box(bx2, by2, bw, h2, "Tratativas E2", p2_box)
        c.line(rx, dy, bx2 + bw / 2, by2)

        step = (rx - lx) / len(pp_list)
        cx = lx
        c.circle(cx, dy, 4, fill=1)
        has_cb = sum(pp_list) > 0
        if has_cb: c.drawString(cx - 10, dy + 15, "VT 15m")
        c.drawString(cx - 10, dy - 20, f"{pfx} Inicial")  # Aplica o prefixo dinâmico

        for i, dist in enumerate(pp_list):
            nx = cx + step
            mid = (cx + nx) / 2
            if dist > 0 and has_cb: c.drawString(mid - 15, dy + 5, f"PP {dist}m")
            c.circle(nx, dy, 4, fill=1)
            if i == len(pp_list) - 1:
                c.drawString(nx - 10, dy - 20, f"{pfx} Final")  # Aplica o prefixo dinâmico
                if has_cb: c.drawString(nx - 10, dy + 15, "VT 15m")
            else:
                c.drawString(nx - 8, dy - 20, pfx)  # Aplica o prefixo dinâmico
            cx = nx

    # --- DESENHO DAS VTs SOBRESSALENTES ---
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


def merge_overlay(overlay_path, out_path):
    if not os.path.exists(TEMPLATE_PDF): os.replace(overlay_path, out_path); return
    overlay = PdfReader(str(overlay_path))
    template = PdfReader(TEMPLATE_PDF)
    if len(template.pages) > 0 and len(overlay.pages) > 0:
        merger = PageMerge(template.pages[0])
        merger.add(overlay.pages[0]).render()
    PdfWriter(str(out_path), trailer=template).write()


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
<br><a href="/" style="color:#666; text-decoration:none;">&laquo; Voltar ao Gerador</a></div></body></html>"""

ADMIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Painel Administrativo</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0"><style>
body{font-family:'Segoe UI',sans-serif; background:#f0f2f5; padding:20px; margin:0;}
.container{max-width:1000px; margin:auto; background:#fff; padding:25px; border-radius:10px; box-shadow:0 2px 10px rgba(0,0,0,0.1);}
h2 {color: #333; margin-top:0;}
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
.form-grid{display:grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap:15px;}
.actions-cell {white-space: nowrap; width: 150px;}
.search-container { display: flex; justify-content: space-between; align-items: center; margin-top: 30px; margin-bottom: 10px; }
.search-input { padding: 10px 15px; border: 1px solid #ccc; border-radius: 20px; width: 100%; max-width: 300px; outline: none; transition: 0.3s; font-size: 14px;}
.search-input:focus { border-color: #007bff; box-shadow: 0 0 5px rgba(0,123,255,0.3); }
@media (max-width: 768px) { .form-grid{grid-template-columns: 1fr;} table {display:block; overflow-x:auto;} .search-container { flex-direction: column; align-items: flex-start; gap: 10px; } .search-input { max-width: 100%; } }
</style><script>
function toggleEdit(rowId) {
    const row = document.getElementById(rowId);
    const spans = row.querySelectorAll('.view-data');
    const inputs = row.querySelectorAll('.edit-input');
    const btnEdit = row.querySelector('.btn-edit');
    const btnSave = row.querySelector('.btn-save');
    const btnCancel = row.querySelector('.btn-cancel');
    const btnDel = row.querySelector('.btn-del');
    let isEditing = inputs[0].style.display !== 'none';
    if (isEditing) { spans.forEach(s => s.style.display = ''); inputs.forEach(i => i.style.display = 'none'); btnEdit.style.display = ''; btnSave.style.display = 'none'; btnCancel.style.display = 'none'; btnDel.style.display = '';
    } else { spans.forEach(s => s.style.display = 'none'); inputs.forEach(i => i.style.display = ''); btnEdit.style.display = 'none'; btnSave.style.display = ''; btnCancel.style.display = ''; btnDel.style.display = 'none'; }
}
document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('search-admin');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            const filter = this.value.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
            const rows = document.querySelectorAll('tbody tr');
            rows.forEach(row => {
                const rowText = row.innerText.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
                if (rowText.includes(filter)) { row.style.display = ''; } else { row.style.display = 'none'; }
            });
        });
    }
});
</script></head><body><div class="container">
<div style="display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #eee; padding-bottom:15px; margin-bottom:20px;">
<h2>⚙️ Gerenciar Técnicos na Nuvem</h2><div><a href="/" style="text-decoration:none; color:#007bff; margin-right:15px;">&laquo; Gerador</a> <a href="/logout" style="text-decoration:none; color:#dc3545;">Sair</a></div></div>
<form method="post" style="background:#f8f9fa; padding:20px; border-radius:8px; border:1px solid #eee;">
<h3 style="margin-top:0; color:#444; margin-bottom:15px;">Adicionar Novo Técnico</h3><input type="hidden" name="action" value="add">
<div class="form-grid"><input type="text" name="nome" class="edit-input" placeholder="Nome Completo" required style="padding:12px;">
<input type="text" name="re" class="edit-input" placeholder="RE" style="padding:12px;">
<input type="text" name="area" class="edit-input" placeholder="Área" style="padding:12px;">
<input type="text" name="placa" class="edit-input" placeholder="Placa" style="padding:12px;"></div>
<button type="submit" class="btn btn-add">+ Salvar Técnico</button></form>
<div class="search-container"><h3 style="color:#444; margin:0;">Técnicos Cadastrados</h3>
<input type="text" id="search-admin" class="search-input" placeholder="🔍 Buscar por nome, RE ou placa..."></div>
<table><thead><tr><th>Nome</th><th>RE</th><th>Área</th><th>Veículo</th><th style="text-align:center;">Ações</th></tr></thead><tbody>
{% for nome, info in tecnicos.items() %}<tr id="row-{{ loop.index }}">
<form method="post"><input type="hidden" name="action" value="edit"><input type="hidden" name="original_nome" value="{{ nome }}">
<td><span class="view-data">{{ nome.title() }}</span><input class="edit-input" name="new_nome" value="{{ nome.title() }}" style="display:none;" required></td>
<td><span class="view-data">{{ info.re }}</span><input class="edit-input" name="re" value="{{ info.re }}" style="display:none;"></td>
<td><span class="view-data">{{ info.area }}</span><input class="edit-input" name="area" value="{{ info.area }}" style="display:none;"></td>
<td><span class="view-data">{{ veiculos.get(nome, '-') }}</span><input class="edit-input" name="placa" value="{{ veiculos.get(nome, '') }}" style="display:none;"></td>
<td class="actions-cell" style="text-align:center;"><button type="button" class="btn btn-edit" onclick="toggleEdit('row-{{ loop.index }}')">Editar</button>
<button type="submit" class="btn btn-save" style="display:none;">Salvar</button><button type="button" class="btn btn-cancel" style="display:none;" onclick="toggleEdit('row-{{ loop.index }}')">Cancelar</button></td></form>
<td style="border-left:none; text-align:center; width: 60px;"><form method="post" style="display:inline;"><input type="hidden" name="action" value="delete">
<input type="hidden" name="nome" value="{{ nome }}"><button type="submit" class="btn btn-del view-data">Excluir</button></form></td></tr>
{% endfor %}</tbody></table></div></body></html>"""

PASTE_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Colar Relatório</title><style>body{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:#f0f2f5;padding:20px;text-align:center;margin:0}.container{width:90%;max-width:700px;margin:20px auto;background:#fff;padding:25px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.1)}textarea{width:100%;height:300px;padding:15px;margin-bottom:20px;border:2px solid #ddd;border-radius:8px;font-size:16px;font-family:monospace;resize:vertical;background-color:#fafafa;box-sizing:border-box}textarea:focus{border-color:#007bff;outline:none;background:#fff}button{width:100%;padding:15px;font-size:18px;background:#007bff;color:#fff;border:none;border-radius:6px;cursor:pointer;transition:0.2s;font-weight:bold;margin-bottom:15px}button:hover{background:#0056b3}h2{color:#333;margin-bottom:10px}.manual-link{display:inline-block;margin-top:15px;color:#666;text-decoration:none;font-size:14px; margin-right:15px;}.manual-link:hover{text-decoration:underline;color:#007bff}.info{color:#666;font-size:14px;margin-bottom:20px}</style></head><body><div class="container"><h2>Gerador de Croquis</h2><p class="info">Cole abaixo o texto do WhatsApp ou do Sistema <strong>GENESIS</strong>.</p><form method="post" action="/preencher"><textarea name="raw_text" placeholder="Cole aqui..."></textarea><br><button type="submit">Processar Texto &raquo;</button></form><div><a href="/form" class="manual-link">Preencher manualmente</a> | <a href="/admin" class="manual-link" style="color:#28a745;">☁️ Painel de Técnicos</a></div></div></body></html>"""

FORM_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Confirmar Dados - Gerador de Croqui</title>
<style>body{font-family:'Segoe UI',sans-serif;background:#f0f2f5;padding:10px;margin:0} .container{width:95%;max-width:900px;margin:10px auto;background:#fff;padding:20px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.05);box-sizing:border-box} input,textarea{width:100%;padding:12px;margin-bottom:15px;border:1px solid #ccc;border-radius:5px;font-size:16px;box-sizing:border-box} textarea{height:150px;font-family:monospace} button{padding:15px;font-size:16px;border:none;border-radius:5px;cursor:pointer;font-weight:bold;color:#fff;width:100%;margin-bottom:10px} #btn-validate{background:#28a745} #btn-validate:hover{background:#218838} h3{margin-top:20px;border-bottom:2px solid #eee;padding-bottom:10px;color:#444;font-size:18px} label{font-weight:600;font-size:14px;color:#555;display:block;margin-bottom:5px} .error{border:2px solid #dc3545!important;background:#fff0f0} .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:15px} .grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:15px} @media(max-width:768px){.grid-2,.grid-3{grid-template-columns:1fr;gap:10px} .container{padding:15px;width:100%}} .modal-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:999;display:none;justify-content:center;align-items:center} .modal-content{background:#fff;padding:25px;border-radius:12px;width:90%;max-width:400px;box-shadow:0 5px 15px rgba(0,0,0,0.3)} .modal-title{font-size:1.2rem;font-weight:bold;margin-bottom:15px;color:#dc3545} .modal-list{margin-bottom:20px;padding-left:20px;color:#333} .modal-actions{display:flex;flex-direction:column;gap:10px} #btn-modal-back{background:#6c757d} #btn-modal-proceed{background:#007bff} .tag{display:inline-block;background:#e9ecef;color:#333;padding:8px 14px;border-radius:20px;margin:4px;font-size:14px;border:1px solid #ddd} .tag span{margin-left:10px;cursor:pointer;color:#dc3545;font-weight:bold} #exec-list{max-height:200px;overflow-y:auto;border:1px solid #eee;border-radius:4px;margin-bottom:10px} #exec-list div{padding:12px;border-bottom:1px solid #f0f0f0;cursor:pointer;display:flex;justify-content:space-between} #exec-list div:hover{background:#f8f9fa;color:#007bff} .area-badge{color:#999;font-size:0.9em} .back-btn{background:#007bff;text-decoration:none;display:block;color:white;padding:15px;border-radius:5px;text-align:center;margin-bottom:10px;font-weight:bold}</style></head>
<body><div id="modal-overlay" class="modal-overlay"><div class="modal-content"><div class="modal-title">Campos Vazios</div><p>Faltam preencher:</p><ul id="modal-list" class="modal-list"></ul><div class="modal-actions"><button id="btn-modal-back" type="button">Voltar</button><button id="btn-modal-proceed" type="button">Gerar Assim Mesmo</button></div></div></div>
<div class="container"><form method="post" action="/generate" target="_blank"><input type="hidden" name="lat" value="{{ data.get('lat','') }}"><input type="hidden" name="lon" value="{{ data.get('lon','') }}">
<h3>Dados Principais</h3><div class="grid-2"><div><label>TA</label><input name="ta" value="{{ data.get('ta','') }}"></div><div><label>Código Obra (SGM)</label><input name="codigo_obra" value="{{ data.get('codigo_obra','') }}"></div></div>
<label>Causa</label><input name="causa" value="{{ data.get('causa','') }}"><label>Endereço</label><input name="endereco" value="{{ data.get('endereco','') }}">
<div class="grid-3"><div><label>Localidade</label><input name="localidade" value="{{ data.get('localidade','') }}"></div><div><label>ES</label><input name="es" value="{{ data.get('es','') }}"></div><div><label>AT</label><input name="at" value="{{ data.get('at','') }}"></div></div>
<div class="grid-2"><div><label>Tronco</label><input name="tronco" value="{{ data.get('tronco','') }}"></div><div><label>Veículo</label><input name="veiculo" value="{{ data.get('veiculo','') }}"></div></div>
<div class="grid-2"><div><label>Supervisor</label><input name="supervisor" value="{{ data.get('supervisor','Wellington') }}"></div><div><label>Data</label><input name="data" value="{{ data.get('data','') }}"></div></div>
<h3>Executantes</h3><div id="exec-tags" style="margin-bottom:10px"></div><input id="exec-input" placeholder="Buscar técnico na nuvem..."><div id="exec-list"></div><input type="hidden" name="executantes" id="exec-hidden">
<h3>Tratativas</h3><textarea name="itens">{{ itens_texto }}</textarea><div style="margin-top:30px"><button id="btn-validate" type="submit">Gerar PDF Final</button><a href="/" class="back-btn">Voltar para Início</a></div></form></div>
<script>document.addEventListener('DOMContentLoaded', () => { let tecnicos = []; let selecionados = {{ executantes_list|tojson }}; let veiculosMap = {{ veiculos_map|tojson }}; fetch('/tecnicos').then(r => r.json()).then(d => { tecnicos = d; console.log("Base de técnicos carregada!"); }); const form = document.querySelector('form'); const input = document.getElementById('exec-input'); const list = document.getElementById('exec-list'); const hidden = document.getElementById('exec-hidden'); const tagsBox = document.getElementById('exec-tags'); const inputVeiculo = document.querySelector('input[name="veiculo"]'); const modalOverlay = document.getElementById('modal-overlay'); const modalList = document.getElementById('modal-list'); const btnValidate = document.getElementById('btn-validate'); const btnModalBack = document.getElementById('btn-modal-back'); const btnModalProceed = document.getElementById('btn-modal-proceed'); function atualizarHidden() { hidden.value = selecionados.join(', '); if (selecionados.length > 0) input.classList.remove('error'); } function renderTags() { tagsBox.innerHTML = ''; selecionados.forEach(nome => { const tag = document.createElement('div'); tag.className = 'tag'; tag.innerHTML = `${nome} <span>&times;</span>`; tag.querySelector('span').onclick = () => { selecionados = selecionados.filter(n => n !== nome); atualizarHidden(); renderTags(); }; tagsBox.appendChild(tag); }); } renderTags(); atualizarHidden(); input.addEventListener('input', () => { const v = input.value.toLowerCase(); list.innerHTML = ''; if (!v) return; input.classList.remove('error'); tecnicos.filter(t => t.name.toLowerCase().includes(v) && !selecionados.includes(t.name)).slice(0, 8).forEach(t => { const div = document.createElement('div'); div.innerHTML = `<span>${t.name}</span> <span class="area-badge">Área ${t.area}</span>`; div.onclick = () => { selecionados.push(t.name); const nomeChave = t.name.toLowerCase(); if (veiculosMap[nomeChave] && inputVeiculo.value === "") { inputVeiculo.value = veiculosMap[nomeChave]; inputVeiculo.classList.remove('error'); } atualizarHidden(); renderTags(); input.value = ''; list.innerHTML = ''; }; list.appendChild(div); }); }); document.querySelectorAll('input, textarea').forEach(el => { el.addEventListener('input', function() { if (this.value.trim() !== '') this.classList.remove('error'); }); }); btnValidate.addEventListener('click', (e) => { e.preventDefault(); let missing = []; const fields = [ {name: 'ta', label: 'TA'}, {name: 'codigo_obra', label: 'Código Obra'}, {name: 'causa', label: 'Causa'}, {name: 'endereco', label: 'Endereço'}, {name: 'localidade', label: 'Localidade'}, {name: 'tronco', label: 'Tronco'}, {name: 'veiculo', label: 'Veículo'}, {name: 'supervisor', label: 'Supervisor'}, {name: 'data', label: 'Data'}, {name: 'itens', label: 'Tratativas'} ]; fields.forEach(f => { const el = document.querySelector(`[name="${f.name}"]`); if (!el.value.trim()) { el.classList.add('error'); missing.push(f.label); } }); if (selecionados.length === 0) { input.classList.add('error'); missing.push('Executantes'); } if (missing.length > 0) { modalList.innerHTML = missing.map(i => `<li>${i}</li>`).join(''); modalOverlay.style.display = 'flex'; } else { form.submit(); } }); btnModalBack.addEventListener('click', () => { modalOverlay.style.display = 'none'; }); btnModalProceed.addEventListener('click', () => { modalOverlay.style.display = 'none'; form.submit(); }); });</script></body></html>"""


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
                                        'area': request.form.get('area', '').strip()}
                placa = request.form.get('placa', '').strip().upper()
                if placa: db['veiculos'][nome] = placa
                save_db(db)
        elif action == 'edit':
            orig_nome = request.form.get('original_nome')
            new_nome = request.form.get('new_nome', '').strip().lower()
            re_code = request.form.get('re', '').strip()
            area = request.form.get('area', '').strip()
            placa = request.form.get('placa', '').strip().upper()
            if orig_nome and new_nome and orig_nome in db['tecnicos']:
                if new_nome != orig_nome:
                    del db['tecnicos'][orig_nome]
                    if orig_nome in db['veiculos']: del db['veiculos'][orig_nome]
                db['tecnicos'][new_nome] = {'re': re_code, 'area': area}
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


# --- ROTAS PRINCIPAIS ---
@app.route('/')
def index(): return render_template_string(PASTE_HTML)


@app.route('/tecnicos')
def tecnicos():
    db = load_db()
    return json.dumps([{'name': k, 'area': v.get('area', '')} for k, v in db['tecnicos'].items()])


@app.route('/form')
def form_vazio():
    db = load_db()
    return render_template_string(FORM_HTML, data={}, itens_texto="", executantes_list=[], veiculos_map=db['veiculos'])


@app.route('/preencher', methods=['POST'])
def preencher():
    db = load_db()
    raw_text = request.form.get('raw_text', '')

    parsed_manual, raw_mat = extract_fields(raw_text, db)

    ta_encontrada = parsed_manual.get('ta')
    if ta_encontrada:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            texto_telegram = loop.run_until_complete(search_telegram_message(ta_encontrada))
            loop.close()

            if texto_telegram:
                parsed_telegram, _ = extract_fields(texto_telegram, db)
                for campo in ['es', 'at', 'tronco', 'data']:
                    if not parsed_manual[campo] and parsed_telegram[campo]:
                        parsed_manual[campo] = parsed_telegram[campo]
        except Exception as e:
            print(f"Erro Telegram: {e}")

    raw_mat = organizar_tratativas(raw_mat)
    material_lines = [formatar_texto(l.strip()) for l in raw_mat.splitlines() if l.strip()]

    exec_names = [e['name'].title() for e in parsed_manual.get('executantes_parsed', [])]
    itens_texto = "\n".join(material_lines)
    return render_template_string(FORM_HTML, data=parsed_manual, itens_texto=itens_texto, executantes_list=exec_names,
                                  veiculos_map=db['veiculos'])


@app.route('/view/<filename>')
def view_pdf(filename): return redirect(url_for('outputs', filename=filename))


@app.route('/outputs/<path:filename>')
def outputs(filename): return send_from_directory(OUTPUT_DIR, filename)


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
        'ta': request.form.get('ta', ''), 'codigo_obra': request.form.get('codigo_obra', ''),
        'causa': request.form.get('causa', ''), 'endereco': request.form.get('endereco', ''),
        'localidade': request.form.get('localidade', ''), 'es': request.form.get('es', ''),
        'at': request.form.get('at', ''), 'tronco': request.form.get('tronco', ''),
        'veiculo': request.form.get('veiculo', ''), 'data': request.form.get('data', ''),
        'supervisor': request.form.get('supervisor', ''), 'executantes_parsed': exec_list,
        'lat': request.form.get('lat', ''), 'lon': request.form.get('lon', '')
    }

    # 1. Pega o texto bruto do formulário
    itens_raw = request.form.get('itens', '')

    # 2. Organiza injetando os "Enters" antes de fatiar
    itens_raw = organizar_tratativas(itens_raw)

    # 3. Fatia o texto (agora já organizado) em uma lista limpa
    material_lines = [formatar_texto(l.strip()) for l in itens_raw.splitlines() if l.strip()]

    final_materials = []
    for line in material_lines:
        if ',' in line:
            for p in line.split(','):
                if p.strip(): final_materials.append(formatar_texto(p.strip()))
        else:
            final_materials.append(line)

    material_lines = final_materials

    # --- INTEGRAÇÃO DA VT SOBRESSALENTE ---
    vts_extra = extrair_vt_sobressalente(material_lines)
    total_extra_vt = sum(v['len'] for v in vts_extra)

    total_len = detect_launch(material_lines)
    is_double_point = False
    if total_len is None and detect_double_point(material_lines):
        is_double_point = True
        total_len = 0

    pp_list = generate_pps(total_len, extra_vt=total_extra_vt) if total_len is not None and total_len > 0 else (
        [0, 0, 0, 0] if is_double_point else [])

    codigo = re.sub(r'[^\w\-]', '', parsed.get('ta') or f"doc_{random.randint(1000, 9999)}")
    overlay_path = OUTPUT_DIR / f"{codigo}_overlay.pdf"
    out_pdf = OUTPUT_DIR / f"{codigo}.pdf"

    create_overlay(parsed, material_lines, pp_list, overlay_path, vts_extra)
    merge_overlay(overlay_path, out_pdf)
    return redirect(url_for('view_pdf', filename=out_pdf.name))


if __name__ == '__main__':
    if not os.path.exists(TEMPLATE_PDF):
        c = canvas.Canvas(TEMPLATE_PDF)
        c.drawString(100, 700, "TEMPLATE AUSENTE")
        c.save()
    app.run(debug=True, port=5000)