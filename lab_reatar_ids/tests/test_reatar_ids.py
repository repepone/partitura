"""Pruebas de reatar_ids.py.

Usan los MEI generados por herramientas/experimento.py con Verovio 6.1.0 y
6.3.0 (carpeta datos/mei). En las variantes «con_ids» cada nota lleva el mismo
id en las dos versiones (se puso en el MusicXML), así que el emparejado
correcto es la identidad: el tiempo del id X debe acabar en el id X.

Ejecutar desde la carpeta lab_reatar_ids:  python -m pytest tests
"""

import copy
import json
import sys
from fractions import Fraction
from pathlib import Path

import pytest
from lxml import etree

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

import reatar_ids as r  # noqa: E402

DATOS = LAB / "datos" / "mei"
PIEZAS = ["mozart_k265_var1", "lilypond_01b_intervalos", "lilypond_24a_adornos",
          "lilypond_46e_anacrusa"]
NS = {"m": r.MEI_NS}


def ruta(pieza, version, variante):
    return DATOS / pieza / ("%s_%s.mei" % (version, variante))


def mapa_de(mei):
    notas, _, _ = r.leer_mei(mei)
    return {n.id: 1000 + 250 * k for k, n in enumerate(notas)}


def escribir(arbol, destino):
    arbol.write(str(destino), xml_declaration=True, encoding="UTF-8")
    return destino


# ---------------------------------------------------------------------------
# Datos reales (Verovio 6.1.0 -> 6.3.0)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pieza", PIEZAS)
def test_con_ids_de_referencia_todo_acierta(pieza):
    viejo, nuevo = ruta(pieza, "v610", "con_ids"), ruta(pieza, "v630", "con_ids")
    mapa = mapa_de(viejo)
    mapa_nuevo, informe = r.reatar(viejo, nuevo, mapa)
    assert mapa_nuevo == mapa  # identidad: cada tiempo vuelve a su id
    res = informe["resumen"]
    assert res["huerfanas"] == 0 and res["ambiguas"] == 0


@pytest.mark.parametrize("pieza", PIEZAS)
def test_ids_aleatorios_todo_emparejado(pieza):
    viejo, nuevo = ruta(pieza, "v610", "sin_ids"), ruta(pieza, "v630", "sin_ids")
    mapa = mapa_de(viejo)
    mapa_nuevo, informe = r.reatar(viejo, nuevo, mapa)
    ids_viejos = {n.id for n in r.leer_mei(viejo)[0]}
    ids_nuevos = {n.id for n in r.leer_mei(nuevo)[0]}
    assert not ids_viejos & ids_nuevos  # los ids cambian entre versiones
    assert len(mapa_nuevo) == len(mapa)
    assert set(mapa_nuevo) == ids_nuevos
    assert sorted(mapa_nuevo.values()) == sorted(mapa.values())


def test_alter_se_empareja_por_posicion_y_se_avisa():
    viejo = ruta("lilypond_01b_intervalos", "v610", "con_ids")
    nuevo = ruta("lilypond_01b_intervalos", "v630", "con_ids")
    mapa = mapa_de(viejo)
    mapa_nuevo, informe = r.reatar(viejo, nuevo, mapa)
    assert mapa_nuevo == mapa
    cambios = informe["altura_cambiada"]
    assert len(cambios) == 55  # medido también con Verovio (getMIDIValuesForElement)
    assert all(c["id_viejo"] == c["id_nuevo"] for c in cambios)
    assert all("emparejada por posición, no por altura" in c["nota"] for c in cambios)
    assert "no por su altura" in informe["aviso_altura"]


def test_ligadura_sigue_ligada():
    viejo = ruta("lilypond_24a_adornos", "v610", "sin_ids")
    nuevo = ruta("lilypond_24a_adornos", "v630", "sin_ids")
    _, informe = r.reatar(viejo, nuevo, mapa_de(viejo))
    lg = informe["resumen"]["ligaduras"]
    assert lg["notas_ligadas_en_viejo"] >= 1
    assert lg["siguen_ligadas_en_nuevo"] == lg["notas_ligadas_en_viejo"]
    assert lg["mismo_papel_inicio_medio_final"] == lg["notas_ligadas_en_viejo"]
    assert lg["ligaduras_conservadas_completas"] == lg["ligaduras_viejas"]


