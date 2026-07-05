"""
================================================================================
 INTERFAZ GRÁFICA (Tkinter) PARA EL SISTEMA INTEGRAL DE GESTIÓN
 Punto 3.4 de la guía: Interfaz con Tkinter
================================================================================

Este archivo NO modifica la lógica de negocio. Importa todo lo que ya existe
en 'sistema_base.py' (Cliente, Servicio, GestorSistema, etc.) y construye
una ventana sobre ella. Esto es justamente lo que tu arquitectura en capas
permite: la GUI es una capa de presentación más, intercambiable, que no
necesita tocar entidades.py, gestor.py, etc.

Componentes pedidos:
    1. Un campo de entrada para los datos del cliente.
    2. Un área de texto que actúa como "consola" en la ventana (en vez
       de imprimir en la terminal).
    3. Un botón que dispara la simulación de las 10 operaciones y
       captura cualquier error SIN congelar la ventana.

Decisión técnica clave: la simulación corre en un hilo (threading.Thread)
separado del hilo principal de Tkinter. Si la simulación corriera en el
mismo hilo que dibuja la ventana, Tkinter se "congelaría" (no respondería
a clics ni se podría mover/cerrar) mientras la simulación se ejecuta.
Como Tkinter no es seguro para escribir desde otro hilo directamente,
la comunicación entre el hilo de trabajo y la ventana se hace con una
queue.Queue: el hilo de la simulación deja mensajes en la cola, y la
ventana los va leyendo periódicamente con `after()`.

Para ejecutar (requiere tener el archivo del sistema de gestión en la
misma carpeta que este script — ver la sección de carga dinámica abajo
para más detalle sobre por qué no se usa un "import" normal):
    python interfaz_grafica.py
"""

from __future__ import annotations

import datetime
import glob
import importlib.util
import json
import os
import queue
import random
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# -----------------------------------------------------------------------
# CARGA DINÁMICA DEL MÓDULO DE LÓGICA DE NEGOCIO
# -----------------------------------------------------------------------
# AUDITORÍA: el archivo original se llama
# "213023_56_Fase4_Daniel Santamaria.py" — un nombre con espacios y
# guiones bajos que Python NO puede importar con la sintaxis normal
# `from sistema_base import ...`, porque un nombre de módulo en Python
# debe ser un identificador válido (sin espacios). Por eso se usa
# `importlib`, que carga un archivo .py directamente desde su RUTA en
# disco, sin que su nombre necesite ser un identificador válido.
#
# Esto también hace que la GUI sea más robusta para la entrega: no
# depende de que tú renombres tu archivo de tarea, ni de adivinar el
# nombre exacto. Busca, en la misma carpeta que este script, el primer
# archivo que coincida con el patrón "*Fase4*Santamaria*.py" (ajusta el
# patrón si tu archivo tiene otro nombre) y lo carga como si fuera un
# módulo más.
CARPETA_ACTUAL = os.path.dirname(os.path.abspath(__file__))

# Patrones de búsqueda en orden de preferencia: primero el nombre exacto
# de la entrega, y si no se encuentra, una búsqueda más flexible.
_PATRONES_BUSQUEDA = [
    "213023_56_Fase4_Daniel_Santamaria.py",   # nombre real del archivo entregado
    "213023_56_Fase4_Daniel Santamaria.py",   # variante con espacio (por si acaso)
    "213023_56_Fase4*Santamaria*.py",
    "*Fase4*Santamaria*.py",
    "sistema_base.py",
]


def _localizar_archivo_sistema() -> str:
    """
    Busca, en la carpeta de este script, el archivo .py que contiene
    la lógica de negocio (GestorSistema, Cliente, Servicio, etc.).

    Se prueba cada patrón en orden hasta encontrar una coincidencia.
    Si ninguno coincide, se lanza FileNotFoundError con un mensaje claro
    indicando qué se buscó, en vez de dejar que falle más adelante con
    un error confuso de importación.
    """
    for patron in _PATRONES_BUSQUEDA:
        coincidencias = glob.glob(os.path.join(CARPETA_ACTUAL, patron))
        if coincidencias:
            return coincidencias[0]

    raise FileNotFoundError(
        "No se encontró el archivo del sistema de gestión en la carpeta "
        f"'{CARPETA_ACTUAL}'. Se buscaron estos patrones: {_PATRONES_BUSQUEDA}. "
        "Asegúrate de que el archivo .py con tu lógica de negocio "
        "(Cliente, Servicio, GestorSistema, etc.) esté en la misma "
        "carpeta que interfaz_grafica.py."
    )


