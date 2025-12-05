from flask import Flask, render_template_string, request, send_file
from reportlab.pdfgen import canvas
from reportlab.lib.colors import red, black
from pdfrw import PdfReader, PdfWriter, PageMerge
from pathlib import Path
import re, random, os

app = Flask(__name__)
app.secret_key = "chave_secreta_segura"

# NOME DO ARQUIVO PDF DE FUNDO
TEMPLATE_PDF = "CROQUI.pdf"
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

# --- CONFIGURAÇÃO: MODO DE CALIBRAÇÃO ---
DEBUG_MODE = False

# --- CONFIGURAÇÃO: BANCO DE DADOS DE TÉCNICOS (NOME -> RE) ---
DB_TECNICOS = {
    "aguinaldo": "1538837",
    "alessandro": "7455011",
    "cleiton": "7885997",
    "emerson": "7896018",
    "julio": "7456263",
    "leandro": "7801963",
    "pablo": "7876084",
    "roger": "776287",
    "leonardo": "8068992",
    "lucas": "Sem RE",
    "joaquim": "Sem RE",
    "marcos": "Sem RE",
    "wellington": "Sup. 1234"
}

# ----------------------------
# 1. Configurações de Posição
# ----------------------------
COORDS = {
    'codigo_obra': (0.18, 0.039),
    'ta': (0.18, 0.210),

    'causa': (0.17, 0.152),

    'endereco': (0.17, 0.125),

    'localidade': (0.11, 0.096),
    'es': (0.28, 0.096),
    'at': (0.34, 0.096),

    'tronco': (0.10, 0.067),

    'executantes': (0.47, 0.212),

    'veiculo': (0.47, 0.040),
    'supervisor': (0.63, 0.040),
    'data': (0.83, 0.049),

    'materials_block': (0.045, 0.33),
    'croqui_rect': (0.02, 0.65, 0.95, 0.90)
}

EXEC_CONFIG = {
    'name_x': 0.47,
    're_x': 0.65,
    'start_y': 0.212,
    'step_y': 0.028,
    'max_rows': 6
}


# ----------------------------
# 2. Funções Auxiliares
# ----------------------------
def pct_to_pt(xpct, ypct, width_pt, height_pt):
    return xpct * width_pt, ypct * height_pt


def get_re_for_name(name):
    first_name = name.strip().split(' ')[0].lower()
    return DB_TECNICOS.get(first_name, "")


def extract_fields(text):
    kw_fields = [
        (r"t\.?a\.?\s*[:\-]?\s*([0-9]{5,})", 'ta'),
        (r"c[oó]digo\s+de\s+obra\s*[:\-]?\s*([0-9]{6,})", 'codigo_obra'),
        (r"causa\s*[:\-]?\s*(.+)", 'causa'),
        (r"end[eê]re[cç]o\s*[:\-]?\s*(.+)", 'endereco'),
        (r"tronco\s*[:\-]?\s*([0-9]+)", 'tronco'),
        (r"prim\s*[:\-]?\s*(.+)", 'prim'),
        (r"dist\.?\s*[:\-]?\s*(.+)", 'dist'),
        (r"executantes?\s*[:\-]?\s*(.+)", 'executantes_raw'),
        (r"ve[ií]culo\s*[:\-]?\s*(\S+)", 'veiculo'),
        (r"data\s*[:\-]?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", 'data'),
    ]

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    joined = "\n".join(lines)
    data = {key: '' for _, key in kw_fields}

    for pattern, key in kw_fields:
        m = re.search(pattern, joined, re.IGNORECASE)
        if m:
            data[key] = m.group(1).strip()

    localidade_match = re.search(r"localidade\s*[:\-]?\s*(.*?)(?:\s+ES\s+|$)", joined, re.IGNORECASE)
    if localidade_match:
        data['localidade'] = localidade_match.group(1).strip()

    es_match = re.search(r"\bES\s*[:\-]?\s*(\S+)", joined, re.IGNORECASE)
    if es_match:
        data['es'] = es_match.group(1).strip()

    at_match = re.search(r"\bAT\s*[:\-]?\s*(\S+)", joined, re.IGNORECASE)
    if at_match:
        data['at'] = at_match.group(1).strip()

    if not data.get('prim'):
        prim_m = re.search(r"\bPRIM\s*[:\-]?\s*(\S+)", joined, re.IGNORECASE)
        if prim_m:
            data['prim'] = prim_m.group(1)

    if not data.get('dist'):
        dist_m = re.search(r"\bDIST\.?\s*[:\-]?\s*(\S+)", joined, re.IGNORECASE)
        if dist_m:
            data['dist'] = dist_m.group(1)

    data['supervisor'] = "Wellington"

    exec_raw = data.get('executantes_raw', '')
    parts = re.split(r'[;,]|\s+e\s+', exec_raw)
    exec_list = []
    for p in parts:
        clean_name = p.strip()
        if clean_name:
            re_code = get_re_for_name(clean_name)
            exec_list.append({'name': clean_name, 're': re_code})
    data['executantes_parsed'] = exec_list

    if "Tratativas:" in text:
        material_lines = text.split("Tratativas:")[1].strip().splitlines()
    else:
        material_lines = [l for l in lines if re.match(r'^\d+', l)]

    return data, [l.strip() for l in material_lines if l.strip()]


