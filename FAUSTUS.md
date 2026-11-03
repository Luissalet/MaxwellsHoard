# Maxwell's Hoard — capacidades para Faustus

Estado: v0.1.0, candidato (no registrado en Hub). Arranque explícito `python -m maxwell` (puerto 5243). MCP stdio `python -m maxwell.mcp_server`.

## Puede
- Resolver conducción térmica estacionaria 2D (fuentes por región, convección en bordes y caras, flujo, temperaturas fijas) con balance de energía.
- Resolver elasticidad lineal en tensión plana (empotramientos, apoyos deslizantes, fuerzas, presión, gravedad) con equilibrio de fuerzas, von Mises, masa y factor de seguridad.
- Convertir datos ausentes en preguntas (sujeción, salida de calor, propiedades de material).
- Verificar contra 3 referencias analíticas y estudiar refinamiento de malla con orden observado y detección de singularidades.
- Comparar variantes por rutas con veredicto frente a requisitos.
- Diseño inverso paramétrico (1-3 parámetros) con revalidación en malla fina y casos de carga reservados; frontera de compromisos factibles.
- Importar perfiles de espesor constante desde STL o desde un modelo de Vulcan's Hoard (API local, `VULCAN_URL`).
- Guardar cada estudio con su entrada exacta.

## No puede (todavía)
- 3D, fluidos, radiación explícita, contacto, pandeo, plasticidad, fatiga, transitorios, propiedades dependientes de temperatura.
- Geometría curva exacta (los perfiles importados se escalonan; picos de tensión junto a huecos curvos sobreestimados).
- Identificación de parámetros desde medidas reales.

## Herramientas MCP
maxwell_examples, maxwell_materials, maxwell_check, maxwell_solve, maxwell_refinement, maxwell_compare, maxwell_design_search, maxwell_verify_reference, maxwell_import_geometry, maxwell_records.
