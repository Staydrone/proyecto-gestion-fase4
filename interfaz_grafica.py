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

import glob
import importlib.util
import os
import queue
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

        # Inicia el "sondeo" periódico de la cola. Esto es lo que
        # mantiene viva la actualización del área de texto sin bloquear
        # la ventana: se revisa la cola cada 100 ms en el hilo principal.
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
        self.area_consola.tag_config("exito", foreground="#1a7f37")
        self.area_consola.tag_config("error", foreground="#c0392b")
        self.area_consola.tag_config("info", foreground="#2c3e50")

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
        Las mismas 10 operaciones de tu main.py original, reutilizando
        gestor.registrar_cliente, gestor.crear_servicio, gestor.crear_reserva
        y gestor.cambiar_estado_reserva exactamente como ya estaban escritas.
        No se duplica lógica de negocio: solo se vuelve a invocar.

        CORRECCIÓN: se reinicia GestorSistema al inicio de cada ejecución.
        Sin esto, una segunda pulsación del botón ▶ encontraba clientes,
        servicios y reservas ya creados por la ejecución anterior, lo que
        provocaba errores de documento duplicado o comportamiento impredecible.
        Al crear un GestorSistema nuevo aquí, cada simulación arranca desde
        un estado limpio. Los clientes registrados manualmente desde el
        formulario (self.gestor) NO se ven afectados porque el formulario
        usa el atributo self.gestor, que solo se actualiza en __init__;
        la simulación trabaja con su propia instancia local.
        """
        gestor = GestorSistema()  # instancia local, aislada del formulario
        # Pre-cargar lista negra para demostrar Mejora 3 en la GUI
        gestor.bloquear_documento("7654321098")
        registrar_evento("===== INICIO DE LA SIMULACIÓN (desde GUI) =====")

        # ── MEJORA 1 y 2: Validación semántica via ValidadorNegocio ──────────
        sistema = __import__("sistema_negocio")
        ValidadorNegocio = sistema.ValidadorNegocio

        print("\n=== [MEJORA 1 y 2] Validación semántica de documentos ===")
        casos = [
            ("1020304050", "VÁLIDO — 10 dígitos, sin anomalías"),
            ("9988776655", "VÁLIDO — 10 dígitos, sin anomalías"),
            ("80123456",   "VÁLIDO — 8 dígitos, sin anomalías"),
            ("ABC123",     "letras — rechazado"),
            ("1234567",    "7 dígitos — rechazado"),
            ("11111111",   "repetidos — fraude"),
            ("12345678",   "ascendente — fraude"),
            ("012345678",  "empieza en 0 — rechazado"),
        ]
        for doc, desc in casos:
            valido, motivo = ValidadorNegocio.es_documento_valido(doc)
            icono = "✅" if valido else "❌"
            print(f"  {icono} {doc:<13} {desc}: {motivo if not valido else 'Aceptado'}")
        print("— Fin validación documentos —")

        print("\n=== [MEJORA 2] ValidadorNegocio.es_email_corporativo() ===")
        emails = [
            ("ana.gomez@unad.edu.co",       "institucional"),
            ("luis@empresa.com.co",          "corporativo"),
            ("usuario@gmail.com",            "personal — rechazado"),
            ("temp@mailinator.com",          "desechable — rechazado"),
        ]
        for em, desc in emails:
            valido, motivo = ValidadorNegocio.es_email_corporativo(em)
            icono = "✅" if valido else "❌"
            print(f"  {icono} {em:<35} {desc}")
        print("— Fin validación emails —")

        # ── MEJORA 3: Lista negra ─────────────────────────────────────────────
        print("\n=== [MEJORA 3] Lista negra — DocumentoBloqueadoError ===")
        gestor.registrar_cliente(
            nombre="Sospechoso", documento="7654321098",
            email="sospechoso@empresa.com.co"
        )
        print("— Fin lista negra —")

        # ── Operaciones originales del sistema ────────────────────────────────
        print("\n=== Operación 1: Registrar cliente válido ===")
        cliente_ana = gestor.registrar_cliente(
            nombre="ana gómez", documento="1020304050",
            email="ana.gomez@unad.edu.co", telefono="3001234567"
        )

        print("\n=== Operación 2: Cliente con documento inválido ===")
        gestor.registrar_cliente(nombre="Carlos Ruiz", documento="ABC123", email="carlos@empresa.com.co")

        print("\n=== Operación 3: Registrar segundo cliente válido ===")
        cliente_luis = gestor.registrar_cliente(
            nombre="luis fernández", documento="9988776655", email="luis.fernandez@empresa.com.co"
        )

        print("\n=== Operación 4: Cliente con email inválido ===")
        gestor.registrar_cliente(nombre="Marta Díaz", documento="1111222233", email="marta-arroba-correo.com")

        print("\n=== Operación 5: Registrar servicio de Hotel válido ===")
        hotel = gestor.crear_servicio(tipo="hotel", nombre="Hotel Costa Azul", precio_base=120.0, noches=3, estrellas=4)

        print("\n=== Operación 6: Transporte con precio negativo ===")
        gestor.crear_servicio(tipo="transporte", nombre="Van Ejecutiva", precio_base=-50.0, unidades=4, con_seguro=True)

        print("\n=== Operación 7: Registrar servicio de Experiencia válido ===")
        experiencia = gestor.crear_servicio(tipo="experiencia", nombre="Tour Ciudad Amurallada", precio_base=45.0, participantes=6)

        print("\n=== Operación 8: Crear reserva válida (Ana + Hotel) ===")
        reserva_ana = gestor.crear_reserva(cliente_ana, hotel)

        print("\n=== Operación 9: Reserva sobre servicio NO disponible ===")
        if experiencia is not None:
            experiencia.marcar_no_disponible()
        gestor.crear_reserva(cliente_luis, experiencia)

        print("\n=== Operación 10: Transiciones de estado de una reserva ===")
        if reserva_ana is not None:
            gestor.cambiar_estado_reserva(reserva_ana.id, "confirmar")
            gestor.cambiar_estado_reserva(reserva_ana.id, "confirmar")  # inválida a propósito
            gestor.cambiar_estado_reserva(reserva_ana.id, "finalizar")

        print("\n=== Resumen final de reservas ===")
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
                elif "❌" in mensaje or "⚠️" in mensaje:
                    etiqueta = "error"
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