def detect_launch(material_lines):
    joined = " ".join(material_lines).lower()
    m = re.search(r"([0-9]{1,4})\s*metr[ao]s?", joined)
    if m:
        return int(m.group(1))
    return None


def generate_pps(total_length, vt_each=15):
    usable = total_length - (2 * vt_each)
    if usable <= 0:
        return []
    num_spans = max(1, round(usable / 40))
    span_len = round(usable / num_spans)
    return [span_len] * num_spans


# ----------------------------
# 3. Geração do PDF (Overlay)
# ----------------------------
def create_overlay(parsed, materials_raw, pp_list, overlay_path):
    if not os.path.exists(TEMPLATE_PDF):
        width_pt, height_pt = 595.27, 841.89
    else:
        tpl = PdfReader(TEMPLATE_PDF)
        page0 = tpl.pages[0]
        media = page0.MediaBox
        llx, lly, urx, ury = map(float, media)
        width_pt = urx - llx
        height_pt = ury - lly

    c = canvas.Canvas(str(overlay_path), pagesize=(width_pt, height_pt))

    def put_xy(key, text, size=9, manual_coords=None):
        if not text:
            return

        if manual_coords:
            xpct, ypct = manual_coords
        elif key in COORDS:
            xpct, ypct = COORDS[key]
        else:
            return

        x, y = pct_to_pt(xpct, ypct, width_pt, height_pt)
        c.setFont("Helvetica", size)

        if DEBUG_MODE:
            c.setStrokeColor(red)
            c.rect(x - 2, y - 2, 100, size + 4, fill=0)
            c.setFillColor(red)
            c.setFont("Helvetica", 6)
            c.drawString(x, y + size + 2, f"{key}")
            c.setFillColor(black)
            c.setFont("Helvetica", size)
            c.setStrokeColor(black)

        lines = str(text).split('\n')
        for i, ln in enumerate(lines):
            c.drawString(x, y - (i * (size + 2)), ln)

    # Campos básicos
    for key, val in parsed.items():
        if key not in ['executantes_parsed', 'executantes_raw']:
            put_xy(key, val, size=9)

    # Executantes
    execs = parsed.get('executantes_parsed', [])
    for i, item in enumerate(execs):
        if i >= EXEC_CONFIG['max_rows']:
            break
        current_y = EXEC_CONFIG['start_y'] - (i * EXEC_CONFIG['step_y'])
        put_xy(f"exec_{i}", item['name'], size=9,
               manual_coords=(EXEC_CONFIG['name_x'], current_y))
        if item['re']:
            put_xy(f"re_{i}", item['re'], size=9,
                   manual_coords=(EXEC_CONFIG['re_x'], current_y))

    # Materiais
    mxp, myp = COORDS['materials_block']
    mx, my = pct_to_pt(mxp, myp, width_pt, height_pt)
    c.setFont('Helvetica', 8)
    for i, line in enumerate(materials_raw[:20]):
        c.drawString(mx, my - (i * 10), line)

    # Croqui
    left_pct, bottom_pct, right_pct, top_pct = COORDS['croqui_rect']

    draw_y = height_pt * ((top_pct + bottom_pct) / 2)
    left_x = width_pt * (left_pct + 0.05)
    right_x = width_pt * (right_pct - 0.05)

    c.setLineWidth(2)
    c.setDash(4, 2)
    c.line(left_x, draw_y, right_x, draw_y)
    c.setDash([])

    c.setFont('Helvetica-Bold', 10)

    # =======================================
    #   *** CASO NÃO HAJA LANÇAMENTO ***
    # → Criar 3 XC (Início - Meio - Fim)
    # =======================================
    if len(pp_list) == 0:
        total_width = right_x - left_x
        mid_x = left_x + total_width / 2

        # XC Início
        c.circle(left_x, draw_y, 4, fill=1)
        c.drawString(left_x - 12, draw_y - 20, "Início")

        # XC Meio
        c.circle(mid_x, draw_y, 4, fill=1)
        c.drawString(mid_x - 8, draw_y - 20, "XC")

        # MOSTRAR SOMENTE UM VT NO MEIO
        c.drawString(mid_x - 12, draw_y + 15, "VT 15m")

        # XC Fim
        c.circle(right_x, draw_y, 4, fill=1)
        c.drawString(right_x - 8, draw_y - 20, "Fim")

        c.showPage()
        c.save()
        return

    # =======================================
    #   *** CASO HAJA LANÇAMENTO NORMAL ***
    # =======================================
    total_width = right_x - left_x
    spans = len(pp_list)
    step = total_width / spans
    current_x = left_x

    # XC inicial
    c.circle(current_x, draw_y, 4, fill=1)
    c.drawString(current_x - 12, draw_y - 20, "Inicio")
    c.drawString(current_x, draw_y + 15, "VT 15m")

    for i, dist in enumerate(pp_list):
        next_x = current_x + step
        mid_x = (current_x + next_x) / 2

        if dist > 0:
            c.drawString(mid_x - 15, draw_y + 5, f"PP {dist}m")

        c.circle(next_x, draw_y, 4, fill=1)

        if i == len(pp_list) - 1:
            c.drawString(next_x - 20, draw_y + 15, "VT 15m")
            c.drawString(next_x - 8, draw_y - 20, "Fim")
        else:
            c.drawString(next_x - 8, draw_y - 20, "XC")

        current_x = next_x

    c.showPage()
    c.save()


