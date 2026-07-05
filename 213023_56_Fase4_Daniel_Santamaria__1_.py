"""
================================================================================
 SISTEMA INTEGRAL DE GESTIÓN DE CLIENTES, SERVICIOS Y RESERVAS
 VERSIÓN UNIFICADA (un solo archivo .py)
================================================================================

Este archivo agrupa, en un único módulo, lo que originalmente estaba
dividido en:

    1. excepciones.py      -> Excepciones personalizadas del dominio
    2. logger_sistema.py    -> Registro de eventos/errores en archivo .log
    3. entidades.py         -> EntidadBase, Cliente, Servicio y subclases
    4. reserva.py           -> Clase Reserva y su máquina de estados
    5. gestor.py            -> GestorSistema (lógica de negocio central)
    6. main.py              -> Script de simulación (10 operaciones)

¿Por qué seguía dividido en módulos antes?
    Separar en archivos es la práctica recomendada en proyectos reales: cada
    módulo se puede testear, mantener y reutilizar por separado, y un cambio
    en 'entidades.py' no obliga a tocar 'gestor.py'. Esa es la razón de la
    versión multi-archivo que construimos primero.

¿Por qué unirlo aquí?
    Para comodidad de entrega/ejecución: un solo archivo es más fácil de
    compartir, subir a una plataforma de tareas, o ejecutar con un solo
    comando, sin preocuparse por rutas de import relativas. La organización
    interna (con las secciones marcadas abajo) conserva exactamente la misma
    separación lógica, solo que ahora vive en un único namespace de Python.

Para ejecutar:
    python sistema_gestion_unico.py

Integrantes:
    Daniel Alejandro Santamaría Torres
    Omar Camilo Santiago
    Paola Rocío Salazar Meneses
"""

from __future__ import annotations

import os
import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
import logging


# =============================================================================
# SECCIÓN 1: EXCEPCIONES PERSONALIZADAS
# (equivalente al antiguo excepciones.py)
# =============================================================================

class ErrorSistemaGestion(Exception):
    """
    Excepción base de la que heredan todas las excepciones del sistema.
    Permite capturar 'cualquier error del sistema' con un solo except
    si así se desea, sin perder la posibilidad de capturar errores
    específicos cuando se necesite mayor granularidad.
    """
    pass


class ClienteInvalidoError(ErrorSistemaGestion):
    """Se lanza cuando los datos de un Cliente no cumplen las reglas
    de negocio (ej. cédula vacía, email con formato incorrecto, etc.)."""
    pass


class ClienteNoEncontradoError(ErrorSistemaGestion):
    """Se lanza cuando se busca un cliente por su identificador
    y este no existe en el sistema."""
    pass


class DocumentoBloqueadoError(ErrorSistemaGestion):
    """Se lanza cuando se intenta registrar un cliente cuyo documento
    está en la lista negra del sistema (Mejora 3 — fraude conocido)."""
    pass


class ServicioInvalidoError(ErrorSistemaGestion):
    """Se lanza cuando los datos de un Servicio no son válidos
    (ej. precio negativo, duración 0, etc.)."""
    pass


class ServicioNoDisponibleError(ErrorSistemaGestion):
    """Se lanza cuando se intenta reservar un servicio que está
    marcado como no disponible o sin cupos."""
    pass


class ReservaInvalidaError(ErrorSistemaGestion):
    """Se lanza cuando una operación de Reserva viola alguna regla
    de negocio (ej. cancelar una reserva ya finalizada)."""
    pass


class EstadoReservaError(ErrorSistemaGestion):
    """Se lanza cuando se intenta hacer una transición de estado
    no permitida en una Reserva (ej. de 'CANCELADA' a 'CONFIRMADA')."""
    pass


# =============================================================================
# SECCIÓN 2: SISTEMA DE LOGGING (registro de eventos y errores en .log)
# (equivalente al antiguo logger_sistema.py)
# =============================================================================

# Ruta del archivo de log. Se ubica junto a este script.
RUTA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sistema_gestion.log")

def configurar_logger() -> logging.Logger:
    """
    Configura y retorna el logger principal del sistema.

    Usamos un logger con nombre propio ('sistema_gestion') en vez del
    logger raíz, para no interferir con otros loggers si este módulo
    se integra a un proyecto más grande.

    AUDITORÍA (punto crítico #6): `logging.FileHandler` puede lanzar
    OSError/PermissionError si el proceso no tiene permisos de escritura
    en el directorio, si el disco está lleno, o si la ruta no es válida
    en el entorno de despliegue. Como esta función se ejecuta a nivel de
    módulo (al hacer `import logger_sistema`), un fallo aquí tumbaría
    TODO el sistema antes de que cualquier try/except de gestor.py o
    main.py pudiera intervenir. Por eso el FileHandler se envuelve en su
    propio try/except: si falla, el sistema sigue funcionando registrando
    en consola (StreamHandler) en vez de morir en el arranque. El logging
    es una herramienta de soporte y nunca debe ser un punto único de fallo
    para la lógica de negocio.

    Returns:
        logging.Logger: instancia configurada lista para usar (con archivo
        si fue posible, o con salida a consola como respaldo).
    """
    logger = logging.getLogger("sistema_gestion")
    logger.setLevel(logging.DEBUG)

    formato = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Evita agregar handlers duplicados si la función se llama varias veces
    # (por ejemplo, si el módulo se importa más de una vez en distintos puntos).
    if not logger.handlers:
        try:
            manejador_archivo = logging.FileHandler(RUTA_LOG, encoding="utf-8")
            manejador_archivo.setLevel(logging.DEBUG)
            manejador_archivo.setFormatter(formato)
            logger.addHandler(manejador_archivo)
        except OSError as error:
            # Fallback: no hay archivo, pero el sistema sigue operando.
            # Se notifica una sola vez por consola para que quede claro
            # por qué no se está generando el .log esperado.
            manejador_consola = logging.StreamHandler()
            manejador_consola.setLevel(logging.DEBUG)
            manejador_consola.setFormatter(formato)
            logger.addHandler(manejador_consola)
            print(
                f"⚠️  No se pudo crear el archivo de log en '{RUTA_LOG}' "
                f"({error}). Los eventos se mostrarán solo en consola."
            )

    return logger


