"""Prepara dos variantes de un MusicXML para el experimento.

- sin_ids: quita el atributo ``id`` de cada <note> (caso real: Verovio
  inventa los ids).
- con_ids: pone ``id="gtNNNNN"`` en cada <note> (verdad de referencia: Verovio
  copia ese id al MEI en las dos versiones).

Uso: python preparar_musicxml.py ENTRADA.xml|.mxl SALIDA_sin_ids.xml SALIDA_con_ids.xml
"""

import sys
import zipfile

from lxml import etree


def leer(ruta):
    if ruta.endswith(".mxl"):
        with zipfile.ZipFile(ruta) as z:
            cont = etree.fromstring(z.read("META-INF/container.xml"))
            raiz = cont.find(".//{*}rootfile").get("full-path")
            return etree.ElementTree(etree.fromstring(z.read(raiz)))
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    return etree.parse(ruta, parser)


def main(entrada, sin_ids, con_ids):
    arbol = leer(entrada)
    for n in arbol.iter("note"):
        n.attrib.pop("id", None)
    arbol.write(sin_ids, xml_declaration=True, encoding="UTF-8")
    for k, n in enumerate(arbol.iter("note")):
        n.set("id", "gt%05d" % k)
    arbol.write(con_ids, xml_declaration=True, encoding="UTF-8")


if __name__ == "__main__":
    main(*sys.argv[1:4])
