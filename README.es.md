# Maxwell's Hoard

Ingeniería física de piezas planas en tu propio PC: **conducción térmica estacionaria** y **elasticidad lineal en tensión plana**, resueltas con elementos finitos cuadráticos, con todas las condiciones a la vista, cada resultado comprobado contra un balance y un solver en el que solo se confía hasta donde pasan sus referencias analíticas.

Maxwell guarda junto a cada resultado la geometría, materiales, apoyos, cargas, fuentes de calor, malla e hipótesis; almacena la entrada exacta de cada estudio y convierte el dato que falta (cómo se sujeta la pieza, por dónde sale el calor) en una pregunta concreta en vez de un supuesto invisible.

## Qué hace

- **Modelo del problema** (JSON, SI, °C): perfil rectangular con espesor uniforme; regiones rectangulares que cambian material, son huecos, llevan una fuente de calor (`power` W o `q` W/m³) o convección en caras; tramos de borde con temperatura, convección, flujo, empotramiento/apoyo deslizante, fuerzas totales o presión; gravedad; sondas; requisitos.
- **Solver**: triángulos de seis nodos (T6) sobre una rejilla que pasa exactamente por cada borde de región y tramo de contorno; integración exacta; resolución dispersa directa. Devuelve campos, extremos y dónde ocurren, medias por región, sondas, masa, factor de seguridad frente a fluencia, **balance de energía** y **equilibrio de fuerzas**.
- **Datos que faltan → preguntas**: pieza (o trozo separado) que aún puede moverse como sólido rígido, cuerpo sin salida de calor, material sin la propiedad necesaria.
- **Referencias analíticas**: viga en voladizo (flexión + cortante de Timoshenko y tensión a media luz), placa cuadrada calentada (serie de Fourier doble), pared con temperatura fija y convección. Cada una cambia además una condición y comprueba la respuesta.
- **Estudio de refinamiento de malla**: ×1, ×2, ×4, orden observado, extrapolación de Richardson, error estimado y aviso explícito cuando un pico no converge (esquinas entrantes y extremos de empotramiento son singulares).
- **Comparación de variantes** con cambios por ruta (`regions.vent.x0`, `boundary.equipment.fy`) y veredictos.
- **Diseño inverso**: 1–3 parámetros con significado, objetivo y requisitos; búsqueda en malla gruesa, revalidación de los mejores en malla fina **y en casos de carga reservados que no participaron en la búsqueda**; recomendación aceptada y frontera de compromisos factibles.
- **Geometría de Vulcan's Hoard**: un STL de espesor constante (por id de modelo de Vulcan o subido) se convierte en el perfil; los huecos pasan a regiones vacías con resolución declarada; se informa de la concordancia de volumen y se rechazan piezas cuya sección cambia a lo largo del espesor.
- **Registros** de cada cálculo y estudio con entrada, salida e hipótesis.

Encargos de ejemplo: qué disposición de ventilación mantiene bajo 85 °C una placa con dos fuentes de calor (la de la derecha falla), y un soporte en acero y aluminio con tres espesores, más una búsqueda que descarta el soporte más ligero porque no aguanta un caso reservado con un 25 % más de carga.

## Arranque

```
python -m venv .venv
.venv\Scripts\pip install -e .[test]
.venv\Scripts\python -m maxwell            # http://127.0.0.1:5243
.venv\Scripts\python -m pytest
```

API HTTP y herramientas MCP: ver README.md.

## Límites

Bidimensional (tensión plana; conducción en el plano con convección en caras opcional). Sin sólidos 3D, fluidos, radiación (salvo dentro de un coeficiente de convección), contacto, pandeo, plasticidad, fatiga, transitorios ni propiedades dependientes de la temperatura. Geometría rectangular exacta o aproximación escalonada de un perfil importado. Materiales con valores nominales. Solo Python (NumPy/SciPy, licencias BSD), sin binarios externos de mallado ni de cálculo.

## Skills para los agentes que se conectan

Esta app lleva procedimientos de la biblioteca de skills del espacio de trabajo de la familia para los agentes que se conectan: `plate-thermal-stress-check`, `measured-improvement`, `verification-loop`. Aparecen en lo que el agente lee al conectarse, se leen con `skills_list` y `skill_read`, se buscan y asignan con `skills_library` y `skills_assign`, y se ofrecen como prompts. Se eligen en la página de skills (`/api/agent/skills/page`) o en la pestaña Skills del hub; el bloque `skills` de `faustus-plugin.json` guarda lo que la app pide por defecto.
