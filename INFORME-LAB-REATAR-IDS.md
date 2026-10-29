# Informe del laboratorio: reatar los ids de nota al pasar de Verovio 6.1.0 a 6.3.0

## Resumen

- Verovio inventa los ids de las notas al azar en cada conversión. Ni con la misma semilla dan las dos versiones los mismos ids: los ids viejos no se pueden «regenerar».
- Lo que Verovio sí respeta, en las dos versiones, es el id que ya traiga cada nota en el MusicXML (`<note id="...">`): pasa intacto al MEI.
- El mapa de sincronía se puede traducir emparejando las notas por su sitio en la partitura (compás, pentagrama, capa, momento del compás y lugar en el acorde). El script `lab_reatar_ids/reatar_ids.py` lo hace.
- Medido en 5 piezas y en 173 ficheros de prueba (4.633 notas): todas las notas acabaron en su nota correcta, sin huérfanas ni ambiguas, y las ligaduras siguen ligadas.
- Las notas que cambian de altura por el arreglo de `<alter>` (72 de 1.760 en la Berceuse de Chopin) se emparejan por su sitio, no por su altura, y el informe las lista aparte.
- Recomendación: traducir el mapa una vez y, además, escribir esos ids en el MusicXML («ruta B»), para que la próxima reconversión ya no los cambie.
- Todo se ha probado con partituras públicas. El MEI y el mapa reales del usuario no se han tocado: quedan «SIN MEDIR».

Notación: «leído» significa que sale de leer el código fuente citado; «medido», que sale de ejecutar las versiones indicadas en este laboratorio.

## 1. Cómo genera Verovio los ids

Versiones estudiadas (las de las ruedas de PyPI, `pip install verovio==6.1.0` y `verovio==6.3.0`; las dos están en PyPI):

| Versión | `getVersion()` | Commit de la publicación | Licencia |
|---|---|---|---|
| 6.1.0 | `6.1.0-682d606` | `682d60684450e780f0a1dcb7e394bda12eea4501` (12-03-2026) | LGPL-3.0 |
| 6.3.0 | `6.3.0-425dd7b` | `425dd7b6ba26edcecbe345c10b15586d095743d9` (19-08-2026) | LGPL-3.0 |

Las citas son `fichero:línea` en 6.1.0 / 6.3.0 del repositorio `rism-digital/verovio`.

| # | Afirmación | Fuente | Tipo |
|---|---|---|---|
| 1 | Cada objeto que crea Verovio (nota, compás, capa, alteración, haz...) recibe un id nuevo al construirse, y también cada copia. | `src/object.cpp:194` / `:196` (`Object::Init` llama a `GenerateID`); copias en `:110` y `:155` / `:157` | leído |
| 2 | El id es una letra más un número en base 36. Ese número es `Hash(++contador)`, y el contador es uno solo, global por hilo (`s_xmlIDCounter`). | `src/object.cpp:69`, `:822-827` / `:824-829`, `:1280-1285` / `:1292-1297`, `:1287` / `:1299` | leído |
| 3 | Sin opciones, el contador arranca con un número aleatorio (`std::random_device`) al crear el primer objeto. | `src/object.cpp:73`, `:81`, `:1266-1278` / `:1278-1290` | leído |
| 3m | Sin opciones, dos conversiones del mismo MusicXML con la misma versión: 0 de 218 ids de nota coinciden (Mozart K. 265, en las dos versiones). | `resultados/resultados.json` → `semillas.sin_opciones` | medido |
| 4 | `xmlIdSeed` (≠ 0) fija el arranque del contador: `contador = Hash(semilla)`. | `src/options.cpp:979-981` / `:980-982`; `src/toolkit.cpp:1187` / `:1212`; `ResetXmlIdSeed` en `:1536-1539` / `:1576-1579` | leído |
| 5 | `xmlIdChecksum` usa como semilla el CRC del texto de entrada. | `src/toolkit.cpp:522-525` / `:538-541`; `src/options.cpp:1218-1220` / `:1223-1225` | leído |
| 4m/5m | Con `xmlIdSeed=1234` o con `xmlIdChecksum`, dos conversiones con la misma versión dan los 218 ids iguales. Los ids son deterministas dentro de una versión. | `semillas.xmlIdSeed_1234`, `semillas.xmlIdChecksum` | medido |
| 6 | Entre versiones no se conservan: como el contador avanza una vez por objeto creado, cualquier objeto de más o de menos cambia todos los ids que vienen detrás. | deducción de 1 y 2 | leído |
| 6m | Mozart K. 265, misma semilla en las dos versiones: la 6.1.0 escribe 657 elementos con id y la 6.3.0, 459. Solo 1 de 218 notas conserva su id. Además, 56 ids de la 6.1.0 reaparecen en la 6.3.0, y 55 de ellos en **otra nota**. Una semilla fija es peligrosa: produce ids que parecen válidos pero señalan la nota equivocada, sin avisar. | `semillas.xmlIdSeed_1234` | medido |
| 7 | El atributo `id` de `<note>` en el MusicXML se copia tal cual como `xml:id` de la nota MEI (también se respetan los `id` de compases, haces, ligaduras de expresión, etc.). | `src/iomusxml.cpp:3008` y `:3112` / `:3003` y `:3113` | leído |
| 7m | Poniendo `id="gtNNNNN"` en cada `<note>` del MusicXML, los dos MEI tienen exactamente los mismos ids de nota en las 5 piezas y en los 173 ficheros con notas del barrido. | `piezas[].ref.ids_identicos_en_las_dos_versiones`, `barrido.ficheros_con_ids_gt_identicos` | medido |
| 8 | La 6.1.0 no lee `<alter>` para la altura de las notas normales. Deduce la alteración sonora de los `<accidental>` escritos y de la armadura, con una memoria por nombre de nota **sin octava** que se borra en cada compás. Una alteración en otra octava, o una nota ligada que cruza la barra sin `<accidental>`, puede quedar mal. | `src/iomusxml.cpp:1877`, `:3153-3192`, `:4454-4456` (6.1.0) | leído |
| 9 | La 6.3.0 lee `<alter>` y deduce de él la alteración sonora (`@accid.ges`). | `src/iomusxml.cpp:3144`, `:3158` (6.3.0); commits `d11c392fb` (29-06-2026) y `e59ec90d6` (15-07-2026) | leído |
| 10 | La 6.3.0 deja de escribir `@accid.ges="n"` cuando lo considera innecesario. | commit `a761ed4bd` | leído |
| 11 | La 6.3.0 tampoco es perfecta: en el fichero 32a de la suite de LilyPond, un `<accidental-mark>` (un signo de adorno que no altera la nota) acaba como doble sostenido en 16 notas que el MusicXML da naturales; la 6.1.0 falla 1. | alturas según `getMIDIValuesForElement` de cada versión | medido |