def _cargar_modulo_sistema():
    """
    Carga el archivo localizado como un módulo de Python usando
    importlib, sin necesidad de que su nombre sea un identificador
    válido (puede tener espacios, números al inicio, etc.).
    """
    ruta_archivo = _localizar_archivo_sistema()
    especificacion = importlib.util.spec_from_file_location("sistema_negocio", ruta_archivo)
    modulo = importlib.util.module_from_spec(especificacion)
    # Se registra en sys.modules para que el módulo cargado se comporte
    # como cualquier otro import normal de aquí en adelante.
    sys.modules["sistema_negocio"] = modulo
    especificacion.loader.exec_module(modulo)
    print(f"✅ Lógica de negocio cargada desde: {ruta_archivo}")
    return modulo


try:
    _sistema = _cargar_modulo_sistema()
except FileNotFoundError as error:
    print(f"❌ {error}")
    sys.exit(1)

# A partir de aquí, el resto del archivo usa estos nombres exactamente
# igual que si hubieran sido importados con `from sistema_base import ...`.
GestorSistema = _sistema.GestorSistema
registrar_error = _sistema.registrar_error
registrar_evento = _sistema.registrar_evento
RUTA_LOG = _sistema.RUTA_LOG


# =============================================================================
# MEJORA 1 — Generación de documentos sintéticos realistas
# =============================================================================
# Rango oficial de cédulas colombianas expedidas a partir del año 2000.
# El generador descarta secuencias inválidas para ser compatible con
# ValidadorNegocio.es_documento_valido() del sistema de negocio.
_DOC_RANGO_MIN = 1_000_000_000
_DOC_RANGO_MAX = 1_150_000_000


def _generar_documento_sintetico() -> str:
    """
    Genera una cédula colombiana realista de 10 dígitos dentro del rango
    1.000.000.000 – 1.150.000.000, descartando automáticamente las
    secuencias que ValidadorNegocio consideraría fraude:
      - Todos los dígitos iguales (11111111).
      - Secuencia puramente ascendente (12345678).
      - Primer dígito 0 (imposible en el rango, pero se verifica igualmente).

    Se usa un bucle con reintentos; estadísticamente converge en < 5 intentos
    porque las secuencias inválidas son una fracción mínima del rango de 150M.
    """
    for _ in range(100):  # límite de seguridad
        doc = str(random.randint(_DOC_RANGO_MIN, _DOC_RANGO_MAX))
        if doc[0] == "0":
            continue
        if len(set(doc)) == 1:  # todos iguales
            continue
        if all(int(doc[i + 1]) - int(doc[i]) == 1 for i in range(len(doc) - 1)):
            continue  # ascendente perfecta
        return doc
    return str(random.randint(_DOC_RANGO_MIN, _DOC_RANGO_MAX))  # fallback


# =============================================================================
# MEJORA 2 — Formato de moneda colombiana (COP)
# =============================================================================

def _formatear_cop(valor: float) -> str:
    """
    Convierte un float a formato moneda colombiana:
      375.0   → '$375.000,00'
      1375.5  → '$1.375.500,00'

    Colombia usa punto (.) como separador de miles y coma (,) como
    separador decimal, al revés del estándar anglosajón.
    Se implementa manualmente para no depender de locales del SO, que
    varían entre Windows, macOS y Linux.
    """
    centavos = round(valor * 100)
    entero = centavos // 100
    decimal = centavos % 100
    # Separador de miles con punto
    entero_fmt = f"{entero:,}".replace(",", ".")
    return f"${entero_fmt},{decimal:02d}"


# =============================================================================
# MEJORA 4 — Persistencia: ruta del archivo de estado
# =============================================================================
_RUTA_ESTADO_JSON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "estado_sistema.json"
)


class RedirectorConsolaGlobal:
    """
    Reemplaza sys.stdout globalmente UNA sola vez (en __init__ de la ventana)
    y permanece instalado durante toda la vida de la aplicación.

    Usa threading.local() para que cada hilo tenga su propio destino:
      - Si el hilo llamó a activar(cola) → sus print() van a esa cola.
      - Si no llamó a activar() (o llamó a desactivar()) → sus print()
        van al stdout original (la terminal real), sin interferencia.

    CORRECCIÓN respecto a la versión anterior (RedirectorConsola):
    La versión anterior reasignaba sys.stdout (variable global) en cada
    operación: una en el hilo de la GUI y la misma en el hilo de la
    simulación. Si ambos corrían a la vez existía una condición de carrera
    donde un hilo podía restaurar el stdout del otro antes de tiempo.
    Con threading.local() cada hilo gestiona su propio puntero de destino
    sin tocar el de los demás; la variable global sys.stdout solo se
    modifica UNA vez al arrancar.
    """

    def __init__(self, stdout_original) -> None:
        self._stdout_original = stdout_original
        self._local = threading.local()

    def activar(self, cola: queue.Queue) -> None:
        """Registra `cola` como destino de print() para el hilo llamante."""
        self._local.cola = cola

    def desactivar(self) -> None:
        """El hilo llamante vuelve a escribir en el stdout original."""
        self._local.cola = None

    def write(self, mensaje: str) -> None:
        cola = getattr(self._local, "cola", None)
        if cola is not None:
            if mensaje.strip():
                cola.put(mensaje)
        else:
            self._stdout_original.write(mensaje)

    def flush(self) -> None:
        cola = getattr(self._local, "cola", None)
        if cola is None:
            self._stdout_original.flush()


