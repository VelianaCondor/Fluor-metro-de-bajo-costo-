# Fluorómetro de clorofila — Procesamiento, visualización y comunicaciones

Software del área de **procesamiento y comunicaciones** del fluorómetro para la detección de clorofila. Incluye:

- el firmware de los dos microcontroladores: el **ESP32-S3** (maestro) y el **ESP32** del nodo cámara;
- la **aplicación web local en Python**, que recibe, procesa, muestra y guarda las mediciones;
- un **simulador** del maestro para desarrollar y probar la aplicación sin hardware.

> Estado: el firmware compila sin errores ni advertencias con arduino-esp32 **3.3.2**, y la aplicación se probó de punta a punta con el simulador (por TCP y por puerto serie virtual). **Aún no se ha probado sobre el hardware real.**

---

## Contenido del paquete

```
firmware/
  comun/protocolo_espnow.h          Protocolo ESP-NOW (copia maestra)
  maestro_esp32s3/
    maestro_esp32s3.ino             Maestro: adquisición, LED, control térmico, enlace con la PC
    protocolo_espnow.h              (idéntico al de comun/)
  nodo_camara_esp32/
    nodo_camara_esp32.ino           Nodo cámara: OV7670 + pulsador + envío por ESP-NOW
    protocolo_espnow.h              (idéntico al de comun/)
pc_app/
  app.py                            Servidor local (FastAPI + WebSocket)
  protocolo.py                      Tramas S3 ↔ PC, CRC y estructuras binarias
  enlace.py                         Conexión por puerto COM o Wi-Fi, búsqueda automática
  procesamiento.py                  Intensidad, imagen de fluorescencia, cinética rápida, caracterización
  almacenamiento.py                 Organización de los datos en disco
  simulador_s3.py                   Imita al maestro (sin hardware)
  static/index.html                 Página web (Plotly servido localmente)
  requirements.txt
  datos/                            Aquí se guardan las sesiones
```

---

## Arquitectura

```
                 ┌──────────────── Cámara oscura ─────────────────┐
  LED azul 450 nm ─► hoja ─► filtro pasa-largo 650 nm ─┬─► fotodiodo + TIA ─► divisor ─┐
        ▲                                               └─► OV7670                      │
        │ encendido                                           │ DVP 8 bits              │ ADC1
        │                                                     ▼                         ▼
        │                                         ┌───────────────────┐  ESP-NOW  ┌────────────────────────┐
        │                                         │ ESP32 nodo cámara │◄─────────►│ ESP32-S3 maestro       │
        │                                         │ + pulsador        │           │ núcleo 1: sensores     │
        └─────────────────────────────────────────┴───────────────────┘           │ núcleo 0: comunicación │
                                                                                  └──────────┬─────────────┘
  2 × SHT31 (I2C) ──► lazos PI ──► 2 × AOD4184 (PC817) ──► 2 extractores 12 V                │
                                                                       USB/COM o Wi-Fi (TCP) │
                                                                                             ▼
                                                                  PC: app.py → http://127.0.0.1:8000
```

### Reparto de núcleos del ESP32-S3 (FreeRTOS)

| Tarea | Núcleo · prioridad | Periodo | Qué hace |
|---|---|---|---|
| `tareaTermica` | 1 · 3 | 500 ms | Lee los dos SHT31, calcula dos lazos PI y escribe el PWM de los extractores |
| `tareaFotodiodo` | 1 · 2 | 20 ms | Promedia el ADC en ventanas de 16.7 ms, controla el LED y ejecuta las mediciones |
| `tareaComs` | 0 · 2 | 2 ms | ESP-NOW, enlace USB/TCP, comandos, anuncio UDP y envío de resultados |

La pila Wi-Fi corre en el núcleo 0, y el watchdog del sistema solo vigila la tarea ociosa de ese núcleo. Por eso las tareas de tiempo crítico van al núcleo 1. Los dos núcleos se comunican solo mediante colas, una notificación de tarea y banderas.

---

## Hardware y pines (según el firmware actual)

### Maestro (ESP32-S3-DevKitC-1 N8R8)

