# kml_manager.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
import xml.etree.ElementTree as ET
import os
import re

# Criamos o Blueprint chamando-o de 'mapa'.
# Todas as rotas dele vão começar com '/mapa' no navegador.
mapa_bp = Blueprint('mapa', __name__, url_prefix='/mapa')

KML_PATH = os.path.join('static', 'SMTXSP_Sites_2023104.kml')

def remove_namespace(tree):
    for elem in tree.iter():
        if '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]
    return tree

def read_kml(file_path):
    if not os.path.exists(file_path):
        return []
    tree = ET.parse(file_path)
    tree = remove_namespace(tree)
    root = tree.getroot()
    placemarks = root.findall(".//Placemark")
    places = []
    for pm in placemarks:
        name_tag = pm.find("name")
        coords_tag = pm.find(".//coordinates")
        if name_tag is not None and name_tag.text:
            place_name = name_tag.text.strip()
        else:
            place_name = "Sem Nome"
        if coords_tag is not None and coords_tag.text:
            try:
                lon, lat, *_ = coords_tag.text.strip().split(",")
                places.append({
                    "name": place_name,
                    "lat": lat.strip(),
                    "lon": lon.strip()
                })
            except ValueError:
                print(f"Erro nas coordenadas de: {place_name}")
    return sorted(places, key=lambda p: p["name"].lower())

def add_placemark(file_path, name, lat, lon):
    tree = ET.parse(file_path)
    tree = remove_namespace(tree)
    root = tree.getroot()
    existing = root.findall(".//Placemark[name='%s']" % name)
    if existing:
        return False
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
    if match:
        return match.group(1), match.group(2)
    return None, None

# Trocamos @app.route por @mapa_bp.route
@mapa_bp.route('/')
def index():
    places = read_kml(KML_PATH)
    # Sugestão: coloque o html dessa parte em uma subpasta "templates/mapa/index.html"
    return render_template('mapa/index.html', places=places)

@mapa_bp.route('/add', methods=['POST'])
def add():
    name = request.form['name'].upper()
    lat = request.form.get('lat', '')
    lon = request.form.get('lon', '')

    maps_link = request.form.get('mapsLink')
    if maps_link:
        lat, lon = get_coordinates_from_link(maps_link)
        if not lat or not lon:
            flash("Link do Google Maps inválido.", "error")
            return redirect(url_for('mapa.index')) # <-- ATENÇÃO AQUI: 'mapa.index'

    if not lat or not lon:
        flash("Preencha as coordenadas ou cole um link do Maps.", "error")
        return redirect(url_for('mapa.index'))

    success = add_placemark(KML_PATH, name, lat, lon)
    if success:
        flash("Local adicionado com sucesso!", "success")
    else:
        flash("Já existe um local com esse nome.", "error")

    # <-- ATENÇÃO AQUI: o url_for agora precisa do nome do blueprint
    return redirect(url_for('mapa.index'))