def test_adornos_y_anacrusa_se_leen():
    notas, _, _ = r.leer_mei(ruta("lilypond_24a_adornos", "v630", "con_ids"))
    adornos = [n for n in notas if n.adorno >= 0]
    assert len(adornos) == 15
    # Varias notas de adorno seguidas antes de una nota llevan orden 0, 1, ...
    assert max(n.adorno for n in adornos) >= 1
    notas, _, _ = r.leer_mei(ruta("lilypond_46e_anacrusa", "v630", "con_ids"))
    primera = [n for n in notas if n.compas_ord == 0]
    assert primera and all(n.inicio < Fraction(1, 2) for n in primera)


# ---------------------------------------------------------------------------
# Perturbaciones sobre Mozart: casos que fallan o que piden revisión
# ---------------------------------------------------------------------------


@pytest.fixture
def mozart():
    viejo = ruta("mozart_k265_var1", "v610", "con_ids")
    nuevo = ruta("mozart_k265_var1", "v630", "con_ids")
    return viejo, etree.parse(str(nuevo)), mapa_de(viejo)


def nota(arbol, nid):
    return arbol.find(".//m:note[@xml:id='%s']" % nid,
                      namespaces={"m": r.MEI_NS, "xml": "http://www.w3.org/XML/1998/namespace"})


def hueco(n):
    """Sustituye la nota (o su acorde) por un <space> de la misma duración."""
    el = n.getparent() if etree.QName(n.getparent()).localname == "chord" else n
    sp = etree.Element("{%s}space" % r.MEI_NS, dur=el.get("dur"))
    if el.get("dots"):
        sp.set("dots", el.get("dots"))
    el.addprevious(sp)
    el.getparent().remove(el)


def test_nota_borrada_queda_huerfana(mozart, tmp_path):
    viejo, arbol, mapa = mozart
    hueco(nota(arbol, "gt00003"))
    mapa_nuevo, informe = r.reatar(viejo, escribir(arbol, tmp_path / "n.mei"), mapa)
    assert [h["id_viejo"] for h in informe["huerfanas"]] == ["gt00003"]
    assert mapa_nuevo == {i: t for i, t in mapa.items() if i != "gt00003"}


def test_nota_borrada_sin_hueco_se_alinea_por_secuencia(mozart, tmp_path):
    """Sin hueco, las notas siguientes de la capa adelantan su inicio."""
    viejo, arbol, mapa = mozart
    n = nota(arbol, "gt00003")
    n.getparent().remove(n)
    mapa_nuevo, informe = r.reatar(viejo, escribir(arbol, tmp_path / "n.mei"), mapa)
    assert [h["id_viejo"] for h in informe["huerfanas"]] == ["gt00003"]
    assert mapa_nuevo == {i: t for i, t in mapa.items() if i != "gt00003"}
    assert informe["resumen"]["por_pasada"].get("secuencia", 0) > 0
    assert {x["pasada"] for x in informe["revisar"]} == {"secuencia"}


def test_nota_duplicada_es_ambigua(mozart, tmp_path):
    viejo, arbol, mapa = mozart
    n = nota(arbol, "gt00003")
    capa = n.xpath("ancestor::m:layer", namespaces=NS)[0]
    inicio = {x.id: x for x in r.leer_mei(viejo)[0]}["gt00003"].inicio
    assert inicio == Fraction(3, 16)
    for nid, ncapa in (("duplicada", "9"), ("duplicada2", "8")):
        copia = copy.deepcopy(n)
        copia.set(r.XML_ID, nid)
        nueva = etree.SubElement(capa.getparent(), "{%s}layer" % r.MEI_NS, n=ncapa)
        etree.SubElement(nueva, "{%s}space" % r.MEI_NS, dur="8", dots="1")  # 3/16
        nueva.append(copia)
    hueco(n)
    _, informe = r.reatar(viejo, escribir(arbol, tmp_path / "n.mei"), mapa)
    amb = informe["ambiguas"]
    assert [a["id_viejo"] for a in amb] == ["gt00003"]
    assert sorted(amb[0]["candidatos"]) == ["duplicada", "duplicada2"]


