__author__ = 'Pablo Ramos Criado'
__students__ = 'Kerman Ramos y Rodrigo Castro'


from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import time
from typing import Generator, Any, Self
from geojson import Point
import pymongo
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from bson.objectid import ObjectId
import yaml

def getLocationPoint(address: str) -> Point:
    """ 
    Obtiene las coordenadas de una dirección en formato geojson.Point
    Utilizar la API de geopy para obtener las coordenadas de la direccion
    Cuidado, la API es publica tiene limite de peticiones, utilizar sleeps.

    Parameters
    ----------
        address : str
            direccion completa de la que obtener las coordenadas
    Returns
    -------
        geojson.Point
            coordenadas del punto de la direccion
    """
    # Estado inicial: todavia no hay resultado y llevamos 0 intentos
    location = None
    intentos = 0
    maxIntentos = 5

    # Repetimos mientras no tengamos coordenadas Y queden intentos
    while location is None and intentos < maxIntentos:
        intentos += 1
        try:
            # Espera de 1 segundo para no saturar la API publica (limite de peticiones)
            time.sleep(1)
            # Pregunta a Nominatim por la direccion. Devuelve un objeto con
            # latitude y longitude, o None si no encuentra la direccion.
            # El user_agent identifica nuestra aplicacion ante la API.
            location = Nominatim(user_agent="envivo-abd-p1-rodrigo-kerman").geocode(address)
        except GeocoderTimedOut:
            # La API tardo demasiado: no hacemos nada y el while lo reintenta
            continue

    # Si tras los 5 intentos no hay coordenadas, avisamos con un error.
    # No devolvemos un punto inventado ni None: la fase 2 necesita distinguirlo.
    if location is None:
        raise ValueError(f"No se pudieron obtener coordenadas para: {address}")

    # GeoJSON exige el orden (longitud, latitud), al reves de lo habitual
    return Point((location.longitude, location.latitude))

