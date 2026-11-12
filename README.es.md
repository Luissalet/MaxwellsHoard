# Maxwell's Hoard

Ingeniería física local para piezas planas: conducción térmica estacionaria y elasticidad en tensión plana con elementos finitos. [English](README.md)

![Maxwell's Hoard](app-icon.png)

## Qué es

Maxwell's Hoard resuelve en tu propio PC problemas de ingeniería física de piezas planas: **conducción térmica estacionaria** y **elasticidad lineal en tensión plana**, con elementos finitos cuadráticos, todas las condiciones a la vista, cada resultado comprobado contra un balance y un solver en el que solo se confía hasta donde pasan sus referencias analíticas.

Maxwell guarda junto a cada resultado la geometría, materiales, apoyos, cargas, fuentes de calor, malla e hipótesis; almacena la entrada exacta de cada estudio y convierte el dato que falta (cómo se sujeta la pieza, por dónde sale el calor) en una pregunta concreta en vez de un supuesto invisible.

## Qué hace

- **Modelo del problema** (JSON, SI, °C): perfil rectangular con espesor uniforme; regiones rectangulares que cambian de material, son huecos, llevan una fuente de calor (`power` W o `q` W/m³) o convección en caras; tramos de borde con temperatura, convección (`h`, `t_inf`), flujo de calor, empotramiento o apoyo deslizante, fuerzas totales o presión; gravedad; sondas; requisitos (`max_temperature`, `region_avg_temperature:<id>`, `max_displacement`, `max_von_mises`, `safety_factor`, `mass`, magnitudes de sondas).
- **Solver**: triángulos de seis nodos (T6) sobre una rejilla que pasa exactamente por cada borde de región y tramo de contorno; integración exacta de grado 4; resolución dispersa directa. Devuelve campos de temperatura o de desplazamiento y von Mises, extremos y dónde ocurren, medias por región, sondas, masa, factor de seguridad frente a fluencia, **balance de energía** (fuentes y flujos de entrada = calor que sale por convección y por temperatura fija) y **equilibrio de fuerzas** (cargas aplicadas + reacciones).
- **Datos que faltan → preguntas**: pieza (o trozo separado) que aún puede moverse como sólido rígido, cuerpo sin salida de calor, material sin la propiedad que la física necesita; el resultado es `needs-input` con la pregunta que hay que hacer.
- **Referencias analíticas**: viga en voladizo (flexión + cortante de Timoshenko, tensión de flexión a media luz), placa cuadrada calentada uniformemente (serie de Fourier doble), pared con temperatura fija y convección (resistencias térmicas). Cada una cambia además una condición y comprueba la respuesta (doble carga → doble flecha).
- **Estudio de refinamiento de malla**: valores en ×1, ×2, ×4, orden observado, extrapolación de Richardson, error estimado y aviso explícito cuando un pico sigue creciendo (las esquinas entrantes y los extremos de empotramiento son singulares: su tensión no es una predicción del material).
- **Comparación de variantes**: `{name, changes: {ruta.con.puntos: valor}}`; los elementos de lista se direccionan por id o etiqueta (`regions.vent.x0`, `boundary.equipment.fy`). Veredictos frente a los requisitos.
- **Diseño inverso**: 1–3 parámetros con significado físico, un objetivo y requisitos; búsqueda en rejilla sobre malla gruesa y revalidación de los mejores candidatos en malla fina **y en casos de carga reservados que no participaron en la búsqueda**; devuelve la recomendación aceptada y la frontera de compromisos factibles, no un único diseño «perfecto».
- **Geometría de Vulcan's Hoard**: un STL de espesor constante (por id de modelo, leído de la API local de Vulcan, o subido) se convierte en el perfil; los huecos pasan a regiones vacías con una resolución declarada; se informa de la concordancia de volumen y de la coherencia en el espesor, y se rechazan piezas cuya sección cambia a lo largo del espesor.
- **Rechazos en lugar de suposiciones**: un cuerpo sin camino de salida para el calor pregunta por dónde sale en vez de devolver un cero arbitrario; un factor de seguridad exige el límite elástico de todos los materiales; los niveles de refinamiento deben crecer estrictamente; se rechazan perfiles importados con cajeados ciegos, fondos o paredes cónicas.
- **Registros**: cada cálculo y estudio se guarda con su entrada exacta, salida e hipótesis (`data/records`).

Ejemplos incluidos: qué disposición de ventilación mantiene bajo 85 °C una placa con dos fuentes de calor (la de la derecha falla), un soporte comparado en acero y aluminio con tres espesores, y una búsqueda que descarta el soporte más ligero porque se rompe con un caso reservado con un 25 % más de carga.

## Cómo ejecutarlo

Requiere Python 3.11 o superior.

```
python -m venv .venv
.venv\Scripts\pip install -e .[test]
.venv\Scripts\python -m maxwell            # http://127.0.0.1:5243
.venv\Scripts\python -m pytest
```

La página web (`/`) ofrece editor del problema, mapa de campos (temperatura, desplazamiento, von Mises, deformada exagerada), resumen con balances, requisitos, sondas e hipótesis; tablas de refinamiento, comparación y búsqueda; referencias; y registros.

## API HTTP

| Método | Ruta | Para qué |
| --- | --- | --- |
| GET | `/api/health` | `{service: "maxwell-hoard"}` |
| GET | `/api/materials` | biblioteca de materiales nominales |
| GET | `/api/examples`, `/api/examples/{id}` | ejemplos resueltos |
| POST | `/api/check` | valida y devuelve preguntas por los datos que faltan |
| POST | `/api/solve` | `{problem, refine, field}` |
| POST | `/api/refinement` | `{problem, quantities, levels}` |
| POST | `/api/compare` | `{problem, variants, refine}` |
| POST | `/api/search` | `{problem, parameters, objective, holdout, finalists, tradeoff}` |
| POST | `/api/import` | `{model_id}` (Vulcan) o `{stl_base64}`, `problem`, `resolution_mm`, `thin_axis` |
| GET/POST | `/api/references`, `/api/references/{case}` | lista y verificación de referencias analíticas |
| GET | `/api/records`, `/api/records/{id}` | estudios guardados |

Los problemas inválidos o incompletos responden 422 con `{status, error, questions}`.

## Límites

- Bidimensional: tensión plana para elasticidad y conducción en el plano para el calor (con convección en caras opcional). Sin sólidos 3D, fluidos, radiación (salvo dentro de un coeficiente de convección), contacto, pandeo, plasticidad, fatiga, transitorios ni propiedades dependientes de la temperatura.
- La geometría es rectangular (exacta) o una aproximación escalonada de un perfil importado; los huecos curvos elevan las tensiones máximas locales.
- Los materiales son valores nominales de hoja de datos; hay que confirmarlos en piezas reales. Un solver convergente puede resolver el problema equivocado: las condiciones son responsabilidad del ingeniero, por eso se muestran siempre.

## Conexión con Faustus y Hoard Hub

`faustus-plugin.json` registra la app como plugin de Faustus. El Hub arranca la aplicación web de forma explícita, en un puerto que se adapta si el predeterminado está ocupado. Faustus recibe un panel con el problema actual, sus variantes y el borrador de búsqueda (incluido JSON incompleto) junto con la última operación, su entrada exacta y su resultado compacto; la conversación, el modelo y las herramientas se quedan en Faustus.

MCP (stdio, `python -m maxwell.mcp_server`) expone diez herramientas y no arranca ninguna aplicación HTTP. Listar herramientas no resuelve ni escribe nada.

| Grupo | Herramientas |
| --- | --- |
| Lecturas puras (indicación de solo lectura, usables en modo Plan de Faustus) | `maxwell_examples`, `maxwell_materials`, `maxwell_check` |
| Cálculo y estudios | `maxwell_solve`, `maxwell_refinement`, `maxwell_compare`, `maxwell_design_search` |
| Referencias y geometría | `maxwell_verify_reference`, `maxwell_import_geometry` |
| Registros | `maxwell_records` |

La app lleva además procedimientos de la biblioteca de skills de la familia para los agentes que se conectan (`plate-thermal-stress-check`, `measured-improvement`, `verification-loop`). Aparecen en lo que el agente lee al conectarse, se leen con `skills_list` y `skill_read`, se buscan y asignan con `skills_library` y `skills_assign`, y se ofrecen como prompts. Se eligen en la página de skills (`/api/agent/skills/page`) o en la pestaña Skills del Hub.

## Estructura del proyecto

| Ruta | Contenido |
| --- | --- |
| `maxwell/fem.py`, `model.py` | Solver de elementos finitos y modelo del problema |
| `maxwell/studies.py`, `service.py` | Refinamiento, comparación, diseño inverso y registros |
| `maxwell/geometry_import.py` | Importación de perfiles STL |
| `maxwell/app.py`, `static/` | API HTTP y página web |
| `maxwell/mcp_server.py` | Servidor MCP |
| `maxwell/hoard_link/` | Código compartido de la familia Hoard |
| `tests/` | Pruebas |
| `data/records/` | Estudios guardados |
| `docs/` | Notas de investigación (en español) |

## Créditos

Python puro sobre NumPy y SciPy (licencias BSD); sin binarios externos de mallado ni de cálculo.
