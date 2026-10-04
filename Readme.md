# Fluorómetro de clorofila de bajo costo para plantas 

:rocket: Saber qué tan bien una planta aprovecha la luz no debería requerir un equipo comercial costoso. La fluorescencia de la clorofila *a* es el método más usado para estudiar fotosíntesis y estrés vegetal y puede delatar daño fisiológico antes de que aparezcan síntomas visibles [3], pero el costo del instrumento limita su acceso. Open-JIP demostró que un fluorómetro OJIP abierto, de entre 50 y 100 USD, es posible. Nosotros partimos de su versión para plantas y la llevamos más lejos: mejorar la cadena de detección, reducir la variabilidad entre unidades y validarla contra un equipo comercial, con todo documentado en este repositorio.

## 1. Contexto y problemática

La fluorescencia de la clorofila permite evaluar fotosíntesis y estrés vegetal sin destruir la muestra [1, 3]. Su principal limitante de acceso es el costo del instrumento, y el hardware abierto es una alternativa viable [32].

**Proyecto base: Open-JIP (versión para plantas).** Open-JIP es un fluorómetro abierto basado en la curva de inducción de Kautsky (OJIP), construido con componentes de bajo costo, impresión 3D y un microcontrolador abierto (Arduino Mega); existen dos configuraciones, una para plantas superiores y otra para microalgas [1]. La versión para plantas usa un LED COB de 10 W a 466 nm, un fotodiodo PIN BPW24R con filtro pasa-largo de 695 nm y un amplificador LM358, con un costo de 50 a 100 USD. **En este proyecto solo trabajamos el caso de plantas; la configuración para algas queda fuera de alcance.**

**Limitaciones reportadas en el estudio de Open-JIP [1]:**

- Usa un ADC de 10 bits, frente a los 12–16 bits de los equipos comerciales.
- Falta al menos un equipo comercial para calibración cruzada. La validación contra el FL3500 (PSI) que recoge nuestro estado del arte se hizo con *Chlorella vulgaris* y *Synechococcus* sp., no con hojas de plantas.
- La variabilidad entre unidades proviene del cableado y de las marcas de los componentes.

## 2. Qué queremos hacer :rocket:

**Objetivo general.** Diseñar, construir y validar un fluorómetro de clorofila abierto y de bajo costo para hojas de plantas, tomando como base Open-JIP [1] y mejorando sus limitaciones.

## 3. Principios físicos revisados :memo:
### A. Fotofísica de la clorofila y fluorescencia inducida

1. **Destinos de la energía absorbida.** La energía absorbida por los pigmentos puede usarse en fotoquímica, disiparse como calor o reemitirse como fluorescencia de la clorofila *a*. Los tres procesos compiten y sus rendimientos cuánticos suman uno, así que una caída de la eficiencia fotoquímica se refleja en la fluorescencia [3, 6, 7].
2. **Fluorescencia molecular y desplazamiento de Stokes.** Tras absorber un fotón, la molécula emite a una longitud de onda mayor que la de excitación (desplazamiento de Stokes); la fracción de fotones absorbidos que se reemite es el rendimiento cuántico de fluorescencia [22]. Por eso el detector puede separarse de la excitación con un filtro pasa-largo.
3. **Efecto Kautsky.** Cuando una muestra pasa de la oscuridad a la luz, su fluorescencia sube rápido y luego decae lentamente. Fue descrito por Kautsky y Hirsch en 1931 [8].
4. **Transitorio OJIP y fotosistema II.** En el aumento polifásico rápido (alrededor de 1 s) la fluorescencia refleja el cierre progresivo de los centros de reacción del PSII: **O** (~50 µs, fluorescencia mínima F₀, aceptor primario QA oxidado), **J** (~2 ms, equilibrio entre la reducción de QA y su oxidación por aceptores secundarios), **I** (~30 ms, heterogeneidad de la reserva de plastoquinona) y **P** (máximo, Fm) [8, 9].
5. **Extinción (*quenching*) fotoquímica y no fotoquímica.** La señal se interpreta separando la componente fotoquímica de la disipación térmica; de ahí derivan parámetros como Fv/Fm, el rendimiento cuántico efectivo del PSII (ΦPSII) y la tasa de transporte de electrones (ETR) [7, 11].
6. **Familias de medición.** La modulación por amplitud de pulso (PAM) mide con pulsos cortos y detecta solo la componente alterna, lo que permite trabajar bajo luz ambiental restando el fondo [10, 11]. El OJIP registra el transitorio rápido bajo un pulso saturante [9]. La tasa de repetición rápida (FRR) se usa sobre todo en fitoplancton [5, 12].
7. **Saturación fotoquímica.** Para cerrar todos los centros del PSII, el OJIP requiere irradiancias superiores a 1800 µmol fotones m⁻² s⁻¹ [1].

### B. Espectro y óptica de la hoja