class Model:
    """ 
    Clase de modelo abstracta
    Crear tantas clases que hereden de esta clase como  
    colecciones/modelos se deseen tener en la base de datos.

    Attributes
    ----------
        required_vars : set[str]
            conjunto de atributos requeridos por el modelo
        admissible_vars : set[str]
            conjunto de atributos admitidos por el modelo
        db : pymongo.collection.Collection
            conexion a la coleccion de la base de datos
    
    Methods
    -------
        __setattr__(name: str, value: str | dict) -> None
            Sobreescribe el metodo de asignacion de valores a los 
            atributos del objeto con el fin de controlar qué atributos 
            son modificados y cuando son modificados.
        __getattr__(name: str) -> Any
            Sobreescribe el metodo de acceso a atributos del objeto 
        save()  -> None
            Guarda el modelo en la base de datos
        delete() -> None
            Elimina el modelo de la base de datos
        find(filter: dict[str, str | dict]) -> ModelCursor
            Realiza una consulta de lectura en la BBDD.
            Devuelve un cursor de modelos ModelCursor
        aggregate(pipeline: list[dict]) -> pymongo.command_cursor.CommandCursor
            Devuelve el resultado de una consulta aggregate.
        find_by_id(id: str) -> dict | None
            Busca un documento por su id utilizando la cache y lo devuelve.
            Si no se encuentra el documento, devuelve None.
        init_class(db_collection: pymongo.collection.Collection, required_vars: set[str], admissible_vars: set[str]) -> None
            Inicializa las variables de clase en la inicializacion del sistema.

    """
    # Atributos de CLASE: los rellena init_class, uno distinto por cada modelo
    _required_vars: set[str]
    _admissible_vars: set[str]
    # Nombre del campo de direccion (ej: "direccion"), o None si el modelo no tiene
    _location_var: str | None = None
    _db: pymongo.collection.Collection
    # Atributos internos de Python: NO son datos del documento, no pasan por la validacion
    _internal_vars: set[str] = frozenset(('_modified_vars', '_required_vars', '_admissible_vars', '_db', '_data', '_location_var'))

    def __init__(self, **kwargs: dict[str, str | dict | list]) -> None:
        """
        Inicializa el modelo con los valores proporcionados en kwargs
        Comprueba que los valores proporcionados en kwargs son admitidos
        por el modelo y que las atributos requeridos son proporcionadas.

        Parameters
        ----------
            kwargs : dict[str, str | dict]
                diccionario con los valores de las atributos del modelo
        """
        # Diccionario donde viven TODOS los datos del documento
        self._data: dict[str, str | dict | list] = {}

        # Nombres de los campos modificados desde el ultimo guardado.
        # Es un conjunto (set) para que no haya repetidos.
        self._modified_vars = set()

        # Campos permitidos = requeridos + admitidos + "_id" (lo pone Mongo)
        permitidas = self._required_vars | self._admissible_vars | {'_id'}
        # Si el modelo tiene direccion, tambien se permite su punto GeoJSON (ej: "direccion_loc")
        if self._location_var:
            permitidas.add(self._location_var + '_loc')

        # Nombres de los campos que se han recibido
        kwargsSet = set(kwargs)

        # Comprobacion 1: ¿falta algun campo requerido? (resta de conjuntos)
        faltan = self._required_vars - kwargsSet
        if faltan:
            raise ValueError(f"Faltan atributos requeridos: {sorted(faltan)}")

        # Comprobacion 2: ¿sobra algun campo que no este permitido?
        sobran = kwargsSet - permitidas
        if sobran:
            raise ValueError(f"Atributos no admitidos: {sorted(sobran)}")

        # Todo correcto: guardamos los valores en _data
        self._data.update(kwargs)

    def __setattr__(self, name: str, value: str | dict) -> None:
        """ Sobreescribe el metodo de asignacion de valores a los 
        atributos del objeto con el fin de controlar que atributos 
        son modificados y cuando son modificados.
        """
        # Los atributos internos (_data, _db...) se asignan de forma normal,
        # sin validar. Si no, __init__ se bloquearia a si mismo.
        if name in self._internal_vars:
            super().__setattr__(name, value)
            return

        # Campos permitidos (misma regla que en __init__)
        permitidas = self._required_vars | self._admissible_vars | {'_id'}
        if self._location_var:
            permitidas.add(self._location_var + '_loc')

        # Si el nombre no esta permitido, se rechaza la asignacion
        if name not in permitidas:
            raise ValueError(f"Atributo no admitido: {name}")

        # Guardamos el valor en el diccionario de datos
        self._data[name] = value
        # Apuntamos el nombre del campo como modificado (save() lo usara)
        self._modified_vars.add(name)

    def __getattr__(self, name: str) -> Any:
        """ Sobreescribe el metodo de acceso a atributos del objeto
        __getattr__ solo es llamado cuando no encuentra el atributo
        en el objeto 
        """
        if name in self._internal_vars:
            return super().__getattribute__(name)
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError
        
    def save(self) -> None:
        """
        Guarda el modelo en la base de datos
        Si el modelo no existe en la base de datos, se crea un nuevo
        documento con los valores del modelo. En caso contrario, se
        actualiza el documento existente con los nuevos valores del
        modelo.
        """
        # Nombre del campo de direccion del modelo (o None si no tiene)
        loc_var = self._location_var

        # Si no hay "_id", el documento es NUEVO y todavia no esta en Mongo
        if "_id" not in self._data:
            # CAMINO A: INSERTAR

            # Copia de los datos, para añadirle el punto sin tocar _data todavia
            doc = dict(self._data)

            # Si el modelo tiene direccion y el documento la trae,
            # calculamos el punto GeoJSON y lo guardamos en "<campo>_loc"
            if loc_var and loc_var in doc:
                doc[loc_var + "_loc"] = getLocationPoint(doc[loc_var])

            # Insertamos en Mongo (pymongo añade el "_id" a doc)
            self._db.insert_one(doc)

            # Copiamos a _data lo nuevo (el "_id" y el punto) para que
            # el objeto en memoria coincida con la base de datos
            self._data.update(doc)
        else:
            # CAMINO B: ACTUALIZAR (el documento ya existe en Mongo)

            # Diccionario solo con los campos modificados y su valor actual
            cambios = {campo: self._data[campo] for campo in self._modified_vars}

            # Si lo que cambio es la direccion, el punto antiguo ya no vale:
            # se recalcula y se guarda tanto para Mongo (cambios) como en memoria (_data)
            if loc_var and loc_var in cambios:
                punto = getLocationPoint(cambios[loc_var])
                cambios[loc_var + "_loc"] = punto
                self._data[loc_var + "_loc"] = punto

            # Si hay algo que cambiar, $set modifica SOLO esos campos
            # y deja el resto del documento intacto
            if cambios:
                self._db.update_one({"_id": self._data["_id"]}, {"$set": cambios})

        # Ya esta todo guardado: vaciamos la lista de campos pendientes
        self._modified_vars = set()

    def delete(self) -> None:
        """
        Elimina el modelo de la base de datos
        """
        # Solo se borra si el objeto esta en Mongo (si tiene "_id")
        if "_id" in self._data:
            # Borra de Mongo el documento con ese "_id"
            self._db.delete_one({"_id": self._data["_id"]})
            # Quitamos el "_id" del objeto: queda como "nuevo", y un save()
            # posterior lo insertaria de nuevo
            del self._data["_id"]
    
    @classmethod
    def find(cls, filter: dict[str, str | dict]) -> Any:
        """ 
        Utiliza el metodo find de pymongo para realizar una consulta
        de lectura en la BBDD.
        find debe devolver un cursor de modelos ModelCursor

        Parameters
        ----------
            filter : dict[str, str | dict]
                diccionario con el criterio de busqueda de la consulta
        Returns
        -------
            ModelCursor
                cursor de modelos
        """ 
        # Busqueda en la coleccion de este modelo con el filtro tal cual.
        # Devuelve un cursor de pymongo (diccionarios, aun sin cargar).
        cursor = cls._db.find(filter)

        # Lo envolvemos en un ModelCursor, que lo convertira en objetos modelo
        # (cls es la clase: Recinto, User...)
        return ModelCursor(cls, cursor)

    @classmethod
    def aggregate(cls, pipeline: list[dict]) -> pymongo.command_cursor.CommandCursor:
        """ 
        Devuelve el resultado de una consulta aggregate. 
        No hay nada que hacer en esta funcion.
        Se utilizara para las consultas solicitadas
        en el segundo proyecto de la practica.

        Parameters
        ----------
            pipeline : list[dict]
                lista de etapas de la consulta aggregate 
        Returns
        -------
            pymongo.command_cursor.CommandCursor
                cursor de pymongo con el resultado de la consulta
        """ 
        return cls._db.aggregate(pipeline)
    
    @classmethod
    def find_by_id(cls, id: str) -> Self | None:
        """ 
        NO IMPLEMENTAR HASTA EL TERCER PROYECTO
        Busca un documento por su id utilizando la cache y lo devuelve.
        Si no se encuentra el documento, devuelve None.

        Parameters
        ----------
            id : str
                id del documento a buscar
        Returns
        -------
            Self | None
                Modelo del documento encontrado o None si no se encuentra
        """ 
        #TODO
        pass

    @classmethod
    def init_class(cls, db_collection: pymongo.collection.Collection, indexes:dict[str,str], required_vars: set[str], admissible_vars: set[str]) -> None:
        """ 
        Inicializa los atributos de clase en la inicializacion del sistema.
        Aqui se deben inicializar o asegurar los indices. Tambien se puede
        alguna otra inicialización/comprobaciones o cambios adicionales
        que estime el alumno.

        Parameters
        ----------
            db_collection : pymongo.collection.Collection
                Conexion a la collecion de la base de datos.
            indexes: Dict[str,str]
                Set de indices y tipo de indices para la coleccion
            required_vars : set[str]
                Set de atributos requeridos por el modelo
            admissible_vars : set[str] 
                Set de atributos admitidos por el modelo
        """
        # Parte 1: guardar en la clase su coleccion y sus campos
        cls._db = db_collection
        cls._required_vars = required_vars
        cls._admissible_vars = admissible_vars

        # Parte 2: crear los indices. "indexes" es un dict {campo: tipo}
        # (si es None se usa un dict vacio para que no falle)
        for campo, tipo in (indexes or {}).items():
            if tipo == 'unique':
                # Indice ascendente que no permite valores repetidos
                cls._db.create_index([(campo, pymongo.ASCENDING)], unique=True)
            elif tipo == 'asc':
                # Indice ascendente normal, para acelerar busquedas
                cls._db.create_index([(campo, pymongo.ASCENDING)])
            elif tipo == 'geosphere':
                # Guardamos el nombre BASE del campo de direccion (ej: "direccion")
                cls._location_var = campo
                # El indice 2dsphere va sobre el campo del PUNTO ("direccion_loc"),
                # no sobre el texto de la direccion
                cls._db.create_index([(campo + "_loc", pymongo.GEOSPHERE)])


