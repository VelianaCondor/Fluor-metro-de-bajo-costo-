# Fotodiodo de gran área + ESP32-S3: resumen de pruebas y análisis del divisor

*Estado al 31 de octubre de 2026*

---

## 1. Montaje actual

| Elemento | Detalle |
|---|---|
| Módulo | "Very Low Noise Large Area Photodiode" V1.2 (vendedor techminds, eBay) |
| Fotodiodo | Hamamatsu **S1227-1010BQ**: área 10 × 10 mm, ventana de cuarzo, 190–1000 nm, ~0.36 A/W en el pico, capacitancia ~3000 pF |
| Amplificador | Op-amp de Linear Tech (U3) en transimpedancia. **Rf = 1 MΩ** (SMD código 1004) → 1 V de salida = 1 µA de fotocorriente |
| Alimentación | Fuente de laboratorio a **12.0 V**, límite de corriente 50–80 mA |
| Riel interno | La placa regula a ~5 V para el op-amp, por eso la salida satura cerca de 5 V y no de 12 V |
| Divisor | **R1 = 10 kΩ** (OUT → pin), **R2 = 10 kΩ** (pin → GND), **C = 10 nF** (pin → GND) |
| Pin ADC | **GPIO2 = ADC1_CH1** (ADC1 funciona con WiFi activo) |
| Protección | **Sin diodos Schottky** por ahora |
| Microcontrolador | ESP32-S3-DevKitC-1, alimentado por USB, tierra común con la fuente y la placa |
| Firmware | `fotodiodo_esp32s3_v3.ino` |

```
 Fuente 12 V ──► PWR +12V ┐
 Fuente GND ───► PWR GND  ┤ Placa fotodiodo
                          │
            OUT ──[R1 10k]──┬──────┬──► GPIO2 (ADC1_CH1)
                            │      │
                         [R2 10k] [10 nF]
                            │      │
 GND placa ─────────────────┴──────┴──► GND ESP32 ── GND fuente
```

---

## 2. Mediciones de referencia

### 2.1 Calibración simultánea multímetro + ESP32 (31-oct-2026)

Los dos registros se alinearon en el tiempo por correlación cruzada (correlación 0.999; el ESP32 empezó ~45 s después del multímetro).

| Punto | Multímetro (OUT) | ESP32 (V_adc en el pin) |
|---|---|---|
| Saturación | **4.718 V** | 2.3470 V |
| Nivel bajo estable | **0.100 V** | 0.0258 V |
| **Oscuridad (fotodiodo tapado)** | **0.030 V** | ~0.0001 V (zona muerta) |

**Modelo de calibración (2 puntos):**

> V_out = 1.9894 · V_adc + 0.0488 V

- La pendiente (1.989) está a −0.5 % del valor nominal del divisor (2.0): la ganancia del ADC es buena.
- El error principal es un **offset**: el ADC lee **~24 mV de menos en el pin** (~49 mV en OUT).
- Los puntos intermedios (0.3–4.7 V) concuerdan dentro de ±1–2 %. La dispersión que queda viene de que el multímetro toma 1 lectura/s en un instante desconocido mientras la luz cambiaba.

### 2.2 Zona muerta del ADC cerca de 0 V

Cuando OUT está por debajo de **~0.05 V** (pin < ~24 mV), el ADC del ESP32-S3 marca prácticamente 0. Ejemplo: el multímetro leía 30 mV y el ESP32 0.2 mV.

**Esto corrige una conclusión anterior:** el "fondo de 5.5 mV" que vimos con el fotodiodo tapado **no era real**, era la zona muerta del ADC. La oscuridad medida con el multímetro es **30 mV en OUT** (31.5 mV en el amplificador, ~31.5 nA). Como cae dentro de la zona muerta, el código la usa como valor fijo (`V_DARK_OUT_MM`) en vez de medirla con `d`.

### 2.3 Resistencia de salida de la placa (R6)

| Condición | Saturación en OUT |
|---|---|
| Sin carga (17-oct) | 4.97 V |
| Con divisor 10k/10k (31-oct) | 4.718 V |

> R_serie = 20 kΩ × (4.97 / 4.718 − 1) ≈ 1.07 kΩ

