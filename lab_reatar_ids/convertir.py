"""Convierte MusicXML a MEI con la versión de Verovio instalada en el entorno.

Uso:
    python convertir.py ENTRADA.xml SALIDA.mei [--seed N] [--checksum]

Se ejecuta una vez en cada entorno (uno con verovio==6.1.0 y otro con
verovio==6.3.0). No depende de partitura.
"""

import argparse
import json
import sys

import verovio


def convertir(entrada, salida, seed=None, checksum=False):
    verovio.enableLog(verovio.LOG_OFF)
    tk = verovio.toolkit()
    opciones = {}
    if seed is not None:
        opciones["xmlIdSeed"] = seed
    if checksum:
        opciones["xmlIdChecksum"] = True
    if opciones:
        tk.setOptions(opciones)
    if not tk.loadFile(entrada):
        raise SystemExit(f"Verovio no pudo cargar {entrada}")
    mei = tk.getMEI()
    with open(salida, "w", encoding="utf-8") as f:
        f.write(mei)
    return tk.getVersion()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("entrada")
    p.add_argument("salida")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--checksum", action="store_true")
    a = p.parse_args(argv)
    version = convertir(a.entrada, a.salida, a.seed, a.checksum)
    print(json.dumps({"verovio": version, "entrada": a.entrada, "salida": a.salida}))


if __name__ == "__main__":
    sys.exit(main())