class ModelCursor:
    """ 
    Cursor para iterar sobre los documentos del resultado de una
    consulta. Los documentos deben ser devueltos en forma de objetos
    modelo.

    Attributes
    ----------
        model_class : Model
            Clase para crear los modelos de los documentos que se iteran.
        cursor : pymongo.cursor.Cursor
            Cursor de pymongo a iterar

    Methods
    -------
        __iter__() -> Generator
            Devuelve un iterador que recorre los elementos del cursor
            y devuelve los documentos en forma de objetos modelo.
    """

    def __init__(self, model_class: Model, cursor: pymongo.cursor.Cursor):
        """
        Inicializa el cursor con la clase de modelo y el cursor de pymongo

        Parameters
        ----------
            model_class : Model
                Clase para crear los modelos de los documentos que se iteran.
            cursor: pymongo.cursor.Cursor
                Cursor de pymongo a iterar
        """
        self.model = model_class
        self.cursor = cursor
    
    def __iter__(self) -> Generator:
        """
        Devuelve un iterador que recorre los elementos del cursor
        y devuelve los documentos en forma de objetos modelo.
        Utilizar yield para generar el iterador
        Utilizar la funcion next para obtener el siguiente documento del cursor
        Utilizar alive para comprobar si existen mas documentos.
        """
        # Mientras el cursor pueda tener mas documentos
        while self.cursor.alive:
            try:
                # Pide el siguiente documento (llega como diccionario)
                doc = next(self.cursor)
            except StopIteration:
                # Ya no quedaba ninguno: terminamos el generador
                break
            # Convierte el diccionario en un objeto de la clase (**doc lo
            # desempaqueta como argumentos con nombre) y lo entrega.
            # El generador se pausa aqui hasta que piden el siguiente.
            yield self.model(**doc)