| Función | GPIO | Notas |
|---|---|---|
| Señal del detector | 2 (ADC1_CH1) | Divisor 10k/10k + 10 nF |
| Encendido del LED de excitación | 21 | Salida digital de habilitación (`LED_ACTIVO_ALTO`) |
| I2C de los SHT31 | 8 (SDA), 9 (SCL) | 0x44 = estrato inferior (LED) · 0x45 = estrato superior (detector) |
| Extractor inferior / superior | 17 / 18 | PWM de 120 Hz hacia la entrada TRIG de cada módulo AOD4184 |
| Enlace con la PC | Conector COM (CH343) o USB nativo | 921 600 baudios por el CH343 |

> ⚠️ **Pendiente — alinear con el esquemático final.** En el esquemático, la señal del detector va a **GPIO4**, la consigna de corriente del LED (PWM filtrado hacia el LM358) a **GPIO5**, y los extractores a **GPIO13 / GPIO14**. Hay que cambiar en `maestro_esp32s3.ino` las constantes `PIN_PD`, `PIN_LED_EXC`, `PIN_FAN_INF` y `PIN_FAN_SUP`. Además, `ledExc()` debe escribir un **duty de PWM** (la consigna de corriente) en lugar de un nivel digital.

### Nodo cámara (ESP32 DevKit)

| OV7670 | ESP32 (firmware) |
|---|---|
| SIOC / SIOD | 22 / 21 (pull-up de 4.7 kΩ a 3V3) |
| XCLK / PCLK | 32 / 33 |
| VSYNC / HREF | 34 / 35 |
| D0…D7 | 36, 39, 23, 18, 19, 25, 26, 27 |
| RESET / PWDN | 14 / 13 |
| Pulsador | 4 → GND (pull-up interno) |

> ⚠️ El esquemático final usa otro reparto de pines de datos (D0/D1 en IO16/IO17, PCLK en IO25, VSYNC/HREF en IO27/IO14). Si se cablea según el esquemático, hay que actualizar los `#define CAM_PIN_*`. Si la placa es WROVER, IO16/IO17 no están disponibles (los usa la PSRAM).

---

## Modos de medición (maestro)

Todos los modos restan una **línea base con el LED apagado**. La ventana de 16.7 ms (1/60 s) anula los 60 Hz y sus armónicos, entre ellos el parpadeo de 120 Hz de la iluminación y el PWM de los extractores.

| Modo | Cómo se inicia | Qué hace | Resultado |
|---|---|---|---|
| Continuo | Siempre activo | Un valor cada 20 ms | Señal en vivo y CSV |
| Intensidad | Página | 400 ms de línea base, luego el LED encendido de 0.2 a 12 s, con un punto cada 20 ms | F(t), F en ventana fija, RSD, deriva |
| Intensidad + imagen | Pulsador o página | Lo anterior, más un cuadro **oscuro** antes de encender y un cuadro **con luz** a `t_foto_ms` | Lo anterior + mapa de fluorescencia |
| Blanco | Página | Intensidad sobre una referencia no fluorescente | Se resta de las mediciones siguientes |
| Cinética rápida | Página (hoja adaptada a oscuridad) | ADC a máxima velocidad con marca de tiempo, de 0.1 a 2 s; 30 intervalos por década desde 10 µs | F0, FJ, FI, FM, Fv/Fm, VJ, M0, PIabs |
| LED continuo | Página | LED encendido sin límite | Prueba de estabilidad |

Durante una medición **no se transmite a la PC**. En la cinética rápida, además, se suspende el lazo térmico, se apagan los extractores y se pide a la cámara que no transmita (`BUSY`).

> La cinética rápida requiere que el LED encienda en < 50 µs y que el capacitor del divisor del ADC se reduzca (≈ 1 nF). Con el filtro de consigna del esquemático actual (~20 ms de subida), solo es válido el modo de intensidad.

---

## Control térmico

