# Fluorómetro de clorofila — procesamiento y visualización (v0.2)

Documento: `Fluorometro_Procesamiento_Comunicacion_v0.2.pdf` (se entrega aparte).

## Firmware (Arduino IDE, core arduino-esp32 3.3.x)
- `firmware/nodo_camara_esp32/` → placa **ESP32 Dev Module** (OV7670 en gris 8 bits + pulsador en GPIO4).
- `firmware/maestro_esp32s3/` → **ESP32S3 Dev Module**, PSRAM **OPI PSRAM**, USB CDC On Boot **Disabled**
  si usas el conector COM. Librería **Adafruit SHT31**.
- `protocolo_espnow.h` va idéntico en ambas carpetas.
- En el maestro: `STA_SSID`/`STA_PASS` para el router (vacío = red propia FLUOROMETRO-UNI).
- En el nodo cámara: `MAC_S3` = MAC de tu S3 (28:84:85:87:C1:C0).

## Aplicación en la PC
```
cd pc_app
pip install -r requirements.txt
python app.py                      # COM si responde; si no, Wi-Fi (encuentra la IP por anuncio UDP)
# abrir http://127.0.0.1:8000
```
Sin hardware: `python simulador_s3.py` y luego `python app.py --modo wifi`.
