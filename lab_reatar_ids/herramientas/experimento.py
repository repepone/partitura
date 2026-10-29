"""Experimento medido: reconvertir con Verovio 6.1.0 y 6.3.0 y reatar ids.

Se ejecuta con el Python del entorno de 6.3.0 (que además tiene partitura) y
llama al Python del entorno de 6.1.0 para sus conversiones:

    python herramientas/experimento.py --py61 /ruta/v61/bin/python \
        --py63 /ruta/v63/bin/python --trabajo /tmp/trabajo \
        [--suite /ruta/lilypondTestSuite]

Para cada pieza:
  1. Prepara el MusicXML sin ids de nota (caso real) y con ids «gtNNNNN»
     (verdad de referencia: Verovio copia el id del <note> al MEI).
  2. Convierte las dos variantes con 6.1.0 y con 6.3.0.
  3. Crea un mapa de sincronía SINTÉTICO para el MEI viejo (tiempos
     inventados, 1000 + 250·k ms en orden de documento: solo sirven para
     comprobar que cada tiempo llega a su nota).
  4. Reata con reatar_ids.py y mide: emparejadas, huérfanas, ambiguas,
     aciertos (con la verdad de referencia), ligaduras y cambios de altura.

Escribe resultados/resultados.json y resultados/tabla.md.
"""

import argparse
import json
import shutil
import subprocess
import sys
import traceback
from collections import Counter
from pathlib import Path

from lxml import etree

AQUI = Path(__file__).resolve().parent
LAB = AQUI.parent
REPO = LAB.parent
sys.path.insert(0, str(LAB))
sys.path.insert(0, str(AQUI))

import reatar_ids  # noqa: E402
from preparar_musicxml import leer as leer_musicxml  # noqa: E402

PIEZAS = [
    {
        "nombre": "mozart_k265_var1",
        "titulo": "Mozart, K. 265, variación 1",
        "fuente": REPO / "tests/data/musicxml/mozart_k265_var1.musicxml",
        "licencia": "Repositorio partitura (Apache-2.0); <rights>Public Domain</rights> en el fichero",
        "redistribuir": True,
    },
    {
        "nombre": "chopin_berceuse_op57",
        "titulo": "Chopin, Berceuse op. 57",
        "fuente": REPO / "tests/data/musicxml/test_part_group.xml",
        "licencia": ("Repositorio partitura (Apache-2.0). Origen declarado en el "
                     "fichero: musescore.com/score/932306; licencia de esa "
                     "codificación SIN COMPROBAR"),
        "redistribuir": False,
    },
    {
        "nombre": "lilypond_01b_intervalos",
        "titulo": "Suite MusicXML de LilyPond, 01b (intervalos con alteraciones)",
        "fuente": LAB / "datos/musicxml/lilypond/01b-Pitches-Intervals.xml",
        "licencia": "MIT (suite de pruebas MusicXML de LilyPond, vía music21)",
        "redistribuir": True,
    },
    {
        "nombre": "lilypond_24a_adornos",
        "titulo": "Suite MusicXML de LilyPond, 24a (notas de adorno)",
        "fuente": LAB / "datos/musicxml/lilypond/24a-GraceNotes.xml",
        "licencia": "MIT (suite de pruebas MusicXML de LilyPond, vía music21)",
        "redistribuir": True,
    },
    {
        "nombre": "lilypond_46e_anacrusa",
        "titulo": "Suite MusicXML de LilyPond, 46e (anacrusa, segunda voz que entra tarde)",
        "fuente": LAB / "datos/musicxml/lilypond/46e-PickupMeasure-SecondVoiceStartsLater.xml",
        "licencia": "MIT (suite de pruebas MusicXML de LilyPond, vía music21)",
        "redistribuir": True,
    },
    {
        # Solo para las pruebas con pytest (ligadura entre compases); no va en la tabla.
        "nombre": "lilypond_33b_ligadura",
        "titulo": "Suite MusicXML de LilyPond, 33b (ligadura entre compases)",
        "fuente": LAB / "datos/musicxml/lilypond/33b-Spanners-Tie.xml",
        "licencia": "MIT (suite de pruebas MusicXML de LilyPond, vía music21)",
        "redistribuir": True,
        "en_tabla": False,
    },
]