- Hay dos lazos independientes: **inferior** (disipador del LED) y **superior** (detector). El set point inicial es 27 °C en ambos.
- La acción es inversa: e = T − SP. Un error positivo sube el PWM.
- Se usa un PI con integración condicional (anti-windup), con Kp = 20 %/°C y Ki = 0.5 %/(°C·s) como valores de partida.
- Ajustes para el ventilador de 2 hilos:
  - por debajo de 5 % de duty, el ventilador se apaga;
  - entre 5 % y 30 % se fuerza 30 % (`U_MIN`);
  - en cada arranque se aplica 100 % durante 400 ms.
- El PWM es de **120 Hz**, porque el PC817 del módulo conmuta lento. Si el módulo enciende con la entrada en bajo, poner `PWM_INVERTIDO = true`.
- Si un SHT31 falla, su extractor pasa al 100 %. Si un extractor está al 100 % y el estrato sigue 0.5 °C por encima durante 2 min, se marca `sp_inalc` y la página muestra un aviso.

---

## Comunicaciones

### ESP-NOW: nodo cámara ↔ maestro

La cámara está detrás del filtro de 650 nm, así que registra **fluorescencia** y necesita el LED encendido. Como el LED lo controla el maestro, el pulsador solo **solicita** la captura y el maestro dirige la secuencia:

```
pulsador → FOTO_SOLICITUD → S3
S3 → FOTO_PASO(OSCURO, AEC, ganancia) → cámara captura → FOTO_LISTO
S3 enciende el LED … a t_foto → FOTO_PASO(LUZ) → cámara captura → FOTO_LISTO
S3 apaga el LED al terminar el pulso
cámara → IMG_START / 79 × IMG_CHUNK / IMG_END (oscuro) ⇄ IMG_REPORT
cámara → IMG_START / 79 × IMG_CHUNK / IMG_END (luz)    ⇄ IMG_REPORT
S3 → PC: T_INT + T_IMG (oscuro) + T_IMG (luz)
```

| Mensaje | Sentido | Uso |
|---|---|---|
| `HELLO` / `HELLO_ACK` | cámara ↔ S3 | Búsqueda del canal (1 a 13) y presencia |
| `FOTO_SOLICITUD` | cámara → S3 | Se presionó el pulsador |
| `FOTO_PASO` | S3 → cámara | Capturar el cuadro oscuro o el de luz; exposición, ganancia y espera |
| `FOTO_LISTO` | cámara → S3 | Cuadro capturado |
| `IMG_START` / `IMG_CHUNK` / `IMG_END` | cámara → S3 | Cuadro de 160 × 120 en gris 8 bits = 19 200 B, en 79 trozos de 244 B, con CRC-32 |
| `IMG_REPORT` | S3 → cámara | OK / FALTAN (con mapa de bits de faltantes) / CRC_ERROR / DESCONOCIDA |
| `BUSY` | S3 → cámara | No transmitir durante la cinética rápida |

Cómo funciona la transferencia:
- **Control de flujo:** cada trozo espera el ACK de radio antes de enviar el siguiente.
- **Recuperación:** al final, el S3 responde con un reporte que indica qué trozos faltan, y la cámara reenvía solo esos.
- **Verificación:** un CRC-32 comprueba el cuadro completo. `esp_rom_crc32_le` da el mismo valor que `zlib.crc32` en Python.
- **Sin interferencia con la medición:** la cámara espera a que el LED se apague antes de transmitir.
- **Exposición fija:** el OV7670 trabaja con exposición y ganancia manuales, iguales en los dos cuadros. La librería `esp32-camera` no implementa ese ajuste para este sensor, así que el firmware escribe los registros AEC y GAIN directamente por SCCB.

### Trama S3 ↔ PC (igual por USB/COM y por TCP)

```
| A5 5A | tipo u8 | seq u8 | len u32 LE | payload (len B) | CRC-16 LE |
CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) sobre tipo…payload  (= binascii.crc_hqx en Python)
```