Coincide con **R6 = 1 kΩ** de la placa. Por eso K_CARGA = 21/20 = 1.05.

La lectura de **4.814 V del 23-oct no encaja** con el resto: el ESP32 leyó la misma saturación (V_adc ≈ 2.348 V) ambos días, así que la placa no cambió. Lo más probable es que esa medición se tomara en otra condición (otro punto de medida o el divisor desconectado parcialmente). Se descarta y se usa la del 31-oct.

### 2.4 Ruido

| Magnitud | Valor |
|---|---|
| Ruido del ADC con promedio por ventana de 16.7 ms | **~0.8 mV RMS en OUT** (medido en saturación, donde la salida de la placa está quieta) |
| Resolución práctica | ~1 en 6000 del fondo de escala (≈ 12.5 bits) |

El valor anterior de ~0.25 mV RMS se midió en el borde de la zona muerta, donde el ADC comprime las lecturas, así que subestimaba el ruido.

---

## 3. Qué pasaría con R1 = 8.2 kΩ en lugar de 10 kΩ

### 3.1 Cálculo

Con R1 = 8.2 kΩ y R2 = 10 kΩ, el divisor total baja a 18.2 kΩ y la relación sube a 10 / 18.2 = 0.549.

| Parámetro | R1 = 10 kΩ (actual) | R1 = 8.2 kΩ | Cambio |
|---|---|---|---|
| Relación del divisor | 0.500 | 0.549 | +9.9 % |
| Carga total sobre OUT | 20.0 kΩ | 18.2 kΩ | −9 % |
| Saturación en bornera OUT | 4.718 V (medido) | ~4.71 V (estimado) | −7 mV |
| **Voltaje máximo en el pin** | **~2.36 V** | **~2.59 V** | +0.23 V |
| Margen hasta ~3.1 V (límite útil del ADC a 12 dB) | ~0.74 V | ~0.51 V | menor |
| Margen hasta 3.3 V (máximo del pin) | ~0.94 V | ~0.71 V | menor |
| Impedancia vista por el ADC (R1 ∥ R2) | 5.0 kΩ | 4.5 kΩ | ligeramente mejor |
| Polo RC con 10 nF | ~3.2 kHz | ~3.5 kHz | sin efecto práctico |
| Pin si OUT llegara a 12 V (falla de la placa) | **6.0 V** | **6.6 V** | ambos dañinos sin diodos |
| A_CAL en el código (nominal) | ~1.99 | ~1.81 | recalibrar |
| K_CARGA en el código | 1.050 | ~1.055 | se calcula solo |

### 3.2 Qué se gana

- **~10 % más del rango del ADC.** La misma señal ocupa ~10 % más códigos. Eso equivale a ~0.14 bits, es decir, una mejora de relación señal/ruido de ~0.8 dB.
- El ruido referido a OUT bajaría de ~0.8 mV a ~0.7 mV RMS. Es una diferencia difícil de notar.
- La impedancia que ve el ADC baja un poco, lo que ayuda marginalmente al muestreo.

### 3.3 Qué se pierde

- **Menos margen de seguridad**: el máximo pasa de ~2.36 V a ~2.59 V en el pin. Sigue dentro del rango útil del ADC (~0–3.1 V con 12 dB de atenuación), pero más cerca del tramo alto, donde el ADC del ESP32-S3 es menos lineal.
- **Sin diodos Schottky, una falla de la placa es peor**: si el regulador interno fallara y OUT llegara a 12 V, el pin recibiría 6.6 V en vez de 6.0 V. Ninguno de los dos casos es seguro, pero con 8.2k el exceso es mayor.
- **Hay que recalibrar**: la tolerancia de las resistencias (1–5 %) cambia `A_CAL` y `B_CAL`.

### 3.4 Recomendación

**Mantener 10k/10k por ahora.** La mejora de 8.2k es real pero pequeña (~10 % de rango, <1 dB), y el montaje no tiene diodos de protección.

El cambio a 8.2k tiene sentido solo si se cumplen **las dos** condiciones:

1. Están instalados los diodos de protección (2× BAT85 o BAT43, o un BAT54S): uno del pin a 3V3 y otro de GND al pin.
2. Se hace una calibración de dos puntos después del cambio.