Conclusión del punto 1: los ids son deterministas solo con `xmlIdSeed` o `xmlIdChecksum`, y aun así dependen del número exacto de objetos que crea cada versión. No se pueden conservar entre versiones salvo que vengan escritos en el MusicXML (punto 7).

## 2. La herramienta

`lab_reatar_ids/reatar_ids.py MEI_viejo MEI_nuevo mapa_viejo.json -o mapa_nuevo.json -r informe.json`

Cómo empareja (método «posicion», por defecto):

1. Lee cada nota del MEI y calcula su posición: nº de orden del compás, pentagrama, capa, inicio dentro del compás (en fracciones de redonda, con tresillos y puntillos), orden de nota de adorno y lugar en el acorde (de grave a agudo por nombre de nota).
2. Alinea primero los compases de los dos MEI (cada compás se resume en una «huella» de sus notas). Así un compás de más o de menos no desplaza el resto.
3. Empareja en pasadas, de la más estricta a la más laxa. Solo acepta un par si es único en los dos MEI:
   `exacta` → `sin_duracion` → `sin_capa` → `secuencia` (alinea el orden de las notas dentro de la capa) → `sin_pentagrama` → `solo_posicion`.
   Los pares de las tres últimas pasadas salen en la lista `revisar` del informe.
4. Usa el **nombre escrito** de la nota (letra y octava, sin alteración) y nunca la altura sonora. La corrección de `<alter>` cambia la alteración, no el nombre. Por eso las notas cuya altura cambió se emparejan por posición, y el informe lo dice con todas las letras: «emparejada por posición, no por altura: la altura cambió de c5 a c#5».
5. Lo que no puede decidir lo devuelve: «huérfanas» (no tienen pareja), «ambiguas» (varias parejas posibles) e ids del mapa que no son notas del MEI viejo.

Además, el informe dice para cada nota ligada en el viejo si sigue ligada en el nuevo y con el mismo papel (inicio, medio o final), y cuántas ligaduras completas se conservan.

Alternativa probada: `--metodo partitura`, que empareja con `partitura.load_mei` y su note array (inicio en negras, pentagrama, voz, nombre, octava y orden de adorno). Medido: es peor (sección 3).