# Ficheros de tests/data/musicxml que NO se usan en el barrido por licencia:
EXCLUIDOS_PARTITURA = {
    "test_merge_interpolation.xml",  # Mozart K. 590 de CCARH: «Rights ... reserved»
    "test_ts_map_ts_starts_not_at_zero.xml",  # Bartók, Mikrokosmos: obra no libre en todas partes
}

STEP = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def ejecutar(py, *args):
    r = subprocess.run([str(py), *map(str, args)], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError("Falló %s %s:\n%s" % (py, args, r.stderr[-2000:]))
    return r.stdout


def convertir(py, entrada, salida, *extra):
    salida.parent.mkdir(parents=True, exist_ok=True)
    ejecutar(py, LAB / "convertir.py", entrada, salida, *extra)
    return salida


def alturas(py, mei, trabajo):
    destino = trabajo / (mei.name + ".alturas.json")
    ejecutar(py, AQUI / "alturas_verovio.py", mei, destino)
    with open(destino) as f:
        return json.load(f)["alturas"]


def verdad_musicxml(ruta_con_ids):
    """{gt id: altura MIDI según <pitch>} (None si la alteración es microtonal)."""
    t = leer_musicxml(str(ruta_con_ids))
    out = {}
    for n in t.iter("note"):
        p = n.find("pitch")
        if p is None:
            continue
        alt = float(p.findtext("alter") or 0)
        midi = (int(p.findtext("octave")) + 1) * 12 + STEP[p.findtext("step")] + alt
        out[n.get("id")] = int(midi) if alt == int(alt) else None
    return out


def anacrusas(ruta_con_ids):
    """gt ids de las notas del primer compás si es implícito (anacrusa)."""
    t = leer_musicxml(str(ruta_con_ids))
    ids = set()
    for parte in t.getroot().iter("part"):
        compases = parte.findall("measure")
        if compases and (compases[0].get("implicit") == "yes" or compases[0].get("number") == "0"):
            ids.update(n.get("id") for n in compases[0].iter("note"))
    return ids


def mapa_sintetico(mei):
    notas, _, _ = reatar_ids.leer_mei(mei)
    return {n.id: 1000 + 250 * k for k, n in enumerate(notas)}


def aciertos(mapa_viejo, mapa_nuevo):
    """Con ids de referencia, el tiempo de 'gtX' debe acabar en 'gtX'."""
    bien = sum(1 for i, t in mapa_viejo.items() if mapa_nuevo.get(i) == t)
    mal = sum(1 for i, t in mapa_nuevo.items() if mapa_viejo.get(i) != t)
    return bien, mal


def subconjuntos(mei_viejo, ruta_con_ids):
    notas, _, _ = reatar_ids.leer_mei(mei_viejo)
    grupos = {
        "adorno": {n.id for n in notas if n.adorno >= 0},
        "acorde": {n.id for n in notas if n.acorde_tam > 1},
        "pentagrama_cruzado": {n.id for n in notas if n.pentagrama_cruzado
                               and n.pentagrama_cruzado != n.pentagrama},
        "ligada": {n.id for n in notas if n.ligada},
        "anacrusa": anacrusas(ruta_con_ids) & {n.id for n in notas},
        "capa_2_o_mas": {n.id for n in notas if n.capa not in ("", "1")},
    }
    return grupos


def escribir_ids_en_musicxml(musicxml_con_gt, gt_a_viejo, salida):
    """Ruta B: sustituye cada id 'gtNNNNN' del MusicXML por el id viejo."""
    t = leer_musicxml(str(musicxml_con_gt))
    puestos = 0
    for n in t.iter("note"):
        viejo = gt_a_viejo.get(n.get("id"))
        if viejo:
            n.set("id", viejo)
            puestos += 1
        else:
            n.attrib.pop("id", None)
    t.write(str(salida), xml_declaration=True, encoding="UTF-8")
    return puestos


def medir_pieza(p, a, trabajo):
    nombre = p["nombre"]
    tw = trabajo / nombre
    tw.mkdir(parents=True, exist_ok=True)
    sin_xml, con_xml = tw / "sin_ids.xml", tw / "con_ids.xml"
    ejecutar(sys.executable, AQUI / "preparar_musicxml.py", p["fuente"], sin_xml, con_xml)

    mei = {}
    for ver, py in (("v610", a.py61), ("v630", a.py63)):
        for var, xml in (("sin_ids", sin_xml), ("con_ids", con_xml)):
            mei[(ver, var)] = convertir(py, xml, tw / ("%s_%s.mei" % (ver, var)))

    res = {"pieza": nombre, "titulo": p["titulo"], "licencia": p["licencia"],
           "en_tabla": p.get("en_tabla", True)}

    # --- Caso real: ids aleatorios ---------------------------------------
    viejo, nuevo = mei[("v610", "sin_ids")], mei[("v630", "sin_ids")]
    mapa = mapa_sintetico(viejo)
    mapa_n, inf = reatar_ids.reatar(viejo, nuevo, mapa)
    res["real"] = inf["resumen"]
    res["real"]["notas_mei_viejo"] = inf["mei_viejo"]["notas"]
    res["real"]["notas_mei_nuevo"] = inf["mei_nuevo"]["notas"]
    res["real"]["compases_viejo"] = inf["mei_viejo"]["compases"]
    res["real"]["compases_nuevo"] = inf["mei_nuevo"]["compases"]
    ids_v = {n.id for n in reatar_ids.leer_mei(viejo)[0]}
    ids_n = {n.id for n in reatar_ids.leer_mei(nuevo)[0]}
    res["real"]["ids_de_nota_comunes_entre_versiones"] = len(ids_v & ids_n)

    # --- Verdad de referencia: ids gt iguales en las dos versiones ---------
    viejo_gt, nuevo_gt = mei[("v610", "con_ids")], mei[("v630", "con_ids")]
    notas_v_gt = reatar_ids.leer_mei(viejo_gt)[0]
    notas_n_gt = reatar_ids.leer_mei(nuevo_gt)[0]
    ids_vgt = {n.id for n in notas_v_gt}
    ids_ngt = {n.id for n in notas_n_gt}
    res["ref"] = {
        "notas_con_id_gt_viejo": sum(1 for i in ids_vgt if i.startswith("gt")),
        "notas_con_id_gt_nuevo": sum(1 for i in ids_ngt if i.startswith("gt")),
        "ids_identicos_en_las_dos_versiones": ids_vgt == ids_ngt,
    }
    mapa_gt = mapa_sintetico(viejo_gt)
    mapa_gt_n, inf_gt = reatar_ids.reatar(viejo_gt, nuevo_gt, mapa_gt)
    bien, mal = aciertos(mapa_gt, mapa_gt_n)
    res["ref"]["posicion"] = {"aciertos": bien, "errores": mal,
                              "huerfanas": inf_gt["resumen"]["huerfanas"],
                              "ambiguas": inf_gt["resumen"]["ambiguas"],
                              "por_pasada": inf_gt["resumen"]["por_pasada"]}
    sub = subconjuntos(viejo_gt, con_xml)
    res["ref"]["subconjuntos"] = {
        k: {"notas": len(v), "aciertos": sum(1 for i in v if mapa_gt_n.get(i) == mapa_gt.get(i))}
        for k, v in sub.items()}

    # Alternativa: partitura.load_mei + note arrays.
    try:
        mapa_p, inf_p = reatar_ids.reatar(viejo_gt, nuevo_gt, mapa_gt, metodo="partitura")
        bp, mp = aciertos(mapa_gt, mapa_p)
        res["ref"]["partitura"] = {"aciertos": bp, "errores": mp,
                                   "huerfanas": inf_p["resumen"]["huerfanas"],
                                   "ambiguas": inf_p["resumen"]["ambiguas"]}
    except Exception as e:  # se informa, no se oculta
        res["ref"]["partitura"] = {"error": "%s: %s" % (type(e).__name__, str(e)[:300])}

    # --- Alturas según cada versión de Verovio ----------------------------
    alt_v = alturas(a.py61, viejo_gt, tw)  # lo que sonaba/veía el visor con 6.1.0
    alt_n = alturas(a.py63, nuevo_gt, tw)  # lo que sonará/verá con 6.3.0
    verdad = verdad_musicxml(con_xml)
    comunes = [i for i in alt_v if i in alt_n]
    con_verdad = [i for i in comunes if verdad.get(i) is not None]
    res["alturas"] = {
        "notas_comparadas": len(comunes),
        "cambian_entre_versiones": sum(1 for i in comunes if alt_v[i] != alt_n[i]),
        "notas_con_altura_del_musicxml": len(con_verdad),
        "mal_en_610_segun_musicxml": sum(1 for i in con_verdad if alt_v[i] != verdad[i]),
        "mal_en_630_segun_musicxml": sum(1 for i in con_verdad if alt_n[i] != verdad[i]),
        "microtonales_excluidas": sum(1 for i in comunes if i in verdad and verdad[i] is None),
    }
    # ¿Coincide la aproximación de reatar_ids con lo que dice Verovio?
    aprox_v = {n.id: n.midi for n in notas_v_gt}
    aprox_n = {n.id: n.midi for n in notas_n_gt}
    res["alturas"]["aprox_discrepa_de_verovio_610"] = sum(1 for i in alt_v if aprox_v.get(i) != alt_v[i])
    res["alturas"]["aprox_discrepa_de_verovio_630"] = sum(1 for i in alt_n if aprox_n.get(i) != alt_n[i])
    res["alturas"]["aviso_reatar_con_verovio"] = reatar_ids.reatar(
        viejo_gt, nuevo_gt, mapa_gt, alturas="verovio")[1]["resumen"][
        "altura_cambiada_emparejadas_por_posicion"] if a.alturas_verovio_en_proceso else None

    # --- Ruta B: llevar los ids viejos al MusicXML y reconvertir ------------
    # Primero, viejo (aleatorio) -> gt emparejando dentro de la MISMA versión.
    pares_misma, _ = reatar_ids.emparejar_posicion(reatar_ids.leer_mei(viejo)[0], notas_v_gt)
    gt_a_viejo = {gt: v for v, (gt, _) in pares_misma.items()}
    xml_b = tw / "con_ids_viejos.xml"
    puestos = escribir_ids_en_musicxml(con_xml, gt_a_viejo, xml_b)
    mei_b = convertir(a.py63, xml_b, tw / "v630_ruta_b.mei")
    notas_b = {n.id: n for n in reatar_ids.leer_mei(mei_b)[0]}
    notas_viejas = {n.id: n for n in reatar_ids.leer_mei(viejo)[0]}
    conservados = [i for i in notas_viejas if i in notas_b]
    misma_pos = sum(1 for i in conservados
                    if notas_b[i].clave() == notas_viejas[i].clave()
                    and (notas_b[i].pname, notas_b[i].oct) == (notas_viejas[i].pname, notas_viejas[i].oct))
    res["ruta_b"] = {"ids_puestos_en_musicxml": puestos,
                     "notas_mei_viejo": len(notas_viejas),
                     "ids_viejos_presentes_en_mei_630": len(conservados),
                     "y_en_la_misma_posicion": misma_pos}

    # Copias redistribuibles para las pruebas con pytest.
    if p["redistribuir"]:
        destino = LAB / "datos/mei" / nombre
        destino.mkdir(parents=True, exist_ok=True)
        for (ver, var), ruta in mei.items():
            shutil.copy(ruta, destino / ("%s_%s.mei" % (ver, var)))
        res_dir = LAB / "resultados" / nombre
        res_dir.mkdir(parents=True, exist_ok=True)
        with open(res_dir / "mapa_viejo_sintetico.json", "w") as f:
            json.dump(mapa, f, indent=1)
        with open(res_dir / "mapa_nuevo.json", "w") as f:
            json.dump(mapa_n, f, indent=1)
        with open(res_dir / "informe.json", "w") as f:
            json.dump(inf, f, ensure_ascii=False, indent=1, default=str)
    return res


def barrido(ficheros, a, trabajo):
    """Lo mismo, resumido, sobre muchos ficheros pequeños."""
    filas = []
    for f in ficheros:
        nombre = f.stem
        tw = trabajo / "barrido" / nombre
        tw.mkdir(parents=True, exist_ok=True)
        fila = {"fichero": f.name}
        try:
            sin_xml, con_xml = tw / "sin.xml", tw / "con.xml"
            ejecutar(sys.executable, AQUI / "preparar_musicxml.py", f, sin_xml, con_xml)
            v, n = convertir(a.py61, con_xml, tw / "v610.mei"), convertir(a.py63, con_xml, tw / "v630.mei")
            m = mapa_sintetico(v)
            mn, inf = reatar_ids.reatar(v, n, m)
            bien, mal = aciertos(m, mn)
            ids_n = {x.id for x in reatar_ids.leer_mei(n)[0]}
            fila.update(notas=len(m), aciertos=bien, errores=mal,
                        ids_gt_identicos=(set(m) == ids_n and all(i.startswith("gt") for i in m)),
                        huerfanas=inf["resumen"]["huerfanas"],
                        ambiguas=inf["resumen"]["ambiguas"],
                        revisar=inf["resumen"]["revisar"],
                        altura_cambiada_aprox=inf["resumen"]["altura_cambiada_emparejadas_por_posicion"],
                        ligadas=inf["resumen"]["ligaduras"]["notas_ligadas_en_viejo"],
                        siguen_ligadas=inf["resumen"]["ligaduras"]["siguen_ligadas_en_nuevo"])
            try:
                mp, _ = reatar_ids.reatar(v, n, m, metodo="partitura")
                fila["partitura_aciertos"] = aciertos(m, mp)[0]
            except Exception as e:
                fila["partitura_error"] = type(e).__name__
        except Exception as e:
            fila["error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
        filas.append(fila)
    return filas


def semillas(a, trabajo):
    """¿Los ids son deterministas? ¿Coinciden entre versiones con la misma semilla?"""
    xml = trabajo / "mozart_k265_var1" / "sin_ids.xml"
    tw = trabajo / "semillas"
    tw.mkdir(parents=True, exist_ok=True)
    out = {}

    def ids(ruta):
        return [n.get(reatar_ids.XML_ID) for n in etree.parse(str(ruta)).iter("{%s}note" % reatar_ids.MEI_NS)]

    for etiqueta, extra in (("sin_opciones", []), ("xmlIdSeed_1234", ["--seed", "1234"]),
                            ("xmlIdChecksum", ["--checksum"])):
        r = {}
        for ver, py in (("v610", a.py61), ("v630", a.py63)):
            x1 = ids(convertir(py, xml, tw / ("%s_%s_1.mei" % (ver, etiqueta)), *extra))
            x2 = ids(convertir(py, xml, tw / ("%s_%s_2.mei" % (ver, etiqueta)), *extra))
            r[ver] = {"notas": len(x1), "iguales_entre_dos_ejecuciones": sum(i == j for i, j in zip(x1, x2))}
            r[ver]["_ids"] = x1
        r["iguales_entre_610_y_630_misma_posicion_en_documento"] = sum(
            i == j for i, j in zip(r["v610"]["_ids"], r["v630"]["_ids"]))
        comunes = set(r["v610"]["_ids"]) & set(r["v630"]["_ids"])
        r["ids_610_que_aparecen_en_630"] = len(comunes)
        r["de_ellos_en_otra_nota"] = sum(
            1 for i in comunes if r["v610"]["_ids"].index(i) != r["v630"]["_ids"].index(i))
        for ver in ("v610", "v630"):
            del r[ver]["_ids"]
            arbol = etree.parse(str(tw / ("%s_%s_1.mei" % (ver, etiqueta))))
            r[ver]["elementos_con_xml_id"] = sum(1 for e in arbol.iter() if e.get(reatar_ids.XML_ID))
        out[etiqueta] = r
    return out


def tabla_md(resultados):
    lineas = [
        "| Pieza | Notas viejo / nuevo | Emparejadas | Huérfanas | Ambiguas | Aciertos (ref.) | Errores (ref.) | partitura: aciertos | Ligadas: siguen ligadas | Altura cambia 6.1→6.3 (Verovio) | Mal en 6.1.0 / 6.3.0 vs MusicXML |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in resultados["piezas"]:
        if not r.get("en_tabla", True):
            continue
        re_, rf, al = r["real"], r["ref"], r["alturas"]
        part = rf["partitura"]
        part_txt = ("%d/%d" % (part["aciertos"], re_["ids_en_mapa"])) if "aciertos" in part else "error: " + part["error"].split(":")[0]
        lineas.append("| %s | %d / %d | %d | %d | %d | %d | %d | %s | %d: %d | %d de %d | %d / %d |" % (
            r["titulo"], re_["notas_mei_viejo"], re_["notas_mei_nuevo"], re_["emparejadas"],
            re_["huerfanas"], re_["ambiguas"], rf["posicion"]["aciertos"], rf["posicion"]["errores"],
            part_txt, re_["ligaduras"]["notas_ligadas_en_viejo"], re_["ligaduras"]["siguen_ligadas_en_nuevo"],
            al["cambian_entre_versiones"], al["notas_comparadas"],
            al["mal_en_610_segun_musicxml"], al["mal_en_630_segun_musicxml"]))
    return "\n".join(lineas) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--py61", required=True)
    ap.add_argument("--py63", required=True)
    ap.add_argument("--trabajo", required=True)
    ap.add_argument("--suite", help="carpeta lilypondTestSuite de music21 (opcional)")
    a = ap.parse_args()
    trabajo = Path(a.trabajo)
    trabajo.mkdir(parents=True, exist_ok=True)
    try:
        import verovio
        a.alturas_verovio_en_proceso = verovio.toolkit().getVersion().startswith("6.3")
    except ImportError:
        a.alturas_verovio_en_proceso = False

    resultados = {
        "verovio_610": ejecutar(a.py61, "-c", "import verovio;print(verovio.toolkit().getVersion())").strip(),
        "verovio_630": ejecutar(a.py63, "-c", "import verovio;print(verovio.toolkit().getVersion())").strip(),
        "piezas": [],
    }
    for p in PIEZAS:
        print("Pieza:", p["nombre"], flush=True)
        try:
            resultados["piezas"].append(medir_pieza(p, a, trabajo))
        except Exception:
            traceback.print_exc()
            raise
    resultados["semillas"] = semillas(a, trabajo)

    ficheros = []
    if a.suite:
        ficheros += sorted(Path(a.suite).glob("*.xml"))
    ficheros += sorted(f for f in (REPO / "tests/data/musicxml").iterdir()
                       if f.suffix in (".xml", ".musicxml") and f.name not in EXCLUIDOS_PARTITURA)
    print("Barrido de %d ficheros" % len(ficheros), flush=True)
    filas = barrido(ficheros, a, trabajo)
    con_notas = [f for f in filas if f.get("notas")]
    resultados["barrido"] = {
        "ficheros": len(filas),
        "con_notas": len(con_notas),
        "con_error": [f for f in filas if "error" in f],
        "notas": sum(f["notas"] for f in con_notas),
        "ficheros_con_ids_gt_identicos": sum(1 for f in con_notas if f.get("ids_gt_identicos")),
        "aciertos": sum(f["aciertos"] for f in con_notas),
        "errores": sum(f["errores"] for f in con_notas),
        "huerfanas": sum(f["huerfanas"] for f in con_notas),
        "ambiguas": sum(f["ambiguas"] for f in con_notas),
        "revisar": sum(f["revisar"] for f in con_notas),
        "ligadas": sum(f["ligadas"] for f in con_notas),
        "siguen_ligadas": sum(f["siguen_ligadas"] for f in con_notas),
        "partitura_ficheros_ok": sum(1 for f in con_notas if "partitura_aciertos" in f),
        "partitura_aciertos": sum(f.get("partitura_aciertos", 0) for f in con_notas),
        "partitura_notas_en_ficheros_ok": sum(f["notas"] for f in con_notas if "partitura_aciertos" in f),
        "partitura_errores_por_tipo": dict(Counter(f["partitura_error"] for f in con_notas if "partitura_error" in f)),
        "imperfectos": [f for f in con_notas if f["aciertos"] != f["notas"] or f["errores"]],
        "filas": filas,
    }

    salida = LAB / "resultados"
    salida.mkdir(exist_ok=True)
    with open(salida / "resultados.json", "w") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=1, default=str)
    with open(salida / "tabla.md", "w") as f:
        f.write(tabla_md(resultados))
    print(tabla_md(resultados))
    b = resultados["barrido"]
    print("Barrido: %d ficheros, %d notas, %d aciertos, %d errores, %d huérfanas, %d ambiguas"
          % (b["ficheros"], b["notas"], b["aciertos"], b["errores"], b["huerfanas"], b["ambiguas"]))


if __name__ == "__main__":
    main()
