# Sistema Integral de Gestión — UNAD
### Código: `213023_56_Fase4_Daniel_Santamaria.py` + `interfaz_grafica.py`

---

## Tabla de contenidos

1. [Descripción general](#1-descripción-general)
2. [Arquitectura de capas](#2-arquitectura-de-capas)
3. [Estructura del proyecto](#3-estructura-del-proyecto)
4. [Requisitos e instalación](#4-requisitos-e-instalación)
5. [Cómo ejecutar](#5-cómo-ejecutar)
6. [Manejo de concurrencia](#6-manejo-de-concurrencia-threading--queue)
7. [Criterios de validación](#7-criterios-de-validación)
8. [Máquina de estados FSM](#8-máquina-de-estados-reservas)
9. [Sistema de logs](#9-sistema-de-logs-y-trazabilidad)
10. [Persistencia de datos](#10-persistencia-de-datos-json)
11. [Mejoras implementadas](#11-mejoras-implementadas-fase-4)
12. [Decisiones de diseño](#12-decisiones-de-diseño)

---

## 1. Descripción general

Sistema de gestión de clientes, servicios turísticos y reservas, desarrollado
en Python puro con interfaz gráfica Tkinter. El sistema modela las operaciones
de una agencia de viajes: registro de clientes con validación de identidad,
creación de servicios (hotel, transporte, experiencia) con cálculo de precios,
y gestión del ciclo de vida de reservas mediante una máquina de estados formal.

---

## 2. Arquitectura de capas

El proyecto sigue una separación estricta de responsabilidades en tres capas,
inspirada en el patrón MVC adaptado a una aplicación de escritorio:

```
┌─────────────────────────────────────────────────┐
│              CAPA DE PRESENTACIÓN               │
│           interfaz_grafica.py                   │
│  • Widgets Tkinter (formulario, consola, botones)│
│  • Redirección de stdout (RedirectorConsolaGlobal│
│  • Comunicación entre hilos (queue.Queue)        │
│  • Formateo COP (_formatear_cop)                 │
│  • Persistencia JSON (_guardar_estado / _cargar) │
└──────────────────────┬──────────────────────────┘
                       │  llama a →
┌──────────────────────▼──────────────────────────┐
│              CAPA DE LÓGICA DE NEGOCIO           │
│      213023_56_Fase4_Daniel_Santamaria.py        │
│                                                  │
│  GestorSistema   ←── orquesta todo              │
│  ├── registrar_cliente()                         │
│  ├── crear_servicio()                            │
│  ├── crear_reserva()                             │
│  ├── cambiar_estado_reserva()   ← FSM            │
│  ├── bloquear_documento()       ← lista negra    │
│  ├── listar_clientes/servicios/reservas()        │
│  └── ValidadorNegocio           ← reglas BRE     │
│                                                  │
│  Entidades: Cliente, ServicioHotel,              │
│             ServicioTransporte, ServicioExperiencia│
│             Reserva, EstadoReserva (Enum)        │
└──────────────────────┬──────────────────────────┘
                       │  escribe a →
┌──────────────────────▼──────────────────────────┐
│           CAPA DE INFRAESTRUCTURA                │
│  • Logging:     sistema_gestion.log              │
│  • Persistencia: estado_sistema.json             │
│  • Funciones:   registrar_evento()               │
│                 registrar_error()                │
│                 registrar_advertencia()          │
│                 registrar_fraude()               │
└─────────────────────────────────────────────────┘
```

**Principio clave:** la capa de presentación **nunca reimplementa lógica de
negocio**. Solo invoca métodos del gestor y formatea los resultados para
mostrarlos en pantalla. Esto hace que la GUI sea intercambiable: se podría
reemplazar Tkinter por una interfaz web sin tocar una sola línea del gestor.

---

## 3. Estructura del proyecto

```
proyecto/
│
├── 213023_56_Fase4_Daniel_Santamaria.py   ← lógica de negocio (toda)
├── interfaz_grafica.py                    ← presentación Tkinter
├── README.md                              ← este archivo
│
├── sistema_gestion.log    ← generado al ejecutar (auditoría completa)
└── estado_sistema.json    ← generado al cerrar (persistencia de clientes)
```

---

## 4. Requisitos e instalación

| Requisito | Versión mínima | Notas |
|---|---|---|
| Python | 3.10+ | Necesario para `match/case` y `X \| Y` en type hints |
| tkinter | Incluido en Python | En Ubuntu: `sudo apt install python3-tk` |
| Módulos stdlib | — | `json`, `threading`, `queue`, `logging`, `re`, `uuid`, `enum` |

No se requieren dependencias externas (pip). El sistema funciona con la
biblioteca estándar de Python.

---

## 5. Cómo ejecutar

```bash
# Desde la carpeta del proyecto:
python interfaz_grafica.py
```

La GUI localiza automáticamente el archivo de lógica de negocio buscando
el patrón `*Fase4*Santamaria*.py` en la misma carpeta. Si el archivo no se
encuentra, se muestra un mensaje de error claro antes de cerrar.

Para ejecutar solo la lógica (sin GUI):
```bash
python "213023_56_Fase4_Daniel_Santamaria.py"
```

---

## 6. Manejo de concurrencia (threading + Queue)

La interfaz gráfica de Tkinter es **de un solo hilo** (single-threaded). Si
una operación larga corre en el mismo hilo que maneja los eventos de la
ventana, esta se congela.

**Solución implementada:**

```
Hilo principal (Tkinter)                Hilo de trabajo
────────────────────────                ───────────────────────────
_on_ejecutar_simulacion()
  → deshabilita botones
  → lanza Thread ─────────────────────→ _ejecutar_simulacion_en_hilo()
                                           redirector.activar(cola)
after(100 ms) ──┐                          print("✅ ...") → cola.put()
                ↓                          print("❌ ...") → cola.put()
_procesar_cola_mensajes()                  ...
  → cola.get_nowait()                      cola.put("__SIMULACION_FINALIZADA__")
  → _escribir_consola(msg)
  → se reprograma en 100 ms
```

**Componentes clave:**

- `queue.Queue` — cola thread-safe para pasar mensajes del hilo de trabajo
  al hilo principal sin condiciones de carrera.
- `RedirectorConsolaGlobal` — reemplaza `sys.stdout` **una sola vez** al
  arrancar. Usa `threading.local()` para que cada hilo tenga su propio
  destino de salida, sin interferir con los demás.
- `daemon=True` en los hilos de trabajo — garantiza que el proceso termine
  correctamente si el usuario cierra la ventana mientras hay una operación
  en curso.
- Sentinels — mensajes especiales en la cola que señalizan el fin de una
  operación: `"__SIMULACION_FINALIZADA__"` y `("__CLIENTE_REGISTRADO__", bool)`.

---

## 7. Criterios de validación

### 7.1 Validación de cédulas (documentos de identidad)

Implementada en `Cliente.documento` (setter) y `ValidadorNegocio.es_documento_valido()`.

| Regla | Detalle | Ejemplo de rechazo |
|---|---|---|
| Solo dígitos | Sin letras ni símbolos | `"ABC123"` |
| Longitud 8–10 dígitos | Rango legal colombiano | `"1234567"` (7 dígitos) |
| No empieza en 0 | Cédulas colombianas válidas no lo hacen | `"012345678"` |
| Sin dígitos repetidos | Detecta secuencias de fraude | `"11111111"`, `"99999999"` |
| Sin secuencia ascendente | Detecta patrones triviales | `"12345678"`, `"23456789"` |

Los intentos con documentos de fraude se registran con nivel `FRAUDE` en el
log, diferenciándolos de errores de sistema comunes.

### 7.2 Generación de documentos sintéticos

Para pruebas y simulación, `_generar_documento_sintetico()` genera cédulas
realistas en el rango oficial colombiano post-2000:

```
Rango: 1.000.000.000 – 1.150.000.000
```

El generador descarta automáticamente cualquier número que viole las reglas
del validador anterior, garantizando que los datos de prueba siempre sean
coherentes con las reglas de negocio.

### 7.3 Validación de emails

| Criterio | Descripción |
|---|---|
| Formato RFC básico | Debe contener `@` y dominio con punto |
| Dominio corporativo | `ValidadorNegocio.es_email_corporativo()` rechaza dominios personales (`gmail.com`, `hotmail.com`, `yahoo.com`) y desechables (`mailinator.com`, `tempmail.com`) |
| Dominios aceptados | `.edu.co`, `.gov.co`, `.com.co`, `.org.co`, y dominios corporativos genéricos |

### 7.4 Validación de servicios

| Campo | Regla |
|---|---|
| `precio_base` | Debe ser `> 0`; se lanza `ServicioInvalidoError` si es negativo o cero |
| `noches` (hotel) | Entero positivo |
| `estrellas` (hotel) | Entre 1 y 5 |
| `participantes` (experiencia) | Entero positivo |

### 7.5 Lista negra de documentos

`GestorSistema` mantiene un `set` privado `__lista_negra_documentos`. Cualquier
intento de registrar un cliente cuyo documento esté en la lista lanza
`DocumentoBloqueadoError`, que el logger clasifica como intento de fraude.

---

## 8. Máquina de estados (Reservas)

Las reservas siguen una FSM (Finite State Machine) formalizada en un
diccionario de transiciones dentro de `GestorSistema`:

```
        ┌──────────┐
  ─────▶│ PENDIENTE│
        └────┬─────┘
             │ confirmar
      ┌──────▼──────┐      cancelar    ┌───────────┐
      │  CONFIRMADA │────────────────▶│ CANCELADA │
      └──────┬──────┘                  └───────────┘
             │ finalizar
      ┌──────▼──────┐
      │  FINALIZADA │
      └─────────────┘

  PENDIENTE ──cancelar──▶ CANCELADA  (también válida)
```

**Transiciones válidas:**

| Desde | Acción | Hacia |
|---|---|---|
| `PENDIENTE` | `confirmar` | `CONFIRMADA` |
| `PENDIENTE` | `cancelar` | `CANCELADA` |
| `CONFIRMADA` | `finalizar` | `FINALIZADA` |
| `CONFIRMADA` | `cancelar` | `CANCELADA` |

Cualquier otra combinación lanza `EstadoReservaError` y se registra en el
log con nivel `ERROR`, incluyendo el ID de la reserva y la transición
intentada.

---

## 9. Sistema de logs y trazabilidad

El sistema escribe en `sistema_gestion.log` usando el módulo `logging` de
Python con rotación automática.

**Niveles diferenciados:**

| Función | Nivel | Uso |
|---|---|---|
| `registrar_evento()` | `INFO` | Operaciones exitosas (registro, confirmación) |
| `registrar_advertencia()` | `WARNING` | Situaciones anómalas no críticas |
| `registrar_error()` | `ERROR` | Errores de validación, transiciones inválidas |
| `registrar_fraude()` | `CRITICAL` | Documentos en lista negra, patrones de fraude |

**Formato de cada entrada:**
```
2025-07-03 14:22:05 | INFO     | Cliente registrado: Cliente[cb3c2d88] Ana Gómez
2025-07-03 14:22:05 | CRITICAL | FRAUDE — Doc bloqueado: 7654321098 (Sospechoso Prueba)
2025-07-03 14:22:05 | ERROR    | Transición inválida: CONFIRMADA → CONFIRMADA [a0a02ae4]
```

El archivo de log persiste entre sesiones y nunca se sobreescribe, acumulando
un historial completo de todas las operaciones.

---

## 10. Persistencia de datos (JSON)

Al cerrar la ventana (clic en la X o `Alt+F4`), el sistema serializa
automáticamente el estado del gestor del formulario manual en
`estado_sistema.json`.

**Formato del archivo:**
```json
{
  "timestamp": "2025-07-03T14:22:05",
  "version": "1.0",
  "clientes": [
    {
      "nombre": "Camila Torres",
      "documento": "1023456789",
      "email": "camila@empresa.com.co",
      "telefono": "3109876543"
    }
  ]
}
```

Al iniciar la aplicación en sesiones posteriores, los clientes guardados
se restauran automáticamente. Si el archivo está corrupto o ausente, el
sistema arranca con un gestor vacío sin interrumpir la ejecución.

**¿Por qué JSON y no pickle?**

- JSON es legible por humanos y editable con cualquier editor de texto.
- `pickle` ejecuta código Python arbitrario al deserializar: un archivo
  manipulado podría comprometer el sistema. JSON no tiene ese riesgo.
- JSON es portable entre versiones de Python y sistemas operativos.

---

## 11. Mejoras implementadas (Fase 4)

| # | Mejora | Archivo | Estado |
|---|---|---|---|
| 1 | Generación de documentos sintéticos realistas | `interfaz_grafica.py` | ✅ |
| 2 | Formato de moneda COP (`$375.000,00`) | `interfaz_grafica.py` | ✅ |
| 2 | `ValidadorNegocio` — BRE para documentos y emails | `sistema.py` | ✅ |
| 3 | Lista negra de documentos con `DocumentoBloqueadoError` | `sistema.py` | ✅ |
| 4 | Logger diferenciado por nivel (INFO/ERROR/CRITICAL/FRAUDE) | `sistema.py` | ✅ |
| 4 | Persistencia JSON con `WM_DELETE_WINDOW` | `interfaz_grafica.py` | ✅ |
| 5 | FSM formal de estados de reservas | `sistema.py` | ✅ |
| — | Threading thread-safe con `threading.local()` | `interfaz_grafica.py` | ✅ |
| — | Registro de cliente en hilo propio (sin bloquear GUI) | `interfaz_grafica.py` | ✅ |
| — | Reinicio de gestor entre simulaciones | `interfaz_grafica.py` | ✅ |

---

## 12. Decisiones de diseño

**¿Por qué `importlib` y no un import normal?**
El archivo de lógica de negocio tiene espacios y números en el nombre
(`213023_56_Fase4_Daniel Santamaria.py`), lo que hace que Python no pueda
importarlo con `import`. `importlib.util.spec_from_file_location()` carga
cualquier archivo `.py` desde su ruta en disco, sin restricciones de nombre.

**¿Por qué `threading.local()` en el redirector de stdout?**
`sys.stdout` es una variable global. Si dos hilos la reasignan concurrentemente
existe una condición de carrera donde uno puede restaurar el stdout del otro
antes de tiempo. `threading.local()` da a cada hilo su propia copia de la
variable de destino, eliminando la condición de carrera sin necesidad de locks.

**¿Por qué el gestor de la simulación es una instancia local?**
`self.gestor` es el gestor del formulario manual y persiste toda la sesión.
Si la simulación usara el mismo gestor, una segunda pulsación del botón
encontraría clientes y servicios de la ejecución anterior, produciendo errores
de documento duplicado. La instancia local `gestor = GestorSistema()` dentro
de `_simular_diez_operaciones()` garantiza un estado limpio en cada simulación
sin afectar los datos del formulario.

**¿Por qué `daemon=True` en los hilos de trabajo?**
Un hilo no-daemon impide que el proceso Python termine mientras el hilo siga
vivo. Si el usuario cierra la ventana durante una simulación, un hilo
no-daemon mantendría el proceso en memoria indefinidamente. `daemon=True`
garantiza que el proceso termine limpiamente cuando la ventana se cierra.

---

*Desarrollado por Daniel Santamaría — UNAD, Fase 4*