# ----------------------------
# 4. Merge e Rotas
# ----------------------------
def merge_overlay(overlay_path, out_path):
    if not os.path.exists(TEMPLATE_PDF):
        os.replace(overlay_path, out_path)
        return

    overlay = PdfReader(str(overlay_path))
    template = PdfReader(TEMPLATE_PDF)

    if len(template.pages) > 0 and len(overlay.pages) > 0:
        merger = PageMerge(template.pages[0])
        merger.add(overlay.pages[0]).render()

    PdfWriter(str(out_path), trailer=template).write()


INDEX_HTML = """
<!doctype html>
<html>
<head>
    <meta charset='utf-8'>
    <title>Gerador CROQUI Telecom</title>
    <style>
        body { font-family: sans-serif; padding: 20px; background: #f0f2f5; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        textarea { width: 100%; height: 300px; padding: 10px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; }
        button { background: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-size: 16px; margin-top: 10px; }
        button:hover { background: #0056b3; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Gerador de Relatórios Telecom</h2>
        <form method='post' action='/generate' target='_blank'>
<textarea name='text'>T.A: 352699234
Causa: Carga alta
Endereço: Rua Larissa Raveli, 102-174
Localidade: Sorocaba ES JAI AT GC
Tronco: 193 PRIM 05 DIST 10
Código de obra: 2025488798
Executantes: Emerson, Pablo
Veiculo: RVQ0G58
Supervisor: Wellington
Data: 12/11/2025

Tratativas:
200 Metros 04 f.o lançado 
01 PTRO
08 Fusões
04 Tubo Loose sem sangria
01 Álcool isopropílico
01 Fita isolante</textarea>
            <br>
            <button type='submit'>Gerar e Visualizar PDF</button>
        </form>
    </div>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(INDEX_HTML)


@app.route('/generate', methods=['POST'])
def generate():
    text = request.form.get('text', '')
    if not text.strip():
        return "Erro: Texto vazio", 400

    parsed, material_lines = extract_fields(text)
    total_len = detect_launch(material_lines)

    if total_len:
        pp_list = generate_pps(total_len)
    else:
        pp_list = []  # sem lançamento → 3 XC

    codigo = parsed.get('codigo_obra') or f"doc_{random.randint(1000, 9999)}"
    codigo = re.sub(r'[^\w\-]', '', codigo)

    overlay_path = OUTPUT_DIR / f"{codigo}_overlay.pdf"
    out_pdf = OUTPUT_DIR / f"{codigo}.pdf"

    create_overlay(parsed, material_lines, pp_list, overlay_path)
    merge_overlay(overlay_path, out_pdf)

    return send_file(str(out_pdf), as_attachment=False)


if __name__ == '__main__':
    if not os.path.exists(TEMPLATE_PDF):
        print(f"AVISO: {TEMPLATE_PDF} não encontrado. Gerando PDF em branco para teste.")

    app.run(debug=True, port=5000)