Si se necesita más resolución, el divisor no es la palanca importante. Las opciones que sí cambian el resultado son:

- **Aumentar la luz útil o ajustar Rf**, para que la señal de interés use más rango de la placa.
- **Un ADC externo** (ADS1115 de 16 bits, o ADS1220 de 24 bits) para señales lentas y débiles.
- **Un ADC SAR rápido por SPI** si se busca dinámica rápida, como la curva OJIP de fluorescencia.

### 3.5 Cambios en el código si se adopta 8.2 kΩ

```cpp
const float R1_K = 8.2;   // antes 10.0
// K_DIV y K_CARGA se recalculan solos.
// Repetir la calibración de 2 puntos y actualizar A_CAL y B_CAL
```

---

## 4. Firmware v3: qué hace y por qué

| Función | Motivo |
|---|---|
| Promedio por **ventana de 16.667 ms** (2 ciclos de 120 Hz) | Las luces del ambiente parpadean a 120 Hz (red de 60 Hz). Muestreando a 50 Hz ese parpadeo aparecía como una oscilación falsa de **20 Hz** (aliasing). Con una ventana de duración múltiplo del ciclo, el parpadeo se cancela |
| Periodo mínimo de 20 ms | La ventana ya dura ~17 ms |
| `analogReadMilliVolts()` | Usa la calibración de fábrica del chip |
| `V_out = A_CAL·V_adc + B_CAL` (1.9894 y 0.0488 V) | Calibración de 2 puntos contra el multímetro; corrige el offset del ADC |
| `K_CARGA` calculado con R_serie = 0.648 kΩ | Recupera el voltaje del amplificador sin la caída por carga (V_tia ∝ fotocorriente) |
| Columna `est` | 0 = válida, 1 = saturada (OUT ≥ 4.69 V), 2 = bajo el rango del ADC (OUT < ~0.05 V) |
| Offset de oscuridad fijo `V_DARK_OUT_MM = 0.030 V` (comandos `r` y `z`) | La oscuridad está en la zona muerta del ADC; se usa el valor del multímetro |
| Comando `d` con **buffer del último segundo** | En la versión anterior, `d` midió justo cuando la señal bajó momentáneamente, y guardó un valor erróneo. Ahora usa muestras ya registradas antes del comando, y avisa si estaban en la zona muerta del ADC |
| Comando `i` | Muestra la configuración y cuántas lecturas entran en cada ventana |

Salida CSV: `t_ms, V_adc, V_out, V_tia, V_neta, I_nA, est`

- **V_out**: voltaje en la bornera OUT, comparable con el multímetro con el divisor puesto.
- **V_tia**: voltaje del amplificador sin carga. Es la magnitud física: **I_foto = V_tia / Rf**.
- **V_neta**: V_tia menos el offset de oscuridad.
- **I_nA**: fotocorriente neta en nA (con Rf = 1 MΩ, 1 mV = 1 nA).

---

## 4b. Escala física con Rf = 1 MΩ

| Magnitud | Voltaje (V_tia) | Corriente | Potencia óptica aprox. (0.36 A/W, pico) |
|---|---|---|---|
| Saturación | 4.97 V | ~5.0 µA | ~14 µW sobre 1 cm² |
| Oscuridad (tapado, multímetro) | ~31.5 mV | ~31.5 nA | ~90 nW equivalentes |
| Ruido del ADC (0.8 mV RMS) | 0.8 mV | ~0.8 nA | ~2 nW |

- La potencia depende de la longitud de onda: a 633 nm la sensibilidad es ~0.34 A/W, y fuera del pico es menor.
- Según la hoja de datos, este fotodiodo da 32–44 µA a 100 lux. Con 1 MΩ, la placa satura con apenas **~12–15 lux**. Por eso la luz normal de una habitación la satura.
- Los ~31.5 nA en oscuridad están muy por encima de la corriente oscura del fotodiodo sin polarización. Pueden ser luz que aún se filtra o un offset eléctrico de la placa. Para distinguirlos, tapa mejor (caja cerrada, varias capas): si el valor baja, era luz; si se mantiene en 30 mV, es offset de la placa.
- Con el ESP32, cualquier corriente menor a ~50 nA cae en la zona muerta del ADC.

