# Subsistema óptico – Fluorómetro de bajo costo para fluorescencia foliar

Diseño, dimensionamiento e implementación del subsistema óptico de un fluorómetro de bajo costo para estudiar la fluorescencia foliar (clorofila a).

## Principio de medición

La lectura del detector no es fluorescencia pura:

`S_medida = S_fluorescencia + S_reflexión/dispersión + S_ambiente + S_fondo`

(modelo conceptual, no es una ecuación de calibración). El diseño busca favorecer la emisión de interés y reducir las demás contribuciones mediante selección espectral, geometría, filtrado y control de luz ambiental.

## Cambios realizados

| Elemento | Antes | Ahora |
|---|---|---|
| Fuente de excitación | Láser azul 450 nm, 5 mW (con colimador) | LED azul de alta potencia, 10 W nominales, limitado a **2 W eléctricos** por Electrónica |
| Motivo del cambio | Pérdidas de potencia, iluminación no uniforme, difícil reproducibilidad (fuente, colimador y alineación) | Iluminar un área foliar extensa y reducir sensibilidad a la alineación |
| Distribución de luz | Espejos de primera superficie | Guía reflectiva **tronco-cónica** con 4 espejos de primera superficie |
| Filtro de excitación | Filtro azul | Filtro azul 450 nm antes del embudo, para evitar la cola espectral del LED |
| Fotodiodo | BPW34 | **2DU10** (según datasheet: área fotosensible más conveniente y respuesta más rápida) |
| Canal complementario | — | Cámara **OV7670** con filtro rojo 650 nm |
| Procesamiento | — | Maestro–esclavo: ESP32-S3 (maestro) y ESP32-WROOM-32 (esclavo), vía ESP-NOW |
| Área de análisis | — | Círculo de ~4 a 5 cm de diámetro (forma/tamaño modificables) |

## Arquitectura

```
LED azul (2 W) → Filtro azul 450 nm → Guía tronco-cónica → Hoja
  → Filtro rojo pasa-largo 650 nm → Fotodiodo 2DU10 + OV7670 → Etapa de lectura
```

- **Canal fotodiodo:** transimpedancia de bajo ruido (señales del orden de nA), digitalizada por el ESP32-S3.
- **Canal cámara:** OV7670 (CMOS con filtro de Bayer) con filtro pasa-largo 650 nm delante del sensor; permite evaluar variaciones espaciales (mapas de calor, estrés localizado).
- **Comunicación:** el ESP32-WROOM-32 envía datos al ESP32-S3 por ESP-NOW.
- Ambos canales se analizan por separado (distinta respuesta espectral, área y lectura).

## Control de luz parásita, ruido y temperatura

- Fotodiodo y placa de bajo ruido en carcasa metálica (aluminio delgado, pintura negra mate), con abertura alineada al sensor y filtro rojo 650 nm.
- Blindaje tipo jaula de Faraday a tierra analógica y cables coaxiales cortos (ruido RF de los ESP32).
- Ventiladores para el LED y las placas: el flujo de aire se mantiene alejado de la muestra, y si se usa PWM debe comprobarse que no interfiera con la adquisición.

## Dimensionamiento

- Irradiancia: `E(θ, r) ≈ I_e(θ)·cosθ / r²`; para una fuente isotrópica, `E ≈ P_opt / (4πr²)` (estimación de primer orden). Se complementa con medición directa en el plano de la hoja.
- Uniformidad: `U_rel = (E_máx − E_mín) / (E_máx + E_mín) × 100 %`, medida en una cuadrícula de puntos sobre el área objetivo.
- La homogeneidad del área de 4 a 5 cm **no se afirma** hasta contar con los resultados de medición.

## Caracterización y validación

1. **Estabilidad del LED:** precalentamiento de 10 a 15 min como hipótesis de planificación; el tiempo real y el criterio de estabilidad se fijan con la prueba.
2. **Uniformidad:** cuadrícula de puntos con geometría definitiva; el resultado caracteriza el conjunto sensor-montaje, no necesariamente la irradiancia absoluta.
3. **Comparación con el espectrofluorómetro FLUORAT-02 Panorama** (accesorio de fibra óptica para sólidos), en oscuridad y con al menos tres grupos de hojas (sanas, estrés hídrico leve, clorosis o estrés avanzado).
   - Medición del prototipo: voltaje/corriente del fotodiodo y media de píxeles rojos de la OV7670, con exposición controlada del LED (evitar efectos de Kautsky y fatiga fotoquímica).
   - Criterios: regresión lineal `y = m·x + b` con **R² ≥ 0.95**; repetibilidad con 10 mediciones consecutivas y **RSD < 5 %**.

## Conclusión

Se sustituye el láser por un LED azul para iluminar un área foliar mayor y reducir la sensibilidad a la alineación, con guía reflectiva tronco-cónica, filtrado espectral de excitación y emisión, acondicionamiento por transimpedancia, cámara OV7670 complementaria y recinto contra luz ambiental. Las prestaciones finales dependerán de las mediciones de caracterización y validación descritas.