| Tipo | Sentido | Contenido |
|---|---|---|
| `0x01` HELLO | S3 → PC | JSON `{dev, fw, enlace, modo, wifi}` |
| `0x03` LOG | S3 → PC | Texto |
| `0x10` PD | S3 → PC | JSON `{t, vt, vn, s, led}` (lote cada 100 ms) |
| `0x11` TERM | S3 → PC | JSON `{t, sp[2], T[2], RH[2], u[2], ok[2], sp_inalc[2], manual[2]}` (1 Hz) |
| `0x12` cinética | S3 → PC | Cabecera de 34 B + n × `{t f32, F f32, n u16}` |
| `0x13` IMG | S3 → PC | Cabecera de 22 B `{foto_id, captura_id, rol, ancho, alto, formato, crc32, bytes, t_rx}` + píxeles |
| `0x14` ESTADO | S3 → PC | JSON `{enlace, wifi, ip, rssi, cam, cam_hace_ms, led, heap, psram}` (1 Hz) |
| `0x15` INT | S3 → PC | Cabecera de 40 B + n × `{t f32, F f32}` |
| `0x80` CMD | PC → S3 | JSON (ver comandos) |
| `0x81` RESP | S3 → PC | JSON `{ok, cmd}` |

### Comandos PC → S3

| Comando | Efecto |
|---|---|
| `{"cmd":"hello"}` / `{"cmd":"hb"}` | Identificación / latido (cada 1 s) |
| `{"cmd":"intensidad","dur_ms":2000,"foto":0}` | Medición de intensidad |
| `{"cmd":"foto","dur_ms":2000}` | Intensidad + imagen (lo mismo que el pulsador) |
| `{"cmd":"ojip","dur_ms":1000,"led":1}` | Cinética rápida |
| `{"cmd":"led","on":1}` | LED continuo encendido/apagado |
| `{"cmd":"cam","aec":300,"ganancia":16,"t_foto_ms":1000,"dur_ms":2000}` | Exposición de la cámara y tiempos |
| `{"cmd":"dark"}` / `{"cmd":"reset_dark"}` | Guardar / borrar el offset de oscuridad |
| `{"cmd":"periodo","ms":20}` | Periodo del modo continuo (20 a 2000 ms) |
| `{"cmd":"sp","n":0,"valor":27}` | Set point del estrato n (0 inferior, 1 superior; sin `n` = ambos) |
| `{"cmd":"pi","kp":20,"ki":0.5}` | Ganancias del PI |
| `{"cmd":"fan","n":0,"duty":60}` | Duty manual (`duty: -1` vuelve a automático) |
| `{"cmd":"enlace","modo":0}` | 0 automático · 1 forzar USB · 2 forzar Wi-Fi |
| `{"cmd":"img"}` | Reenviar los últimos cuadros |

### Elección del enlace: puerto COM o Wi-Fi

**Arranque de red del maestro (`MODO_WIFI`):**
- `WIFI_ROUTER_O_AP` (por defecto): intenta conectarse al router (`STA_SSID`). Si no lo logra en 10 s, crea su propia red `FLUOROMETRO-UNI` (canal 1, 192.168.4.1). Así el equipo siempre arranca.
- `WIFI_ROUTER`: solo usa el router.
- `WIFI_AP_PROPIO`: solo usa la red propia.
- En todos los casos, el maestro anuncia su IP por **UDP en el puerto 3334** cada 2 s, para que la PC lo encuentre aunque el router le cambie la IP.

**Búsqueda desde la PC** (`enlace.py`, modo `auto`):
1. Prueba los puertos COM con VID conocido (WCH CH34x, Espressif, Silabs): envía HELLO y espera la respuesta.
2. Si ninguno responde, escucha el anuncio UDP durante 2.5 s y prueba **TCP 3333** en las IP anunciadas y en las IP fijas (`--host`, por defecto 192.168.4.1).
3. Con el enlace activo, envía un latido cada 1 s. Si pasan 5 s sin tramas, vuelve a buscar.

**El maestro** escucha siempre los dos enlaces y transmite por el que recibió una trama válida en los últimos 3 s (USB primero), salvo que se haya forzado uno.