«Ruta B» (llevar los ids viejos al MusicXML): se emparejan las notas del MEI viejo con una conversión hecha **con la misma versión vieja** del MusicXML con ids de referencia. Después se escriben los ids viejos en los `<note id>` del MusicXML y se reconvierte con 6.3.0. El MEI nuevo sale con los ids viejos, así que el mapa de sincronía sirve sin cambios, y las reconversiones futuras ya no los romperán (punto 7). Está implementada en `herramientas/experimento.py` (`escribir_ids_en_musicxml`).

## 3. Resultados por pieza (medidos)

Procedimiento: cada MusicXML se convirtió con 6.1.0 y con 6.3.0 en dos variantes.
- «Sin ids»: es el caso real; Verovio inventa los ids.
- «Con ids de referencia»: cada `<note>` lleva `id="gtNNNNN"`. Como Verovio copia ese id (punto 7), en esta variante el emparejado correcto es conocido: el tiempo de `gt00042` tiene que acabar en `gt00042`.

El mapa de sincronía es **sintético**: 1000 + 250·k ms en orden de documento. Solo sirve para comprobar a qué nota llega cada tiempo; no es una grabación.

### 3.1 Emparejado

| Pieza | Notas (viejo / nuevo) | Emparejadas | Huérfanas | Ambiguas | Aciertos con ids de referencia | Errores | partitura: aciertos |
|---|---|---|---|---|---|---|---|
| Mozart, K. 265, variación 1 | 218 / 218 | 218 | 0 | 0 | 218 | 0 | 218 de 218 |
| Chopin, Berceuse op. 57 | 1760 / 1760 | 1760 | 0 | 0 | 1760 | 0 | falla (`KeyError: 'symbol'`) |
| LilyPond 01b (intervalos con alteraciones) | 83 / 83 | 83 | 0 | 0 | 83 | 0 | 83 de 83 |
| LilyPond 24a (notas de adorno) | 28 / 28 | 28 | 0 | 0 | 28 | 0 | 28 de 28 |
| LilyPond 46e (anacrusa, 2.ª voz que entra tarde) | 6 / 6 | 6 | 0 | 0 | 6 | 0 | falla (no encuentra la indicación de compás en `scoreDef`) |

Todas las notas de las 5 piezas se resolvieron en la pasada `exacta`; la lista `revisar` quedó vacía.

Aciertos por tipo de nota (variante con ids de referencia):

| Pieza | Adorno | En acorde | Ligadas | Capa 2 o más | Anacrusa | Pentagrama cruzado |
|---|---|---|---|---|---|---|
| Mozart K. 265 | — | 10 de 10 | — | 53 de 53 | — | — |
| Chopin op. 57 | 44 de 44 | 683 de 683 | 8 de 8 | 767 de 767 | — | — |
| LilyPond 01b | — | — | — | — | — | — |
| LilyPond 24a | 15 de 15 | 2 de 2 | 1 de 1 | — | — | — |
| LilyPond 46e | — | — | — | 1 de 1 | 1 de 1 | — |

(«—» = la pieza no tiene notas de ese tipo.)

### 3.2 Ligaduras

| Pieza | Notas ligadas en el viejo | Siguen ligadas en el nuevo | Mismo papel (inicio/medio/final) | Ligaduras completas conservadas |
|---|---|---|---|---|
| Chopin op. 57 | 8 | 8 | 8 | 4 de 4 |
| LilyPond 24a | 1 | 1 | 1 | 0 de 0 (el `<tie>` solo tiene `startid`, en las dos versiones) |
| LilyPond 33b (solo para pruebas) | 2 | 2 | 2 | 1 de 1 |
| Mozart, 01b, 46e | 0 | — | — | — |

### 3.3 Alturas: el arreglo de `<alter>`

Altura de cada nota tal como la da cada versión de Verovio (`getMIDIValuesForElement`), comparada con la altura escrita en el `<pitch>` del MusicXML:

| Pieza | Notas | Cambian de 6.1.0 a 6.3.0 | Mal en 6.1.0 | Mal en 6.3.0 | Avisadas por `reatar_ids.py` (aproximación / `--alturas verovio`) |
|---|---|---|---|---|---|
| Mozart K. 265 | 218 | 0 | 0 | 0 | 0 / 0 |
| Chopin op. 57 | 1760 | 72 | 72 | 0 | 74 / 72 |
| LilyPond 01b | 83 | 55 | 55 | 0 | 55 / 55 |
| LilyPond 24a | 28 | 0 | 0 | 0 | 0 / 0 |
| LilyPond 46e | 6 | 0 | 0 | 0 | 0 / 0 |

Las 72 notas de Chopin y las 55 de 01b se emparejaron bien (sección 3.1): por posición, no por altura.

