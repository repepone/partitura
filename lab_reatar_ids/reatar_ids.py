#!/usr/bin/env python
"""Reata los ids de nota de un MEI viejo a los de un MEI nuevo.

Caso de uso: una partitura MusicXML se convirtió a MEI con una versión de
Verovio (p. ej. 6.1.0) y un mapa de sincronía externo guarda, por cada id de
nota de ese MEI, su tiempo en una grabación (``{id: timeMs}``). Al reconvertir
con otra versión (p. ej. 6.3.0) los ``xml:id`` cambian. Este script empareja
las notas de los dos MEI **por su posición musical** y traduce el mapa.

Uso:
    python reatar_ids.py MEI_viejo MEI_nuevo mapa_viejo.json \
        [-o mapa_nuevo.json] [-r informe.json] [--metodo posicion|partitura]
        [--alturas aprox|verovio]

Método ``posicion`` (por defecto, solo necesita lxml):
    Cada nota recibe una clave de posición:
    (nº de orden del compás, pentagrama, capa, tiempo de inicio dentro del
    compás en fracciones de redonda, orden de adorno, orden dentro del acorde).
    El orden dentro del acorde se cuenta de grave a agudo por *nombre* de nota
    (pname + oct), que no depende de las alteraciones. Las notas cuya altura
    cambió (p. ej. porque Verovio 6.1.0 ignoraba ``<alter>`` del MusicXML) se
    emparejan por posición, NO por altura, y se listan aparte en el informe.

    Antes de emparejar notas se alinean los compases (huella de notas de cada
    compás + difflib), para que un compás añadido o quitado no desplace el
    resto. Después se hacen pasadas sucesivas, cada una sobre lo que quedó
    sin emparejar, y solo se acepta un par si la clave es única en los dos:
      1. «exacta»: clave completa + pname, oct y duración.
      2. «sin_duracion»: clave completa + pname y oct.
      3. «sin_capa»: compás, pentagrama, inicio, adorno, pname, oct, duración
         (capas renumeradas o intercambiadas).
      4. «secuencia»: dentro de cada compás/pentagrama/capa, alinea el orden
         de las notas (difflib); cubre una nota de más o de menos en la capa.
      5. «sin_pentagrama»: compás, inicio, adorno, pname, oct y duración.
      6. «solo_posicion»: la clave completa sin nombre de nota.
    Las pasadas 4 a 6 se listan en 'revisar'. Lo que tiene varios candidatos
    y no se resuelve queda «ambigua»; lo que no tiene ninguno, «huérfana».
    pname y oct son el nombre escrito de la nota, sin alteración: la
    corrección de <alter> no los cambia.

Método ``partitura`` (alternativa, necesita partitura):
    Usa ``partitura.load_mei`` y su note array; empareja por
    (inicio en negras, pentagrama, voz, nombre, octava, adorno y su orden).

El script no adivina: lo que no puede emparejar con una clave única lo
devuelve en el informe para revisarlo a mano.
"""

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from fractions import Fraction

from lxml import etree

MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

PNAMES = "cdefgab"
PNAME_SEMITONO = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
ACCID_SEMITONOS = {
    "s": 1, "f": -1, "ss": 2, "x": 2, "ff": -2, "xs": 3, "ts": 3, "tf": -3,
    "n": 0, "nf": -1, "ns": 1, "su": 1, "sd": 1, "fu": -1, "fd": -1,
    "nu": 0, "nd": 0,
}
DURACIONES = {
    "maxima": Fraction(8), "long": Fraction(4), "breve": Fraction(2),
    "1": Fraction(1), "2": Fraction(1, 2), "4": Fraction(1, 4),
    "8": Fraction(1, 8), "16": Fraction(1, 16), "32": Fraction(1, 32),
    "64": Fraction(1, 64), "128": Fraction(1, 128), "256": Fraction(1, 256),
    "512": Fraction(1, 512), "1024": Fraction(1, 1024), "2048": Fraction(1, 2048),
}
# Elementos de capa que solo agrupan: se recorren sin cambiar el tiempo.
CONTENEDORES = {"beam", "graceGrp", "ligature", "bTrem", "fTrem", "beamSpan"}
# Elementos de capa que ocupan tiempo pero no son notas.
SILENCIOS = {"rest", "space"}


