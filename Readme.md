# Fluorómetro de clorofila de bajo costo para plantas 

Saber qué tan bien una planta aprovecha la luz no debería requerir un equipo comercial costoso. La fluorescencia de la clorofila *a* es el método más usado para estudiar fotosíntesis y estrés vegetal y puede delatar daño fisiológico antes de que aparezcan síntomas visibles [3], pero el costo del instrumento limita su acceso. Open-JIP demostró que un fluorómetro OJIP abierto, de entre 50 y 100 USD, es posible. Se parte de la versión para plantas y excita con un láser azul de 450 nm para mejorar la cadena de detección, reducir la variabilidad entre unidades y validar el equipo en hojas contra un instrumento comercial, documentado en este repositorio.

## 1. Contexto y problemática

La fluorescencia de la clorofila permite evaluar fotosíntesis y estrés vegetal sin destruir la muestra [1, 3]. Su principal limitante de acceso es el costo del instrumento, y el hardware abierto es una alternativa viable [2].

**Proyecto base: Open-JIP (versión para plantas).** Open-JIP es un fluorómetro abierto basado en la curva de inducción de Kautsky (OJIP), construido con componentes de bajo costo, impresión 3D y un microcontrolador  (Arduino Mega); existen dos configuraciones, una para plantas superiores y otra para microalgas [1]. La versión para plantas usa un LED COB de 10 W a 466 nm, un fotodiodo PIN BPW24R con filtro pasa-largo de 695 nm y un amplificador LM358, con un costo de 50 a 100 USD. **En este proyecto solo trabajamos el caso de plantas; la configuración para algas queda fuera de alcance.**

**Limitaciones reportadas en el estudio de Open-JIP [1]:**

- **Señaladas por los autores [1].**
  - Hace falta al menos un equipo comercial para la calibración cruzada y validación.
  - La variabilidad entre unidades proviene del cableado y de las marcas de los componentes.
- **Identificadas por nosotros.**
  - La validación contra el FL3500 (PSI) se hizo con *Chlorella vulgaris* y *Synechococcus* sp., no con hojas de plantas.
  - Usa un ADC de 10 bits, frente a los 12–16 bits de los equipos comerciales. Los autores muestran que bastó para resolver los transitorios, pero limita la resolución de F₀ y el rango dinámico.

## 2. Qué queremos hacer :rocket:

**Objetivo general.** Diseñar, construir y validar un fluorómetro de clorofila abierto y de bajo costo para hojas de plantas, tomando como base Open-JIP [1] y mejorando sus limitaciones.

## 3. Principios físicos revisados :memo:
1. **Destinos de la energía absorbida.** La energía que absorben los pigmentos se reparte entre fotoquímica, disipación como calor y fluorescencia de la clorofila *a*. Los tres procesos compiten, así que un cambio en la eficiencia fotoquímica se refleja en la fluorescencia. Separar la componente fotoquímica de la no fotoquímica (*quenching*) permite derivar parámetros como Fv/Fm, ΦPSII y la tasa de transporte de electrones (ETR) [3].
2. **Efecto Kautsky y transitorio OJIP.** Cuando una muestra pasa de la oscuridad a la luz, su fluorescencia sube rápido y luego decae lentamente. En el ascenso rápido, la fluorescencia sigue el cierre progresivo de los centros de reacción del fotosistema II (PSII): **O** (~50 µs, fluorescencia mínima F₀, aceptor primario QA oxidado), **J** (~2 ms, equilibrio entre la reducción de QA y su oxidación por aceptores secundarios), **I** (~30 ms, heterogeneidad de la reserva de plastoquinona) y **P** (máximo, Fm) [2, 4].
3. **Excitación y saturación.** El OJIP necesita un pulso de luz que sature los centros del PSII: irradiancias por encima de 1800 µmol fotones m⁻² s⁻¹ [1]. Open-JIP excita en azul (466 nm) [1]. En otro estudio se midió que el pico de excitación del extracto de clorofila rinde 38 % más que la línea de 405 nm, que sirve mejor como fuente de medición de baja dosis [2].
4. **Espectro de emisión y filtro óptico.** La clorofila *a* emite *in vivo* en dos bandas, de 680–690 nm y de 730–740 nm [5]. Cortar en 680–690 nm recupera la banda roja, pero esta se reabsorbe dentro del tejido y deforma el espectro medido [6]. Cortar en 700–720 nm reduce la reabsorción, pero suma la contribución del PSI, que no sigue la fotoquímica del PSII [7]. El filtro pasa-largo de 680–700 nm es, por tanto, un compromiso (Open-JIP usa 695 nm [1]). El filtro también rechaza la fluorescencia azul-verde (400–630 nm) que induce la excitación UV, interferencia para un fluorómetro de clorofila [5].
5. **Fotodiodo PIN de silicio.** Convierte luz en corriente. Sin polarización (modo fotovoltaico) tiene la mínima corriente oscura; con polarización inversa (modo fotoconductivo) la región de agotamiento se ensancha, baja la capacitancia de juntura y mejoran la velocidad y la linealidad, a costa de más corriente oscura [8]. El BPW34 responde entre 430 y 1100 nm y tiene 70 pF sin polarizar frente a ~25 pF (típico) con 3 V [9].
6. **Amplificador de transimpedancia.** Convierte la fotocorriente en voltaje. Su ancho de banda y su estabilidad dependen de la capacitancia del fotodiodo, de la resistencia de realimentación y del producto ganancia-ancho de banda del amplificador; un capacitor de realimentación compensa el efecto de esa capacitancia [10]. Al cambiar de fotodiodo hay que reajustarlo (Open-JIP fija 1 pF para el suyo) [1]. Una alternativa es el integrador conmutado con resta analógica, que evita el compromiso entre ganancia y tiempo de subida, a cambio de un circuito integrado más caro y difícil de conseguir [2].
7. **Muestreo y resolución del ADC.** El OJIP exige capturar F₀ unos 50 µs después de encender el LED y resolver la fase O–J (~2 ms), lo que requiere 5000 muestras/s o más [2]. Open-JIP usa un ADC de 10 bits frente a los 12–16 bits de los equipos comerciales [1].