La aproximación de altura propia del script coincide con Verovio en todas las notas, salvo 10 de Chopin con 6.3.0 (alteraciones que se arrastran entre capas). Por eso existe la opción `--alturas verovio`. La altura solo afecta al aviso, nunca al emparejado.

### 3.4 Barrido amplio

191 ficheros: la suite MusicXML de LilyPond completa (vía music21) más los MusicXML de `tests/data/musicxml` de partitura, salvo los dos excluidos por licencia (sección 6). 173 tienen notas.

| Medida | Resultado |
|---|---|
| Notas | 4633 |
| Aciertos con ids de referencia | 4633 |
| Errores / huérfanas / ambiguas / a revisar | 0 / 0 / 0 / 0 |
| Notas ligadas que siguen ligadas | 38 de 38 |
| Ficheros en los que los ids de referencia salen idénticos en las dos versiones | 173 de 173 |
| Método partitura: ficheros en los que funciona | 133 de 173 (excepciones: 27 `Exception`, 11 `KeyError`, 2 `ValueError`) |
| Método partitura: aciertos en esos 133 | 2313 de 2337 |

Fallos medidos del método partitura: su note array junta las notas ligadas en una, así que las notas que terminan una ligadura quedan huérfanas (33b, 61d, `test_pianoroll_sum`...). Tampoco distingue el orden dentro de un acorde de adorno, y esas notas quedan ambiguas (`test_acciaccatura_chord`: 1 de 8).

### 3.5 Ruta B (ids viejos escritos en el MusicXML y reconversión con 6.3.0)

| Pieza | Ids viejos puestos en el MusicXML | Presentes en el MEI de 6.3.0 | Y en la misma posición |
|---|---|---|---|
| Mozart K. 265 | 218 | 218 | 218 |
| Chopin op. 57 | 1760 | 1760 | 1760 |
| LilyPond 01b | 83 | 83 | 83 |
| LilyPond 24a | 28 | 28 | 28 |
| LilyPond 46e | 6 | 6 | 6 |

### 3.6 Casos difíciles simulados (pruebas con pytest)

No se encontró ningún caso real que fallara: en todas las piezas, la estructura (compases, capas, tiempos) fue idéntica entre versiones. Por eso los fallos se provocaron a mano sobre el MEI 6.3.0 de Mozart, en `lab_reatar_ids/tests/test_reatar_ids.py`. Las 24 pruebas pasan.

| Caso | Resultado medido |
|---|---|
| Nota borrada (con hueco) | queda como huérfana; el resto, bien |
| Nota borrada sin hueco (las siguientes de la capa se adelantan) | huérfana la borrada; el resto se recupera en la pasada `secuencia` y sale en `revisar` |
| La misma nota duplicada en dos capas nuevas | sale como ambigua, con los dos candidatos |
| Capas intercambiadas en un pentagrama | se resuelve en la pasada `sin_capa`; cada tiempo cae en su instante |
| Compás vacío añadido al principio | se alinea por compases; todo se empareja en `exacta` |
| Compás borrado | solo sus notas quedan huérfanas |
| Nombre de nota cambiado | se empareja por posición y sale en `revisar` |
| Alteración cambiada | se empareja y sale en `altura_cambiada` |
| Id del mapa que no es una nota | se lista aparte |

Lección aprendida durante el laboratorio (medida): una primera versión sin alinear compases, ante un compás vacío añadido al principio, emparejaba 65 de las 218 notas de la variación de Mozart con la nota equivocada, normalmente su gemela del compás vecino; además dejaba 42 huérfanas. Los errores no se marcaban como tales. La alineación de compases lo corrigió, y la prueba `test_compas_insertado_no_desplaza_el_resto` lo vigila.

## 4. Límites

- **Las cifras del 100 % se deben a que no hubo cambios de estructura.** En todas las piezas medidas, 6.1.0 y 6.3.0 produjeron los mismos compases, capas y tiempos. Si en la partitura del usuario alguna versión cambia la estructura (por ejemplo, por los cambios de la 6.3.0 en `<forward>` o en la resolución de compases, commit `1f51c826a`), aparecerán huérfanas o pares en `revisar`. Solo se ha probado de forma simulada (3.6).
- **Un MEI viejo retocado a mano** después de convertirlo no se parece a una reconversión: lo editado saldrá como huérfano o en `revisar`.
- **Notas simultáneas idénticas** (el mismo nombre de nota, a la vez y con la misma duración, en dos capas que se intercambian) pueden cruzar su pareja. El tiempo asignado es el mismo, así que la sincronía no cambia. Sí importaría si el mapa diera tiempos distintos a notas simultáneas (un acorde arpegiado, por ejemplo).
- Solo se reatan **notas** (`<note>`). Silencios, compases y otros elementos con id no se tratan.
- La lectura de tiempos del MEI cubre `@dur`, `@dots`, `<tuplet>`, `<beam>`, `<graceGrp>`, `<bTrem>` y `<fTrem>`. `<fTrem>` se suma en secuencia (interpretación propia, no comprobada). No trata `<app>`/`<choice>`, varios `<mdiv>` ni expansiones de repeticiones.
- La altura «aproximada» del script es solo para avisar; para cifras fiables, `--alturas verovio`.
- Alteraciones microtonales: excluidas de la comparación con el MusicXML.
- La rueda de PyPI de 6.1.0 no incluye `glyphnames.json` y escribe errores «Custom tuning» al convertir (medido); la de 6.3.0, no. El visor del usuario puede usar otra compilación.
- El método partitura no sirve como principal: falla en 40 de 173 ficheros y pierde las notas que terminan una ligadura.