class VentanaSistemaGestion:
    """
    Ventana principal de la aplicación.

    Estructura:
        - Sección superior: formulario para registrar un cliente manual.
        - Sección media: botón para disparar la simulación de 10 operaciones.
        - Sección inferior: área de texto (consola) donde se ven los
          resultados, en vez de la terminal.
    """

    def __init__(self, raiz: tk.Tk) -> None:
        self.raiz = raiz
        self.raiz.title("Sistema Integral de Gestión - Clientes, Servicios y Reservas")
        self.raiz.geometry("780x600")
        self.raiz.minsize(640, 480)

        # GestorSistema es el mismo objeto de siempre: la GUI no
        # reimplementa nada, solo lo invoca.
        self.gestor = GestorSistema()

        # Cola de comunicación entre el hilo de la simulación y la ventana.
        self.cola_mensajes: queue.Queue = queue.Queue()

        # CORRECCIÓN: instalar el redirector global UNA sola vez aquí,
        # en lugar de reasignar sys.stdout en cada operación. A partir de
        # este punto, cualquier print() en cualquier hilo pasará por
        # RedirectorConsolaGlobal, que enrutará según threading.local().
        self._stdout_original = sys.stdout
        self._redirector_global = RedirectorConsolaGlobal(self._stdout_original)
        sys.stdout = self._redirector_global

        self._construir_widgets()

        # MEJORA 4 — Persistencia: cargar estado guardado en sesión anterior.
        # Se ejecuta DESPUÉS de construir los widgets para poder mostrar
        # mensajes en la consola visual si la carga falla.
        self._cargar_estado()

        # MEJORA 4 — Persistencia: guardar estado al cerrar la ventana.
        # raiz.protocol intercepta el clic en la X del sistema operativo;
        # sin esto, destroy() ocurriría sin oportunidad de serializar.
        self.raiz.protocol("WM_DELETE_WINDOW", self._al_cerrar_ventana)

        # Inicia el sondeo periódico de la cola (actualización del área
        # de texto sin bloquear la ventana): cada 100 ms en hilo principal.
        self.raiz.after(100, self._procesar_cola_mensajes)

    # ------------------------------------------------------------------
    # CONSTRUCCIÓN DE LA INTERFAZ
    # ------------------------------------------------------------------
    def _construir_widgets(self) -> None:
        # --- Sección 1: formulario de cliente ---
        marco_formulario = ttk.LabelFrame(self.raiz, text="Registrar cliente manualmente")
        marco_formulario.pack(fill="x", padx=10, pady=(10, 5))

        ttk.Label(marco_formulario, text="Nombre:").grid(row=0, column=0, sticky="w", padx=5, pady=4)
        self.entrada_nombre = ttk.Entry(marco_formulario, width=30)
        self.entrada_nombre.grid(row=0, column=1, padx=5, pady=4)

        ttk.Label(marco_formulario, text="Documento:").grid(row=0, column=2, sticky="w", padx=5, pady=4)
        self.entrada_documento = ttk.Entry(marco_formulario, width=20)
        self.entrada_documento.grid(row=0, column=3, padx=5, pady=4)

        ttk.Label(marco_formulario, text="Email:").grid(row=1, column=0, sticky="w", padx=5, pady=4)
        self.entrada_email = ttk.Entry(marco_formulario, width=30)
        self.entrada_email.grid(row=1, column=1, padx=5, pady=4)

        ttk.Label(marco_formulario, text="Teléfono:").grid(row=1, column=2, sticky="w", padx=5, pady=4)
        self.entrada_telefono = ttk.Entry(marco_formulario, width=20)
        self.entrada_telefono.grid(row=1, column=3, padx=5, pady=4)

        self.boton_registrar_cliente = ttk.Button(
            marco_formulario, text="Registrar cliente", command=self._on_registrar_cliente
        )
        self.boton_registrar_cliente.grid(row=2, column=0, columnspan=4, pady=8)

        # --- Sección 2: botones de simulación ---
        marco_acciones = ttk.LabelFrame(self.raiz, text="Simulación del sistema")
        marco_acciones.pack(fill="x", padx=10, pady=5)

        self.boton_simular = ttk.Button(
            marco_acciones,
            text="▶ Ejecutar simulación de 10 operaciones",
            command=self._on_ejecutar_simulacion,
        )
        self.boton_simular.pack(side="left", padx=5, pady=8)

        self.boton_limpiar = ttk.Button(
            marco_acciones, text="Limpiar consola", command=self._limpiar_consola
        )
        self.boton_limpiar.pack(side="left", padx=5, pady=8)

        self.etiqueta_estado = ttk.Label(marco_acciones, text="Listo.", foreground="green")
        self.etiqueta_estado.pack(side="left", padx=15)

        # --- Sección 3: área de texto como "consola" ---
        marco_consola = ttk.LabelFrame(self.raiz, text="Consola de resultados")
        marco_consola.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.area_consola = scrolledtext.ScrolledText(
            marco_consola, wrap="word", font=("Consolas", 9), state="disabled"
        )
        self.area_consola.pack(fill="both", expand=True, padx=5, pady=5)

        # Etiquetas de color para distinguir visualmente éxito/error,
        # igual que los emojis ✅/❌ que ya usa tu lógica en consola.
        self.area_consola.tag_config("exito",      foreground="#1a7f37")
        self.area_consola.tag_config("error",      foreground="#c0392b")
        self.area_consola.tag_config("info",       foreground="#2c3e50")
        self.area_consola.tag_config("fraude",     foreground="#8e44ad")   # violeta
        self.area_consola.tag_config("advertencia",foreground="#d35400")   # naranja
        self.area_consola.tag_config("persistencia",foreground="#2980b9")  # azul

    # ------------------------------------------------------------------
    # ACCIÓN: registrar cliente desde el formulario
    # ------------------------------------------------------------------
    def _on_registrar_cliente(self) -> None:
        """
        Lee los campos del formulario y lanza el registro en un hilo
        de trabajo, igual que la simulación.

        CORRECCIÓN respecto a la versión anterior:
        Antes, la llamada a gestor.registrar_cliente() se ejecutaba
        directamente en el hilo principal de Tkinter (bloqueándolo
        mientras durara). Para operaciones rápidas no se nota, pero es
        un antipatrón: si en el futuro la operación tardara (validación
        remota, acceso a BD, etc.) la ventana se congelaría.
        Ahora se lanza en un Thread propio; el sentinel
        __CLIENTE_REGISTRADO__ le avisa al hilo principal cuando terminó.
        """
        nombre = self.entrada_nombre.get().strip()
        documento = self.entrada_documento.get().strip()
        email = self.entrada_email.get().strip()
        telefono = self.entrada_telefono.get().strip()

        campos_faltantes = []
        if not nombre:
            campos_faltantes.append("Nombre")
        if not documento:
            campos_faltantes.append("Documento")
        if not email:
            campos_faltantes.append("Email")

        if campos_faltantes:
            messagebox.showwarning(
                "Campos incompletos",
                "Por favor completa los siguientes campos antes de registrar "
                f"el cliente:\n\n• " + "\n• ".join(campos_faltantes),
            )
            return

        # Deshabilitar ambos botones mientras corre el hilo de registro,
        # evitando que el usuario lance la simulación al mismo tiempo.
        self.boton_registrar_cliente.config(state="disabled")
        self.boton_simular.config(state="disabled")
        self.etiqueta_estado.config(text="Registrando cliente...", foreground="orange")

        hilo = threading.Thread(
            target=self._ejecutar_registro_cliente_en_hilo,
            args=(nombre, documento, email, telefono),
            daemon=True,
        )
        hilo.start()

    def _ejecutar_registro_cliente_en_hilo(
        self, nombre: str, documento: str, email: str, telefono: str
    ) -> None:
        """
        Cuerpo del hilo de registro. Activa el redirector para este hilo,
        llama al gestor y deposita el sentinel __CLIENTE_REGISTRADO__ en
        la cola cuando termina (con éxito o con error).
        """
        self._redirector_global.activar(self.cola_mensajes)
        cliente = None
        try:
            cliente = self._registrar_cliente_con_encabezado(nombre, documento, email, telefono)
        except Exception as error:
            print(f"❌ Error inesperado en la interfaz: {error}")
            registrar_error(f"interfaz_grafica -> error inesperado en registro: {error}")
        finally:
            self._redirector_global.desactivar()
            # El booleano indica si hay que limpiar el formulario.
            self.cola_mensajes.put(("__CLIENTE_REGISTRADO__", cliente is not None))

    def _registrar_cliente_con_encabezado(self, nombre: str, documento: str, email: str, telefono: str):
        """Pequeño envoltorio que imprime el encabezado y delega en el
        gestor, todo dentro del mismo flujo de salida redirigida."""
        print("\n--- Registrando cliente desde el formulario ---")
        return self.gestor.registrar_cliente(
            nombre=nombre, documento=documento, email=email, telefono=telefono
        )

    # ------------------------------------------------------------------
    # ACCIÓN: ejecutar la simulación de 10 operaciones (en hilo separado)
    # ------------------------------------------------------------------
    def _on_ejecutar_simulacion(self) -> None:
        """
        Lanza la simulación en un hilo de trabajo (threading.Thread) para
        que la ventana NO se congele mientras corren las 10 operaciones.

        Se deshabilita el botón mientras corre, para evitar que el usuario
        dispare la simulación dos veces en paralelo (una doble ejecución
        no rompería el programa, pero sí mezclaría los mensajes en la
        consola de forma confusa).
        """
        self.boton_simular.config(state="disabled")
        self.boton_registrar_cliente.config(state="disabled")
        self.etiqueta_estado.config(text="Ejecutando simulación...", foreground="orange")
        self._escribir_consola("\n========== INICIANDO SIMULACIÓN ==========", "info")

        hilo_trabajo = threading.Thread(target=self._ejecutar_simulacion_en_hilo, daemon=True)
        hilo_trabajo.start()

    def _ejecutar_simulacion_en_hilo(self) -> None:
        """
        Cuerpo de la simulación, ejecutado en el hilo de trabajo.

        CORRECCIÓN respecto a la versión anterior:
        Ya no reasigna sys.stdout globalmente. En su lugar activa el
        redirector para este hilo con self._redirector_global.activar(),
        lo cual es thread-safe porque usa threading.local() internamente.
        """
        self._redirector_global.activar(self.cola_mensajes)
        try:
            self._simular_diez_operaciones()
        except Exception as error:
            print(f"❌ Error crítico no controlado durante la simulación: {error}")
            registrar_error(f"interfaz_grafica -> error crítico en simulación: {error}")
        finally:
            self._redirector_global.desactivar()
            self.cola_mensajes.put("__SIMULACION_FINALIZADA__")

    def _simular_diez_operaciones(self) -> None:
        """
        Simulación completa del sistema con todas las mejoras integradas:

          · Mejora 1 — Documentos generados con _generar_documento_sintetico()
          · Mejora 2 — Precios formateados en COP con _formatear_cop()
          · Mejora 3 — Lista negra con DocumentoBloqueadoError
          · Mejora 4 — Logs diferenciados (registrar_fraude vs registrar_error)
          · Mejora 5 — FSM: transiciones válidas e inválidas demostradas

        Instancia LOCAL de GestorSistema → cada ejecución arranca limpia sin
        afectar los clientes del formulario (self.gestor).
        """
        gestor = GestorSistema()
        registrar_evento("===== INICIO DE LA SIMULACIÓN (desde GUI) =====")

        # ── BLOQUE A: Datos sintéticos (Mejora 1) ────────────────────────────
        print("\n═══ [MEJORA 1] Generación de documentos sintéticos ═══")
        docs_sinteticos = [_generar_documento_sintetico() for _ in range(3)]
        for i, doc in enumerate(docs_sinteticos, 1):
            print(f"  Doc sintético #{i}: {doc}  (rango {_DOC_RANGO_MIN:,}–{_DOC_RANGO_MAX:,})")
        print("— Documentos generados; se usarán en los clientes de prueba —")

        # ── BLOQUE B: Validación semántica (Mejora 2 — ValidadorNegocio) ─────
        sistema_mod = __import__("sistema_negocio")
        ValidadorNegocio = sistema_mod.ValidadorNegocio

        print("\n═══ [MEJORA 2] ValidadorNegocio — documentos ═══")
        casos_doc = [
            (docs_sinteticos[0], "sintético válido"),
            ("ABC123",           "letras → rechazado"),
            ("1234567",          "7 dígitos → rechazado"),
            ("11111111",         "dígitos repetidos → fraude"),
            ("12345678",         "secuencia ascendente → fraude"),
            ("012345678",        "empieza en 0 → rechazado"),
        ]
        for doc, desc in casos_doc:
            valido, motivo = ValidadorNegocio.es_documento_valido(doc)
            icono = "✅" if valido else "❌"
            print(f"  {icono} {doc:<14} {desc}: {motivo if not valido else 'Aceptado'}")

        print("\n═══ [MEJORA 2] ValidadorNegocio — emails corporativos ═══")
        casos_email = [
            ("ana.gomez@unad.edu.co",   "institucional ✓"),
            ("luis@empresa.com.co",      "corporativo ✓"),
            ("usuario@gmail.com",        "personal → rechazado"),
            ("temp@mailinator.com",      "desechable → rechazado"),
        ]
        for em, desc in casos_email:
            valido, _ = ValidadorNegocio.es_email_corporativo(em)
            icono = "✅" if valido else "❌"
            print(f"  {icono} {em:<35} {desc}")

        # ── BLOQUE C: Lista negra (Mejora 3) ─────────────────────────────────
        print("\n═══ [MEJORA 3] Lista negra — DocumentoBloqueadoError ═══")
        DOC_BLOQUEADO = "7654321098"
        gestor.bloquear_documento(DOC_BLOQUEADO)
        gestor.registrar_cliente(
            nombre="Sospechoso Prueba",
            documento=DOC_BLOQUEADO,
            email="sospechoso@empresa.com.co",
        )
        print("— Intento con documento bloqueado registrado en log como FRAUDE —")

        # ── BLOQUE D: Operaciones principales ────────────────────────────────
        print("\n═══ Operación 1: Registrar cliente válido (doc sintético) ═══")
        cliente_ana = gestor.registrar_cliente(
            nombre="Ana Gómez",
            documento=docs_sinteticos[0],
            email="ana.gomez@unad.edu.co",
            telefono="3001234567",
        )

        print("\n═══ Operación 2: Cliente con documento inválido ═══")
        gestor.registrar_cliente(
            nombre="Carlos Ruiz",
            documento="ABC123",
            email="carlos@empresa.com.co",
        )

        print("\n═══ Operación 3: Segundo cliente válido (doc sintético) ═══")
        cliente_luis = gestor.registrar_cliente(
            nombre="Luis Fernández",
            documento=docs_sinteticos[1],
            email="luis.fernandez@empresa.com.co",
        )

        print("\n═══ Operación 4: Cliente con email inválido ═══")
        gestor.registrar_cliente(
            nombre="Marta Díaz",
            documento=docs_sinteticos[2],
            email="marta-arroba-correo.com",
        )

        # ── BLOQUE E: Servicios con formato COP (Mejora 2) ───────────────────
        print("\n═══ Operación 5: Servicio Hotel — precio en COP ═══")
        hotel = gestor.crear_servicio(
            tipo="hotel", nombre="Hotel Costa Azul",
            precio_base=120000.0, noches=3, estrellas=4,
        )
        if hotel is not None:
            print(f"  💰 Precio formateado: {_formatear_cop(hotel.calcular_precio_total())}")

        print("\n═══ Operación 6: Transporte con precio negativo ═══")
        gestor.crear_servicio(
            tipo="transporte", nombre="Van Ejecutiva",
            precio_base=-50000.0, unidades=4, con_seguro=True,
        )

        print("\n═══ Operación 7: Servicio Experiencia — precio en COP ═══")
        experiencia = gestor.crear_servicio(
            tipo="experiencia", nombre="Tour Ciudad Amurallada",
            precio_base=45000.0, participantes=6,
        )
        if experiencia is not None:
            print(f"  💰 Precio formateado: {_formatear_cop(experiencia.calcular_precio_total())}")

        # ── BLOQUE F: Reservas ────────────────────────────────────────────────
        print("\n═══ Operación 8: Reserva válida (Ana + Hotel) ═══")
        reserva_ana = gestor.crear_reserva(cliente_ana, hotel)
        if reserva_ana is not None:
            print(f"  💰 Total reserva: {_formatear_cop(reserva_ana.total)}")

        print("\n═══ Operación 9: Reserva sobre servicio NO disponible ═══")
        if experiencia is not None:
            experiencia.marcar_no_disponible()
        gestor.crear_reserva(cliente_luis, experiencia)

        # ── BLOQUE G: FSM — Máquina de estados (Mejora 5) ────────────────────
        print("\n═══ Operación 10: FSM — Transiciones de estado de una reserva ═══")
        print("  Transiciones válidas del sistema:")
        print("  PENDIENTE → CONFIRMADA → FINALIZADA")
        print("  PENDIENTE → CANCELADA  (también válida)")
        print("  Cualquier otra combinación es bloqueada y registrada en log.\n")
        if reserva_ana is not None:
            gestor.cambiar_estado_reserva(reserva_ana.id, "confirmar")   # ✅
            gestor.cambiar_estado_reserva(reserva_ana.id, "confirmar")   # ❌ misma → log
            gestor.cambiar_estado_reserva(reserva_ana.id, "finalizar")   # ✅

        # ── BLOQUE H: Resumen final ───────────────────────────────────────────
        print("\n═══ Resumen final de reservas ═══")
        gestor.listar_reservas()

        registrar_evento("===== FIN DE LA SIMULACIÓN (desde GUI) =====")
        print(f"\n📄 Log completo en: {RUTA_LOG}")

    # ------------------------------------------------------------------
    # PUENTE ENTRE HILOS: lectura periódica de la cola de mensajes
    # ------------------------------------------------------------------
    def _procesar_cola_mensajes(self) -> None:
        """
        Se ejecuta cada 100 ms en el hilo principal de Tkinter (es seguro
        tocar widgets aquí). Vacía la cola de mensajes que el hilo de
        trabajo fue depositando y los escribe en el área de texto.

        CORRECCIÓN: ahora maneja dos tipos de sentinels:
          - "__SIMULACION_FINALIZADA__" (str): reactiva botones al terminar
            la simulación de 10 operaciones.
          - ("__CLIENTE_REGISTRADO__", bool) (tupla): reactiva botones al
            terminar el registro desde el formulario; si el bool es True,
            también limpia los campos del formulario.
        """
        try:
            while True:
                mensaje = self.cola_mensajes.get_nowait()

                # Sentinel de fin de simulación
                if mensaje == "__SIMULACION_FINALIZADA__":
                    self.boton_simular.config(state="normal")
                    self.boton_registrar_cliente.config(state="normal")
                    self.etiqueta_estado.config(text="Simulación finalizada.", foreground="green")
                    continue

                # Sentinel de fin de registro desde el formulario
                if isinstance(mensaje, tuple) and mensaje[0] == "__CLIENTE_REGISTRADO__":
                    self.boton_simular.config(state="normal")
                    self.boton_registrar_cliente.config(state="normal")
                    self.etiqueta_estado.config(text="Listo.", foreground="green")
                    if mensaje[1]:  # True → el registro fue exitoso
                        self._limpiar_formulario()
                    continue

                etiqueta = "info"
                if "✅" in mensaje:
                    etiqueta = "exito"
                elif "🚨" in mensaje or "FRAUDE" in mensaje or "BLOQUEADO" in mensaje:
                    etiqueta = "fraude"
                elif "❌" in mensaje:
                    etiqueta = "error"
                elif "⚠️" in mensaje:
                    etiqueta = "advertencia"
                elif "💾" in mensaje or "📂" in mensaje:
                    etiqueta = "persistencia"
                self._escribir_consola(mensaje, etiqueta)
        except queue.Empty:
            pass
        finally:
            self.raiz.after(100, self._procesar_cola_mensajes)

    # ------------------------------------------------------------------
    # UTILIDADES DE LA CONSOLA VISUAL
    # ------------------------------------------------------------------
    def _escribir_consola(self, mensaje: str, etiqueta: str = "info") -> None:
        self.area_consola.config(state="normal")
        self.area_consola.insert(tk.END, mensaje + "\n", etiqueta)
        self.area_consola.see(tk.END)  # auto-scroll al final
        self.area_consola.config(state="disabled")

    def _limpiar_consola(self) -> None:
        self.area_consola.config(state="normal")
        self.area_consola.delete("1.0", tk.END)
        self.area_consola.config(state="disabled")

    def _limpiar_formulario(self) -> None:
        """Borra los campos del formulario tras un registro exitoso."""
        self.entrada_nombre.delete(0, tk.END)
        self.entrada_documento.delete(0, tk.END)
        self.entrada_email.delete(0, tk.END)
        self.entrada_telefono.delete(0, tk.END)

    # ------------------------------------------------------------------
    # MEJORA 4 — Persistencia de datos (serialización / deserialización)
    # ------------------------------------------------------------------
    def _guardar_estado(self) -> None:
        """
        Serializa el estado actual del gestor (clientes registrados
        manualmente desde el formulario) en un archivo JSON.

        Se serializa solo `self.gestor` (el gestor del formulario manual),
        NO el de la simulación, que es una instancia local efímera.

        Estructura del JSON guardado:
        {
          "timestamp": "2025-07-03T14:22:00",
          "clientes": [
            {"nombre": "...", "documento": "...", "email": "...", "telefono": "..."}
          ]
        }

        Decisión técnica: se usa JSON (no pickle) porque es legible por
        humanos, portable entre versiones de Python, y no ejecuta código
        arbitrario al deserializar (pickle sí lo hace, lo que es un riesgo
        de seguridad si el archivo es manipulado).
        """
        try:
            clientes_datos = [
                {
                    "nombre":    c.nombre,
                    "documento": c.documento,
                    "email":     c.email,
                    "telefono":  getattr(c, "telefono", ""),
                }
                for c in self.gestor.clientes.values()
            ]
            estado = {
                "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                "version":   "1.0",
                "clientes":  clientes_datos,
            }
            with open(_RUTA_ESTADO_JSON, "w", encoding="utf-8") as archivo:
                json.dump(estado, archivo, ensure_ascii=False, indent=2)

            n = len(clientes_datos)
            registrar_evento(
                f"Estado guardado: {n} cliente(s) → {_RUTA_ESTADO_JSON}"
            )
            self._escribir_consola(
                f"💾 Estado guardado: {n} cliente(s) en estado_sistema.json",
                "persistencia",
            )
        except Exception as error:
            registrar_error(f"Error al guardar estado: {error}")
            self._escribir_consola(f"⚠️ No se pudo guardar el estado: {error}", "advertencia")

    def _cargar_estado(self) -> None:
        """
        Carga el estado previamente guardado en JSON y re-registra los
        clientes en el gestor del formulario manual.

        Si el archivo no existe (primera ejecución) o está corrupto, se
        inicia con un gestor vacío sin interrumpir el arranque. Los errores
        de validación en clientes previamente guardados (ej.: si se cambió
        el validador de documentos) se reportan como advertencias, no como
        fallos críticos.
        """
        if not os.path.exists(_RUTA_ESTADO_JSON):
            return  # primera ejecución — normal, sin advertencias

        try:
            with open(_RUTA_ESTADO_JSON, "r", encoding="utf-8") as archivo:
                estado = json.load(archivo)

            clientes_raw = estado.get("clientes", [])
            timestamp    = estado.get("timestamp", "desconocido")
            restaurados  = 0
            fallidos     = 0

            for datos in clientes_raw:
                try:
                    self.gestor.registrar_cliente(
                        nombre    = datos.get("nombre", ""),
                        documento = datos.get("documento", ""),
                        email     = datos.get("email", ""),
                        telefono  = datos.get("telefono", ""),
                    )
                    restaurados += 1
                except Exception as error_cliente:
                    registrar_error(
                        f"Error restaurando cliente '{datos.get('nombre')}': {error_cliente}"
                    )
                    fallidos += 1

            msg = (
                f"📂 Estado restaurado ({timestamp}): "
                f"{restaurados} cliente(s) cargados"
                + (f", {fallidos} omitido(s) por validación" if fallidos else "")
            )
            registrar_evento(msg)
            self._escribir_consola(msg, "persistencia")

        except (json.JSONDecodeError, KeyError, TypeError) as error:
            registrar_error(f"Archivo de estado corrupto, se inicia en limpio: {error}")
            self._escribir_consola(
                "⚠️ Archivo de estado corrupto — se inicia con gestor vacío.",
                "advertencia",
            )

    def _al_cerrar_ventana(self) -> None:
        """
        Intercepta el cierre de la ventana (clic en la X del SO).
        Guarda el estado antes de destruir la ventana para garantizar
        que ninguna sesión se pierda.
        """
        self._guardar_estado()
        self.raiz.destroy()

    # ------------------------------------------------------------------
    # MEJORA 1+2: Simulación actualizada con datos sintéticos y formato COP
    # ------------------------------------------------------------------
    def _mostrar_seccion(self, titulo: str) -> None:
        """Imprime un encabezado de sección formateado."""
        print(f"\n{'=' * 55}")
        print(f"  {titulo}")
        print(f"{'=' * 55}")


def main() -> None:
    """
    Punto de entrada de la aplicación gráfica.

    AUDITORÍA: igual que en el sistema_base.py de consola, el arranque
    de la ventana se protege con try/except. Si Tkinter no logra
    inicializar la ventana (por ejemplo, en un entorno sin entorno
    gráfico disponible), se informa con un mensaje claro en vez de un
    traceback crudo.
    """
    try:
        raiz = tk.Tk()
        VentanaSistemaGestion(raiz)
        raiz.mainloop()
    except tk.TclError as error:
        print(f"❌ No fue posible iniciar la interfaz gráfica: {error}")
        print("   Verifica que tu entorno tenga soporte para entorno gráfico (display).")
    except Exception as error:
        print(f"❌ Error crítico no controlado al iniciar la aplicación: {error}")


if __name__ == "__main__":
    main()