**Recomendación:** decidir el enlace por defecto midiendo el ruido de la línea base con el detector a oscuras en cada caso: USB y Wi-Fi, con y sin PWM de los extractores. Mientras no haya datos, usar **USB para desarrollo y calibración**.

---

## Aplicación en la PC

### Instalación y ejecución

```bash
cd pc_app
pip install -r requirements.txt        # fastapi, uvicorn, websockets, pyserial, numpy, pillow, plotly

python app.py                          # automático: COM si responde; si no, Wi-Fi
python app.py --modo serie --puerto COM5
python app.py --modo wifi              # encuentra la IP por el anuncio UDP
python app.py --modo wifi --host 192.168.1.50
```

Abrir **http://127.0.0.1:8000**. La página sirve Plotly desde el paquete instalado, así que funciona sin internet, por ejemplo con la PC conectada a la red propia del equipo.

Opciones: `--baud` (921600), `--puerto-tcp` (3333), `--http` (8000), `--rgb565-le` (solo si se usa la cámara en RGB565 y los colores salen cambiados).

### Procesamiento (`procesamiento.py`)

**Intensidad.** La señal se modela como S = S<sub>fluorescencia</sub> + S<sub>reflexión/dispersión</sub> + S<sub>ambiente</sub> + S<sub>fondo</sub>.
- S<sub>ambiente</sub> + S<sub>fondo</sub> se eliminan con la línea base de LED apagado, que resta el maestro, y con la ventana de 16.7 ms.
- S<sub>reflexión/dispersión</sub> se estima con el **blanco**: F neta = F − F<sub>blanco</sub>.
- F se lee **siempre en la misma ventana del pulso** (por defecto, la segunda mitad), porque con luz continua la fluorescencia sube a un pico y luego decae.
- También se calculan el RSD dentro de la ventana, la deriva y el pico.

**Imagen de fluorescencia.**
- Se calcula la diferencia luz − oscuro, que quita el offset del sensor y la luz parásita.
- Si hay un campo plano registrado, se divide por él para corregir la falta de uniformidad de la iluminación.
- Una máscara por umbral de Otsu delimita el área que emite.
- Se reportan la media, el CV espacial, los percentiles P5/mediana/P95 y el porcentaje de zonas por debajo del 60 % de la mediana.
- Se genera un mapa de calor con contorno en las zonas bajas.

**Cinética rápida.**
- F0, FK, FJ y FI se obtienen a 50 µs, 300 µs, 2 ms y 30 ms, interpolando en log t.
- FM es el máximo de la curva, suavizada con una mediana de 3 puntos.
- Parámetros derivados: Fv/Fm, VJ, VI, M0, Sm, ψE0, φE0 y PIabs.
- Se incluye una interpretación orientativa.

**Control de calidad.** La aplicación genera avisos por saturación, deriva > 5 %, SNR bajo, falta de blanco, F0 tardío, muestreo < 20 kS/s, píxeles saturados y cuadro oscuro con nivel alto.

**Caracterización óptica.**

| Prueba | Cálculo | Criterio mostrado |
|---|---|---|
| Estabilidad de la excitación | (máx − mín)/media de la señal en vivo en la última ventana | El que fije el usuario (p. ej. 1 % en 60 s) |
| Uniformidad | Cada medición se asigna a un punto (x, y); se calculan Urel = (Emáx − Emín)/(Emáx + Emín) y el CV | — |
| Validación con espectrofluorómetro | Se asocia la lectura de referencia a la última F; ajuste y = m·x + b | R² ≥ 0.95 |
| Repetibilidad | Mediciones de la muestra activa | RSD < 5 % |

### Interfaz

La página tiene estos paneles:
- muestra con etiqueta;
- controles de medición (intensidad, intensidad + imagen, blanco, cinética rápida, offset de oscuridad, LED continuo);
- exposición de la cámara y campo plano;
- set points de los dos estratos;
- gráficas de F(t), imagen (luz, oscuro y mapa), cinética rápida, señal en vivo, temperatura y PWM;
- las cuatro pruebas de caracterización;
- registro de eventos.

Los indicadores superiores muestran el enlace activo, el tipo de red (router o red propia) con su IP, la muestra actual, si se ve la cámara y el estado del LED.