def test_capas_intercambiadas_se_resuelven_sin_capa(mozart, tmp_path):
    viejo, arbol, mapa = mozart
    cambiados = 0
    for pent in arbol.findall(".//m:measure/m:staff", NS):
        capas = pent.findall("m:layer", NS)
        if len(capas) >= 2 and cambiados < 4:
            cambiados += 1
            a, b = capas[0].get("n"), capas[1].get("n")
            capas[0].set("n", b)
            capas[1].set("n", a)
    assert cambiados >= 1
    nuevo = escribir(arbol, tmp_path / "n.mei")
    mapa_nuevo, informe = r.reatar(viejo, nuevo, mapa)
    assert informe["resumen"]["huerfanas"] == 0
    assert informe["resumen"]["por_pasada"].get("sin_capa", 0) > 0
    # Si dos capas tienen la misma nota a la vez, puede cruzarse el par, pero
    # el tiempo es el mismo: se comprueba que cada tiempo cae en su instante.
    v = {n.id: n for n in r.leer_mei(viejo)[0]}
    w = {n.id: n for n in r.leer_mei(str(nuevo))[0]}
    inv = {t: i for i, t in mapa.items()}
    for id_n, t in mapa_nuevo.items():
        assert (w[id_n].compas_ord, w[id_n].inicio) == (v[inv[t]].compas_ord, v[inv[t]].inicio)


def test_compas_insertado_no_desplaza_el_resto(mozart, tmp_path):
    """En música repetitiva, sin alinear compases se emparejaría con el vecino."""
    viejo, arbol, mapa = mozart
    primero = arbol.find(".//m:measure", NS)
    primero.addprevious(etree.Element("{%s}measure" % r.MEI_NS, n="extra"))
    mapa_nuevo, informe = r.reatar(viejo, escribir(arbol, tmp_path / "n.mei"), mapa)
    assert mapa_nuevo == mapa
    assert informe["compases"]["solo_en_nuevo"] == [0]
    assert informe["resumen"]["por_pasada"] == {"exacta": len(mapa)}


def test_compas_borrado_deja_huerfanas_solo_sus_notas(mozart, tmp_path):
    viejo, arbol, mapa = mozart
    compas = arbol.findall(".//m:measure", NS)[3]
    ids_compas = {n.get(r.XML_ID) for n in compas.iter("{%s}note" % r.MEI_NS)}
    compas.getparent().remove(compas)
    mapa_nuevo, informe = r.reatar(viejo, escribir(arbol, tmp_path / "n.mei"), mapa)
    assert {h["id_viejo"] for h in informe["huerfanas"]} == ids_compas
    assert mapa_nuevo == {i: t for i, t in mapa.items() if i not in ids_compas}


def test_nombre_cambiado_se_marca_para_revisar(mozart, tmp_path):
    viejo, arbol, mapa = mozart
    n = nota(arbol, "gt00005")
    n.set("pname", "c" if n.get("pname") != "c" else "d")
    mapa_nuevo, informe = r.reatar(viejo, escribir(arbol, tmp_path / "n.mei"), mapa)
    assert mapa_nuevo == mapa
    assert [x["id_viejo"] for x in informe["revisar"]] == ["gt00005"]


def test_cambio_de_alteracion_se_avisa(mozart, tmp_path):
    viejo, arbol, mapa = mozart
    n = nota(arbol, "gt00005")
    for a in n.findall("m:accid", NS):
        n.remove(a)
    n.set("accid.ges", "s" if n.get("accid.ges") != "s" else "f")
    mapa_nuevo, informe = r.reatar(viejo, escribir(arbol, tmp_path / "n.mei"), mapa)
    assert mapa_nuevo == mapa
    assert [x["id_viejo"] for x in informe["altura_cambiada"]] == ["gt00005"]


def test_id_del_mapa_que_no_es_nota(mozart):
    viejo, arbol, mapa = mozart
    mapa = dict(mapa, inexistente=1)
    nuevo = ruta("mozart_k265_var1", "v630", "con_ids")
    _, informe = r.reatar(viejo, nuevo, mapa)
    assert informe["ids_del_mapa_que_no_son_notas_del_mei_viejo"] == ["inexistente"]


# ---------------------------------------------------------------------------
# Lectura de tiempos en un MEI mínimo
# ---------------------------------------------------------------------------

