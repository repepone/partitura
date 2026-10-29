# Laboratorio: reatar ids de nota entre versiones de Verovio

El informe completo está en `../INFORME-LAB-REATAR-IDS.md`.

## Uso de la herramienta

Solo necesita Python 3 y `lxml`:

```bash
python reatar_ids.py viejo.mei nuevo.mei mapa_viejo.json -o mapa_nuevo.json -r informe.json
```

- `mapa_viejo.json`: `{"id_de_nota_del_MEI_viejo": tiempo_en_ms, ...}`.
- `mapa_nuevo.json`: el mismo mapa con los ids del MEI nuevo.
- `informe.json`: huérfanas, ambiguas, notas a revisar, notas cuya altura
  cambió (emparejadas por posición, no por altura) y estado de las ligaduras.
- `--alturas verovio`: usa la versión de Verovio instalada para calcular la
  altura de cada nota en el aviso de cambios (más fiable que la aproximación
  propia; no cambia el emparejado).
- `--metodo partitura`: alternativa con `partitura.load_mei`. Medido: peor
  (ver informe).

## Contenido

| Ruta | Qué es |
|---|---|
| `reatar_ids.py` | La herramienta. |
| `convertir.py` | MusicXML → MEI con la versión de Verovio del entorno. |
| `herramientas/preparar_musicxml.py` | Quita o pone ids en los `<note>` de un MusicXML. |
| `herramientas/alturas_verovio.py` | Vuelca la altura MIDI que Verovio da a cada nota. |
| `herramientas/experimento.py` | Todo el experimento; escribe `resultados/`. |
| `datos/musicxml/lilypond/` | Ficheros MIT de la suite de LilyPond (ver su `LEEME.md`). |
| `datos/mei/` | MEI generados con 6.1.0 y 6.3.0, para las pruebas. |
| `resultados/` | Cifras medidas (`resultados.json`, `tabla.md`) e informes por pieza. |
| `tests/` | Pruebas con pytest. |

## Reproducir

```bash
python -m venv v61 && v61/bin/pip install verovio==6.1.0 lxml
```

```bash
python -m venv v63 && v63/bin/pip install verovio==6.3.0 lxml pytest -e ..
```

```bash
v63/bin/python herramientas/experimento.py --py61 v61/bin/python --py63 v63/bin/python --trabajo /tmp/trabajo --suite RUTA/A/music21/musicxml/lilypondTestSuite
```

```bash
v63/bin/python -m pytest tests
```

Al repetir el experimento, los MEI «sin_ids» de `datos/mei/` cambian (Verovio
inventa ids nuevos en cada ejecución); las cifras no.
