"""Vuelca la altura MIDI que Verovio asigna a cada nota de un MEI.

Uso (en el entorno con verovio): python alturas_verovio.py ENTRADA.mei SALIDA.json
Sirve para medir cómo interpreta Verovio la altura de cada nota (lo que
sonaría y vería el visor), sin depender de la aproximación de reatar_ids.py.
"""

import json
import sys

import verovio
from lxml import etree

MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def main(entrada, salida):
    verovio.enableLog(verovio.LOG_OFF)
    tk = verovio.toolkit()
    tk.loadFile(entrada)
    tk.renderToMIDI()
    ids = [n.get(XML_ID) for n in etree.parse(entrada).iter("{%s}note" % MEI_NS)]
    alturas = {}
    for i in ids:
        v = tk.getMIDIValuesForElement(i)
        if v and "pitch" in v:
            alturas[i] = v["pitch"]
    with open(salida, "w") as f:
        json.dump({"verovio": tk.getVersion(), "alturas": alturas}, f)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