MEI_MINIMO = """<?xml version="1.0" encoding="UTF-8"?>
<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1">
 <music><body><mdiv><score>
  <scoreDef><staffGrp><staffDef n="1" lines="5"><keySig sig="1s"/></staffDef></staffGrp></scoreDef>
  <section><measure n="1"><staff n="1"><layer n="1">
   <note xml:id="g1" grace="unacc" dur="8" pname="d" oct="5"/>
   <chord xml:id="c1" dur="4"><note xml:id="a2" pname="e" oct="4"/><note xml:id="a1" pname="c" oct="4"/></chord>
   <tuplet num="3" numbase="2">
    <note xml:id="t1" dur="8" pname="f" oct="4"/>
    <note xml:id="t2" dur="8" pname="f" oct="4" accid="n"/>
    <note xml:id="t3" dur="8" pname="f" oct="4"/>
   </tuplet>
   <beam><note xml:id="b1" dur="8" dots="1" pname="g" oct="4"/><note xml:id="b2" dur="16" pname="a" oct="4"/></beam>
  </layer></staff>
  <tie startid="#b1" endid="#b2"/></measure></section>
 </score></mdiv></body></music></mei>
"""


def test_lectura_de_tiempos_acordes_y_alturas(tmp_path):
    f = tmp_path / "m.mei"
    f.write_text(MEI_MINIMO, encoding="utf-8")
    notas, ligaduras, info = r.leer_mei(str(f))
    por_id = {n.id: n for n in notas}
    assert info == {"compases": 1, "notas": 8}
    assert por_id["g1"].adorno == 0 and por_id["g1"].inicio == 0
    # Orden dentro del acorde de grave a agudo, no por orden de documento:
    assert (por_id["a1"].acorde_idx, por_id["a2"].acorde_idx) == (0, 1)
    assert por_id["t1"].inicio == Fraction(1, 4)
    assert por_id["t2"].inicio == Fraction(1, 4) + Fraction(1, 12)
    assert por_id["b1"].inicio == Fraction(1, 2)
    assert por_id["b2"].inicio == Fraction(1, 2) + Fraction(3, 16)
    # Armadura (fa#), becuadro que se arrastra en el compás:
    assert por_id["t1"].midi == 66 and por_id["t2"].midi == 65 and por_id["t3"].midi == 65
    assert ligaduras == {"b1": "i", "b2": "t"}


def test_linea_de_ordenes(tmp_path):
    viejo = ruta("lilypond_24a_adornos", "v610", "sin_ids")
    nuevo = ruta("lilypond_24a_adornos", "v630", "sin_ids")
    mapa = tmp_path / "mapa_viejo.json"
    mapa.write_text(json.dumps(mapa_de(viejo)))
    salida, informe = tmp_path / "mapa_nuevo.json", tmp_path / "informe.json"
    assert r.main([str(viejo), str(nuevo), str(mapa), "-o", str(salida), "-r", str(informe)]) == 0
    assert len(json.loads(salida.read_text())) == 28
    assert json.loads(informe.read_text())["resumen"]["huerfanas"] == 0


# ---------------------------------------------------------------------------
# Alternativa con partitura (se salta si no está instalada)
# ---------------------------------------------------------------------------


def test_metodo_partitura_mozart():
    pytest.importorskip("partitura")
    viejo = ruta("mozart_k265_var1", "v610", "con_ids")
    nuevo = ruta("mozart_k265_var1", "v630", "con_ids")
    mapa = mapa_de(viejo)
    mapa_nuevo, _ = r.reatar(viejo, nuevo, mapa, metodo="partitura")
    assert mapa_nuevo == mapa


def test_metodo_partitura_pierde_la_continuacion_de_ligadura():
    """Medido: el note array de partitura une las notas ligadas."""
    pytest.importorskip("partitura")
    viejo = ruta("lilypond_33b_ligadura", "v610", "con_ids")
    nuevo = ruta("lilypond_33b_ligadura", "v630", "con_ids")
    mapa = mapa_de(viejo)
    _, inf_pos = r.reatar(viejo, nuevo, mapa)
    _, inf_pt = r.reatar(viejo, nuevo, mapa, metodo="partitura")
    finales = {n.id for n in r.leer_mei(viejo)[0] if n.ligada == "t"}
    assert finales
    assert not finales & {h["id_viejo"] for h in inf_pos["huerfanas"]}
    assert finales <= {h["id_viejo"] for h in inf_pt["huerfanas"]}