## 5. Lo que NO se pudo medir

- SIN MEDIR: el MEI, el mapa de sincronía y el MusicXML reales del usuario (no están en este entorno, a propósito).
- SIN MEDIR: el visor web del usuario. Si usa Verovio en JavaScript, el código que genera los ids es el mismo C++ (leído), pero no se ha ejecutado.
- SIN MEDIR: si el MEI viejo del usuario se generó con `xmlIdSeed`, `xmlIdChecksum` u otra versión distinta de 6.1.0.
- SIN MEDIR: las versiones intermedias 6.1.1, 6.2.0 y 6.2.1.
- SIN MEDIR: por qué cambian, una a una, las 72 notas de Chopin (ligadura sobre la barra, otra octava...). El motivo general está leído en el código (sección 1, punto 8), pero no se han clasificado.
- SIN MEDIR: MusicXML de otros programas (Finale, Sibelius, Dorico) y ficheros `.mxl` comprimidos, salvo los que ya estaban en la suite.
- SIN MEDIR: partituras grandes. La mayor probada tiene 1760 notas (0,18 s; 1,8 s con `--alturas verovio`).
- SIN MEDIR: un cambio real de estructura entre versiones; solo simulado.

## 6. Licencias (comprobadas en sus ficheros)

| Material | Licencia | Dónde se comprobó | Uso aquí |
|---|---|---|---|
| Verovio 6.1.0 y 6.3.0 | LGPL-3.0 | `COPYING.LESSER` en los commits citados; `pyproject.toml` de 6.3.0: `license = "LGPL-3.0-only"`; METADATA de las ruedas: «LGPLv3» (6.1.0) y `LGPL-3.0-only` (6.3.0) | instalado con pip en entornos aparte; código leído y citado por línea, no copiado |
| partitura | Apache-2.0 | `LICENSE` y `pyproject.toml` de este repositorio | método alternativo y fuente de MusicXML de prueba |
| Suite MusicXML de LilyPond (01b, 24a, 33b, 46e y el barrido) | MIT | `music21/musicxml/lilypondTestSuite/__init__.py` (music21 `db86eb4`); `README.md` y `LICENSE` de `cuthbertLab/musicxmlTestSuite` (`77c19f7`) | copiados 4 ficheros con su `LICENSE` en `lab_reatar_ids/datos/musicxml/lilypond/` |
| Mozart K. 265 var. 1 (`tests/data/musicxml/mozart_k265_var1.musicxml`) | `<rights>Public Domain</rights>` en el fichero; repositorio Apache-2.0 | el propio fichero | MEI derivados en `lab_reatar_ids/datos/mei/` |
| Chopin, Berceuse op. 57 (`tests/data/musicxml/test_part_group.xml`) | obra de dominio público; la codificación declara `<source>http://musescore.com/score/932306</source>`; licencia de esa codificación **SIN COMPROBAR** (el proxy devolvió 403) | el propio fichero | solo cifras; no se publica ningún derivado |
| lxml | BSD-3-Clause | METADATA de la rueda | lectura de XML |
| music21 | BSD-3-Clause | `LICENSE` del repositorio | solo como fuente de los ficheros de LilyPond; no se importa |

Excluidos del barrido por licencia: `test_merge_interpolation.xml` (Mozart K. 590 codificado por CCARH, «Rights to all derivative editions reserved») y `test_ts_map_ts_starts_not_at_zero.xml` (Bartók, Mikrokosmos, obra no libre en todas partes).

## 7. Cómo reproducirlo

Instrucciones en `lab_reatar_ids/LEEME.md`. Las cifras de este informe salen de `lab_reatar_ids/resultados/resultados.json`, generado por `lab_reatar_ids/herramientas/experimento.py`.