# Instancia única (patrón singleton informal) que se importa
# desde el resto de los módulos del sistema.
logger_sistema = configurar_logger()


def registrar_evento(mensaje: str) -> None:
    """
    Registra un evento exitoso (nivel INFO) en el log.

    AUDITORÍA: se envuelve en try/except porque una operación de negocio
    (registrar un cliente, crear una reserva, etc.) ya se completó con
    éxito cuando se llama a esta función; un fallo al *escribir el log*
    (ej. error de encoding, disco lleno a mitad de ejecución) no debe
    propagarse y deshacer una operación que técnicamente sí fue exitosa.
    """
    try:
        logger_sistema.info(mensaje)
    except Exception as error:
        print(f"⚠️  No se pudo registrar el evento en el log: {error}")


def registrar_error(mensaje: str) -> None:
    """
    Registra un error o excepción (nivel ERROR) en el log.

    Mismo criterio que `registrar_evento`: el logging es una operación
    de soporte y nunca debe generar una excepción no controlada que
    interrumpa el flujo principal del programa.
    """
    try:
        logger_sistema.error(mensaje)
    except Exception as error:
        print(f"⚠️  No se pudo registrar el error en el log: {error}")


def registrar_advertencia(mensaje: str) -> None:
    """Registra una advertencia (nivel WARNING), para casos que no
    son un error grave pero merecen atención (ej. intento de operación
    sobre un recurso en estado inusual)."""
    try:
        logger_sistema.warning(mensaje)
    except Exception as error:
        print(f"⚠️  No se pudo registrar la advertencia en el log: {error}")


# =============================================================================
# SECCIÓN 3: ENTIDADES (EntidadBase, Cliente, Servicio y subclases)
# (equivalente al antiguo entidades.py)
# =============================================================================