8. **Espectro de emisión *in vivo* y reabsorción.** La emisión tiene dos bandas, en 680–690 nm y en 730–740 nm [13]. Su cociente baja al aumentar el contenido de clorofila por reabsorción de la banda roja y se usa como indicador de estrés [14]. Esa reabsorción dentro del tejido deforma el espectro medido respecto del emitido [16, 17]. Cortar en 700–720 nm la reduce, pero incorpora la contribución del PSI, que no sigue la fotoquímica del PSII [18]. De ahí que el filtro pasa-largo de 680–700 nm sea un compromiso.
9. **Fluorescencia azul-verde (interferencia).** La excitación UV de hojas verdes induce una fluorescencia azul-verde (400–630 nm) además de la de clorofila *a* (630–800 nm) [13]. Proviene sobre todo de ácidos hidroxicinámicos de la pared celular, con el ácido ferúlico como principal emisor [15]. Para un fluorómetro de clorofila es interferencia y la elimina el filtro pasa-largo. Como implicación de diseño, hay que verificar la autofluorescencia de las piezas impresas y del tubo bajo UV, que emiten en esa misma región.
10. **Longitud de onda de excitación y profundidad de sondeo.** El perfil de absorción de la luz dentro de la hoja depende del color incidente, así que la longitud de onda de excitación fija la profundidad de sondeo [19]. Además, Fv/Fm depende de la longitud de onda de excitación [20], y lo mismo ocurre con los parámetros de transporte de electrones medidos con PAM multicolor [21]. Los sistemas abiertos convergen en azul (466 nm en Open-JIP, 450–495 nm en [3]) y se midió que el pico de excitación del extracto de clorofila rinde 38 % más que la línea de 405 nm [2].

### C. Detección y electrónica

11. **Fotodiodo PIN de silicio.** Puede operar en modo fotovoltaico (sin polarización, con la mínima corriente oscura) o fotoconductivo (polarización inversa). La polarización inversa ensancha la región de agotamiento, reduce la capacitancia de juntura, acelera la respuesta y mejora la linealidad, a costa de más corriente oscura [23]. El BPW34 responde entre 430 y 1100 nm y tiene 70 pF de capacitancia sin polarizar, frente a unos 25 pF (típico) con 3 V en inverso [24].
12. **Amplificador de transimpedancia (TIA).** Convierte la fotocorriente en voltaje. Su ancho de banda y su estabilidad dependen de la capacitancia del fotodiodo, de la resistencia de realimentación y del producto ganancia-ancho de banda del amplificador operacional; un capacitor de realimentación compensa el efecto de esa capacitancia [25]. Al cambiar de fotodiodo hay que reajustarlo (Open-JIP fija 1 pF para el suyo) [1]. Una alternativa es integrar en lugar de amplificar: un integrador conmutado con resta analógica evita el compromiso entre ganancia y tiempo de subida y permite variar la ganancia por software con la duración del pulso, con un circuito integrado más caro y difícil de conseguir [2].
13. **Filtros ópticos de borde.** Los filtros interferenciales desplazan su borde con el ángulo de incidencia; los absorbentes son angularmente estables y más baratos [27]. Open-JIP usa un filtro de 695 nm [1].
14. **Muestreo, aliasing y resolución del ADC.** Una señal debe muestrearse a una tasa suficiente para evitar el aliasing, y la resolución finita del ADC introduce ruido de cuantización [26]. En OJIP, F₀ debe capturarse unos 50 µs después de encender el LED y la fase O–J dura unos 2 ms, lo que exige 5000 muestras/s o más [2]; Open-JIP resuelve con 10 bits [1].

## 5. Antecedentes relacionados

- **PAM de muy bajo costo** (< 300 USD): fotodiodo de avalancha, láser de 405 nm e integrador conmutado; frente a un Junior-PAM, ΦPSII correlacionó con pendiente 1.03 y R² = 0.87 [2].
- **Imagen de fluorescencia de bajo costo** con cámara monocromática y LEDs azules [3].
- **Realimentación de iluminación en agricultura de ambiente controlado** usando la fluorescencia como variable de control, hasta ahora con fluorómetros comerciales [28, 29].
- **Modelos livianos de aprendizaje automático** para detectar o clasificar estrés a partir de curvas de fluorescencia [30, 31]. Son compatibles con un fluorómetro que registra de forma autónoma.

## Miembros y Roles :rocket:
-----

| Photo | Name | Role | 
| :---: | :---: | :---: |
|<img src="Resources/Images-members/Jose-Vilchez.jpeg" width="200"> | Jose Ignacio Vilchez Cayetano | Responsable del Área Óptica|
|Image 2  | Cadney Veliana Condor | Responsable del Area de InstrumentaciÓn|
|<img src="Resources/Images-members/Ivan-Prudencio.jpeg" width="200"> | Ivan Esteban Prudencio Ramos | Responsable del Área de Procesamiento y visualización de datos|
|Image 4 | Martin Rivas | Responsable del Área Mecánica|

## 7. Referencias principales :link:
-----