## 5. Antecedentes relacionados

- **PAM de muy bajo costo** (< 300 USD): fotodiodo de avalancha, láser de 405 nm e integrador conmutado; frente a un Junior-PAM, ΦPSII correlacionó con pendiente 1.03 y R² = 0.87.
- **Imagen de fluorescencia de bajo costo** con cámara monocromática y LEDs azules.
- **Realimentación de iluminación en agricultura de ambiente controlado** usando la fluorescencia como variable de control, hasta ahora con fluorómetros comerciales.
- **Modelos livianos de aprendizaje automático** para detectar o clasificar estrés a partir de curvas de fluorescencia. Son compatibles con un fluorómetro que registra de forma autónoma.

## Miembros y Roles :rocket:
-----

| Photo | Name | Role | 
| :---: | :---: | :---: |
|<img src="Resources/Images-members/Jose-Vilchez.jpeg" width="200"> | Jose Ignacio Vilchez Cayetano | Responsable del Área Óptica|
|Image 2  | Cadney Veliana Condor | Responsable del Area de Instrumentación|
|<img src="Resources/Images-members/Ivan-Prudencio.jpeg" width="200"> | Ivan Esteban Prudencio Ramos | Responsable del Área de Procesamiento y visualización de datos|
|Image 4 | Martin Rivas | Responsable del Área Mecánica|

## 7. Referencias principales :link:
-----
[1] Bates, H., Zavafer, A., Szabó, M., y Ralph, P. J. (2019). A guide to Open-JIP, a low-cost open-source chlorophyll fluorometer. *Photosynthesis Research*, 142(3), 361–368. https://doi.org/10.1007/s11120-019-00673-2

[2] Haidekker, M. A., Dong, K., Mattos, E., y van Iersel, M. W. (2022). A very low-cost pulse-amplitude modulated chlorophyll fluorometer. *Computers and Electronics in Agriculture*, 203, 107438. https://doi.org/10.1016/j.compag.2022.107438

[3] Baker, N. R. (2008). Chlorophyll fluorescence: a probe of photosynthesis in vivo. *Annual Review of Plant Biology*, 59, 89–113. https://doi.org/10.1146/annurev.arplant.59.032607.092759

[4] Stirbet, A., y Govindjee. (2011). On the relation between the Kautsky effect (chlorophyll a fluorescence induction) and photosystem II: Basics and applications of the OJIP fluorescence transient. *Journal of Photochemistry and Photobiology B*, 104(1–2), 236–257. https://doi.org/10.1016/j.jphotobiol.2010.12.010

[5] Buschmann, C., y Lichtenthaler, H. K. (1998). Principles and characteristics of multi-colour fluorescence imaging of plants. *Journal of Plant Physiology*, 152, 297–314.

[6] Pedrós, R., Moya, I., Goulas, Y., y Jacquemoud, S. (2008). Chlorophyll fluorescence emission spectrum inside a leaf. *Photochemical & Photobiological Sciences*, 7, 498–502. https://doi.org/10.1039/b719506k

[7] Pfündel, E. (1998). Estimating the contribution of photosystem I to total leaf chlorophyll fluorescence. *Photosynthesis Research*, 56, 185–195. https://doi.org/10.1023/A:1006032804606

[8] Thorlabs, Inc. (s. f.). *Photodiode tutorial* [Documentación técnica]. https://www.thorlabs.com

[9] Vishay Semiconductors. (s. f.). *BPW34, BPW34S: Silicon PIN photodiode* (Document Number 81521) [Hoja de datos]. https://www.vishay.com

[10] Texas Instruments. (2009). *Transimpedance considerations for high-speed amplifiers* (Application Report SBOA122). https://www.ti.com/lit/sboa122