def _local(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else None


@dataclass
class Nota:
    id: str
    compas_ord: int
    compas_n: str
    pentagrama: str
    capa: str
    inicio: Fraction
    adorno: int  # -1 = nota normal; 0, 1, ... = orden de la nota de adorno
    acorde_idx: int  # 0 = fuera de acorde o nota más grave del acorde
    acorde_tam: int
    pname: str
    oct: int
    alter: int  # semitonos de alteración sonora (o None si no se sabe)
    midi: int
    duracion: object = None  # Fraction de redonda (None si el MEI no la da)
    ligada: str = ""  # "", "i" (inicio), "m" (medio), "t" (final)
    pentagrama_cruzado: str = ""
    # Compás en la numeración del MEI viejo, tras alinear compases.
    compas_al: object = None
    # Datos crudos para calcular la altura sonora (no forman parte de la clave).
    _escrito: object = field(default=None, repr=False)
    _gestual: object = field(default=None, repr=False)
    _armadura: dict = field(default_factory=dict, repr=False)
    _oct_ges: int = field(default=0, repr=False)
    _orden: int = field(default=0, repr=False)

    def clave(self):
        c = self.compas_ord if self.compas_al is None else self.compas_al
        return (c, self.pentagrama, self.capa, self.inicio,
                self.adorno, self.acorde_idx)

    def describe(self):
        tipo = "adorno %d" % self.adorno if self.adorno >= 0 else "nota"
        acorde = (" acorde %d/%d" % (self.acorde_idx + 1, self.acorde_tam)
                  if self.acorde_tam > 1 else "")
        return ("compás %s (orden %d), pentagrama %s, capa %s, inicio %s, %s%s, %s%s%d"
                % (self.compas_n, self.compas_ord, self.pentagrama, self.capa,
                   self.inicio, tipo, acorde, self.pname,
                   _alter_txt(self.alter), self.oct))


def _alter_txt(a):
    if a is None:
        return "?"
    return {0: "", 1: "#", -1: "b", 2: "##", -2: "bb"}.get(a, "(%+d)" % a)


# ---------------------------------------------------------------------------
# Lectura del MEI
# ---------------------------------------------------------------------------


def _armadura(sig):
    """'2s' -> {'f': 1, 'c': 1}; '3f' -> {'b': -1, 'e': -1, 'a': -1}."""
    if not sig or sig in ("0", "none", "mixed"):
        return {}
    try:
        n, tipo = int(sig[:-1]), sig[-1]
    except ValueError:
        return {}
    if tipo == "s":
        return {p: 1 for p in "fcgdaeb"[:n]}
    if tipo == "f":
        return {p: -1 for p in "beadgcf"[:n]}
    return {}


def _duracion(el, factor):
    d = el.get("dur")
    if d is None or d not in DURACIONES:
        return None
    base = DURACIONES[d]
    puntos = int(el.get("dots", "0") or 0)
    return base * (2 - Fraction(1, 2 ** puntos)) * factor


def _accid_crudos(nota_el):
    """(gestual, escrito) en semitonos, o None si no están en el MEI."""
    ges = nota_el.get("accid.ges")
    esc = nota_el.get("accid")
    for a in nota_el.iter("{%s}accid" % MEI_NS):
        ges = ges or a.get("accid.ges")
        esc = esc or a.get("accid")
    conv = lambda v: ACCID_SEMITONOS.get(v, 0) if v else None
    return conv(ges), conv(esc)


def _calcular_alturas(notas, ligaduras_inicio):
    """Altura sonora de cada nota, con las reglas habituales de MEI.

    Por orden: @accid.ges; si no, @accid escrito; si no, y la nota es final de
    ligadura, la alteración de la nota de la que viene; si no, la última
    alteración escrita en el mismo compás, pentagrama y capa para ese
    pname+oct (Verovio 6.3.0 arrastra por capa: medido con
    getMIDIValuesForElement); si no, la armadura vigente. Es una aproximación:
    sirve para *avisar* de cambios de altura, no para afinar.
    """
    por_id = {}
    grupos = defaultdict(list)
    for n in notas:
        grupos[(n.compas_ord, n.pentagrama, n.capa)].append(n)
    for clave in sorted(grupos):
        arrastre = {}
        for n in sorted(grupos[clave], key=lambda n: (n.inicio, n.adorno < 0, n._orden)):
            origen = por_id.get(ligaduras_inicio.get(n.id))
            if n._gestual is not None:
                alter = n._gestual
            elif n._escrito is not None:
                alter = n._escrito
            elif origen is not None:
                alter = origen.alter
            elif (n.pname, n.oct) in arrastre:
                alter = arrastre[(n.pname, n.oct)]
            else:
                alter = n._armadura.get(n.pname, 0)
            if n._escrito is not None:
                arrastre[(n.pname, n.oct)] = n._escrito
            n.alter = alter
            n.midi = (n._oct_ges + 1) * 12 + PNAME_SEMITONO.get(n.pname, 0) + alter
            por_id[n.id] = n


def leer_mei(ruta):
    """Devuelve (lista de Nota, dict de ligaduras {id: rol}, info)."""
    arbol = etree.parse(ruta)
    raiz = arbol.getroot()
    ns = {"m": MEI_NS}
    notas = []
    armaduras = defaultdict(dict)  # pentagrama -> {pname: alter}
    armadura_global = {}

    def actualizar_armaduras(el):
        nonlocal armadura_global
        tag = _local(el)
        if tag == "scoreDef":
            sig = el.get("key.sig") or el.get("keysig")
            ks = el.find("m:keySig", ns)
            if ks is not None:
                sig = ks.get("sig", sig)
            if sig is not None:
                armadura_global = _armadura(sig)
                armaduras.clear()
        for sd in el.iter("{%s}staffDef" % MEI_NS):
            sig = sd.get("key.sig") or sd.get("keysig")
            ks = sd.find("m:keySig", ns)
            if ks is not None:
                sig = ks.get("sig", sig)
            if sig is not None:
                armaduras[sd.get("n")] = _armadura(sig)

    compas_ord = -1
    cuerpo = raiz.find(".//m:music/m:body", ns)
    if cuerpo is None:
        cuerpo = raiz
    for el in cuerpo.iter():
        tag = _local(el)
        if tag in ("scoreDef", "staffDef") and el.getparent() is not None \
                and _local(el.getparent()) in ("section", "score", "ending"):
            actualizar_armaduras(el)
        if tag != "measure":
            continue
        compas_ord += 1
        compas_n = el.get("n", "")
        for pent in el.findall("m:staff", ns):
            pn = pent.get("n", "")
            for capa in pent.findall("m:layer", ns):
                cn = capa.get("n", "")
                arm = armaduras.get(pn, armadura_global)
                ctx = {"adorno_t": None, "adorno_k": 0}
                _recorrer_capa(capa, Fraction(0), Fraction(1), False, notas, ctx,
                               compas_ord, compas_n, pn, cn, arm)

    ligaduras = _leer_ligaduras(raiz)
    for n in notas:
        n.ligada = ligaduras.get(n.id, "")
    _calcular_alturas(notas, {b: a for a, b in aristas_ligadura(raiz)})
    info = {"compases": compas_ord + 1, "notas": len(notas)}
    return notas, ligaduras, info


def _recorrer_capa(el, t, factor, adorno_padre, notas, ctx, c_ord, c_n, pn, cn, arm):
    for hijo in el:
        tag = _local(hijo)
        if tag is None:
            continue
        if tag in ("staffDef", "keySig"):
            sig = hijo.get("key.sig") or hijo.get("sig")
            if sig is not None:
                arm = _armadura(sig)
            continue
        es_adorno = adorno_padre or hijo.get("grace") is not None
        if tag == "note":
            dur = _duracion(hijo, factor)
            _registrar([hijo], t, dur, es_adorno, notas, ctx, c_ord, c_n, pn, cn, arm)
            if not es_adorno and dur is not None:
                t += dur
        elif tag == "chord":
            dur = _duracion(hijo, factor)
            miembros = hijo.findall("{%s}note" % MEI_NS)
            if dur is None and miembros:
                dur = _duracion(miembros[0], factor)
            _registrar(miembros, t, dur, es_adorno, notas, ctx, c_ord, c_n, pn, cn, arm)
            if not es_adorno and dur is not None:
                t += dur
        elif tag in SILENCIOS:
            dur = _duracion(hijo, factor)
            if dur is not None:
                t += dur
        elif tag == "tuplet":
            num = int(hijo.get("num", "1") or 1)
            numbase = int(hijo.get("numbase", "1") or 1)
            t = _recorrer_capa(hijo, t, factor * Fraction(numbase, num), es_adorno,
                               notas, ctx, c_ord, c_n, pn, cn, arm)
        elif tag in CONTENEDORES:
            t = _recorrer_capa(hijo, t, factor, es_adorno, notas, ctx,
                               c_ord, c_n, pn, cn, arm)
        # mRest, mSpace, clef, barLine, etc.: no aportan notas
    return t


def _registrar(miembros, t, dur, es_adorno, notas, ctx, c_ord, c_n, pn, cn, arm):
    if es_adorno:
        if ctx["adorno_t"] != t:
            ctx["adorno_t"], ctx["adorno_k"] = t, 0
        adorno = ctx["adorno_k"]
        ctx["adorno_k"] += 1
    else:
        adorno = -1
        ctx["adorno_t"], ctx["adorno_k"] = None, 0

    def paso(n):
        p = n.get("pname", "c")
        o = int(n.get("oct", "4") or 4)
        return o * 7 + (PNAMES.index(p) if p in PNAMES else 0)

    orden = sorted(range(len(miembros)), key=lambda i: (paso(miembros[i]), i))
    for idx, i in enumerate(orden):
        n = miembros[i]
        nid = n.get(XML_ID)
        if nid is None:
            continue
        pname = n.get("pname", "")
        octava = int(n.get("oct", "0") or 0)
        oct_ges = int(n.get("oct.ges", octava) or octava)
        gestual, escrito = _accid_crudos(n)
        notas.append(Nota(
            id=nid, compas_ord=c_ord, compas_n=c_n, pentagrama=pn, capa=cn,
            inicio=t, adorno=adorno, acorde_idx=idx, acorde_tam=len(miembros),
            pname=pname, oct=octava, alter=None, midi=None, duracion=dur,
            pentagrama_cruzado=n.get("staff", ""),
            _escrito=escrito, _gestual=gestual, _armadura=arm,
            _oct_ges=oct_ges, _orden=len(notas)))


def _leer_ligaduras(raiz):
    """{id de nota: 'i' | 'm' | 't'} a partir de <tie> y de @tie."""
    sale, entra = set(), set()
    for tie in raiz.iter("{%s}tie" % MEI_NS):
        a = (tie.get("startid") or "").lstrip("#")
        b = (tie.get("endid") or "").lstrip("#")
        if a:
            sale.add(a)
        if b:
            entra.add(b)
    roles = {}
    for nid in sale | entra:
        roles[nid] = "m" if (nid in sale and nid in entra) else ("i" if nid in sale else "t")
    for n in raiz.iter("{%s}note" % MEI_NS):
        if n.get("tie") and n.get(XML_ID):
            roles.setdefault(n.get(XML_ID), n.get("tie"))
    return roles


def aristas_ligadura(ruta_o_raiz):
    """Conjunto de pares (id_inicio, id_final) de los <tie> del MEI."""
    raiz = ruta_o_raiz
    if not hasattr(raiz, "iter"):
        raiz = etree.parse(ruta_o_raiz).getroot()
    aristas = set()
    for tie in raiz.iter("{%s}tie" % MEI_NS):
        a = (tie.get("startid") or "").lstrip("#")
        b = (tie.get("endid") or "").lstrip("#")
        if a and b:
            aristas.add((a, b))
    return aristas


# ---------------------------------------------------------------------------
# Emparejado
# ---------------------------------------------------------------------------

def _c(n):
    return n.compas_ord if n.compas_al is None else n.compas_al


PASADAS = [
    # pname + oct son el nombre escrito de la nota, sin alteración: la
    # corrección de <alter> cambia la alteración, no el nombre ni la octava.
    ("exacta", lambda n: n.clave() + (n.pname, n.oct, n.duracion)),
    ("sin_duracion", lambda n: n.clave() + (n.pname, n.oct)),
    ("sin_capa", lambda n: (_c(n), n.pentagrama, n.inicio, n.adorno,
                            n.pname, n.oct, n.duracion)),
    "secuencia",  # alineado por capa, ver _emparejar_secuencias
    ("sin_pentagrama", lambda n: (_c(n), n.inicio, n.adorno, n.pname, n.oct,
                                  n.duracion)),
    # Última pasada: misma posición pero distinto nombre de nota.
    ("solo_posicion", lambda n: n.clave()),
]
# Pasadas cuyo resultado se lista en el informe para revisarlo a mano.
PASADAS_A_REVISAR = {"secuencia", "sin_pentagrama", "solo_posicion"}


def alinear_compases(viejas, nuevas):
    """Empareja los compases del MEI nuevo con los del viejo.

    Cada compás se resume en una huella (sus notas por pentagrama, inicio,
    adorno, nombre, octava y duración, sin alteraciones) y las dos listas de
    huellas se alinean con difflib. Así un compás añadido o quitado en una
    versión no desplaza todo lo que viene detrás (y en música repetitiva no
    se empareja una nota con la del compás vecino). Los tramos distintos de
    igual longitud se emparejan uno a uno.

    Devuelve ({compás nuevo: compás viejo}, info).
    """
    from difflib import SequenceMatcher

    def huellas(notas):
        h = defaultdict(list)
        for n in notas:
            h[n.compas_ord].append((n.pentagrama, n.inicio, n.adorno, n.pname, n.oct, n.duracion))
        total = max(h) + 1 if h else 0
        return [tuple(sorted(h.get(i, []), key=repr)) for i in range(total)]

    hv, hn = huellas(viejas), huellas(nuevas)
    sm = SequenceMatcher(None, hv, hn, autojunk=False)
    mapa, distintos, sin_par_v, sin_par_n = {}, 0, [], []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            mapa.update({b0 + k: a0 + k for k in range(a1 - a0)})
        elif op == "replace" and (a1 - a0) == (b1 - b0):
            mapa.update({b0 + k: a0 + k for k in range(a1 - a0)})
            distintos += a1 - a0
        else:
            sin_par_v += list(range(a0, a1))
            sin_par_n += list(range(b0, b1))
    info = {"compases_viejo": len(hv), "compases_nuevo": len(hn),
            "emparejados": len(mapa), "con_contenido_distinto": distintos,
            "solo_en_viejo": sin_par_v, "solo_en_nuevo": sin_par_n}
    return mapa, info


def _emparejar_secuencias(libres_v, libres_n, pares):
    """Alinea, dentro de cada (compás, pentagrama, capa), la secuencia de notas
    que quedan libres por (adorno, pname, oct, duración), con difflib.

    Resuelve el caso en que una versión tiene una nota de más o de menos en
    una capa: las notas siguientes cambian de tiempo de inicio, pero su orden
    y su nombre se conservan.
    """
    from difflib import SequenceMatcher

    grupos_v, grupos_n = defaultdict(list), defaultdict(list)
    for n in libres_v.values():
        grupos_v[(_c(n), n.pentagrama, n.capa)].append(n)
    for n in libres_n.values():
        grupos_n[(_c(n), n.pentagrama, n.capa)].append(n)
    for g, vs in grupos_v.items():
        ns_ = grupos_n.get(g)
        if not ns_:
            continue
        orden = lambda n: (n.inicio, n.adorno < 0, n.adorno, n.acorde_idx)
        vs, ns_ = sorted(vs, key=orden), sorted(ns_, key=orden)
        ficha = lambda n: (n.adorno >= 0, n.acorde_tam, n.acorde_idx, n.pname, n.oct, n.duracion)
        sm = SequenceMatcher(None, [ficha(n) for n in vs], [ficha(n) for n in ns_],
                             autojunk=False)
        for bloque in sm.get_matching_blocks():
            for k in range(bloque.size):
                v, w = vs[bloque.a + k], ns_[bloque.b + k]
                pares[v.id] = (w.id, "secuencia")
                del libres_v[v.id]
                del libres_n[w.id]


def emparejar_posicion(viejas, nuevas, info=None):
    """Devuelve (pares {id_viejo: (id_nuevo, pasada)}, ambiguas {id_viejo: [ids]}).

    Si se pasa ``info`` (un dict), se rellena con el resultado de alinear compases.
    """
    mapa_c, info_c = alinear_compases(viejas, nuevas)
    if info is not None:
        info.update(info_c)
    for n in viejas:
        n.compas_al = n.compas_ord
    for n in nuevas:
        n.compas_al = mapa_c.get(n.compas_ord, ("solo_en_nuevo", n.compas_ord))
    pares = {}
    libres_v = {n.id: n for n in viejas}
    libres_n = {n.id: n for n in nuevas}
    ambiguas = {}
    for pasada in PASADAS:
        if pasada == "secuencia":
            _emparejar_secuencias(libres_v, libres_n, pares)
            continue
        nombre, f = pasada
        idx_v, idx_n = defaultdict(list), defaultdict(list)
        for n in libres_v.values():
            idx_v[f(n)].append(n)
        for n in libres_n.values():
            idx_n[f(n)].append(n)
        for k, vs in idx_v.items():
            ns_ = idx_n.get(k, [])
            if len(vs) == 1 and len(ns_) == 1:
                v, w = vs[0], ns_[0]
                pares[v.id] = (w.id, nombre)
                del libres_v[v.id]
                del libres_n[w.id]
            elif ns_ and (len(vs) > 1 or len(ns_) > 1):
                for v in vs:
                    ambiguas.setdefault(v.id, [w.id for w in ns_])
    ambiguas = {k: v for k, v in ambiguas.items() if k in libres_v}
    return pares, ambiguas


def emparejar_partitura(ruta_vieja, ruta_nueva):
    """Alternativa con partitura.load_mei y note arrays."""
    import partitura as pt

    def tabla(ruta):
        sc = pt.load_mei(ruta)
        na = pt.utils.music.ensure_notearray(
            sc, include_staff=True, include_pitch_spelling=True,
            include_grace_notes=True)
        ids_mei = {n.get(XML_ID) for n in etree.parse(str(ruta)).iter("{%s}note" % MEI_NS)}
        campos = na.dtype.names
        filas = []
        for r in na:
            # Con varias partes, partitura antepone el id de la parte
            # ("P01_n123"): se quita para volver al xml:id del MEI.
            pid = str(r["id"])
            if pid not in ids_mei and "_" in pid and pid.split("_", 1)[1] in ids_mei:
                pid = pid.split("_", 1)[1]
            filas.append(dict(
                id=pid,
                clave=(round(float(r["onset_quarter"]), 6), int(r["staff"]),
                       int(r["voice"]), str(r["step"]), int(r["octave"]),
                       bool(r["is_grace"]) if "is_grace" in campos else False,
                       int(r["local_grace_order"]) if "local_grace_order" in campos else -1),
                midi=int(r["pitch"])))
        return filas

    viejas, nuevas = tabla(ruta_vieja), tabla(ruta_nueva)
    idx_v, idx_n = defaultdict(list), defaultdict(list)
    for r in viejas:
        idx_v[r["clave"]].append(r)
    for r in nuevas:
        idx_n[r["clave"]].append(r)
    pares, ambiguas = {}, {}
    for k, vs in idx_v.items():
        ns_ = idx_n.get(k, [])
        if len(vs) == 1 and len(ns_) == 1:
            pares[vs[0]["id"]] = (ns_[0]["id"], "partitura")
        elif ns_:
            for v in vs:
                ambiguas[v["id"]] = [w["id"] for w in ns_]
    midi_v = {r["id"]: r["midi"] for r in viejas}
    midi_n = {r["id"]: r["midi"] for r in nuevas}
    return pares, ambiguas, midi_v, midi_n, len(viejas), len(nuevas)


# ---------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------


MOTIVOS = {
    "secuencia": "mismo orden en la capa, pero distinto tiempo de inicio",
    "sin_pentagrama": "misma nota y tiempo, pero en otro pentagrama",
    "solo_posicion": "misma posición, distinto nombre de nota",
}


def alturas_verovio(ruta):
    """{id: altura MIDI} según la versión de Verovio instalada."""
    import verovio
    verovio.enableLog(verovio.LOG_OFF)
    tk = verovio.toolkit()
    tk.loadFile(str(ruta))
    tk.renderToMIDI()
    alturas = {}
    for n in etree.parse(str(ruta)).iter("{%s}note" % MEI_NS):
        nid = n.get(XML_ID)
        v = tk.getMIDIValuesForElement(nid) if nid else None
        if v and "pitch" in v:
            alturas[nid] = v["pitch"]
    return alturas, tk.getVersion()


def reatar(mei_viejo, mei_nuevo, mapa_viejo, metodo="posicion", alturas="aprox"):
    """Traduce ``mapa_viejo`` ({id_viejo: tiempo}) y devuelve (mapa_nuevo, informe).

    ``alturas``: "aprox" (lectura propia del MEI) o "verovio" (pregunta a la
    versión de Verovio instalada). Solo afecta al aviso de cambios de altura,
    nunca al emparejado.
    """
    viejas, lig_v, info_v = leer_mei(mei_viejo)
    nuevas, lig_n, info_n = leer_mei(mei_nuevo)
    por_id_v = {n.id: n for n in viejas}
    por_id_n = {n.id: n for n in nuevas}

    info_compases = {}
    if metodo == "partitura":
        pares, ambiguas, midi_v, midi_n, nv, nn = emparejar_partitura(mei_viejo, mei_nuevo)
    else:
        pares, ambiguas = emparejar_posicion(viejas, nuevas, info_compases)
        midi_v = {n.id: n.midi for n in viejas}
        midi_n = {n.id: n.midi for n in nuevas}
    fuente_alturas = "aproximación propia (reatar_ids._calcular_alturas)"
    if alturas == "verovio":
        midi_v, version = alturas_verovio(mei_viejo)
        midi_n, _ = alturas_verovio(mei_nuevo)
        fuente_alturas = "Verovio %s (getMIDIValuesForElement)" % version

    mapa_nuevo = {}
    huerfanas, ambiguas_mapa, no_en_mei = [], [], []
    altura_cambiada, revisar = [], []
    por_pasada = defaultdict(int)
    for id_v, tiempo in mapa_viejo.items():
        if id_v not in por_id_v:
            no_en_mei.append(id_v)
            continue
        if id_v in pares:
            id_n, pasada = pares[id_v]
            mapa_nuevo[id_n] = tiempo
            por_pasada[pasada] += 1
            if pasada in PASADAS_A_REVISAR:
                revisar.append({"id_viejo": id_v, "id_nuevo": id_n, "pasada": pasada,
                                "posicion_vieja": por_id_v[id_v].describe(),
                                "posicion_nueva": por_id_n[id_n].describe(),
                                "motivo": MOTIVOS[pasada]})
            mv, mn = midi_v.get(id_v), midi_n.get(id_n)
            if mv is not None and mn is not None and mv != mn:
                v, w = por_id_v[id_v], por_id_n.get(id_n)
                altura_cambiada.append({
                    "id_viejo": id_v, "id_nuevo": id_n,
                    "posicion": v.describe(),
                    "midi_viejo": mv, "midi_nuevo": mn,
                    "nota": ("emparejada por posición, no por altura: "
                             "la altura cambió de %s a %s" % (
                                 v.pname + _alter_txt(v.alter) + str(v.oct),
                                 (w.pname + _alter_txt(w.alter) + str(w.oct)) if w else mn)),
                })
        elif id_v in ambiguas:
            ambiguas_mapa.append({"id_viejo": id_v, "posicion": por_id_v[id_v].describe(),
                                  "candidatos": ambiguas[id_v]})
        else:
            huerfanas.append({"id_viejo": id_v, "posicion": por_id_v[id_v].describe()})

    # Ligaduras: ¿la nota emparejada sigue ligada y con el mismo papel?
    ligadas_v = [i for i in mapa_viejo if lig_v.get(i)]
    sigue = sum(1 for i in ligadas_v if i in pares and lig_n.get(pares[i][0]))
    mismo_papel = sum(1 for i in ligadas_v
                      if i in pares and lig_n.get(pares[i][0]) == lig_v.get(i))
    aristas_v = aristas_ligadura(mei_viejo)
    aristas_n = aristas_ligadura(mei_nuevo)
    conservadas = sum(1 for a, b in aristas_v
                      if a in pares and b in pares and (pares[a][0], pares[b][0]) in aristas_n)

    asignados = set(mapa_nuevo)
    nuevas_sin_tiempo = [n.id for n in nuevas if n.id not in asignados]

    informe = {
        "metodo": metodo,
        "mei_viejo": {"ruta": str(mei_viejo), **info_v},
        "mei_nuevo": {"ruta": str(mei_nuevo), **info_n},
        "compases": info_compases,
        "resumen": {
            "ids_en_mapa": len(mapa_viejo),
            "emparejadas": len(mapa_nuevo),
            "por_pasada": dict(por_pasada),
            "huerfanas": len(huerfanas),
            "ambiguas": len(ambiguas_mapa),
            "ids_del_mapa_que_no_son_notas_del_mei_viejo": len(no_en_mei),
            "altura_cambiada_emparejadas_por_posicion": len(altura_cambiada),
            "revisar": len(revisar),
            "notas_nuevas_sin_tiempo": len(nuevas_sin_tiempo),
            "ligaduras": {
                "notas_ligadas_en_viejo": len(ligadas_v),
                "siguen_ligadas_en_nuevo": sigue,
                "mismo_papel_inicio_medio_final": mismo_papel,
                "ligaduras_viejas": len(aristas_v),
                "ligaduras_conservadas_completas": conservadas,
            },
        },
        "aviso_altura": ("Las notas de 'altura_cambiada' se emparejaron por su "
                         "posición en el compás, no por su altura. Es lo esperado "
                         "cuando la versión vieja de Verovio ignoraba <alter>."),
        "fuente_alturas": fuente_alturas,
        "altura_cambiada": altura_cambiada,
        "revisar": revisar,
        "huerfanas": huerfanas,
        "ambiguas": ambiguas_mapa,
        "ids_del_mapa_que_no_son_notas_del_mei_viejo": no_en_mei,
        "notas_nuevas_sin_tiempo": nuevas_sin_tiempo,
    }
    return mapa_nuevo, informe


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mei_viejo")
    p.add_argument("mei_nuevo")
    p.add_argument("mapa_viejo", help="JSON {id_viejo: timeMs}")
    p.add_argument("-o", "--salida", default="mapa_nuevo.json")
    p.add_argument("-r", "--informe", default="informe_no_emparejado.json")
    p.add_argument("--metodo", choices=["posicion", "partitura"], default="posicion")
    p.add_argument("--alturas", choices=["aprox", "verovio"], default="aprox",
                   help="cómo calcular la altura para el aviso de cambios")
    a = p.parse_args(argv)

    with open(a.mapa_viejo, encoding="utf-8") as f:
        mapa_viejo = json.load(f)
    mapa_nuevo, informe = reatar(a.mei_viejo, a.mei_nuevo, mapa_viejo, a.metodo, a.alturas)
    with open(a.salida, "w", encoding="utf-8") as f:
        json.dump(mapa_nuevo, f, ensure_ascii=False, indent=1)
    with open(a.informe, "w", encoding="utf-8") as f:
        json.dump(informe, f, ensure_ascii=False, indent=1, default=str)

    r = informe["resumen"]
    print("Emparejadas: %d de %d" % (r["emparejadas"], r["ids_en_mapa"]))
    print("Huérfanas: %d   Ambiguas: %d   Ids que no son notas: %d"
          % (r["huerfanas"], r["ambiguas"], r["ids_del_mapa_que_no_son_notas_del_mei_viejo"]))
    if r["altura_cambiada_emparejadas_por_posicion"]:
        print("ATENCIÓN: %d notas cambiaron de altura entre versiones; se "
              "emparejaron por POSICIÓN, no por altura (ver 'altura_cambiada' "
              "en %s)." % (r["altura_cambiada_emparejadas_por_posicion"], a.informe))
    if r["revisar"]:
        print("REVISAR: %d notas se emparejaron con una regla relajada "
              "(ver 'revisar' en el informe)." % r["revisar"])
    lg = r["ligaduras"]
    print("Ligaduras: %d notas ligadas en el viejo, %d siguen ligadas en el nuevo"
          % (lg["notas_ligadas_en_viejo"], lg["siguen_ligadas_en_nuevo"]))
    print("Mapa nuevo: %s   Informe: %s" % (a.salida, a.informe))
    return 0


if __name__ == "__main__":
    sys.exit(main())