def initApp(definitions_path: str = "./models.yml", mongodb_uri="mongodb://localhost:27017/", db_name="abd", scope=globals()) -> None:
    """ 
    Declara las clases que heredan de Model para cada uno de los 
    modelos de las colecciones definidas en definitions_path.
    Inicializa las clases de los modelos proporcionando los indices y 
    atributos admitidos y requeridos para cada una de ellas y la conexión a la
    collecion de la base de datos.
    
    Parameters
    ----------
        definitions_path : str
            ruta al fichero de definiciones de modelos
        mongodb_uri : str
            uri de conexion a la base de datos
        db_name : str
            nombre de la base de datos
    """
    # Paso 1: conectar con MongoDB y elegir la base de datos
    client = MongoClient(mongodb_uri, server_api=ServerApi('1'))
    db = client[db_name]

    # Paso 2: leer el YAML (queda como un diccionario de Python)
    with open(definitions_path, encoding="utf-8") as f:
        definiciones = yaml.safe_load(f)

    # Paso 3: crear una clase por cada modelo del YAML
    for nombre, definicion in definiciones.items():
        # Traducimos las listas del YAML a un diccionario {campo: tipo_de_indice}
        indexes = {}

        # Indices unicos
        for campo in definicion.get("unique_indexes") or []:
            indexes[campo] = "unique"

        # Indices normales ascendentes
        for campo in definicion.get("regular_indexes") or []:
            indexes[campo] = "asc"

        # Indice geoespacial (solo si el modelo declara location_index)
        location = definicion.get("location_index")
        if location:
            indexes[location] = "geosphere"

        # Creamos la clase en tiempo de ejecucion (hereda de Model)
        # y la dejamos en scope, ej: scope["Recinto"]
        scope[nombre] = type(nombre, (Model,), {})

        # Inicializamos la clase con su coleccion, sus indices y sus campos
        scope[nombre].init_class(
            db_collection=db[nombre],
            indexes=indexes,
            required_vars=set(definicion.get("required_vars") or []),
            admissible_vars=set(definicion.get("admissible_vars") or []),
        )

if __name__ == '__main__':
    
    # Inicializar base de datos y modelos con initApp
    initApp()

    # Limpiar documentos de ejecuciones anteriores (los indices se mantienen)
    Recinto._db.delete_many({})

    # Crear modelo
    r = Recinto(nombre="WiZink Center", direccion="Av. Felipe II, Madrid", aforo=17000)

    # Asignar nuevo valor a variable admitida del objeto 
    r.zonas = {"pista": 8000, "grada": 9000}

    # Asignar nuevo valor a variable no admitida del objeto:
    # debe lanzar ValueError, que capturamos para mostrar el aviso
    try:
        r.color = "rojo"
    except ValueError as e:
        print("Rechazado correctamente:", e)

    # Guardar (documento nuevo: se inserta, con su punto GeoJSON)
    r.save()

    # Asignar nuevo valor a variable admitida del objeto
    r.aforo = 17500

    # Guardar (documento existente: solo se actualiza "aforo")
    r.save()

    # Buscar nuevo documento con find
    cursor = Recinto.find({"nombre": "WiZink Center"})

    # Obtener primer documento (iter + next sacan el primero del cursor)
    primero = next(iter(cursor))
    print(primero.nombre, primero.aforo)

    # Modificar valor de variable admitida
    primero.aforo = 18000
    
    # Guardar
    primero.save()

    # Comprobar directamente en Mongo que el documento quedo actualizado
    print(Recinto._db.find_one({"nombre": "WiZink Center"}))