### Datos guardados

```
datos/sesion_AAAAMMDD_HHMMSS/
  telemetria_fotodiodo.csv          t_ms, V_tia, V_neta, sat, led
  termico.csv                       t_ms, sp_inf, sp_sup, T_inf, T_sup, RH_inf, RH_sup, u_inf, u_sup
  uniformidad.csv · validacion.csv
  muestra_001/
    notas.json                      etiqueta, si es blanco
    int_<id>.csv / .json            curva de intensidad y su análisis
    ojip_<id>.csv / .json           curva de cinética rápida y sus parámetros
    cap_<id>_luz.png · _oscuro.png · _mapa.png · .npz · .json
```

---

## Simulador (sin hardware)

```bash
python simulador_s3.py                         # TCP 127.0.0.1:3333 + anuncio UDP
python app.py --modo wifi

python simulador_s3.py --pty                   # Linux/macOS: imprime /dev/pts/N
python app.py --modo serie --puerto /dev/pts/N
```

El simulador genera:
- telemetría del fotodiodo;
- dos lazos térmicos;
- mediciones de intensidad con efecto de pico y descenso;
- cuadros oscuro y luz de una hoja sintética, con iluminación no uniforme y una zona dañada;
- curvas de cinética rápida;
- blancos (`blanco: 1`).

---

## Compilar y cargar el firmware

**Requisitos:** Arduino IDE con el core **arduino-esp32 3.x** (probado con 3.3.2) y la librería **Adafruit SHT31**, que instala también Adafruit BusIO.

| Sketch | Placa | Opciones |
|---|---|---|
| `maestro_esp32s3` | ESP32S3 Dev Module | PSRAM **OPI PSRAM**; USB CDC On Boot **Disabled** si se usa el conector COM (CH343), **Enabled** si se usa el USB nativo |
| `nodo_camara_esp32` | ESP32 Dev Module | Partition Scheme con SPIFFS/LittleFS |

Antes de cargar:
1. `protocolo_espnow.h` debe ser **idéntico** en las dos carpetas.
2. En `nodo_camara_esp32.ino`, poner en `MAC_S3` la MAC de estación del maestro: `{0x28, 0x84, 0x85, 0x87, 0xC1, 0xC0}`.
3. En `maestro_esp32s3.ino`, poner `STA_SSID` y `STA_PASS` del router, o dejarlos vacíos para usar la red propia.
4. Revisar los pines (ver la sección de hardware).

### Parámetros que se ajustan en el banco

| Parámetro | Archivo | Cómo se obtiene |
|---|---|---|
| `K_CAL`, `OFS_CAL`, `V_SAT_OUT`, `R_SERIE_K` | maestro | Calibración de 2 puntos con multímetro y el detector definitivo |
| `cam_aec`, `cam_ganancia`, `t_foto_ms` | maestro (o desde la página) | Imagen sin saturar y con nivel útil |
| `U_MIN`, `PWM_INVERTIDO` | maestro | Duty mínimo de giro del ventilador; polaridad del módulo |
| `KP`, `KI` | maestro (o comando `pi`) | Escalones manuales y modelo de primer orden con retardo |
| `SP_C` | maestro (o desde la página) | Requisito térmico de cada estrato |

---

## Limitaciones conocidas y pendientes

- Los pines del firmware deben alinearse con el esquemático final, y el LED debe pasar a una consigna PWM de corriente (ver arriba).
- La cinética rápida depende de que el LED encienda rápido y de reducir el capacitor del divisor del ADC.
- El ADC interno del ESP32-S3 muestrea entre 20 y 60 kS/s, sin espaciado uniforme. Si no basta, habrá que usar ADC continuo por DMA o un ADC externo.
- Falta medir en hardware: la tasa real de ESP-NOW, valores útiles de exposición del OV7670, la conmutación del PC817 con 3.3 V y la sintonía de los lazos PI.
- Antes de interpretar la imagen, revisar si la lente de la OV7670 trae un filtro de corte infrarrojo.
