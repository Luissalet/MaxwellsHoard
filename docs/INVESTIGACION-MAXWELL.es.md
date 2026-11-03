# Maxwell: decisiones de la primera entrega

## Dominio elegido
Un único dominio físico por cálculo, en dos variantes que comparten geometría, malla y elementos: conducción térmica estacionaria y elasticidad lineal en tensión plana, sobre perfiles planos de espesor uniforme. Quedan fuera fluidos, contacto, pandeo, plasticidad, curado y transitorios: no comparten la dificultad de validación.

## Formulación
- Geometría: rectángulo exterior + regiones rectangulares (material, hueco, fuente de calor, convección en caras). La malla pasa exactamente por cada borde de región y extremo de tramo de contorno; cada celda se divide en dos triángulos cuadráticos T6.
- Material: biblioteca nominal (acero S235, aluminio 6061-T6, cobre, FR-4 efectivo, ABS) o propiedades propias; los valores siempre aparecen en las hipótesis.
- Condiciones: temperatura, convección, flujo y aislamiento; empotramiento, apoyo deslizante, fuerza total, presión y gravedad. Un borde sin condición es aislado/libre, y así se dice.
- Comprobaciones internas: balance de energía y equilibrio de fuerzas en cada resultado (residuo relativo ~1e-12 en los ejemplos).
- Lo que falta se pregunta: mecanismo (rango de los modos rígidos restringidos < 3 por cada trozo conexo), cuerpo sin salida de calor, propiedad de material ausente, carga sobre un borde vacío.

## Referencias analíticas y refinamiento
| Referencia | Magnitud | Error (malla por defecto) |
| --- | --- | --- |
| Voladizo, carga en extremo | flecha en punta (Euler-Bernoulli + cortante Timoshenko) | 0,23 % |
| Voladizo | tensión de flexión a media luz | 0,70 % |
| Placa cuadrada calentada | temperatura en el centro (serie de Fourier doble) | 0,005 % |
| Placa cuadrada calentada | temperatura en un cuarto | 0,011 % |
| Pared con convección | temperatura exterior (resistencias en serie) | exacta (1e-13) |

Además cada referencia cambia una condición (doble carga, doble fuente) y comprueba la respuesta. El refinamiento ×1/×2/×4 da orden observado ≈4 en la placa (extrapolación de Richardson a 2e-7 del valor) y ≈1–1,5 en desplazamientos del voladizo (dominados por la esquina empotrada); los picos de von Mises en esquinas entrantes y extremos de empotramiento se marcan como «no convergen», que es lo correcto: son singulares.

## Viabilidad en Windows y licencias
- Implementación propia en Python con NumPy y SciPy (BSD-3): instala con pip en Windows sin compiladores; 29 pruebas en el PC en ~12 s.
- FEniCSx (LGPL-3) no tiene ruedas nativas de Windows: exige conda o WSL; Gmsh es GPL-2+ con excepciones de enlazado. Ninguno se distribuye aquí; quedan como opción si se necesitan mallas no estructuradas, revisando antes su distribución.
- Rendimiento: la búsqueda de 35 variantes del soporte con revalidación tarda ~3–6 s; el mayor estudio de refinamiento (93 500 incógnitas) <1 s por nivel.

## API, MCP y objetos
- Objetos: problema (JSON), resultado (resumen, sondas, requisitos, hipótesis, campo), estudio (refinamiento, comparación, búsqueda) y registro con entrada exacta.
- HTTP: `/api/check`, `/api/solve`, `/api/refinement`, `/api/compare`, `/api/search`, `/api/import`, `/api/references`, `/api/records`.
- MCP: `maxwell_check`, `maxwell_solve`, `maxwell_refinement`, `maxwell_compare`, `maxwell_design_search`, `maxwell_verify_reference`, `maxwell_import_geometry`, `maxwell_examples`, `maxwell_materials`, `maxwell_records`.

## Intercambio con Vulcan
Vulcan genera piezas en STL (receta CAD paramétrica o biblioteca). Maxwell las lee por su API local (`/library/api/models/{id}` del estudio, con vuelta a `/api/models/{id}` en versiones anteriores) o por archivo, detecta el eje delgado, muestrea la sección a media altura y al 20 %/80 % para rechazar piezas que no son de espesor constante, convierte los huecos en regiones vacías ajustadas a las coordenadas reales de los vértices y compara volumen (0,2 % en la placa con agujero de Vulcan, exacto en piezas de bordes rectos). Si el módulo Biblioteca 3D está apagado, lo pregunta en vez de encenderlo.

## Diseño inverso
La búsqueda usa 1–3 parámetros con significado, malla gruesa, y revalida los mejores candidatos factibles en malla fina y en casos de carga reservados que no participan en la búsqueda. En el soporte de ejemplo, los tres candidatos más ligeros cumplen en búsqueda y en malla fina pero fallan con un 25 % más de carga: se descartan y se recomienda el cuarto. Se entrega la frontera de compromisos factibles (masa frente a desplazamiento), no un diseño único. El análisis estadístico de fronteras sigue siendo cosa de Nightingale.

## Pendiente de evidencia real
Las pruebas son sintéticas o analíticas. Falta medir una pieza real (temperaturas con termopar o flecha con comparador) y contrastarla: eso no se puede hacer desde el código.