## 4c. Cómo medir por debajo de la zona muerta (opcional)

1. **Resistencia de 100 kΩ de 3V3 al pin.** Con R1 = R2 = 10 kΩ, desplaza el pin a ~0.16 V cuando OUT = 0 V, y la saturación queda en ~2.40 V (dentro del rango). Contras: el ruido del riel de 3V3 entra atenuado ~20 veces, y hay que recalibrar.
2. **ADC externo (ADS1115)**: mide bien desde 0 V y elimina el problema de raíz.

## 5. Resumen de lo conversado

1. **Identificación**: el módulo trae el fotodiodo Hamamatsu S1227-1010BQ, así que no fue necesario comprar otro. La salida debe adaptarse porque el ESP32 solo tolera 0–3.3 V.
2. **Fuente**: no importa su corriente máxima. Se configura a 12 V con el límite de corriente en 50–80 mA, y se verifica la polaridad antes de conectar.
3. **Saturación**: se esperaban ~12 V, pero la placa satura en ~4.97 V por su riel interno de ~5 V. Por eso el divisor inicial de 33k/10k desperdiciaba rango.
4. **Divisor**: se propuso 8.2k/10k y se eligió **10k/10k** por margen, al no tener diodos de protección.
5. **Pin**: GPIO2 corresponde a ADC1_CH1 (y GPIO1 a ADC1_CH0). Ambos son del ADC1 y funcionan con WiFi. Hay que evitar los pines de arranque (0, 3, 45, 46).
6. **Diodos de protección recomendados**: BAT85 o BAT43 (DO-35, aptos para protoboard), o BAT54S (SOT-23). Conviene baja fuga; los 1N5817/1N5819 son solo un último recurso.
7. **ADC externo**: no es necesario ahora. Con el promedio por ventana, el ADC del ESP32 rindió **~0.8 mV RMS** en OUT, mejor que la estimación inicial de 5–10 mV. Pero tiene una zona muerta bajo ~0.05 V en OUT (~50 nA). Un ADC externo se justifica para medir corrientes menores a eso o para dinámica rápida.
8. **Diagnóstico de los datos**:
   - Patrón de 20 Hz → parpadeo de 120 Hz con aliasing → corregido con la ventana de 16.7 ms.
   - Fondo de ~55 mV → luz filtrada. El "~5.5 mV" posterior resultó ser la zona muerta del ADC, no oscuridad real.
   - Escalones de pocos mV → pequeños cambios de luz residual; muestran la sensibilidad del sistema.
   - `d` guardó un offset incorrecto → corregido con el buffer del último segundo.
9. **Calibración**: con registros simultáneos (31-oct) se obtuvo V_out = 1.9894·V_adc + 0.0488 V, se confirmó R6 ≈ 1 kΩ (K_CARGA = 1.05) y se encontró la zona muerta del ADC bajo ~0.05 V en OUT. La lectura de 4.814 V del 23-oct se descartó.
10. **Rf = 1 MΩ** (SMD 1004): 1 V en el amplificador = 1 µA.

---

## 6. Pendientes

- [x] Leer **Rf**: código 1004 = **1 MΩ**.
- [x] Oscuridad con el multímetro: **30 mV en OUT** (fotodiodo tapado).
- [ ] Repetir en **oscuridad total** (caja cerrada) para saber si los 30 mV son luz filtrada u offset de la placa.
- [x] Calibración de dos puntos simultánea (31-oct).
- [ ] Repetir la calibración con **luz fija sostenida ≥ 5 s en cada nivel** (~0.5, 1, 2, 3, 4 V) para afinar los puntos intermedios.
- [ ] Si se necesita medir por debajo de ~50 nA: sacar la señal de la zona muerta (resistencia de polarización al pin o ADC externo, ver sección 4c).
- [ ] Instalar los diodos de protección en el nodo del ADC.
- [ ] Construir una caja oscura con fuente de luz en DC para mediciones repetibles.
- [ ] Decidir si se pasa a R1 = 8.2 kΩ (solo después de los dos puntos anteriores).
