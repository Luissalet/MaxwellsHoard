# Maxwell's Hoard — capacidades para Faustus

Estado: v0.1.0, candidato (no registrado en Hub). Arranque explícito `python -m maxwell` (puerto 5243). MCP stdio `python -m maxwell.mcp_server`.

Correcciones1982 preparadas sobrea86a49f; revisión e integración pendientes junto a la baseecosystem1935. Espacio propio maxwell y proyectoFaustus1548272a539c.51pruebas positivas, incluidas15de revisión y MCPstdio real; interfaz probada enBrave con datos inventados.

## Puede
- Resolver conducción térmica estacionaria 2D (fuentes por región, convección en bordes y caras, flujo, temperaturas fijas) con balance de energía.
- Resolver elasticidad lineal en tensión plana (empotramientos, apoyos deslizantes, fuerzas, presión, gravedad) con equilibrio de fuerzas, von Mises, masa y factor de seguridad.
- Convertir datos ausentes en preguntas (sujeción, salida de calor, propiedades de material).
- Verificar contra 3 referencias analíticas y estudiar refinamiento de malla con orden observado y detección de singularidades.
- Comparar variantes por rutas con veredicto frente a requisitos.
- Diseño inverso paramétrico (1-3 parámetros) con revalidación en malla fina y casos de carga reservados; frontera de compromisos factibles.
- Importar perfiles de espesor constante desde STL o desde un modelo de Vulcan's Hoard (API local, `VULCAN_URL`).
- Validar todas las caras de la extrusión antes del muestreo: rechazar fondos, vaciados ciegos y paredes inclinadas aunque coincidan tres secciones. Las tolerancias geométricas declaradas admiten el redondeo de STL float32.
- Guardar cada estudio con su entrada exacta.

La convección de coeficiente cero no fija temperatura. Un requisito de factor de seguridad pregunta por cualquier resistencia de material que falte; sin ese requisito se pueden calcular desplazamientos, pero el factor global queda indefinido. El refinamiento exige niveles crecientes y mallas distintas. El balance térmico sin flujo informa su resolución numérica. Los registros tienen IDs únicos y publicación atómica, preservando lectores deIDs anteriores.

## No puede (todavía)
- 3D, fluidos, radiación explícita, contacto, pandeo, plasticidad, fatiga, transitorios, propiedades dependientes de temperatura.
- Geometría curva exacta (los perfiles importados se escalonan; picos de tensión junto a huecos curvos sobreestimados).
- Identificación de parámetros desde medidas reales.

## Herramientas MCP
Integración de familia1987: panel canónico mediante `/api/copilot`, borrador actual y última operación con su entrada exacta. El panel usa Faustus y sus modelos globales. Descubrir MCP no arranca HTTP; el Hub dispone de arranque explícito con puerto adaptable. Contrato HTTP agent no implementado; las10 herramientas propias se exponen por MCPstdio. Candidato pendiente de revisión e integración.

maxwell_examples, maxwell_materials, maxwell_check, maxwell_solve, maxwell_refinement, maxwell_compare, maxwell_design_search, maxwell_verify_reference, maxwell_import_geometry, maxwell_records.