class EntidadBase(ABC):
    """
    Clase abstracta de la que heredan todas las entidades del sistema.

    Provee:
        - Un identificador único (UUID) generado automáticamente.
        - La fecha/hora de creación de la entidad.
        - El método abstracto `resumen()`, que cada subclase concreta
          debe implementar para describirse a sí misma (polimorfismo).

    No puede instanciarse directamente: ABC + @abstractmethod lo impiden.
    """

    def __init__(self) -> None:
        self.__id: str = str(uuid.uuid4())[:8]  # id corto, legible en logs
        self.__fecha_creacion: datetime = datetime.now()

    @property
    def id(self) -> str:
        """Identificador único de la entidad (solo lectura)."""
        return self.__id

    @property
    def fecha_creacion(self) -> datetime:
        """Fecha y hora en que la entidad fue creada (solo lectura)."""
        return self.__fecha_creacion

    @abstractmethod
    def resumen(self) -> str:
        """
        Debe retornar una descripción breve y legible de la entidad.
        Cada subclase concreta define su propia versión (polimorfismo).
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# CLIENTE
# ---------------------------------------------------------------------------
class Cliente(EntidadBase):
    """
    Representa a un cliente del sistema.

    Encapsulamiento:
        Todos los atributos son privados (prefijo `__`) y se accede a ellos
        únicamente mediante propiedades (`@property`), que además validan
        los datos antes de asignarlos. Esto evita que el resto del programa
        deje al objeto en un estado inconsistente (ej. email inválido).
    """

    _PATRON_EMAIL = re.compile(r"^[\w.\-]+@([\w\-]+\.)+[a-zA-Z]{2,}$")

    def __init__(self, nombre: str, documento: str, email: str, telefono: str = "") -> None:
        super().__init__()
        # Se delega la validación a los setters (propiedades) para no
        # duplicar lógica de validación en el constructor.
        self.nombre = nombre
        self.documento = documento
        self.email = email
        self.telefono = telefono
        self.__activo: bool = True  # un cliente puede ser desactivado lógicamente

    # --- nombre ---
    @property
    def nombre(self) -> str:
        return self.__nombre

    @nombre.setter
    def nombre(self, valor: str) -> None:
        if not isinstance(valor, str) or not valor.strip():
            raise ClienteInvalidoError("El nombre del cliente no puede estar vacío.")
        self.__nombre = valor.strip().title()

    # --- documento ---
    @property
    def documento(self) -> str:
        return self.__documento

    @documento.setter
    def documento(self, valor: str) -> None:
        if not isinstance(valor, str) or not valor.strip().isdigit():
            raise ClienteInvalidoError(
                f"Documento inválido: '{valor}'. Debe contener solo dígitos."
            )
        self.__documento = valor.strip()

    # --- email ---
    @property
    def email(self) -> str:
        return self.__email

    @email.setter
    def email(self, valor: str) -> None:
        if not isinstance(valor, str) or not self._PATRON_EMAIL.match(valor.strip()):
            raise ClienteInvalidoError(f"Email con formato inválido: '{valor}'.")
        self.__email = valor.strip().lower()

    # --- telefono (opcional, sin validación estricta) ---
    @property
    def telefono(self) -> str:
        return self.__telefono

    @telefono.setter
    def telefono(self, valor: str) -> None:
        self.__telefono = valor.strip() if isinstance(valor, str) else ""

    # --- activo (solo lectura desde fuera; se modifica con métodos) ---
    @property
    def activo(self) -> bool:
        return self.__activo

    def desactivar(self) -> None:
        """Desactiva lógicamente al cliente (no se elimina del sistema)."""
        self.__activo = False

    def activar(self) -> None:
        """Reactiva a un cliente previamente desactivado."""
        self.__activo = True

    def resumen(self) -> str:
        """Implementación concreta del método abstracto de EntidadBase."""
        estado = "Activo" if self.__activo else "Inactivo"
        return f"Cliente[{self.id}] {self.__nombre} (Doc: {self.__documento}) - {estado}"

    def __str__(self) -> str:
        return self.resumen()


# ---------------------------------------------------------------------------
# VALIDADOR DE NEGOCIO (MEJORA 2)
# ---------------------------------------------------------------------------
class ValidadorNegocio:
    """
    Validaciones de negocio adicionales, más estrictas que las validaciones
    de formato básicas que ya hace Cliente en sus setters (@email.setter,
    @documento.setter).

    Mientras Cliente solo verifica que el documento tenga dígitos y que el
    email tenga forma de email, ValidadorNegocio verifica reglas de negocio
    reales: longitud exacta de cédula colombiana, secuencias sospechosas de
    fraude, y si el dominio del correo es corporativo/institucional en vez
    de personal o desechable.

    Se implementa como métodos estáticos porque no depende de estado de
    ninguna instancia: son funciones puras de validación reutilizables
    tanto por GestorSistema como por código externo (ej. interfaz_grafica.py).
    """

    LONGITUD_DOCUMENTO = 10

    # Dominios que se consideran corporativos/institucionales válidos.
    SUFIJOS_CORPORATIVOS = (".com.co", ".edu.co")

    # Dominios de correo desechable/temporal, rechazados explícitamente.
    DOMINIOS_DESECHABLES = (
        "mailinator.com",
        "tempmail.com",
        "10minutemail.com",
        "guerrillamail.com",
        "yopmail.com",
    )

    @staticmethod
    def es_documento_valido(documento: str) -> tuple[bool, str]:
        """
        Verifica que el documento sea una cédula colombiana plausible:
        solo dígitos, longitud exacta de 10, y sin patrones típicos de
        fraude (todos los dígitos iguales o secuencia ascendente perfecta).

        Retorna (True, "Documento válido.") o (False, motivo_del_rechazo).
        """
        if not isinstance(documento, str) or not documento.isdigit():
            return False, "El documento debe contener solo dígitos."

        if len(documento) != ValidadorNegocio.LONGITUD_DOCUMENTO:
            return False, (
                f"El documento debe tener {ValidadorNegocio.LONGITUD_DOCUMENTO} "
                f"dígitos (recibido: {len(documento)})."
            )

        if documento[0] == "0":
            return False, "El documento no puede empezar en cero."

        if len(set(documento)) == 1:
            return False, "Documento sospechoso: todos los dígitos son iguales (posible fraude)."

        es_ascendente = all(
            int(documento[i + 1]) - int(documento[i]) == 1
            for i in range(len(documento) - 1)
        )
        if es_ascendente:
            return False, "Documento sospechoso: secuencia ascendente perfecta (posible fraude)."

        return True, "Documento válido."

    @staticmethod
    def es_email_corporativo(email: str) -> tuple[bool, str]:
        """
        Verifica que el dominio del email sea corporativo (.com.co) o
        institucional (.edu.co), rechazando dominios personales genéricos
        (gmail.com, hotmail.com, etc.) y dominios de correo desechable.

        Retorna (True, motivo_aceptación) o (False, motivo_del_rechazo).
        """
        if not isinstance(email, str) or "@" not in email:
            return False, "Email con formato inválido."

        dominio = email.strip().lower().split("@")[-1]

        if dominio in ValidadorNegocio.DOMINIOS_DESECHABLES:
            return False, f"Dominio de correo desechable no permitido: '{dominio}'."

        if any(dominio.endswith(sufijo) for sufijo in ValidadorNegocio.SUFIJOS_CORPORATIVOS):
            return True, "Correo corporativo/institucional válido."

        return False, f"El dominio '{dominio}' no es corporativo ni institucional."


# ---------------------------------------------------------------------------
# SERVICIO (CLASE ABSTRACTA) Y SUBCLASES
# ---------------------------------------------------------------------------
class Servicio(EntidadBase):
    """
    Clase abstracta que representa cualquier servicio ofrecido por el
    sistema (hotel, transporte, experiencia turística, etc.).

    Define atributos comunes (nombre, precio_base, disponible) y declara
    el método abstracto `calcular_costo_total()`, que cada subclase debe
    implementar con su propia lógica de negocio (polimorfismo real, no
    solo una descripción distinta).
    """

    def __init__(self, nombre: str, precio_base: float) -> None:
        super().__init__()
        self.nombre = nombre
        self.precio_base = precio_base
        self.__disponible: bool = True

    @property
    def nombre(self) -> str:
        return self.__nombre

    @nombre.setter
    def nombre(self, valor: str) -> None:
        if not isinstance(valor, str) or not valor.strip():
            raise ServicioInvalidoError("El nombre del servicio no puede estar vacío.")
        self.__nombre = valor.strip()

    @property
    def precio_base(self) -> float:
        return self.__precio_base

    @precio_base.setter
    def precio_base(self, valor: float) -> None:
        try:
            valor_numerico = float(valor)
        except (TypeError, ValueError):
            raise ServicioInvalidoError(f"El precio base debe ser numérico, se recibió: '{valor}'.")
        if valor_numerico <= 0:
            raise ServicioInvalidoError("El precio base debe ser mayor a cero.")
        self.__precio_base = valor_numerico

    @property
    def disponible(self) -> bool:
        return self.__disponible

    def marcar_no_disponible(self) -> None:
        self.__disponible = False

    def marcar_disponible(self) -> None:
        self.__disponible = True

    @abstractmethod
    def calcular_costo_total(self) -> float:
        """
        Calcula el costo final del servicio aplicando la lógica
        particular de cada tipo de servicio (impuestos, recargos,
        descuentos, etc.). Cada subclase lo implementa de forma distinta.
        """
        raise NotImplementedError

    def calcular_precio_total(self) -> float:
        """
        Alias público de calcular_costo_total() que mantiene compatibilidad
        con código externo (ej. interfaz_grafica.py) sin duplicar lógica.

        La lógica real vive en calcular_costo_total() de cada subclase;
        este método solo delega, garantizando que cualquier subclase nueva
        que implemente calcular_costo_total() también tenga calcular_precio_total()
        disponible de forma automática sin tener que redefinirlo.
        """
        return self.calcular_costo_total()

    @property
    def precio_diario(self) -> float:
        """
        Alias de precio_base con nombre semántico orientado a finanzas.
        Permite usar `servicio.precio_diario` como tarifa base unitaria
        (por noche, por persona, por trayecto) en cálculos externos.
        """
        return self.precio_base

    def resumen(self) -> str:
        disp = "Disponible" if self.__disponible else "No disponible"
        return (f"{self.__class__.__name__}[{self.id}] {self.__nombre} "
                f"- ${self.calcular_costo_total():,.2f} - {disp}")

    def __str__(self) -> str:
        return self.resumen()


class ServicioHotel(Servicio):
    """
    Servicio de hospedaje. El costo total depende del precio base
    por noche multiplicado por la cantidad de noches, más un cargo
    fijo de servicio (limpieza/administración).
    """

    CARGO_SERVICIO = 15000.0

    def __init__(self, nombre: str, precio_base: float, noches: int, estrellas: int = 3) -> None:
        super().__init__(nombre, precio_base)
        if not isinstance(noches, int) or noches <= 0:
            raise ServicioInvalidoError("La cantidad de noches debe ser un entero mayor a 0.")
        if not isinstance(estrellas, int) or not (1 <= estrellas <= 5):
            raise ServicioInvalidoError("Las estrellas del hotel deben estar entre 1 y 5.")
        self.noches = noches
        self.estrellas = estrellas

    def calcular_costo_total(self) -> float:
        """Precio por noche * número de noches + cargo fijo de servicio."""
        return round(self.precio_base * self.noches + self.CARGO_SERVICIO, 2)


class ServicioTransporte(Servicio):
    """
    Servicio de transporte (traslados, alquiler de vehículo, etc.).
    El costo total depende del precio base por trayecto/día,
    la distancia o cantidad de unidades, y un seguro opcional.
    """

    PORCENTAJE_SEGURO = 0.10  # 10% adicional si se incluye seguro

    def __init__(self, nombre: str, precio_base: float, unidades: int, con_seguro: bool = False) -> None:
        super().__init__(nombre, precio_base)
        if not isinstance(unidades, int) or unidades <= 0:
            raise ServicioInvalidoError("Las unidades (km/días) deben ser un entero mayor a 0.")
        self.unidades = unidades
        self.con_seguro = bool(con_seguro)

    def calcular_costo_total(self) -> float:
        """Precio base * unidades, más seguro opcional sobre ese subtotal."""
        subtotal = self.precio_base * self.unidades
        if self.con_seguro:
            subtotal += subtotal * self.PORCENTAJE_SEGURO
        return round(subtotal, 2)


class ServicioExperiencia(Servicio):
    """
    Servicio de experiencia/actividad (tours, entradas a eventos, etc.).
    El costo total depende del precio base por persona y la cantidad
    de participantes, con un descuento por grupos grandes.
    """

    UMBRAL_DESCUENTO = 5      # a partir de 5 personas aplica descuento
    PORCENTAJE_DESCUENTO = 0.15  # 15% de descuento grupal

    def __init__(self, nombre: str, precio_base: float, participantes: int) -> None:
        super().__init__(nombre, precio_base)
        if not isinstance(participantes, int) or participantes <= 0:
            raise ServicioInvalidoError("La cantidad de participantes debe ser un entero mayor a 0.")
        self.participantes = participantes

    def calcular_costo_total(self) -> float:
        """Precio por persona * participantes, con descuento grupal si aplica."""
        subtotal = self.precio_base * self.participantes
        if self.participantes >= self.UMBRAL_DESCUENTO:
            subtotal -= subtotal * self.PORCENTAJE_DESCUENTO
        return round(subtotal, 2)


# =============================================================================
# SECCIÓN 4: RESERVA (clase Reserva y su máquina de estados)
# (equivalente al antiguo reserva.py)
# =============================================================================

class EstadoReserva(str, Enum):
    """
    Enum que define los estados posibles de una Reserva.
    Hereda de `str` además de `Enum` para que sea fácil compararla
    e imprimirla directamente como texto (ej. en logs).
    """
    PENDIENTE = "PENDIENTE"
    CONFIRMADA = "CONFIRMADA"
    CANCELADA = "CANCELADA"
    FINALIZADA = "FINALIZADA"


# Transiciones de estado permitidas: clave = estado actual,
# valor = conjunto de estados a los que puede pasar desde ahí.
_TRANSICIONES_VALIDAS = {
    EstadoReserva.PENDIENTE: {EstadoReserva.CONFIRMADA, EstadoReserva.CANCELADA},
    EstadoReserva.CONFIRMADA: {EstadoReserva.FINALIZADA, EstadoReserva.CANCELADA},
    EstadoReserva.CANCELADA: set(),    # estado terminal, no admite más cambios
    EstadoReserva.FINALIZADA: set(),   # estado terminal, no admite más cambios
}


class Reserva:
    """
    Representa la reserva de un Servicio por parte de un Cliente.

    No hereda de EntidadBase porque conceptualmente una Reserva no es
    una "entidad de catálogo" como Cliente o Servicio, sino una
    transacción que los relaciona; aun así mantiene su propio id único
    y encapsula su estado para garantizar transiciones válidas.
    """

    def __init__(self, cliente: Cliente, servicio: Servicio) -> None:
        if not isinstance(cliente, Cliente):
            raise ReservaInvalidaError("La reserva requiere una instancia válida de Cliente.")
        if not isinstance(servicio, Servicio):
            raise ReservaInvalidaError("La reserva requiere una instancia válida de Servicio.")
        if not cliente.activo:
            raise ReservaInvalidaError(
                f"No se puede reservar para un cliente inactivo: {cliente.nombre}."
            )
        if not servicio.disponible:
            raise ServicioNoDisponibleError(
                f"El servicio '{servicio.nombre}' no está disponible actualmente."
            )

        self.__id: str = str(uuid.uuid4())[:8]
        self.__cliente: Cliente = cliente
        self.__servicio: Servicio = servicio
        self.__estado: EstadoReserva = EstadoReserva.PENDIENTE
        self.__fecha_creacion: datetime = datetime.now()
        self.__historial_estados: list[tuple[EstadoReserva, datetime]] = [
            (self.__estado, self.__fecha_creacion)
        ]

    @property
    def id(self) -> str:
        return self.__id

    @property
    def cliente(self) -> Cliente:
        return self.__cliente

    @property
    def servicio(self) -> Servicio:
        return self.__servicio

    @property
    def estado(self) -> EstadoReserva:
        return self.__estado

    @property
    def historial_estados(self) -> list[tuple[EstadoReserva, datetime]]:
        """Retorna una copia del historial para evitar que se modifique
        directamente desde fuera de la clase."""
        return list(self.__historial_estados)

    def _cambiar_estado(self, nuevo_estado: EstadoReserva) -> None:
        """
        Método interno que centraliza la validación de transiciones
        de estado. Es el único punto del programa donde `__estado`
        cambia, lo que garantiza consistencia.
        """
        transiciones_permitidas = _TRANSICIONES_VALIDAS[self.__estado]
        if nuevo_estado not in transiciones_permitidas:
            raise EstadoReservaError(
                f"Transición inválida: no se puede pasar de '{self.__estado.value}' "
                f"a '{nuevo_estado.value}' en la reserva {self.__id}."
            )
        self.__estado = nuevo_estado
        self.__historial_estados.append((nuevo_estado, datetime.now()))

    def confirmar(self) -> None:
        """Confirma una reserva PENDIENTE."""
        self._cambiar_estado(EstadoReserva.CONFIRMADA)

    def finalizar(self) -> None:
        """Finaliza una reserva CONFIRMADA (servicio ya prestado)."""
        self._cambiar_estado(EstadoReserva.FINALIZADA)

    def cancelar(self) -> None:
        """Cancela una reserva PENDIENTE o CONFIRMADA."""
        self._cambiar_estado(EstadoReserva.CANCELADA)

    def calcular_total(self) -> float:
        """Delega en el Servicio asociado el cálculo del costo total
        (polimorfismo: cada tipo de servicio calcula distinto)."""
        return self.__servicio.calcular_costo_total()

    @property
    def total(self) -> float:
        """
        Propiedad de acceso rápido al costo total de la reserva.
        Alias de calcular_total() para uso en la capa de presentación:
        permite escribir `reserva.total` en vez de `reserva.calcular_total()`.
        Ambas formas siguen siendo válidas; esta solo mejora la legibilidad.
        """
        return self.calcular_total()

    def resumen(self) -> str:
        return (
            f"Reserva[{self.__id}] Cliente: {self.__cliente.nombre} | "
            f"Servicio: {self.__servicio.nombre} | Estado: {self.__estado.value} | "
            f"Total: ${self.calcular_total():,.2f}"
        )

    def __str__(self) -> str:
        return self.resumen()


# =============================================================================
# SECCIÓN 5: GESTOR DEL SISTEMA (lógica de negocio central)
# (equivalente al antiguo gestor.py)
# =============================================================================

# Catálogo de tipos de servicio disponibles para la fábrica crear_servicio().
# Centraliza qué subclases de Servicio existen: agregar un nuevo tipo en el
# futuro solo requiere registrar su clase aquí, sin tocar el script de
# simulación ni duplicar manejo de excepciones en el código cliente.
_TIPOS_SERVICIO_DISPONIBLES = {
    "hotel": ServicioHotel,
    "transporte": ServicioTransporte,
    "experiencia": ServicioExperiencia,
}


class GestorSistema:
    """
    Orquesta clientes, servicios y reservas, y es el único punto de
    entrada "seguro" para realizar operaciones críticas del sistema.
    """

    def __init__(self) -> None:
        self.clientes: dict[str, Cliente] = {}
        self.servicios: dict[str, Servicio] = {}
        self.reservas: dict[str, Reserva] = {}
        self.lista_negra: set[str] = set()

    # ------------------------------------------------------------------
    # CLIENTES
    # ------------------------------------------------------------------
    def registrar_cliente(self, nombre: str, documento: str, email: str, telefono: str = "") -> Cliente | None:
        """
        Crea y registra un nuevo Cliente en el sistema.
        Retorna la instancia creada si todo sale bien, o None si falló.
        """
        cliente_creado: Cliente | None = None
        try:
            documento_normalizado = str(documento).strip()

            # Rechazo inmediato: el documento ya está en la lista negra
            # (agregado previamente vía bloquear_documento()).
            if documento_normalizado in self.lista_negra:
                registrar_error(
                    f"registrar_cliente -> intento con documento en lista negra "
                    f"(FRAUDE): {documento_normalizado}"
                )
                raise DocumentoBloqueadoError(
                    f"El documento '{documento_normalizado}' está en la lista negra "
                    f"y no puede registrarse."
                )

            # Validación de negocio adicional (Mejora 2): si ValidadorNegocio
            # detecta un patrón de fraude (dígitos repetidos, secuencia
            # ascendente), se escala automáticamente bloqueando el documento
            # para que cualquier intento futuro sea rechazado de inmediato.
            valido, motivo = ValidadorNegocio.es_documento_valido(documento_normalizado)
            if not valido and "fraude" in motivo.lower():
                self.bloquear_documento(documento_normalizado)
                registrar_error(f"registrar_cliente -> documento bloqueado automáticamente (FRAUDE): {motivo}")
                raise DocumentoBloqueadoError(motivo)

            cliente_creado = Cliente(nombre=nombre, documento=documento, email=email, telefono=telefono)
        except ErrorSistemaGestion as error:
            print(f"❌ Error al registrar cliente: {error}")
            registrar_error(f"registrar_cliente -> {error}")
        except Exception as error:  # red de seguridad ante errores no previstos
            print(f"❌ Error inesperado al registrar cliente: {error}")
            registrar_error(f"registrar_cliente -> error inesperado: {error}")
        else:
            self.clientes[cliente_creado.id] = cliente_creado
            print(f"✅ Cliente registrado: {cliente_creado.resumen()}")
            registrar_evento(f"Cliente registrado correctamente: {cliente_creado.resumen()}")
        finally:
            print("— Fin de la operación 'registrar_cliente' —")
        return cliente_creado

    def bloquear_documento(self, documento: str) -> None:
        """
        Agrega un documento a la lista negra del sistema (Mejora 3).

        Cualquier intento posterior de registrar_cliente() con este
        documento será rechazado de inmediato con DocumentoBloqueadoError,
        sin necesidad de volver a instanciar Cliente ni repetir análisis
        de fraude ya realizado antes.
        """
        documento_normalizado = str(documento).strip()
        self.lista_negra.add(documento_normalizado)
        registrar_evento(f"Documento agregado a la lista negra: {documento_normalizado}")
        print(f"🚫 Documento '{documento_normalizado}' agregado a la lista negra.")

    # ------------------------------------------------------------------
    # SERVICIOS
    # ------------------------------------------------------------------
    def crear_servicio(self, tipo: str, **parametros) -> Servicio | None:
        """
        Fábrica única y segura para construir Y registrar un Servicio.

        AUDITORÍA (corrección #2): antes, main.py instanciaba subclases de
        Servicio (ej. ServicioTransporte(...)) directamente, fuera del
        GestorSistema, y envolvía esa construcción en un try/except manual
        y duplicado. Si ese try se omitía (algo muy probable al extender
        el script), una construcción inválida (ej. precio negativo) lanzaba
        ServicioInvalidoError sin control y cerraba el programa.

        Este método es ahora el ÚNICO punto donde se construyen instancias
        de Servicio: la construcción (que puede fallar) y el registro
        quedan dentro del mismo bloque try/except/else/finally, así que
        cualquier código cliente (main.py, una futura interfaz web, etc.)
        nunca necesita su propio try para esto.

        Args:
            tipo: clave del tipo de servicio ('hotel', 'transporte',
                'experiencia'). Ver _TIPOS_SERVICIO_DISPONIBLES.
            **parametros: argumentos propios del constructor de cada
                subclase (ej. noches=3 para 'hotel').

        Returns:
            La instancia creada y ya registrada, o None si falló.
        """
        servicio_creado: Servicio | None = None
        try:
            clase_servicio = _TIPOS_SERVICIO_DISPONIBLES.get(tipo.lower().strip())
            if clase_servicio is None:
                raise ErrorSistemaGestion(
                    f"Tipo de servicio '{tipo}' no reconocido. "
                    f"Use uno de: {list(_TIPOS_SERVICIO_DISPONIBLES.keys())}."
                )
            servicio_creado = clase_servicio(**parametros)
        except ErrorSistemaGestion as error:
            print(f"❌ Error al crear servicio: {error}")
            registrar_error(f"crear_servicio -> {error}")
        except TypeError as error:
            # Parámetros incorrectos/faltantes para el constructor
            # de la subclase (ej. olvidar 'noches' en un ServicioHotel).
            print(f"❌ Parámetros inválidos para el servicio '{tipo}': {error}")
            registrar_error(f"crear_servicio -> parámetros inválidos para '{tipo}': {error}")
        except Exception as error:
            print(f"❌ Error inesperado al crear servicio: {error}")
            registrar_error(f"crear_servicio -> error inesperado: {error}")
        else:
            self.servicios[servicio_creado.id] = servicio_creado
            print(f"✅ Servicio registrado: {servicio_creado.resumen()}")
            registrar_evento(f"Servicio registrado correctamente: {servicio_creado.resumen()}")
        finally:
            print("— Fin de la operación 'crear_servicio' —")
        return servicio_creado

    def registrar_servicio(self, servicio: Servicio | None) -> Servicio | None:
        """
        Registra una instancia de Servicio YA CONSTRUIDA en el catálogo.

        Se conserva por compatibilidad (ej. pruebas unitarias que ya
        construyen el objeto), pero el camino recomendado para todo
        código nuevo es `crear_servicio()`, que evita instanciar
        subclases de Servicio fuera de un bloque controlado.
        """
        try:
            if servicio is None or not isinstance(servicio, Servicio):
                raise ErrorSistemaGestion("Se intentó registrar un servicio nulo o de tipo inválido.")
        except ErrorSistemaGestion as error:
            print(f"❌ Error al registrar servicio: {error}")
            registrar_error(f"registrar_servicio -> {error}")
            return None
        except Exception as error:
            print(f"❌ Error inesperado al registrar servicio: {error}")
            registrar_error(f"registrar_servicio -> error inesperado: {error}")
            return None
        else:
            self.servicios[servicio.id] = servicio
            print(f"✅ Servicio registrado: {servicio.resumen()}")
            registrar_evento(f"Servicio registrado correctamente: {servicio.resumen()}")
            return servicio
        finally:
            print("— Fin de la operación 'registrar_servicio' —")

    # ------------------------------------------------------------------
    # RESERVAS
    # ------------------------------------------------------------------
    def crear_reserva(self, cliente: Cliente | None, servicio: Servicio | None) -> Reserva | None:
        """
        Crea una Reserva a partir de un Cliente y un Servicio ya
        registrados en el sistema. Maneja explícitamente los casos en
        que cliente/servicio no existan o no cumplan las reglas de negocio.
        """
        reserva_creada: Reserva | None = None
        try:
            reserva_creada = Reserva(cliente=cliente, servicio=servicio)
        except ErrorSistemaGestion as error:
            print(f"❌ Error al crear la reserva: {error}")
            registrar_error(f"crear_reserva -> {error}")
        except Exception as error:
            print(f"❌ Error inesperado al crear la reserva: {error}")
            registrar_error(f"crear_reserva -> error inesperado: {error}")
        else:
            self.reservas[reserva_creada.id] = reserva_creada
            print(f"✅ Reserva creada: {reserva_creada.resumen()}")
            registrar_evento(f"Reserva creada correctamente: {reserva_creada.resumen()}")
        finally:
            print("— Fin de la operación 'crear_reserva' —")
        return reserva_creada

    def cambiar_estado_reserva(self, id_reserva: str, accion: str) -> bool:
        """
        Aplica una transición de estado sobre una reserva existente.

        Args:
            id_reserva: identificador de la reserva.
            accion: una de 'confirmar', 'cancelar' o 'finalizar'.

        Returns:
            bool: True si la transición se aplicó con éxito, False en caso contrario.
        """
        exito = False
        try:
            reserva = self.reservas.get(id_reserva)
            if reserva is None:
                raise ErrorSistemaGestion(f"No existe una reserva con id '{id_reserva}'.")

            acciones_disponibles = {
                "confirmar": reserva.confirmar,
                "cancelar": reserva.cancelar,
                "finalizar": reserva.finalizar,
            }
            metodo = acciones_disponibles.get(accion)
            if metodo is None:
                raise ErrorSistemaGestion(
                    f"Acción '{accion}' no reconocida. Use: {list(acciones_disponibles.keys())}."
                )
            metodo()  # ejecuta confirmar(), cancelar() o finalizar()
        except ErrorSistemaGestion as error:
            print(f"❌ Error al cambiar estado de la reserva: {error}")
            registrar_error(f"cambiar_estado_reserva -> {error}")
        except Exception as error:
            print(f"❌ Error inesperado al cambiar estado de la reserva: {error}")
            registrar_error(f"cambiar_estado_reserva -> error inesperado: {error}")
        else:
            exito = True
            print(f"✅ Estado actualizado: {reserva.resumen()}")
            registrar_evento(f"Reserva {id_reserva} actualizada a estado '{reserva.estado.value}'.")
        finally:
            print("— Fin de la operación 'cambiar_estado_reserva' —")
        return exito

    # ------------------------------------------------------------------
    # REPORTES
    # ------------------------------------------------------------------
    def listar_reservas(self) -> None:
        """Imprime un resumen de todas las reservas registradas."""
        if not self.reservas:
            print("(No hay reservas registradas todavía).")
            return
        for reserva in self.reservas.values():
            print(f"  • {reserva.resumen()}")


# =============================================================================
# SECCIÓN 6: SCRIPT DE SIMULACIÓN (10 operaciones, válidas e inválidas)
# (equivalente al antiguo main.py)
# =============================================================================

def imprimir_separador(titulo: str) -> None:
    print("\n" + "=" * 70)
    print(f" {titulo}")
    print("=" * 70)


def main() -> None:
    gestor = GestorSistema()
    registrar_evento("===== INICIO DE LA SIMULACIÓN =====")

    # ------------------------------------------------------------------
    # OPERACIÓN 1 (VÁLIDA): registrar un cliente correcto
    # ------------------------------------------------------------------
    imprimir_separador("Operación 1: Registrar cliente válido")
    cliente_ana = gestor.registrar_cliente(
        nombre="ana gómez", documento="1020304050", email="ana.gomez@correo.com", telefono="3001234567"
    )

    # ------------------------------------------------------------------
    # OPERACIÓN 2 (INVÁLIDA): cliente con documento no numérico
    # ------------------------------------------------------------------
    imprimir_separador("Operación 2: Registrar cliente con documento inválido")
    gestor.registrar_cliente(
        nombre="Carlos Ruiz", documento="ABC123", email="carlos@correo.com"
    )

    # ------------------------------------------------------------------
    # OPERACIÓN 3 (VÁLIDA): registrar un segundo cliente correcto
    # ------------------------------------------------------------------
    imprimir_separador("Operación 3: Registrar segundo cliente válido")
    cliente_luis = gestor.registrar_cliente(
        nombre="luis fernández", documento="9988776655", email="luis.fernandez@correo.com"
    )

    # ------------------------------------------------------------------
    # OPERACIÓN 4 (INVÁLIDA): cliente con email mal formado
    # ------------------------------------------------------------------
    imprimir_separador("Operación 4: Registrar cliente con email inválido")
    gestor.registrar_cliente(
        nombre="Marta Díaz", documento="1111222233", email="marta-arroba-correo.com"
    )

    # ------------------------------------------------------------------
    # OPERACIÓN 5 (VÁLIDA): registrar un ServicioHotel
    # ------------------------------------------------------------------
    imprimir_separador("Operación 5: Registrar servicio de Hotel válido")
    hotel = gestor.crear_servicio(
        tipo="hotel", nombre="Hotel Costa Azul", precio_base=120000.0, noches=3, estrellas=4
    )

    # ------------------------------------------------------------------
    # OPERACIÓN 6 (INVÁLIDA): ServicioTransporte con precio negativo
    #   AUDITORÍA (corrección #2): antes esta operación instanciaba
    #   ServicioTransporte(...) directamente y la envolvía en un
    #   try/except manual aquí en main.py, duplicando lógica que ya
    #   existe en el gestor. Ahora crear_servicio() es el único punto
    #   de construcción+registro: la excepción se controla SIEMPRE,
    #   sin depender de que main.py recuerde poner su propio try.
    # ------------------------------------------------------------------
    imprimir_separador("Operación 6: Registrar transporte con precio negativo")
    gestor.crear_servicio(
        tipo="transporte", nombre="Van Ejecutiva", precio_base=-50000.0, unidades=4, con_seguro=True
    )

    # ------------------------------------------------------------------
    # OPERACIÓN 7 (VÁLIDA): registrar un ServicioExperiencia
    # ------------------------------------------------------------------
    imprimir_separador("Operación 7: Registrar servicio de Experiencia válido")
    experiencia = gestor.crear_servicio(
        tipo="experiencia", nombre="Tour Ciudad Amurallada", precio_base=45000.0, participantes=6
    )

    # ------------------------------------------------------------------
    # OPERACIÓN 8 (VÁLIDA): crear una reserva válida (cliente + hotel)
    # ------------------------------------------------------------------
    imprimir_separador("Operación 8: Crear reserva válida (Ana + Hotel)")
    reserva_ana = gestor.crear_reserva(cliente_ana, hotel)

    # ------------------------------------------------------------------
    # OPERACIÓN 9 (INVÁLIDA): crear una reserva con servicio no disponible
    # ------------------------------------------------------------------
    imprimir_separador("Operación 9: Reserva sobre un servicio NO disponible")
    if experiencia is not None:
        experiencia.marcar_no_disponible()
    gestor.crear_reserva(cliente_luis, experiencia)

    # ------------------------------------------------------------------
    # OPERACIÓN 10 (MIXTA): flujo de estados de una reserva
    #   - Confirmar la reserva de Ana (válido)
    #   - Intentar volver a "confirmar" una reserva ya CONFIRMADA (inválido)
    # ------------------------------------------------------------------
    imprimir_separador("Operación 10: Transiciones de estado de una reserva")
    if reserva_ana is not None:
        gestor.cambiar_estado_reserva(reserva_ana.id, "confirmar")   # válida
        gestor.cambiar_estado_reserva(reserva_ana.id, "confirmar")   # inválida (ya está CONFIRMADA)
        gestor.cambiar_estado_reserva(reserva_ana.id, "finalizar")   # válida

    # ------------------------------------------------------------------
    # RESUMEN FINAL
    # ------------------------------------------------------------------
    imprimir_separador("Resumen final de reservas registradas")
    gestor.listar_reservas()

    registrar_evento("===== FIN DE LA SIMULACIÓN =====")
    print(f"\n📄 Revisa el archivo de log con el detalle completo en:\n   {RUTA_LOG}")


if __name__ == "__main__":
    # AUDITORÍA (hallazgo C): además de que cada operación dentro de
    # GestorSistema tenga su propio try/except, el punto de entrada del
    # programa también debe estar protegido. Esto cubre cualquier error
    # no previsto que ocurra FUERA de los métodos del gestor (por ejemplo,
    # si una futura operación llama directamente a una clase del dominio
    # sin pasar por el gestor), evitando que el programa termine con un
    # traceback crudo y sin dejar rastro en el log.
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  Simulación interrumpida por el usuario (Ctrl+C).")
        registrar_advertencia("Simulación interrumpida manualmente por el usuario.")
    except Exception as error:
        print(f"\n❌ Error crítico no controlado: {error}")
        registrar_error(f"main -> error crítico no controlado: {error}")